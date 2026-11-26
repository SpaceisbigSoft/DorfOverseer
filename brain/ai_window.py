"""(R29 W9, Phase 14.3) The AI window: the strategist (--ai) on for one fort
folder for a set span of game time, switched on by a file, ending by itself.

The keepers' window script starts every fort the same way (no --ai). To give
one fort the strategist for a game year without restarting anything with new
flags, write, in THAT fort folder's logs (fort A: DF-AI\\logs):

    logs\\ai-window.json   {"on": true, "years": 1}

The overseer reads it every cycle. The first cycle that sees it stamps the
window on the fort then loaded (its key, the game tick it started at, the
tick it ends at) in logs\\ai-window.state.json, connects the backend
(overseer.make_backend: config.json's strategist_backend, as with --ai) and
from then on the strategist reviews as with --ai (advice only while
config.json's "strategist_shadow" is not false: review.shadow_on). Only that
folder's overseer reads that file, so the other forts are untouched.

It ends by itself, with a journal line (kind "ai_window", "event": "ended")
and the spend, at the first of:
  - the game reaching its end tick (one game year from the start by default;
    "until_year": N instead ends it at the start of game year N);
  - the window's own token cap ("max_tokens", default MAX_TOKENS_DEFAULT);
  - "on": false in the request (or the request file removed);
  - another fort loaded in the folder (the window belongs to the fort it began on).
An ended window never starts again by itself: a new request (any change to
the file's contents) starts a new one.

The caps (on top of the bank, the panel's and the PC's real-day caps, which
all still hold):
  - "max_tokens": the whole window; nothing past it (the backend refuses too);
  - "season_tokens": each game season (default SEASON_TOKENS_DEFAULT);
  - "event_reserve": the share of each season's cap only event reviews may
    use (default EVENT_RESERVE_DEFAULT), so a siege late in a season is still
    reviewed.
Every call's tokens are counted in the state file by game season
("spent.seasons": {"256-winter": {"tokens", "calls", "events", "skipped"}}),
and each season's sum is journaled as it closes (kind "ai_window", "event":
"season"). python brain/ai_window.py prints the spend.

A --ai given on the command line is left as it was: the window never turns
off a backend it did not make. Never raises into the cycle; no key is ever
read, said or written here.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

REQUEST_FILE = "ai-window.json"
STATE_FILE = "ai-window.state.json"

TICKS_PER_DAY = 1200
TICKS_PER_YEAR = 12 * 28 * TICKS_PER_DAY

# Sizing (the dry run on fort A's live report of 25 Nov, y256 winter: one
# review ~5,600 tokens with a short answer; handoff-ai.md: 6,200-6,500
# uncached). At the sliders' Normal: a review every 14 game days (6 a season)
# plus up to 1 event review a month (3 a season), the season's own review
# falling on a routine one: ~9 a season, ~36 a year, ~235,000 tokens. Fort A
# runs a game year in ~2.5 real hours (25 Nov: a season ~36 minutes), so the
# whole year lands in one or two real days: the window's cap stays under the
# PC's 250,000 a real day.
MAX_TOKENS_DEFAULT = 240_000
SEASON_TOKENS_DEFAULT = 80_000
EVENT_RESERVE_DEFAULT = 0.2
MAKE_RETRY_TICKS = TICKS_PER_DAY      # a backend that couldn't connect: tried again a game day later
REVIEW_SIZE = 6_500                   # one review, for the words only (the counts are what was used)


class WindowClosed(Exception):
    """The window's cap or end reached: the call is refused before it is made."""


def _logs() -> Path:
    try:
        from dfhack import logs_dir
        return logs_dir()
    except Exception:  # noqa: BLE001
        return Path(os.environ.get("DFAI_LOG_DIR") or Path(__file__).resolve().parent.parent / "logs")


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(data, indent=1)
        try:
            from dfhack import write_atomic
            write_atomic(path, text)
        except ImportError:
            path.write_text(text, encoding="utf-8")
    except OSError:
        pass


# (r6 c2) kept local: unlike util's helpers (a default, a floor, nan/inf refused)
def _int(v, default, lo=0):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        return default
    return max(lo, int(v))


def _share(v, default):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v < 1:
        return default
    return float(v)


def signature(req) -> str:
    """A request's identity: any change to its contents is a new window."""
    return hashlib.sha1(json.dumps(req, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]


def caps(req: dict) -> dict:
    return {"max_tokens": _int(req.get("max_tokens"), MAX_TOKENS_DEFAULT, 1),
            "season_tokens": _int(req.get("season_tokens"), SEASON_TOKENS_DEFAULT, 1),
            "event_reserve": _share(req.get("event_reserve"), EVENT_RESERVE_DEFAULT)}


def _abs(state: dict) -> int | None:
    d = state.get("date") if isinstance(state, dict) else None
    if not isinstance(d, dict) or "error" in d or "date" in (state.get("_errors") or {}):
        return None
    y, t = d.get("year"), d.get("tick")
    if isinstance(y, bool) or isinstance(t, bool) or not isinstance(y, int) or not isinstance(t, int):
        return None
    return y * TICKS_PER_YEAR + t


def _season(state: dict) -> str | None:
    d = state.get("date") if isinstance(state, dict) else None
    if not isinstance(d, dict) or not isinstance(d.get("year"), int) or not isinstance(d.get("season"), str):
        return None
    return f"{d['year']}-{d['season']}"


def _date_words(tick: int) -> str:
    y, t = divmod(int(tick), TICKS_PER_YEAR)
    season = ("spring", "summer", "autumn", "winter")[min(3, t // (3 * 28 * TICKS_PER_DAY))]
    return f"y{y} {season} (day {t // TICKS_PER_DAY + 1} of the year)"


class Window:
    """One folder's window: the request, its state, the backend it made."""

    def __init__(self, logs: Path | None = None):
        self.logs = logs
        self.made = None              # the backend this window made (wrapped), or None
        self.cli = False              # a backend from --ai: the window leaves it alone
        self.retry_at = None          # a failed connect: the tick to try again
        self.season = None            # the cycle's game season (for the counts)
        self.active = False           # a window is open this cycle (the caps apply)

    # --- files -----------------------------------------------------------------
    def _dir(self) -> Path:
        return self.logs if self.logs is not None else _logs()

    def request(self):
        r = _read(self._dir() / REQUEST_FILE)
        return r if isinstance(r, dict) else None

    def state(self) -> dict:
        s = _read(self._dir() / STATE_FILE)
        return s if isinstance(s, dict) else {}

    def save(self, st: dict) -> None:
        _write(self._dir() / STATE_FILE, st)

    # --- the cycle's hook --------------------------------------------------------
    def backend(self, cli_backend, state: dict, key: str | None, make, say=print, journal=None):
        """The backend this cycle reviews with: the command line's if given,
        else this window's while it is open, else None. Opens, counts and
        closes the window (with its journal lines). Never raises."""
        try:
            return self._backend(cli_backend, state, key, make, say, journal)
        except Exception as e:  # noqa: BLE001 - the window never stops a cycle
            self.active = False
            try:
                say(f"AI window: not read this cycle ({type(e).__name__}); no review from it now.")
            except Exception:  # noqa: BLE001
                pass
            return cli_backend

    def _journal(self, journal, key, state, entry):
        if journal is None:
            return
        try:
            journal({"kind": "ai_window", "fort": key, "date": (state or {}).get("date"), **entry})
        except Exception:  # noqa: BLE001
            pass

    def _backend(self, cli_backend, state, key, make, say, journal):
        self.active = False
        if cli_backend is not None and cli_backend is not self.made:
            self.cli = True
            return cli_backend          # --ai on the command line: as before
        now, season = _abs(state), _season(state)
        req = self.request()
        st = self.state()
        sig = signature(req) if req is not None else None
        if st.get("request") and st.get("request") != sig and not st.get("ended"):
            # the request changed or went away under an open window: closed first
            self._close(st, "the request changed or was removed", key, state, say, journal)
            st = self.state()
        if req is None or req.get("on") is not True:
            if st.get("request") == sig and not st.get("ended") and st.get("start_tick") is not None:
                self._close(st, "switched off (\"on\": false)", key, state, say, journal)
            self.made = None
            return None
        if now is None or key is None:
            return self.made if (st.get("request") == sig and not st.get("ended")) else None
        if st.get("request") != sig:
            st = self._open(req, sig, now, key, state, say, journal)
        if st.get("ended"):
            self.made = None
            return None
        if st.get("fort") != key:
            self._close(st, f"another fort is loaded ({key}; the window was {st.get('fort')}'s)",
                        key, state, say, journal)
            self.made = None
            return None
        self._season_turn(st, season, key, state, journal)
        c = caps(req)
        spent = _spent(st)
        if now >= int(st.get("until_tick") or 0):
            self._close(st, f"its game time is over ({_date_words(now)})", key, state, say, journal)
            self.made = None
            return None
        if spent["total"] >= c["max_tokens"]:
            self._close(st, f"its token cap is used ({spent['total']:,} of {c['max_tokens']:,})",
                        key, state, say, journal)
            self.made = None
            return None
        self.active = True
        if self.made is None:
            if self.retry_at is not None and now < self.retry_at:
                return None
            inner = make()
            if inner is None:
                self.retry_at = now + MAKE_RETRY_TICKS
                say("AI window: the strategist could not connect (see above); tried again a game day later.")
                return None
            self.retry_at = None
            self.made = Capped(inner, self)
            try:
                from review import SHADOW_WORDS, shadow_on
                if shadow_on():
                    say(SHADOW_WORDS)
            except Exception:  # noqa: BLE001
                pass
        return self.made

    def _open(self, req, sig, now, key, state, say, journal) -> dict:
        years = req.get("years", 1)
        until = None
        uy = req.get("until_year")
        if isinstance(uy, int) and not isinstance(uy, bool):
            until = uy * TICKS_PER_YEAR
        elif not isinstance(years, bool) and isinstance(years, (int, float)) and 0 < years <= 5:
            until = now + int(years * TICKS_PER_YEAR)
        else:
            until = now + TICKS_PER_YEAR
        c = caps(req)
        st = {"request": sig, "fort": key, "start_tick": now, "until_tick": until,
              "start": _date_words(now), "until": _date_words(until),
              "opened_at": datetime.now().isoformat(timespec="seconds"),
              "caps": c, "spent": {"total": 0, "calls": 0, "events": 0, "skipped": 0, "seasons": {}},
              "season": _season(state), "ended": None}
        if until <= now:
            st["ended"] = {"why": f"its end ({_date_words(until)}) is already past", "tick": now,
                           "at": st["opened_at"]}
        self.save(st)
        if st["ended"]:
            say(f"AI window: not opened: {st['ended']['why']}.")
            self._journal(journal, key, state, {"event": "refused", "why": st["ended"]["why"]})
            return st
        say(f"AI window open for this fort: the strategist reviews from {st['start']} until {st['until']}, "
            f"at most {c['max_tokens']:,} tokens in all and {c['season_tokens']:,} a game season "
            f"({int(c['event_reserve'] * 100)}% of each season kept for event reviews).")
        self._journal(journal, key, state, {"event": "opened", "start_tick": now, "until_tick": until,
                                            "caps": c})
        return st

    def _season_turn(self, st, season, key, state, journal) -> None:
        self.season = season
        last = st.get("season")
        if season is None or season == last:
            return
        if last:
            row = _spent(st)["seasons"].get(last) or {"tokens": 0, "calls": 0, "events": 0, "skipped": 0}
            self._journal(journal, key, state, {"event": "season", "season": last, **row,
                                                "total": _spent(st)["total"]})
        st["season"] = season
        self.save(st)

    def _close(self, st, why, key, state, say, journal) -> None:
        now = _abs(state)
        last = st.get("season")
        sp = _spent(st)
        if last and last in sp["seasons"]:
            self._journal(journal, key, state, {"event": "season", "season": last, **sp["seasons"][last],
                                                "total": sp["total"], "partial": True})
        st["ended"] = {"why": why, "tick": now, "at": datetime.now().isoformat(timespec="seconds")}
        self.save(st)
        self.active = False
        say(f"AI window closed: {why}. The strategist used {sp['total']:,} tokens in {sp['calls']} call(s) "
            f"({sp['events']} for events); the local planner runs on alone.")
        self._journal(journal, st.get("fort") or key, state, {"event": "ended", "why": why, "spent": sp,
                                                              "start_tick": st.get("start_tick"),
                                                              "end_tick": now})

    # --- the caps -----------------------------------------------------------------
    def can_spend(self, estimate: int, important: bool) -> tuple[bool, str]:
        """review.maybe_review asks before each review: the window's caps."""
        if not self.active:
            return True, ""
        st = self.state()
        req = self.request() or {}
        c = st.get("caps") if isinstance(st.get("caps"), dict) else caps(req)
        sp = _spent(st)
        est = max(0, int(estimate or 0))
        if sp["total"] + est > c["max_tokens"]:
            return False, f"the AI window's cap ({sp['total']:,} of {c['max_tokens']:,} used)"
        used = int((sp["seasons"].get(self.season) or {}).get("tokens") or 0)
        room = c["season_tokens"] if important else int(c["season_tokens"] * (1 - c["event_reserve"]))
        if used + est > room:
            return False, (f"the AI window's season cap ({used:,} of {c['season_tokens']:,} this season"
                           + ("" if important else ", the rest kept for event reviews") + ")")
        return True, ""

    def note_skip(self) -> None:
        if not self.active:
            return
        st = self.state()
        sp = _spent(st)
        sp["skipped"] += 1
        row = sp["seasons"].setdefault(self.season or "?", {"tokens": 0, "calls": 0, "events": 0, "skipped": 0})
        row["skipped"] = int(row.get("skipped") or 0) + 1
        st["spent"] = sp
        self.save(st)

    def note_spend(self, used: int, important: bool) -> None:
        st = self.state()
        if not st.get("request"):
            return
        sp = _spent(st)
        used = max(0, int(used or 0))
        sp["total"] += used
        sp["calls"] += 1
        sp["events"] += 1 if important else 0
        row = sp["seasons"].setdefault(self.season or "?", {"tokens": 0, "calls": 0, "events": 0, "skipped": 0})
        row["tokens"] = int(row.get("tokens") or 0) + used
        row["calls"] = int(row.get("calls") or 0) + 1
        row["events"] = int(row.get("events") or 0) + (1 if important else 0)
        st["spent"] = sp
        self.save(st)

    def closed_now(self) -> bool:
        """The hard stop: past the whole cap, or ended."""
        st = self.state()
        if st.get("ended"):
            return True
        c = st.get("caps") if isinstance(st.get("caps"), dict) else caps(self.request() or {})
        return _spent(st)["total"] >= c["max_tokens"]


def _spent(st: dict) -> dict:
    sp = st.get("spent") if isinstance(st.get("spent"), dict) else {}
    out = {k: _int(sp.get(k), 0) for k in ("total", "calls", "events", "skipped")}
    out["seasons"] = sp.get("seasons") if isinstance(sp.get("seasons"), dict) else {}
    return out


class Capped:
    """The window's backend: the real one behind the window's hard stop, each
    call's tokens counted to the window by season."""

    def __init__(self, inner, window: Window):
        self.inner, self.window = inner, window
        self.name = getattr(inner, "name", type(inner).__name__)

    def __getattr__(self, k):
        return getattr(self.inner, k)

    def ask(self, *a, **kw):
        if self.window.closed_now():
            raise WindowClosed("the AI window is closed or its token cap is used: no call made")
        reply = self.inner.ask(*a, **kw)
        try:
            used = getattr(reply, "budget_tokens", None)
            if not isinstance(used, (int, float)):
                used = int(getattr(reply, "input_tokens", 0) or 0) + int(getattr(reply, "output_tokens", 0) or 0)
            self.window.note_spend(int(used), bool(kw.get("important")))
        except Exception:  # noqa: BLE001  (counting never loses the answer)
            pass
        return reply


WINDOW = Window()


def report(logs: Path | None = None) -> str:
    """The spend in words (python brain/ai_window.py)."""
    w = Window(logs)
    st, req = w.state(), w.request()
    if not st:
        return ("No AI window has run in this folder."
                + (f" A request is waiting: {json.dumps(req)}" if req else ""))
    sp = _spent(st)
    lines = [f"AI window for {st.get('fort')}: {st.get('start')} -> {st.get('until')}"
             + (f"; ended: {st['ended'].get('why')}" if st.get("ended") else "; open"),
             f"caps: {json.dumps(st.get('caps'))}",
             f"spent: {sp['total']:,} tokens, {sp['calls']} call(s), {sp['events']} for events, "
             f"{sp['skipped']} skipped by the caps"]
    for k, row in sorted(sp["seasons"].items()):
        lines.append(f"  {k}: {int(row.get('tokens') or 0):,} tokens, {row.get('calls', 0)} call(s), "
                     f"{row.get('events', 0)} event(s), {row.get('skipped', 0)} skipped")
    return "\n".join(lines)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    print(report(Path(sys.argv[1]) if len(sys.argv) > 1 else None))

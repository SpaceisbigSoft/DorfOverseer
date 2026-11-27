"""(F2b) One attempt ledger for every action (see the comment below).

Kept out of planner_core_refusals: planner_core's names and each part's names
are pinned (tests/test_r7_d3.py); planner_core_refusals.note_refusal books
here through a local import, and planner_refusal_streak.wait consults it."""

from __future__ import annotations

import hashlib
import json
import re

from digest import _d
from planner_core_base import EMERGENCY, TICKS_PER_DAY
from planner_core_refusals import OWN_PACE, is_release

# --- (F2b) One attempt ledger for every action ---------------------------------------------
# The back-offs above are keyed by rule plus a whitelist of parameters
# (REFUSAL_KEYS): a site the bridge chose in Lua is invisible, a refusal under a
# new bridge version is tried again at once, and the waits are in game days,
# which pass in about one cycle in a fast fort (D, 26 Nov: a butcher's shop
# refused about 19 times in 7 h, its waits already doubled to 64 then 84 game
# days). This ledger is one record per attempt key:
#   * the key: the action's type and ALL its parameters, canonicalised
#     (attempt_key); the record holds the target the bridge answered with
#     (reply_target: a building, project, zone, site or x/y/z) and the reason
#     normalised (norm_reason: counts and bracketed lists aside);
#   * the outcomes: "ok" (done), "refused", "error" (a Lua error, or no answer),
#     "none" (done, nothing changed: record_no_effect, from a caller that can tell);
#   * the hold: a refusal or a Lua error holds the key 1 game day, then 2, 4 ...
#     (LEDGER_MAX_DAYS), and at least LEDGER_FIRST_MINUTES real minutes, doubling;
#     the same outcome for the same target with the same reason LEDGER_STREAK
#     times in a row holds it for the backstop (LEDGER_BACKSTOP_DAYS game days and
#     LEDGER_BACKSTOP_MINUTES real minutes, the longer, doubling each time after,
#     capped), said once ("held: <action> at <target>: <reason> x3"). An unsure
#     failure ("none", no answer) holds only from the streak on.
#   * a hold ends early when what the action depends on changes (fingerprint:
#     NOT the bridge's version; the levels finished when the reason is about
#     room, the wells for water, the farm plots for farms, the dwarves when it is
#     about people); a changed parameter is another key; a changed target or
#     reason begins the streak again.
# Kept in Memory.repeat_book["attempts"] (old saves: empty), at most LEDGER_KEEP
# records (the working memory's budget). Consulted in select() through
# planner_refusal_streak.wait (the same exemptions: emergencies, critical
# defence, releases, transient survival steps). The module constants may be
# overridden by a cfg key of the same name in lower case (kept out of
# PLANNER_CONFIG, whose keys are pinned by test_r7_d6).
LEDGER_BOOK = "attempts"
LEDGER_FIRST_DAYS = 1
LEDGER_MAX_DAYS = 28
LEDGER_FIRST_MINUTES = 2
LEDGER_MAX_MINUTES = 60
LEDGER_STREAK = 3
LEDGER_BACKSTOP_DAYS = 28
LEDGER_BACKSTOP_MAX_DAYS = 336
LEDGER_BACKSTOP_MINUTES = 60
LEDGER_BACKSTOP_MAX_MINUTES = 720
LEDGER_KEEP = 24
LEDGER_WHY_MAX = 80
LEDGER_FORGET_DAYS = 2 * 336
NO_EFFECT_WORDS = "done, nothing changed"
TARGET_KEYS = ("building_id", "project_id", "zone_id", "entrance_id", "site_id", "pile_id", "location_id",
               "squad_id", "unit_id", "item_id", "workshop")
_LUA_ERROR = re.compile(r"\.lua:\d+:|attempt to (index|call|compare|perform|concatenate)|stack traceback")
_COORD = re.compile(r"\(?\b(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\b\)?")
_PEOPLE = re.compile(r"\b(nobody|no one|dwarf|dwarves|citizens?|free|worker|workers|soldiers?)\b", re.I)


def _lc(cfg, name: str):
    """A ledger constant, or its cfg override (the name in lower case)."""
    v = _d(cfg).get(name.lower())
    default = globals()[name]
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else default


def _canon(v):
    """A parameter's value in a stable form: dicts by key, lists of plain values sorted."""
    if isinstance(v, dict):
        return {str(k): _canon(x) for k, x in sorted(v.items(), key=lambda kv: str(kv[0]))}
    if isinstance(v, (list, tuple)):
        items = [_canon(x) for x in v]
        if all(isinstance(x, (int, float, str, bool)) or x is None for x in items):
            try:
                return sorted(items, key=lambda x: (str(type(x)), x))
            except TypeError:
                return sorted(items, key=str)
        return items
    return v


def attempt_text(action) -> str:
    """The action's type and all its parameters, canonicalised (dry_run aside)."""
    a = {k: v for k, v in _d(action).items() if k != "dry_run"}
    return json.dumps(_canon(a), sort_keys=True, default=str, separators=(",", ":"))


def attempt_key(p) -> str:
    """The ledger's key of a proposal (or a bare action): short, stable."""
    a = getattr(p, "action", p)
    return hashlib.sha1(attempt_text(a).encode("utf-8")).hexdigest()[:12]


def _label(a: dict) -> str:
    a = _d(a)
    bits = [str(a.get("type") or "action").replace("_", " ")]
    for k in ("kind", "recipe", "name", "job", "what", "post", "office"):
        if isinstance(a.get(k), (str, int)) and not isinstance(a.get(k), bool):
            bits.append(str(a[k]))
            break
    return " ".join(bits)[:48]


def reply_target(r) -> str:
    """The target the bridge answered with: a building, project, zone, site ...
    or a tile (x/y/z, `at`, `pos`, or "x, y, z" in its words). "" if none."""
    r = _d(r)
    if isinstance(r.get("_target"), str) and r["_target"]:
        return r["_target"][:32]
    for k in TARGET_KEYS:
        v = r.get(k)
        if isinstance(v, (int, str)) and not isinstance(v, bool) and str(v) != "":
            return f"{k.replace('_id', '')} {v}"[:32]
    for src in (r, _d(r.get("at")), _d(r.get("pos")), _d(r.get("site"))):
        if all(isinstance(src.get(c), (int, float)) for c in ("x", "y", "z")):
            return f"({src['x']},{src['y']},{src['z']})"
    for k in ("at", "pos"):
        v = r.get(k)
        if isinstance(v, (list, tuple)) and 2 <= len(v) <= 3 and all(isinstance(c, (int, float)) for c in v):
            return "(" + ",".join(str(c) for c in v) + ")"
    m = _COORD.search(str(r.get("error") or ""))
    return f"({m.group(1)},{m.group(2)},{m.group(3)})" if m else ""


def refusal_target(reply) -> dict:
    """(F2b) {"_target": ...} from a refusal the bridge raised (BridgeError.reply),
    to go in the answer the planner records (its other fields are left out:
    they were never read for a refusal raised so); {} when it named none."""
    t = reply_target(reply) if isinstance(reply, dict) else ""
    return {"_target": t} if t else {}


_BRACKETS_RE = re.compile(r"\s*\([^()]*\)")


def norm_reason(text) -> str:
    """A reason without its counts: numbers and what is in brackets aside (the
    bridge's counts and lists), spaces folded."""
    t = str(text or "").strip()
    for _ in range(4):
        u = _BRACKETS_RE.sub("", t)
        if u == t:
            break
        t = u
    t = re.sub(r"\d+", "#", t)
    return re.sub(r"\s+", " ", t).strip()[:LEDGER_WHY_MAX]


def fingerprint(p, state, why: str = "") -> dict:
    """What a held attempt depends on: when it changes, the hold ends. Never
    the bridge's version."""
    s = _d(state)
    if not s:
        return {}
    fp = {}
    try:
        import planner_refusal_streak as _rs      # (local: it imports this module)
        from planner_core_fort import levels_done
        why = str(why or "")
        if _rs.SPACE_WORDS.search(why) or _rs._water(p) or _rs._farm(p):
            fp["levels"] = levels_done(s)
        if _rs._water(p):
            fp["wells"] = _d(_d(s.get("buildings")).get("other")).get("Well", 0)
        if _rs._farm(p):
            f = _d(s.get("farms"))
            fp["plots"] = f.get("plots") if isinstance(f.get("plots"), int) else len(f.get("plot_list") or [])
        adults = _d(s.get("dwarves")).get("adults")
        if _PEOPLE.search(why) and isinstance(adults, int):
            fp["dwarves"] = adults
    except Exception:  # noqa: BLE001  (unknown: no fingerprint, the time backstop only)
        return {}
    return fp


def ledger_book(memory) -> dict:
    """Memory.repeat_book["attempts"]: {attempt_key: record}."""
    from planner_backoff import repeat_book
    return repeat_book(memory, LEDGER_BOOK)


def outcome_of(r) -> str | None:
    """"ok", "refused", "error", or None (not counted: the in-game halt, an
    answer to wait, a search cut short: their own back-offs)."""
    r = _d(r)
    ok = r.get("ok")
    if ok is True:
        return "ok"
    if r.get("halted") or r.get("waiting") or r.get("timed_out"):
        return None
    if ok is None:
        return "error"            # no answer: may have gone through (held only from the streak on)
    if ok is False:
        return "error" if _LUA_ERROR.search(str(r.get("error") or "")) else "refused"
    return None


def _skip(p) -> bool:
    a = _d(getattr(p, "action", None))
    return (not a or bool(a.get("dry_run")) or getattr(p, "rule", None) in EMERGENCY
            or a.get("type") in OWN_PACE or is_release(a))


def record_attempt(memory, p, r, now: int, state=None, cfg=None) -> dict | None:
    """(F2b) One attempt answered: the ledger's record for its key updated.
    Returns the record (None when not counted)."""
    if memory is None or not isinstance(now, int) or _skip(p):
        return None
    out = outcome_of(r)
    if out is None:
        return None
    r = _d(r)
    why = "" if out == "ok" else norm_reason(r.get("error") or r.get("note") or out)
    return _book_outcome(memory, p, out, reply_target(r), why, now, state, cfg)


def record_no_effect(memory, key, now: int, state=None, cfg=None, why: str = NO_EFFECT_WORDS,
                     p=None) -> dict | None:
    """(F2b) The hook for "done, nothing changed": an attempt answered ok whose
    effect the caller could not see. key: attempt_key(p) (or the proposal). Its
    target is the one its last ok carried. Held from LEDGER_STREAK in a row."""
    if memory is None or not isinstance(now, int):
        return None
    if not isinstance(key, str):
        p, key = key, attempt_key(key)
    book = ledger_book(memory)
    old = _d(book.get(key))
    if p is None:
        p = _Bare(old.get("type"))
    return _book_outcome(memory, p, "none", str(old.get("t") or ""), norm_reason(why), now, state, cfg, key=key)


class _Bare:
    """A proposal-like stand-in for record_no_effect called with a key only."""
    rule = ""

    def __init__(self, t):
        self.action = {"type": t} if t else {}


def _book_outcome(memory, p, out: str, target: str, why: str, now: int, state, cfg, key=None) -> dict:
    book = ledger_book(memory)
    key = key or attempt_key(p)
    a = _d(getattr(p, "action", None))
    old = _d(book.get(key))
    if isinstance(old.get("at"), int) and old["at"] > now:
        old = {}                               # the game's time went back (an older save)
    if out == "none" and old.get("o") == "ok" and old.get("ns"):
        old = dict(old, o="none", s=old["ns"], n=old["ns"], w=old.get("nw"))
    fp = fingerprint(p, state, why)
    rec = {"type": a.get("type") or old.get("type"), "l": _label(a) if a else old.get("l", ""),
           "o": out, "t": target, "at": now}
    if out == "ok":
        rec.update(n=0, s=0)
        if old.get("o") == "none" or (old.get("o") == "ok" and old.get("ns")):
            # a "none" streak goes on through the ok its caller books first (record_no_effect)
            rec.update(ns=old.get("s") if old.get("o") == "none" else old.get("ns"),
                       nw=old.get("w") if old.get("o") == "none" else old.get("nw"))
        book[key] = rec
        _ledger_prune(book, now, cfg)
        return rec
    same = (old.get("o") == out and old.get("t") == target and old.get("w") == why
            and old.get("f", {}) == fp)
    s = int(old.get("s") or 0) + 1 if same else 1
    n = int(old.get("n") or 0) + 1 if old.get("o") not in (None, "ok") else 1
    rec.update(w=why, n=n, s=s)
    if fp:
        rec["f"] = fp
    sure = out in ("refused", "error") and not (out == "error" and why.startswith("no reply"))
    streak = int(_lc(cfg, "LEDGER_STREAK"))
    ticks = 0
    if s >= streak:
        b = min(s - streak, 20)
        days = min(_lc(cfg, "LEDGER_BACKSTOP_MAX_DAYS"), _lc(cfg, "LEDGER_BACKSTOP_DAYS") * 2 ** b)
        mins = min(_lc(cfg, "LEDGER_BACKSTOP_MAX_MINUTES"), _lc(cfg, "LEDGER_BACKSTOP_MINUTES") * 2 ** b)
        ticks = max(int(days * TICKS_PER_DAY), _real(state, mins))
        rec["x"] = s
        if s == streak:
            rec["say"] = True                  # said once: "held: ... x3"
    elif sure:
        b = min(n - 1, 20)
        days = min(_lc(cfg, "LEDGER_MAX_DAYS"), _lc(cfg, "LEDGER_FIRST_DAYS") * 2 ** b)
        mins = min(_lc(cfg, "LEDGER_MAX_MINUTES"), _lc(cfg, "LEDGER_FIRST_MINUTES") * 2 ** b)
        ticks = max(int(days * TICKS_PER_DAY), _real(state, mins))
    if ticks > 0:
        rec["u"] = now + ticks
    book[key] = rec
    _ledger_prune(book, now, cfg)
    return rec


def _real(state, minutes) -> int:
    from planner_backoff import real_ticks
    return real_ticks(state, minutes)


def _ledger_prune(book: dict, now: int, cfg) -> None:
    forget = int(_lc(cfg, "LEDGER_FORGET_DAYS")) * TICKS_PER_DAY
    for k in [k for k, v in book.items()
              if not isinstance(v, dict) or not isinstance(v.get("at"), int) or not 0 <= now - v["at"] <= forget]:
        book.pop(k, None)
    most = int(_lc(cfg, "LEDGER_KEEP"))
    if len(book) > most:
        # the oldest done (ok) records go first, then the oldest of the rest; of the holds still
        # running, the one ending first goes first (a streak's backstop is kept longest)
        def rank(k):
            v = book[k]
            holding = isinstance(v.get("u"), int) and now < v["u"]
            return (holding, v.get("o") != "ok", v["u"] if holding else v["at"])
        for k in sorted(book, key=rank)[:len(book) - most]:
            book.pop(k, None)


def ledger_wait(memory, p, state, now: int, cfg=None):
    """(F2b) (days left, record) while the ledger holds this attempt, else None.
    The hold ends when its time is over or what it depends on changed
    (fingerprint); the bridge's version is not such a change."""
    if memory is None or not isinstance(now, int) or _skip(p):
        return None
    rec = _d(_d(_d(getattr(memory, "repeat_book", None)).get(LEDGER_BOOK)).get(attempt_key(p)))
    until, at = rec.get("u"), rec.get("at")
    if not isinstance(until, int) or not isinstance(at, int) or at > now or not now < until:
        return None
    if state is not None and rec.get("f", {}) != fingerprint(p, state, str(rec.get("w") or "")):
        return None
    return max(1, -(-(until - now) // TICKS_PER_DAY)), rec


def ledger_held_line(p, days: int, rec: dict) -> str:
    rec = _d(rec)
    where = f" at {rec['t']}" if rec.get("t") else ""
    what = {"refused": "refused", "error": "failed", "none": "done and nothing changed"}.get(rec.get("o"), "failed")
    if rec.get("x"):
        return (f"{p.rule}: held: {rec.get('l') or 'its step'}{where}: {rec.get('w') or what} x{rec['x']}; "
                f"asks again in {days} day(s), sooner if the fort changes")
    return (f"{p.rule}: {rec.get('l') or 'its step'}{where} {what} ({str(rec.get('w') or '')[:80]}); "
            f"tries again in {days} day(s), sooner if the fort changes")


def ledger_notes(memory) -> list[str]:
    """The streak holds begun since the last cycle, each said once."""
    out = []
    book = _d(_d(getattr(memory, "repeat_book", None)).get(LEDGER_BOOK))
    for _k, v in sorted(book.items(), key=lambda kv: str(kv[0])):
        if isinstance(v, dict) and v.get("say"):
            where = f" at {v['t']}" if v.get("t") else ""
            out.append(f"held: {v.get('l') or v.get('type') or 'an action'}{where}: {v.get('w') or v.get('o')} "
                       f"x{v.get('x') or LEDGER_STREAK}")
    return out


def ledger_said(memory) -> None:
    book = _d(_d(getattr(memory, "repeat_book", None)).get(LEDGER_BOOK))
    for v in book.values():
        if isinstance(v, dict) and v.get("say"):
            v["say"] = False

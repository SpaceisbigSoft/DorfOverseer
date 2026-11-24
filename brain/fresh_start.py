"""(0.105.100) The planned restart, "a fresh start" (the owner, 24 Nov 03:12:
"save and close the games occasionally and then reopen them; they benefit
from not running for too many hours": every 3 hours).

Every `fresh_start_hours` (config.json, default 3; 0 = off) of the game
running under this keeper, counted from the moment the reviver saw it load
the fort (not the keeper's start), the keeper (brain/keeper.py, --revive
only: the reviver reopens the game) asks for a fresh start:

  * staggered: on this keeper's first period, (port - 5000) sixths of a
    period later (5000-5005: 0, 30, 60 ... 150 min at 3 h), so the six forts
    started together don't all close together; and never while another fort's
    game is starting, loading or being freshly started (each keeper writes its
    own small file in the PC-wide folder beside the token cap's day file,
    %LOCALAPPDATA%\\DF-AI\\fresh-starts\\; brain/tokens.py pc_file_from);
  * only at a calm moment, from the overseer's own word (logs/calm.json,
    written each cycle by note_cycle and each poll by note_status): no threat
    that can reach the dwarves, no invader on the map, no alarm up, none of
    the AI's gates shut, no tantrum or berserk loose, the game not paused or
    halted, not saving, not a season's last days (DF's autosave comes then).
    Strange moods survive a save: not waited for. Not calm: re-checked each
    chore; `fresh_start_max_wait_hours` (2) past due, it goes at the next
    moment with no threat on the map (paused, halted and saving still hold);
  * the overseer stopped, the game saved (DFHack's quicksave, the path the
    overseer's own save before a new level takes), the save waited for until
    a save folder of the fort is newer than the request and has stayed still
    SAVE_STABLE_S, the game closed by its pid (revive.kill_command: taskkill;
    DFHack has no clean quit, `die` ends DF without a word, and a taskkill
    after a confirmed save is what the reviver does to a hung game anyway),
    and its process waited out;
  * the keeper's own Python then starts again (a new copy with the same
    arguments, the folder's lock handed over; no change to start-keepers.ps1),
    and its reviver opens the game and loads the newest save, the one just
    written (revive.load_candidates: newest first). logs/fresh-start.json
    tells the new keeper it was planned: its reviver says "Revive (planned):"
    so the soak report and the run check never count it as a crash.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

DEFAULT_HOURS = 3.0
DEFAULT_MAX_WAIT_H = 2.0
FORTS = 6                     # the keepers on the owner's PC (start-keepers.ps1)
BASE_PORT = 5000
CALM_STALE_S = 1200           # the overseer's word older than this: not known (it's stopped, or stuck)
STATUS_STALE_S = 300          # ... its last poll of the game's status older than this: not known
SAVE_WAIT_S = 900             # the save not written in this long: given up (the game left running)
SAVE_STABLE_S = 30            # the new save unchanged this long: written
CLOSE_WAIT_S = 120            # the game's process gone within this
RETRY_S = 3600                # a fresh start that couldn't be done: tried again this much later
PC_ALIVE_S = 600              # another keeper's PC-wide file older than this: that keeper is gone
PC_BUSY_MAX_S = 2700          # ... busy for longer than this: stuck (a fallen fort, a broken game): not waited for
PC_WRITE_EVERY_S = 120
PLANNED_MAX_S = 1800          # the new keeper's "planned" reopening at most this long, then as any revive
SAY_EVERY_S = 3600


def _logs() -> Path:
    from dfhack import logs_dir
    return logs_dir()


def calm_file() -> Path:
    return _logs() / "calm.json"


def mark_file() -> Path:
    return _logs() / "fresh-start.json"


# (r6 c2) kept local: a finite, non-negative number of hours, else the default
def _hours_or(v, default):
    import math
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
        return default
    return float(v)


def settings(cfg: dict | None = None) -> tuple[float, float]:
    """(hours, max wait hours) from config.json: fresh_start_hours (0 = off)
    and fresh_start_max_wait_hours."""
    if cfg is None:
        from dfhack import read_config
        cfg = read_config()
    cfg = cfg if isinstance(cfg, dict) else {}
    return (_hours_or(cfg.get("fresh_start_hours", DEFAULT_HOURS), DEFAULT_HOURS),
            _hours_or(cfg.get("fresh_start_max_wait_hours", DEFAULT_MAX_WAIT_H), DEFAULT_MAX_WAIT_H))


def stagger_s(port: int | None, hours: float) -> float:
    """This fort's offset on its first period: (port - 5000) sixths of it
    (the six keepers' ports are 5000-5005); 0 for an unknown port."""
    if not isinstance(port, int) or isinstance(port, bool):
        return 0.0
    return ((port - BASE_PORT) % FORTS) * hours * 3600.0 / FORTS


# ---------------------------------------------------------------------------
# the overseer's side: the calm word (logs/calm.json)
# ---------------------------------------------------------------------------

_LIVE: dict = {}
_WRITTEN: dict = {"at": float("-inf"), "text": ""}
WRITE_EVERY_S = 60


from digest import _d, _l  # noqa: E402  (r6 c2) the shared ones




def calm_verdict(state: dict, memory=None) -> tuple[list[str], bool]:
    """Why the fort isn't calm (empty: calm), and whether a threat is on the
    map at all (the max wait's test): from the full report."""
    s = _d(state)
    why = []
    o = _d(s.get("others_on_map"))
    threats = [t for t in _l(o.get("threats")) if isinstance(t, dict)]
    reach = int(o.get("threats_that_can_reach_dwarves") or 0) if isinstance(
        o.get("threats_that_can_reach_dwarves"), (int, float)) else 0
    reach = max(reach, sum(1 for t in threats if t.get("can_reach_dwarves") is True))
    invaders = [t for t in threats if t.get("invader")]
    great = [t for t in threats if t.get("great_danger") and t.get("can_reach_dwarves") is not False]
    if reach:
        why.append(f"{reach} threat(s) can reach the dwarves")
    if invaders:
        why.append(f"{len(invaders)} invader(s) on the map (a siege or a raid)")
    siege = not invaders and bool(_d(s.get("military")).get("siege"))
    if siege:
        why.append("a siege")
    if great and not reach:
        why.append("a great danger on the map")
    if s.get("civ_alert") is True:
        why.append("the civilian alarm is up")
    try:
        from planner_gates_lockdown import ai_gates_shut
        if ai_gates_shut(s, memory):
            why.append("the AI's gates are shut")
    except Exception:  # noqa: BLE001  (a missing piece never makes it calm by mistake... nor stuck)
        pass
    t = _d(s.get("tantrums"))
    loose = int(t.get("loose") or 0) if isinstance(t.get("loose"), (int, float)) else 0
    if loose:
        why.append(f"{loose} tantrum(s) loose")
    if _l(_d(s.get("hazards")).get("berserk")) or (isinstance(t.get("berserk"), (int, float)) and t["berserk"]):
        why.append("a berserk dwarf loose")
    # (0.105.100, verifier) a siege the report names without its invaders listed
    # is a threat on the map too: the max wait never closes the game in one
    return why, bool(reach or invaders or great or siege)


def _write(now: float, force: bool = False) -> None:
    try:
        # (0.105.100, verifier) compared without its times: status_at changes each
        # poll, so the file was written at every poll instead of once a minute
        text = json.dumps({k: v for k, v in _LIVE.items() if k not in ("status_at", "cycle_at")},
                          sort_keys=True)
        same = text == _WRITTEN["text"]
        if same and not force and now - _WRITTEN["at"] < WRITE_EVERY_S:
            return
        from dfhack import write_atomic
        p = calm_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(p, json.dumps({**_LIVE, "written": now}))
        _WRITTEN.update(at=now, text=text)
    except Exception:  # noqa: BLE001  (never stops the overseer)
        pass


def note_status(st: dict, halted: bool = False, season_end: bool = False, now: float | None = None) -> None:
    """The overseer's loop, each poll of the game's status."""
    now = time.time() if now is None else now
    st = _d(st)
    _LIVE.update(status_at=now, in_fort=bool(st.get("in_fort")), paused=bool(st.get("paused")),
                 halted=bool(halted), saving=bool(st.get("saving")), season_end=bool(season_end))
    _write(now)


def note_cycle(state: dict, memory=None, fort: str | None = None, now: float | None = None) -> None:
    """The overseer's cycle, after a report with the threats in it."""
    now = time.time() if now is None else now
    if "others_on_map" not in _d(state):
        return                      # a pulse without the threats: the last full word stands
    why, threat = calm_verdict(state, memory)
    _LIVE.update(cycle_at=now, why=why, threat=threat, fort=fort)
    _write(now, force=True)


def read_calm(now: float | None = None, path: Path | None = None) -> tuple[bool | None, list[str], bool]:
    """(calm, why not, a threat on the map) from logs/calm.json: calm None
    when the overseer's word is too old to go by."""
    now = time.time() if now is None else now
    try:
        d = json.loads((path or calm_file()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, ["no word from the overseer yet"], True
    d = _d(d)
    cyc, sat = d.get("cycle_at"), d.get("status_at")
    if not isinstance(cyc, (int, float)) or now - cyc > CALM_STALE_S:
        return None, ["no recent report from the overseer"], True
    why = [w for w in _l(d.get("why")) if isinstance(w, str)]
    hold = []
    if not isinstance(sat, (int, float)) or now - sat > STATUS_STALE_S:
        hold.append("no recent word of the game's status")
    else:
        if not d.get("in_fort"):
            hold.append("no fort loaded")
        if d.get("halted"):
            hold.append("halted in the game (Ctrl-Shift-H)")
        if d.get("paused"):
            hold.append("the game is paused")
        if d.get("saving"):
            hold.append("the game is saving")
        if d.get("season_end"):
            hold.append("a season's last days (DF's autosave comes)")
    return (not why and not hold), hold + why, bool(d.get("threat")) or bool(hold)


# ---------------------------------------------------------------------------
# the PC-wide word: which keepers' games are starting, loading or restarting
# ---------------------------------------------------------------------------

PC_DIR: Path | None = None    # tests set this


def pc_dir() -> Path:
    if PC_DIR is not None:
        return Path(PC_DIR)
    try:
        import tokens
        from dfhack import read_config
        return tokens.pc_file_from(read_config()).parent / "fresh-starts"
    except Exception:  # noqa: BLE001
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) / "DF-AI" if base else Path.home() / ".df-ai") / "fresh-starts"


def label() -> str:
    from dfhack import PROJECT_ROOT
    return PROJECT_ROOT.name


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)[:60] or "fort"


def publish(me: str, busy: str | None, since: float | None, now: float) -> None:
    """This keeper's own line in the PC-wide folder, written whole."""
    try:
        d = pc_dir()
        d.mkdir(parents=True, exist_ok=True)
        from dfhack import write_atomic
        write_atomic(d / f"{_safe(me)}.json", json.dumps({"label": me, "busy": busy, "since": since, "at": now}))
    except Exception:  # noqa: BLE001
        pass


def others_busy(me: str, now: float) -> list[tuple[str, str, float]]:
    """Other keepers whose game is starting, loading or restarting now:
    (label, what, since), oldest first; a keeper gone quiet or stuck busy
    for long is not waited for."""
    out = []
    try:
        files = list(pc_dir().glob("*.json"))
    except OSError:
        return []
    for f in files:
        if f.stem == _safe(me):
            continue
        try:
            d = _d(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        at, since, busy = d.get("at"), d.get("since"), d.get("busy")
        if not busy or not isinstance(at, (int, float)) or now - at > PC_ALIVE_S:
            continue
        since = since if isinstance(since, (int, float)) else at
        if now - since > PC_BUSY_MAX_S:
            continue
        out.append((str(d.get("label") or f.stem), str(busy), float(since)))
    return sorted(out, key=lambda x: (x[2], x[0]))


def reviver_busy(rv) -> tuple[str | None, float | None]:
    """What this keeper's game is doing that the others should wait out:
    starting (down), at the title screen, loading; or None."""
    if rv is None:
        return None, None
    if getattr(rv, "loading", None):
        return "loading", rv.loading[1]
    if getattr(rv, "title_since", None) is not None:
        return "at the title screen", rv.title_since
    if getattr(rv, "down_since", None) is not None:
        return "starting", rv.down_since
    if getattr(rv, "planned", False):
        return "reopening", getattr(rv, "planned_since", None)
    return None, None


# ---------------------------------------------------------------------------
# the keeper's side: when one is due, and doing it
# ---------------------------------------------------------------------------

class FreshStart:
    """When a fresh start is due (`check`), and the PC-wide word (`publish_state`)."""

    def __init__(self, log, reviver, clock=time.time, cfg: dict | None = None, port: int | None = None,
                 after_fresh: bool = False, me: str | None = None):
        self.log, self.rv, self.clock = log, reviver, clock
        self.hours, self.max_wait_h = settings(cfg)
        if port is None:
            try:
                from dfhack import configured_port
                port = configured_port()
            except Exception:  # noqa: BLE001
                port = None
        self.port = port
        # the stagger on this keeper's first period only: a keeper started by
        # a fresh start keeps the spacing its predecessor had
        self.offset = 0.0 if after_fresh else stagger_s(port, self.hours)
        self.me = me or label()
        self.first_load: float | None = None
        self.load_seen: float | None = None
        self.due_since: float | None = None
        self.retry_at = float("-inf")
        self.said: dict = {}
        self.busy: str | None = None          # this keeper's own fresh start under way
        self.busy_since: float | None = None
        self.pc_written = (None, float("-inf"))
        self.busy_run: float | None = None    # (0.105.100, verifier) when this stretch of busy began

    def on(self) -> bool:
        return self.hours > 0 and self.rv is not None

    def period_s(self) -> float:
        return self.hours * 3600.0

    def first_line(self) -> str | None:
        if not self.on():
            return None
        return (f"Fresh start is on: every {self.hours:g} h of play the game is saved, closed and opened again at a "
                f"calm moment (within {self.max_wait_h:g} h of being due)"
                + (f"; this fort's first one {int(self.offset // 60)} min later than that (port {self.port}: "
                   "the forts take turns)" if self.offset else "") + ".")

    def _say(self, key: str, now: float, line: str) -> None:
        if now - self.said.get(key, float("-inf")) >= SAY_EVERY_S:
            self.said[key] = now
            self.log(line)

    def loaded_at(self) -> float | None:
        return getattr(self.rv, "world_since", None) if self.rv is not None else None

    def due_at(self) -> float | None:
        la = self.loaded_at()
        if la is None:
            return None
        if self.first_load is None:
            self.first_load = la
        if la != self.load_seen:
            self.load_seen, self.due_since = la, None   # a new load (a revive): a new period
        return la + self.period_s() + (self.offset if la == self.first_load else 0.0)

    def _held(self) -> str | None:
        rv = self.rv
        if getattr(rv, "loading", None) or getattr(rv, "wrong_load", None):
            return "the reviver is loading"
        try:
            import fallen
            import pin
            m = fallen.idle()
            if m and fallen.holds_for(m, pin.current()):
                return "the fort has fallen"
        except Exception:  # noqa: BLE001
            pass
        try:
            import session_end
            e = session_end.ending()
            if e:
                return e
        except Exception:  # noqa: BLE001
            pass
        return None

    def check(self, now: float | None = None) -> dict | None:
        """A fresh start to do now: {"hours": since the load, "how": why now},
        or None (not due, not calm, another game busy)."""
        now = self.clock() if now is None else now
        if not self.on() or now < self.retry_at:
            return None
        due = self.due_at()
        if due is None or now < due:
            return None
        if self._held():
            return None
        self.due_since = self.due_since or now
        hours = (now - self.loaded_at()) / 3600.0
        calm, why, threat = read_calm(now)
        how = None
        if calm:
            how = "calm"
        elif calm is not None and now - self.due_since >= self.max_wait_h * 3600 and not threat:
            how = (f"not calm for {self.max_wait_h:g} h ({'; '.join(why)}) but no threat on the map")
        if how is None:
            self._say("calm", now, f"Fresh start: due ({hours:.1f} h since the game loaded), waiting for a calm "
                                   f"moment: {'; '.join(why) or 'not calm'}.")
            return None
        others = others_busy(self.me, now)
        if others:
            lb, what, _ = others[0]
            self._say("pc", now, f"Fresh start: due, but {lb}'s game is {what}: waiting its turn (one game at a "
                                 "time on this PC).")
            return None
        # said, then looked again: two keepers at the same moment, the older word wins
        # (0.105.100, verifier: only an older word holds this one back; both
        # stepped back before, and two keepers in step stepped back together)
        publish(self.me, "saving for a fresh start", now, now)
        others = [o for o in others_busy(self.me, now) if (o[2], o[0]) < (now, self.me)]
        if others:
            publish(self.me, None, None, now)
            return None
        self.busy, self.busy_since = "saving for a fresh start", now
        return {"hours": hours, "how": how, "due_since": self.due_since}

    def publish_state(self, now: float | None = None) -> None:
        """This keeper's word for the others (every chore; written when it changes or every few minutes)."""
        now = self.clock() if now is None else now
        busy, since = (self.busy, self.busy_since) if self.busy else reviver_busy(self.rv)
        # (0.105.100, verifier) the start of the whole busy stretch, not of its
        # last step: a game that tries a load every few minutes at the title
        # restarted its own "since" each try and held every other fort's
        # fresh start for ever (PC_BUSY_MAX_S never reached)
        if busy:
            self.busy_run = since if self.busy_run is None or since is None else min(self.busy_run, since)
            since = self.busy_run
        else:
            self.busy_run = None
        last, at = self.pc_written
        if (busy, since) == last and now - at < PC_WRITE_EVERY_S:
            return
        self.pc_written = ((busy, since), now)
        publish(self.me, busy, since, now)

    def put_off(self, now: float, why: str) -> None:
        """A fresh start that couldn't be done: the game runs on; tried again in an hour."""
        self.busy = self.busy_since = self.busy_run = None
        self.retry_at = now + RETRY_S
        publish(self.me, None, None, now)
        self.pc_written = (None, float("-inf"))
        self.log(f"Fresh start: not done ({why}): the game runs on; tried again in {RETRY_S // 60} min.")


def newest_save(cands=None, root=None) -> tuple[str | None, float | None, Path | None]:
    """The save the reviver would load first (revive.load_candidates, newest
    first, damaged ones passed over): its name, world.sav time and folder."""
    import revive
    from backup import save_mtime
    try:
        names, _world = (cands or revive.load_candidates)()
        if not names:
            return None, None, None
        r = (root or revive._fort_root)()
        p = Path(r) / names[0]
        return names[0], save_mtime(p), p
    except Exception:  # noqa: BLE001
        return None, None, None


def wait_saved(asked_at: float, clock=time.time, sleep=time.sleep, newest=newest_save, beat=None,
               wait_s: float = SAVE_WAIT_S, stable_s: float = SAVE_STABLE_S) -> str | None:
    """The fort's newest save written after `asked_at` and still for
    `stable_s`: its folder name; None after `wait_s` without one."""
    from backup import folder_mtime
    start = clock()
    seen = None
    while clock() - start < wait_s:
        name, stamp, folder = newest()
        if name and isinstance(stamp, (int, float)) and stamp >= asked_at - 1:
            try:
                m = folder_mtime(folder) if folder is not None else stamp
            except OSError:
                m = None
            now = clock()
            if m is not None:
                if seen and seen[0] == name and seen[1] == m and now - seen[2] >= stable_s and now - m >= stable_s:
                    return name
                if not seen or seen[:2] != (name, m):
                    seen = (name, m, now)
        # (0.105.100, verifier) beat() False: given up now (the game went down)
        if beat and beat() is False:
            return None
        sleep(5)
    return None


def write_mark(data: dict) -> None:
    try:
        from dfhack import write_atomic
        p = mark_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(p, json.dumps(data))
    except Exception:  # noqa: BLE001
        pass


def read_mark(now: float | None = None) -> dict | None:
    """The last keeper's note of a planned close, when recent (PLANNED_MAX_S): else None."""
    now = time.time() if now is None else now
    try:
        d = _d(json.loads(mark_file().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None
    at = d.get("closed_at")
    if d.get("phase") != "closed" or not isinstance(at, (int, float)) or not 0 <= now - at <= PLANNED_MAX_S:
        return None
    return d


def mark_done(d: dict, now: float) -> None:
    write_mark({**d, "phase": "done", "done_at": now})


def close_game(rv, log, clock=time.time, sleep=time.sleep, run=None, kill=None, gone=None) -> bool:
    """This folder's own game closed by its pid (revive.kill_command; never
    by name) and waited out. True when it is gone."""
    import subprocess
    import revive
    kill = kill or revive.kill_command
    cmd = kill()
    if not cmd or cmd[0] != "taskkill":
        log(f"Fresh start: the game couldn't be closed ({cmd[-1] if cmd else 'no command'}).")
        return False
    try:
        r = (run or subprocess.run)(cmd, capture_output=True, text=True, timeout=30)
        out = ((getattr(r, "stdout", "") or getattr(r, "stderr", "") or "").strip())[:120]
    except (OSError, subprocess.SubprocessError) as e:
        log(f"Fresh start: the game couldn't be closed ({e}).")
        return False
    if gone is None:
        def gone():
            own = revive.own_game_state()
            if own is True:
                return False
            try:
                return rv.probe() == "down"
            except Exception:  # noqa: BLE001
                return own is False
    start = clock()
    while clock() - start < CLOSE_WAIT_S:
        if gone():
            log(f"Fresh start: the game is closed ({out or 'taskkill'}).")
            return True
        sleep(3)
    log(f"Fresh start: the game was told to close ({out}) but is still there after {CLOSE_WAIT_S} s.")
    return False

"""Bringing the game back during a long unattended run (keeper --revive).

Two things can end a run that the overseer alone can't fix:
  * Dwarf Fortress closes or crashes: nothing answers dfhack-run. After
    DOWN_S (START_DOWN_S if it wasn't running when the keeper started) the game is started again with the command in config.json's
    "df_launch" (a path to Dwarf Fortress.exe, or a steam:// link for the
    DFHack entry); at most once every LAUNCH_EVERY_S.
  * The game is up but at the title screen (no world loaded): after TITLE_S
    (TITLE_OWN_S when the keeper started this copy itself: nobody is at it)
    the fort's newest save folder is loaded from the title screen (lua/ai-title.lua)
    (the folder from logs/last-fort.json, which the overseer writes each
    cycle; the newest of it and DF's autosaves); at most LOADS_PER_HOUR an hour.

Everything it does is logged by the keeper. Off unless --revive is given:
closing DF yourself would otherwise start it again.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from backup import newest_folder
from dfhack import (PROJECT_ROOT, DFHack, DFHackError, GameNotRunning, NoAnswer, configured_port,  # noqa: E501
                    port_env, read_config, save_root)

LAST_FORT = Path(os.environ.get("DFAI_LOG_DIR") or PROJECT_ROOT / "logs") / "last-fort.json"
PROBE_EVERY_S = 60
DOWN_S = 180
# the game not running when the keeper starts (never seen up this run): start it
# almost at once, probing every START_PROBE_S
START_PROBE_S = 15
START_DOWN_S = 15
# (0.105.33) ... unless a Dwarf Fortress process already runs (started with the
# keeper, still loading before DFHack listens): a second copy isn't started
# until this long
START_BUSY_S = 120
TITLE_S = 120
# (0.105.117) the game the keeper started itself (within LAUNCH_EVERY_S): nobody is at
# its title screen, so the save is loaded after TITLE_OWN_S, not TITLE_S (the player's grace)
TITLE_OWN_S = 15
LAUNCH_EVERY_S = 900
LOADS_PER_HOUR = 3
HUNG_S = 1800                # (0.100.1) no answer this long (not down, not at the title): DF is closed
                             # (0.104.138: 30 min, was 15: Teacheroar's autosaves took up to 10)
SAVE_QUIET_S = 180           # (0.104.138) never while a save folder was written this recently
HUNG_KILL_EVERY_S = 3600     # at most once an hour
# (0.105.0) a save that crashes DF on load (or never comes up) was tried all
# night: after LOAD_FAILS_MAX failed loads the next candidate is tried
LOAD_FAILS_MAX = 2
LOAD_TIMEOUT_S = 900         # loading, and no fort this long after: a failed load
# (r14 k1 fixes) a load counts in full as hung only when DF was silent from
# within this of its start through LOAD_TIMEOUT_S (a busy PC times dfhack-run
# out now and then mid-load: that is one failure, as before)
HUNG_LOAD_MARGIN_S = 2 * PROBE_EVERY_S
DF_EXE = "Dwarf Fortress.exe"
SAY_AGAIN_S = 3600           # (0.105.48, K17) a lasting trouble (another game, a wrong fort) said hourly
RESTORES_KEPT = 2            # (0.105.48, K17) "AI restore" folders kept in the game's saves
OLD_FOLDER = "_to_delete"    # ... the older ones moved here, beside the save folder (never deleted)


def write_last_fort(df_path: str | None, save_dir: str | None, fort: str | None,
                    world: str | None = None, run: str | None = None) -> None:
    """The overseer, each cycle: where the fort's save lives (only when it changed).
    (0.105.48, K8) With `run`, this fort's run id (brain/fort_run.py): the
    keeper's pin takes it, and the restore takes only that run's copies."""
    if not df_path or not save_dir:
        return
    data = {"df_path": df_path, "save_dir": save_dir, "fort": fort}
    if world:
        data["world"] = world
    if run:
        data["run"] = run
    try:
        if LAST_FORT.exists() and json.loads(LAST_FORT.read_text(encoding="utf-8")) == data:
            # (0.105.0) touched, not rewritten: the keeper's pin (brain/pin.py)
            # takes the fort the overseer named since the keeper started
            os.utime(LAST_FORT, None)
            return
        LAST_FORT.parent.mkdir(parents=True, exist_ok=True)
        from dfhack import write_atomic
        write_atomic(LAST_FORT, json.dumps(data))   # (0.100) the reviver may be reading it
    except (OSError, ValueError):
        pass


def save_to_load() -> str | None:
    """The folder name load-save should load: the newest of the fort's save
    and DF's autosaves."""
    try:
        d = json.loads(LAST_FORT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    folder = newest_folder(save_root(d["df_path"], d["save_dir"]) or Path(d["df_path"]) / "save", d["save_dir"])
    return folder.name if folder else None


def load_candidates() -> tuple[list[str], str | None]:
    """The fort's own save folder and DF's autosaves, newest first, and the
    world they must belong to: DF's "autosave 1/2" folders are shared by every
    world, so the newest one may be another world's (the title screen says
    which world each save is; lua/ai-title.lua checks).

    (0.105.0) With the keeper's pin (brain/pin.py) the pinned fort's folder and
    world, never last-fort.json's: a manual daytime run of another fort changed
    which world the reviver loaded."""
    import pin
    p = pin.current()
    if p:
        d = {"df_path": p.get("df_path"), "save_dir": p.get("save_dir"), "world": p.get("world")}
    else:
        try:
            d = json.loads(LAST_FORT.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return [], None
    if not d.get("df_path") or not d.get("save_dir"):
        return [], d.get("world")
    root = save_root(d["df_path"], d["save_dir"]) or Path(d["df_path"]) / "save"   # (0.99.13)
    from backup import save_mtime
    import save_check
    # (0.105.0 review) a backup restored earlier ("AI restore <date>") is a candidate too
    cands = [root / d["save_dir"]] + sorted(root.glob("autosave*")) + sorted(root.glob(RESTORE_PREFIX + "*"))
    cands = [c for i, c in enumerate(cands) if c.is_dir() and c not in cands[:i]]
    cands.sort(key=save_mtime, reverse=True)
    # (r14 k1) never a damaged save (brain/save_check.py: a world.sav torn when
    # the PC went down; E's 'autosave 3' hung DF on load twice), the pinned
    # folder too; the reviver says which were passed over (LAST_DAMAGED)
    LAST_DAMAGED.clear()
    keep = []
    for c in cands:
        why = save_check.damage(c)
        if why:
            LAST_DAMAGED.append((c.name, why))
        else:
            keep.append(c)
    return [c.name for c in keep], d.get("world")


# (r14 k1) the damaged folders the last load_candidates() passed over: (name, why)
LAST_DAMAGED: list[tuple[str, str]] = []


RESTORE_PREFIX = "AI restore"


def restore_from_backup(log=None) -> str | None:
    """(0.105.0) Every save of the pinned fort failed to load: the newest copy
    of it in backups/ (any folder, by its world and site) is copied into DF's save folder as "AI restore <date>" and its
    folder name returned (None if there is none). Each copy is restored once."""
    import shutil
    import backup
    import pin
    p = pin.current()
    if not p or not backup.safe_save_dir(p.get("save_dir")) or not p.get("df_path"):
        return None
    # (0.105.33) every backups/ folder's copies of the pinned world and site:
    # the copies go to backups/<the save folder loaded>, which a revive (an
    # "autosave N") or a restore changes; never another world's autosave copy
    # (0.105.48, K8) with the pin's run id, only this run's copies (an old run
    # of the same embark has the same world and site), newest save first
    copies = backup.copies_of(p.get("world"), p.get("site"), p.get("save_dir"), run=pin.run_id())
    root = save_root(p["df_path"], p["save_dir"]) or Path(p["df_path"]) / "save"
    import save_check
    for c in copies:
        name = f"{RESTORE_PREFIX} {c.name}"
        why = save_check.damage(c)
        if why:
            # (r14 k1) a copy of a torn save would only fail again: the next older one
            if log and (str(c), why) not in _COPY_SAID:
                _COPY_SAID.add((str(c), why))
                log(f"Revive: the backup copy {c} "
                    + (f"{why}: not a save DF can load" if save_check.no_sav(why) else f"is damaged ({why})")
                    + ": not restored.")
            continue
        dest = root / name
        if dest.exists() or (root.parent / OLD_FOLDER / name).exists():
            continue                      # restored before (and failed, or it'd be loaded): an older one
        # (0.105.48, K17) copied under a temporary name outside the save
        # folder (DF never lists it), then renamed in whole: a copy torn by a
        # full disk was skipped as "restored before" and offered as a save
        tmp = root.parent / OLD_FOLDER / f"{name}.partial"
        try:
            tmp.parent.mkdir(parents=True, exist_ok=True)
            if tmp.exists():
                _move_aside(tmp, tmp.parent, log)
            shutil.copytree(c, tmp)
            tmp.rename(dest)
        except OSError as e:
            if log:
                log(f"Revive: couldn't copy the backup {c} into the game's saves ({e}).")
            return None
        if log:
            log(f"Revive: every save of the pinned fort failed to load; the backup copy {c.name} is now the "
                f"save '{name}'.")
        prune_restores(root, keep=name, log=log)
        return name
    return None


_COPY_SAID: set = set()


def _move_aside(folder: Path, into: Path, log=None) -> bool:
    """(0.105.48, K17) `folder` moved into `into` under a free name (deleting
    may be refused on this PC: nothing is deleted). Never raises; False when
    the move was refused."""
    try:
        into.mkdir(parents=True, exist_ok=True)
        dest = into / folder.name
        n = 1
        while dest.exists():
            n += 1
            dest = into / f"{folder.name} ({n})"
        folder.rename(dest)
        return True
    except OSError as e:
        if log:
            log(f"Revive: couldn't move {folder.name} aside ({e}); left where it is.")
        return False


def prune_restores(root: Path, keep: str | None = None, log=None) -> list[str]:
    """(0.105.48, K17) Only the newest RESTORES_KEPT "AI restore" folders the
    AI made stay in the game's save folder (each is the size of a save, and
    they were never removed); older ones are moved into OLD_FOLDER beside
    it, never deleted. The folder the pin or last-fort.json names (the fort
    being run) and `keep` always stay. Returns the names moved; never raises."""
    try:
        import pin
        busy = {keep, (pin.current() or {}).get("save_dir")}
        try:
            busy.add(json.loads(LAST_FORT.read_text(encoding="utf-8")).get("save_dir"))
        except (OSError, ValueError, AttributeError):
            pass
        mine = sorted((d for d in root.glob(RESTORE_PREFIX + " *") if d.is_dir()), key=lambda d: d.name,
                      reverse=True)
    except OSError:
        return []
    moved = []
    for d in mine[RESTORES_KEPT:]:
        if d.name in busy:
            continue
        if _move_aside(d, root.parent / OLD_FOLDER, log):
            moved.append(d.name)
    if moved and log:
        log(f"Revive: {len(moved)} older restored save(s) moved out of the game's saves into "
            f"{root.parent / OLD_FOLDER} (delete them there when you like): {', '.join(moved)}.")
    return moved


def save_written_within(seconds: float, clock=time.time) -> bool:
    """(0.104.138) True when the fort's save or an autosave folder (or a file
    in one) was written in the last `seconds`: DF is saving, not hung."""
    try:
        d = json.loads(LAST_FORT.read_text(encoding="utf-8"))
        root = save_root(d["df_path"], d["save_dir"]) or Path(d["df_path"]) / "save"
        folders = [root / d["save_dir"]] + sorted(root.glob("autosave*"))
    except (OSError, ValueError, KeyError, TypeError):
        return False
    now = clock()
    for f in folders:
        try:
            if not f.is_dir():
                continue
            newest = max([f.stat().st_mtime] + [c.stat().st_mtime for c in f.iterdir()])
            if now - newest < seconds:
                return True
        except OSError:
            continue
    return False


# (0.105.33) lua/ai-title.lua's answers that last (the same try fails the same
# way next time); "a list was open ... backed out", "not at the title screen"
# and "a world is already loaded" pass, and aren't counted
_NO_WORLD_SAVE = "no save of the world"
_ONE_FOLDER = ("no save called", "is not listed", "two saves called")


def refused_folders(out: str, folders: list[str], folder: str, matched: bool) -> list[str]:
    """(0.105.33) The folders a refused load counts against. load-match
    (`matched`): every folder offered, when none is a save of the world, or
    when the world's save was refused (load-match tries only that world's
    saves, and doesn't say which one). A plain load: the one folder, when
    there is no save of that name or its world isn't listed."""
    m = re.search(r'"error"\s*:\s*"((?:[^"\\]|\\.)*)"', out or "")
    err = m.group(1) if m else (out or "")
    if matched and (_NO_WORLD_SAVE in err or any(x in err for x in _ONE_FOLDER)):
        return list(folders)
    if any(x in err for x in _ONE_FOLDER):
        return [folder]
    return []


def df_running(run=None, exe: str | None = None) -> bool:
    """(0.105.33) A Dwarf Fortress process exists (Windows' tasklist; False
    elsewhere or when it can't tell).

    (0.105.42) With exe (this keeper's own game, config's df_launch): only that
    game's process counts. Six copies share the name "Dwarf Fortress.exe": on
    13 Nov 22:30 the keepers B-F each saw A's game running, took it for their
    own still starting, and waited 2 minutes before launching theirs."""
    if os.name != "nt" and run is None:
        return False
    run = run or subprocess.run
    if exe:
        try:
            r = run(["powershell", "-NoProfile", "-Command",
                     "Get-Process -Name 'Dwarf Fortress' -ErrorAction SilentlyContinue | "
                     "ForEach-Object { $_.Path }"],
                    capture_output=True, text=True, timeout=30)
            out = getattr(r, "stdout", "") or ""
            want = os.path.normcase(os.path.normpath(exe))
            paths = [os.path.normcase(os.path.normpath(ln.strip())) for ln in out.splitlines() if ln.strip()]
            if paths or getattr(r, "returncode", 1) == 0:
                return want in paths
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        lst = run(["tasklist", "/FI", f"IMAGENAME eq {DF_EXE}", "/FO", "CSV", "/NH"],
                  capture_output=True, text=True, timeout=30).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return False
    return any(DF_EXE.lower() in ln.lower() for ln in lst.splitlines())


def any_df_running(run=None) -> bool | None:
    """(r1g9) Whether any Dwarf Fortress process runs on this PC (Windows'
    tasklist): True, False, or None when it can't tell (not Windows, the
    list failed)."""
    if os.name != "nt" and run is None:
        return None
    run = run or subprocess.run
    try:
        r = run(["tasklist", "/FI", f"IMAGENAME eq {DF_EXE}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    out = getattr(r, "stdout", "") or ""
    if getattr(r, "returncode", 0) != 0 and not out.strip():
        return None
    return any(DF_EXE.lower() in ln.lower() for ln in out.splitlines())


def own_exe() -> str | None:
    """(0.105.42) This keeper's game's .exe (config's df_launch when it names
    one; None for a steam:// link)."""
    cmd = launch_command()
    return cmd if cmd and cmd.lower().endswith(".exe") else None


def launch_command() -> str | None:
    cmd = read_config().get("df_launch")
    return cmd if isinstance(cmd, str) and cmd.strip() else None


def _listening_pid(port: int, netstat_out: str) -> int | None:
    """(0.105.1) The process listening on 127.0.0.1:<port> (or any address),
    from `netstat -ano -p TCP`'s lines: "TCP  127.0.0.1:5001  0.0.0.0:0  LISTENING  1234"."""
    for line in netstat_out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            if parts[1].rsplit(":", 1)[-1] == str(port) and parts[4].isdigit():
                return int(parts[4])
    return None


def _pids_of_exe(exe: str, run) -> list[int]:
    """(0.105.48, K8) The process ids of the Dwarf Fortress whose .exe is `exe`
    (PowerShell's Get-Process, as df_running): [] when none, or when it can't tell."""
    return _exe_pids(exe, run) or []


def _exe_pids(exe: str, run) -> list[int] | None:
    """(0.105.48, K17) As _pids_of_exe, but None when it can't tell
    (PowerShell failed): "none running" and "unknown" differ for a launch."""
    try:
        r = run(["powershell", "-NoProfile", "-Command",
                 "Get-Process -Name 'Dwarf Fortress' -ErrorAction SilentlyContinue | "
                 "ForEach-Object { [string]$_.Id + '|' + $_.Path }"],
                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    text = getattr(r, "stdout", "") or ""
    if not text.strip() and getattr(r, "returncode", 1) != 0:
        return None
    from util import same_path
    out = []
    for ln in text.splitlines():
        if not ln.strip():
            continue
        pid, _, path = ln.strip().partition("|")
        if not pid.strip().isdigit() or not path.strip():
            return None                   # a process whose path can't be read: can't tell
        if same_path(path.strip(), exe):
            out.append(int(pid))
    return out


def own_game_state(exe: str | None = None, run=None) -> bool | None:
    """(0.105.48, K17) Whether this keeper's own game (its .exe, default
    game_exe()) has a process: True, False, or None when it can't tell (no
    .exe known, not Windows, PowerShell failed). Never another game's: six
    copies share the name."""
    if os.name != "nt" and run is None:
        return None
    exe = exe or game_exe()
    if not exe:
        return None
    pids = _exe_pids(exe, run or subprocess.run)
    return None if pids is None else bool(pids)


def game_exe() -> str | None:
    """(0.105.48, K8) This keeper's own game's .exe: config's df_launch when it
    names one, else Dwarf Fortress.exe in the pinned (or last) fort's DF
    folder (a Steam game started by a steam:// link). None when unknown."""
    exe = own_exe()
    if exe:
        return exe
    try:
        import pin
        p = pin.current() or {}
        df_path = p.get("df_path") or json.loads(LAST_FORT.read_text(encoding="utf-8")).get("df_path")
    except (OSError, ValueError, AttributeError):
        df_path = None
    return str(Path(df_path) / DF_EXE) if isinstance(df_path, str) and df_path else None


def kill_command(port: int | None = None, run=None, exe: str | None = None) -> list[str]:
    """(0.105.1) How to close this keeper's hung game: by the process id that
    listens on its DFHack port (a hung game still holds the port), so a second
    game on another port is never touched.

    (0.105.48, K8) Never by image name (six games share "Dwarf Fortress.exe":
    a netstat that failed killed all six, some mid-save): with no listener
    found, by the process whose .exe is this keeper's own game (`exe`, default
    game_exe()); when neither tells, nothing is closed."""
    port = port or configured_port() or 5000
    run = run or subprocess.run
    exe = exe or game_exe()
    own = _exe_pids(exe, run) if exe else None
    try:
        out = run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=30).stdout or ""
        pid = _listening_pid(port, out)
        if pid:
            if own is not None and pid not in own:
                # (0.105.48, K17) the port's listener is not this folder's game
                # (a config.json without its own dfhack_port reaches A's on 5000)
                return ["cmd", "/c", "echo", f"the game on port {port} (process {pid}) is not this folder's "
                        f"own game ({exe}): left alone"]
            return ["taskkill", "/F", "/PID", str(pid)]
    except (OSError, subprocess.SubprocessError):
        pass
    pids = own or []
    if len(pids) == 1:
        return ["taskkill", "/F", "/PID", str(pids[0])]
    why = (f"{len(pids)} games run from {exe}" if len(pids) > 1
           else f"no game of this folder found by its port {port} or its .exe ({exe or 'not known'})")
    return ["cmd", "/c", "echo", f"{why}: left alone (never closed by name)"]


def _absolute(p: str) -> bool:
    return bool(re.match(r"^([A-Za-z]:[\\/]|[\\/])", p or ""))


def save_stamp(folder: str) -> float | None:
    """(0.105.48, K8) When the save `folder` was last written (its world.sav's
    time, backup.save_mtime), in the pinned (or last) fort's save root; None
    when it isn't there. DF reuses "autosave N" every season: a count of
    failed loads holds only for the save as it was when it failed."""
    try:
        root = _fort_root()
        d = root / folder
        if not d.is_dir():
            return None
        from backup import save_mtime
        return save_mtime(d)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _fort_root() -> Path:
    """The pinned (or last) fort's save root. Raises when unknown."""
    import pin
    p = pin.current() or json.loads(LAST_FORT.read_text(encoding="utf-8"))
    return save_root(p["df_path"], p["save_dir"]) or Path(p["df_path"]) / "save"


def damaged_folder(folder: str) -> str | None:
    """(r14 k1) Why the save `folder` in the pinned (or last) fort's save root
    is damaged (brain/save_check.py), or None (whole, absent, unknown)."""
    try:
        import save_check
        return save_check.damage(_fort_root() / folder)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


class Reviver:
    def __init__(self, log, dfhack: DFHack | None = None, launcher=None, clock=time.time):
        self.log, self.clock = log, clock
        self.df = dfhack
        self.launcher = launcher or self._launch
        self.last_probe = float("-inf")
        self.down_since = self.title_since = None
        self.last_launch = float("-inf")
        self.unknown_since = None
        self.last_kill = float("-inf")
        self.loads: list[float] = []
        self.seen_up = False             # the game answered at some point this run
        self.candidates = load_candidates
        # (0.105.0) failed loads per save folder; the load under way: (folder, since)
        self.load_fails: dict[str, int] = {}
        # (0.105.48, K8) ... each for the save as it was when it failed (its
        # world.sav's time): a folder DF has written again since is tried again
        self.fail_stamp: dict[str, float | None] = {}
        self.save_stamp = save_stamp
        # (r14 k1) a damaged save (a world.sav torn by a sudden shutdown) is
        # never loaded; said once per folder as written (folder, its stamp)
        self.damaged = damaged_folder
        self.damaged_said: set = set()
        self.late_load: str | None = None         # (r14 k1 fixes) the last load counted failed, game still up
        self.loading: tuple[str, float] | None = None
        self.restore = restore_from_backup
        self.restored: list[str] = []
        # (0.105.33; 0.105.42 its own game only; 0.105.48, K17: True, False or
        # None when it can't tell, and asked before every launch)
        self.df_running = lambda: own_game_state()
        from util import own_df_folder
        self.own_folder = own_df_folder           # (0.105.48, K17) the game this folder runs
        self.said: dict[str, float] = {}          # a lasting trouble's line: when last said
        self.stalls: dict[str, int] = {}          # title-screen stalls in a row, per folder (not failed loads)
        self.wrong_load: str | None = None        # a load of ours that brought up another fort
        self.close_game = self._close_game
        # (r1g9) the session ending (Windows shutting down or logging off, the
        # console's close signal) and any Dwarf Fortress left on the PC
        import session_end
        self.session_ending = session_end.ending
        self.any_df = any_df_running
        self.all_closed_said = False
        # (0.105.100) when the pinned fort's world came up (brain/fresh_start.py
        # counts its hours from it; None while down or at the title), and a
        # reopening after the keeper's own planned close: its lines say
        # "Revive (planned):", never counted as a crash (brain/soak_report.py)
        self.world_since: float | None = None
        self.planned = False
        self.planned_since: float | None = None

    def _tag(self) -> str:
        return "Revive (planned)" if self.planned else "Revive"

    def _held(self, state: str, now: float) -> bool:
        """(r1g9) Nothing is started, loaded or closed: the fort has fallen
        (logs/fallen.json, brain/fallen.py: left for the player), or the
        session is ending (R-AD: C reloaded, A and F relaunched while Windows
        shut down). True when held (said hourly)."""
        why, key = None, None
        try:
            import fallen
            m = fallen.idle()
            # (x3, V7) a mark left by another fort than the pinned one holds nothing:
            # the pinned fort is started and loaded as usual (the overseer's loop
            # then takes that mark off, seeing another fort loaded)
            import pin
            if m and not fallen.holds_for(m, pin.current()):
                m = None
        except Exception:  # noqa: BLE001
            m = None
        if m:
            why, key = (f"the fort has fallen ({m.get('why') or 'no citizens left'}; logs/fallen.json): the game "
                        "is left as it is until you act"), "fallen"
        else:
            try:
                e = self.session_ending()
            except Exception:  # noqa: BLE001
                e = None
            if e:
                why, key = f"{e}: the game is not started again, loaded or closed", "ending"
        if why is None:
            return False
        if state == "down" and self.down_since is None:
            self.down_since = now
        self.title_since = self.unknown_since = None
        if key == "ending":
            self.down_since = None
        self.loading = None
        self._say_hourly(key, now, f"Revive: {why}.")
        return True

    def _all_closed_hold(self, now: float) -> bool:
        """(r1g9) This folder's game closed after it ran, and no Dwarf
        Fortress at all is left on the PC: every game closed together, as
        Windows does at a shutdown or logoff. No relaunch for
        g9_all_closed_hold_s from when it went (the console's close signal
        comes within it when the session is ending). True when held."""
        try:
            anyone = self.any_df()
        except Exception:  # noqa: BLE001
            anyone = None
        if anyone is not False or not self.seen_up or self.down_since is None:
            self.all_closed_said = False
            return False
        import session_end
        hold = session_end.all_closed_hold_s()
        if now - self.down_since >= hold:
            return False
        if not self.all_closed_said:
            self.all_closed_said = True
            self.log(f"Revive: this folder's game closed, and no Dwarf Fortress is left running on this PC (all of "
                     "them closed together: Windows shutting down or logging off?): not started again for "
                     f"{int(hold)} s after it went.")
        return True

    def _say_hourly(self, key: str, now: float, line: str) -> None:
        """(0.105.48, K17) A line said at most once every SAY_AGAIN_S."""
        if now - self.said.get(key, float("-inf")) >= SAY_AGAIN_S:
            self.said[key] = now
            self.log(line)

    def _close_game(self, now: float, why: str, safe_mid_save: bool = False) -> bool:
        """(0.105.48, K17) This folder's own game closed (by its pid, never by
        name; never while a save folder is being written unless
        `safe_mid_save`). True when it was closed; at most once an hour."""
        if os.name != "nt" or now - self.last_kill < HUNG_KILL_EVERY_S:
            return False
        if not safe_mid_save and save_written_within(SAVE_QUIET_S):
            self._say_hourly("save_quiet", now, f"Revive: {why}, but it is still writing a save: left to finish.")
            return False
        self.last_kill = now
        try:
            cmd = kill_command()
            if cmd[0] != "taskkill":
                self.log(f"Revive: {why}, but {cmd[-1]}.")
                return False
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            self.log(f"Revive: {why}: closed it ({(r.stdout or r.stderr).strip()[:120]}); it's started again "
                     "once it's gone.")
            return True
        except (OSError, subprocess.SubprocessError) as e:
            self.log(f"Revive: {why}, and it couldn't be closed ({e}).")
            return False

    def _dfhack(self) -> DFHack:
        if self.df is None:
            self.df = DFHack.from_config()
        return self.df

    @staticmethod
    def _launch(cmd: str) -> None:
        # (0.105.1) a game's own .exe (a second copy run beside the Steam one)
        # starts in its own folder, where it finds data\ and dfhack-config\,
        # with DFHACK_PORT set to this folder's port, so its DFHack listens
        # where this keeper's dfhack-run calls
        exe = Path(cmd)
        if os.name == "nt" and exe.suffix.lower() == ".exe" and exe.is_file():
            subprocess.Popen([str(exe)], cwd=str(exe.parent), env=port_env(configured_port()),
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        elif os.name == "nt":
            os.startfile(cmd)                    # a steam:// link
        else:
            subprocess.Popen(cmd, shell=True)    # (tests and other systems)

    PROBE_LUA = ("local w = dfhack.isWorldLoaded() and 'WORLD-LOADED' or 'NO-WORLD' "
                 # (0.105.0) the loaded fort's site, for the keeper's pin (read in pcall: a probe)
                 "local ok, s = pcall(function() return df.global.plotinfo.site_id end) "
                 # (0.105.48, K17) and the game's folder, last (it may hold spaces): which game answers
                 "local okp, p = pcall(dfhack.getDFPath) "
                 "print(w .. ' SITE=' .. tostring(ok and dfhack.isMapLoaded() and s or '') "
                 ".. ' DFPATH=' .. tostring(okp and p or ''))")

    def probe(self) -> str:
        """'down' (nothing answers), 'title' (no world loaded), 'world',
        'unknown' (dfhack-run timed out: hung?), 'broken' (dfhack-run itself
        failed, or answered nonsense: the game isn't the trouble) or
        'foreign' (the game answering is not this folder's own)."""
        try:
            out = self._dfhack().run("lua", self.PROBE_LUA)
        except GameNotRunning:
            return "down"
        except NoAnswer:
            return "unknown"
        except DFHackError as e:
            # (0.105.48, K17) dfhack-run missing, a bad config.json, an error
            # exit: not a hung game (a healthy game was closed hourly)
            self.broken_why = str(e)[:160]
            return "broken"
        m = re.search(r"SITE=(-?\d+)", out)
        self.site = m.group(1) if m else None
        pm = re.search(r"DFPATH=(.*)$", out, re.M)
        self.df_path = pm.group(1).strip() if pm else None
        if "WORLD-LOADED" not in out and "NO-WORLD" not in out:
            self.broken_why = f"the probe's answer was {out.strip()[:120]!r}"
            return "broken"
        own = self.own_folder()
        if own and self.df_path and _absolute(self.df_path):
            from util import same_path
            if not same_path(own, self.df_path):
                return "foreign"
        return "world" if "WORLD-LOADED" in out else "title"

    def _load_failed(self, why: str) -> None:
        """(0.105.0) The load under way failed: counted against its folder."""
        folder = self.loading[0]
        self.loading = None
        self._count_fail(folder, why)

    def _fails(self, folder: str) -> int:
        """(0.105.48, K8) The failed loads of the save now in `folder`: none
        when DF wrote that folder again since they failed ("autosave 2" is a
        new save each season; the count kept it out for the keeper's whole
        run, and each bad night dropped one more name)."""
        if folder not in self.load_fails:
            return 0
        try:
            now_stamp = self.save_stamp(folder)
        except Exception:  # noqa: BLE001  (can't tell: the count stands)
            return self.load_fails[folder]
        if now_stamp != self.fail_stamp.get(folder):
            self.load_fails.pop(folder, None)
            self.fail_stamp.pop(folder, None)
            self.log(f"Revive: '{folder}' was written again since it failed to load: it is tried again.")
            return 0
        return self.load_fails[folder]

    def _late_success(self) -> None:
        """(r14 k1 fixes) A load counted as failed (timed out, hung) whose game
        then came up with the pinned fort after all: the count is taken back,
        so a slow but healthy save isn't passed over for an older one."""
        import pin
        p = pin.current()
        site = getattr(self, "site", None)
        if site in (None, "") or (p and str(site) != str(p.get("site"))):
            return
        folder, self.late_load = self.late_load, None
        if self.load_fails.pop(folder, None):
            self.fail_stamp.pop(folder, None)
            self.log(f"Revive: '{folder}' came up after all (a slow load, not a bad save): its failed loads "
                     "are forgotten.")

    def _count_fail(self, folder: str, why: str, full: bool = False) -> None:
        """(r14 k1) `full`: a lasting fault, counted as LOAD_FAILS_MAX at once.
        (r14 k1 fixes) The folder is kept (late_load) until another load or the
        game closing: if its fort comes up after all, the count is undone."""
        self.late_load = folder
        n = self._fails(folder) + 1
        n = self.load_fails[folder] = max(n, LOAD_FAILS_MAX) if full else n
        try:
            self.fail_stamp[folder] = self.save_stamp(folder)
        except Exception:  # noqa: BLE001
            self.fail_stamp[folder] = None
        self.log(f"Revive: loading '{folder}' failed ({why}); {n} failed load(s) of it"
                 + (": it isn't tried again, the next older save is." if n >= LOAD_FAILS_MAX else "."))

    def _watch_load(self, state: str, now: float) -> None:
        if self.loading is None:
            if state == "world" and self.late_load:
                self._late_success()
            elif state == "down":
                self.late_load = None
            return
        folder, since = self.loading
        if state == "world":
            import pin
            p = pin.current()
            site = getattr(self, "site", None)
            if site in (None, ""):
                # (0.105.0 review) the world is up but no fort's map yet (still
                # loading): not a success; the timeout still counts
                if now - since >= LOAD_TIMEOUT_S:
                    self._load_failed(f"no fort {LOAD_TIMEOUT_S // 60} minutes after")
                return
            if p and site not in (None, "") and str(site) != str(p.get("site")):
                self.log(f"Revive: '{folder}' loaded another site ({site}, not the pinned {p.get('site')}): "
                         "the overseer won't act on it. That save isn't tried again; the game is closed and started "
                         "again for the next one.")
                # (0.105.48, K17) a lasting fault of the save (it holds
                # another fort): counted in full, and the fort unloaded (tick)
                self.loading = None
                self._count_fail(folder, "another site")
                self.load_fails[folder] = max(self.load_fails.get(folder, 0), LOAD_FAILS_MAX)
                self.wrong_load = folder
                self.late_load = None
                return
            self.loading = None
            self.stalls.pop(folder, None)
            self.load_fails.pop(folder, None)
            self.fail_stamp.pop(folder, None)
        elif state == "down":
            self._load_failed("Dwarf Fortress closed")
            self.late_load = None
        elif state == "title":
            # (0.105.48, K17) the load goes on in steps inside the game: one
            # that stopped at the title screen (a list that wouldn't scroll)
            # is the title screen's fault, not the save's: tried again, uncounted
            kind, step = self._title_progress(folder)
            if kind == "stalled" or (kind == "going" and now - since >= LOAD_TIMEOUT_S):
                self.loading = None
                n = self.stalls[folder] = self.stalls.get(folder, 0) + 1
                self.log(f"Revive: loading '{folder}' stopped at the title screen ({step}); tried again, not "
                         f"counted against the save ({n} stall(s) in a row).")
            elif now - since >= LOAD_TIMEOUT_S:
                self._load_failed(f"no fort {LOAD_TIMEOUT_S // 60} minutes after")
        elif state == "unknown" and now - since >= LOAD_TIMEOUT_S:
            # (r14 k1) DF stopped answering while it loaded the save and never
            # came back (E's torn 'autosave 3' hung it): counted in full, so the
            # next try (after the hung game is closed) takes the next save.
            # (r14 k1 fixes) only when silent from (about) the load's start:
            # a busy PC's timeouts later in the load are one failure
            silent_from = self.unknown_since if self.unknown_since is not None else now
            if silent_from <= since + HUNG_LOAD_MARGIN_S:
                self.loading = None
                self._count_fail(folder, f"Dwarf Fortress gave no answer from the load's start through "
                                         f"{LOAD_TIMEOUT_S // 60} minutes: hung", full=True)
            else:
                self._load_failed(f"no fort {LOAD_TIMEOUT_S // 60} minutes after, Dwarf Fortress not answering")
        elif now - since >= LOAD_TIMEOUT_S:
            self._load_failed(f"no fort {LOAD_TIMEOUT_S // 60} minutes after")

    def _skip_damaged(self, folders: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
        """(r14 k1) The candidates without the damaged ones, and those passed
        over (load_candidates' own, and any the check here finds: a pinned
        folder, a candidates list from elsewhere): never loaded."""
        skipped = list(LAST_DAMAGED)
        keep = []
        for f in folders:
            try:
                why = self.damaged(f)
            except Exception:  # noqa: BLE001  (can't tell: not skipped)
                why = None
            if why:
                skipped.append((f, why))
            else:
                keep.append(f)
        return keep, skipped

    def _say_damaged(self, skipped: list[tuple[str, str]], nxt: str | None) -> None:
        """(r14 k1) Each damaged folder said once per save as written (its
        stamp), with a Needs you line: the AI never moves, deletes or
        rewrites a save."""
        import save_check
        for f, why in skipped:
            try:
                stamp = self.save_stamp(f)
            except Exception:  # noqa: BLE001
                stamp = None
            if (f, stamp) in self.damaged_said:
                continue
            self.damaged_said.add((f, stamp))
            then = f"loading '{nxt}'" if nxt else "no other save of the fort is left to load"
            if save_check.no_sav(why):
                # (r14 k1 fixes) not torn, just not a save DF can load: nothing to move
                self.log(f"Revive: '{f}' {why}: not a save DF can load: skipped, {then}.")
                continue
            guess = ", written as the PC went down?" if save_check.torn(why) else ""
            self.log(f"Revive: '{f}' is damaged ({why}{guess}): skipped, {then}.")
            try:
                root = _fort_root()
                where, aside = f" in {root}", f" into {root.parent / 'old-saves'}"
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                where, aside = "", " out of the game's save folder"
            self.log(f"Revive: Needs you: the save '{f}'{where} is damaged and is never loaded; move it{aside} "
                     "when you like (the AI never moves, deletes or rewrites a save; DF writes over it at a "
                     "later autosave anyway).")

    def _title_progress(self, folder: str) -> tuple[str, str]:
        """(0.105.48, K17) How the load of `folder` goes, from lua/ai-title.lua's
        step log (ai-title status): ("stalled", step) when a step stopped at the
        title screen, ("started", step) once the save was clicked and the load
        began, ("going", step) while the steps run, ("unknown", why) when it
        can't be read (then a timeout counts as before)."""
        try:
            out = self._dfhack().run("ai-title", "status")
        except DFHackError as e:
            return "unknown", str(e)[:80]
        d = None
        for line in reversed((out or "").splitlines()):
            if line.strip().startswith("{"):
                try:
                    d = json.loads(line.strip())
                except ValueError:
                    d = None
                break
        if not isinstance(d, dict) or (d.get("folder") not in (None, folder)):
            return "unknown", "no step log of this load"
        steps = d.get("steps") if isinstance(d.get("steps"), list) else []
        last = steps[-1] if steps and isinstance(steps[-1], dict) else {}
        name = str(last.get("step") or "")
        if not name:
            return "unknown", "no step log of this load"   # (a load that ran always logs its start)
        if name.startswith("stopped"):
            return "stalled", name[:160]
        if name == "save clicked":
            if last.get("loading") or last.get("ok"):
                return "started", name
            return "stalled", "the save was clicked, but no load began"
        if name in ("worlds listed", "saves listed") and last.get("ok") is False:
            return "stalled", f"{name}: the list never opened"
        if name == "saves listed" and last.get("game_index") is None:
            return "stalled", "the world's save list doesn't hold the save"
        return "going", name[:160]

    def tick(self) -> None:
        now = self.clock()
        # (0.105.117) the copy the keeper started, at its title with no load under way: looked at
        # every START_PROBE_S, so its save loads ~TITLE_OWN_S after the title shows (not 2-3 min)
        quick = (not self.seen_up or (self.title_since is not None and self.loading is None
                                      and now - self.last_launch < LAUNCH_EVERY_S))
        if now - self.last_probe < (START_PROBE_S if quick else PROBE_EVERY_S):
            return
        self.last_probe = now
        state = self.probe()
        if state in ("title", "world"):
            self.seen_up = True
        if state == "world" and getattr(self, "site", None) not in (None, ""):
            self.world_since = self.world_since if self.world_since is not None else now
        elif state in ("down", "title"):
            self.world_since = None
        self._watch_load(state, now)
        if state in ("down", "title", "unknown") and self._held(state, now):
            return
        if state in ("foreign", "broken"):
            # (0.105.48, K17) another folder's game answers on this port, or
            # dfhack-run itself fails: nothing is loaded, closed or started
            self.down_since = self.title_since = self.unknown_since = None
            if state == "foreign":
                self._say_hourly("foreign", now, f"Revive: the game answering on this folder's port is "
                                 f"{getattr(self, 'df_path', None)}, not this folder's own game "
                                 f"({self.own_folder()}): nothing is loaded, closed or started in it. "
                                 "Check dfhack_port in config.json (each keeper needs its own).")
            else:
                self._say_hourly("broken", now, "Revive: dfhack-run doesn't work "
                                 f"({getattr(self, 'broken_why', '?')}): the game isn't closed for it. "
                                 "Check dfhack_run in config.json.")
            return
        if state == "down":
            self.title_since = None
            self.down_since = self.down_since or now
            wait = DOWN_S if self.seen_up else START_DOWN_S
            if now - self.down_since >= wait and now - self.last_launch >= LAUNCH_EVERY_S:
                # (0.105.48, K17) never a second copy of this folder's game: its
                # own .exe still has a process (starting slowly, closing, or
                # hung before DFHack listens): no launch; past HUNG_S, closed
                try:
                    running = self.df_running()
                except Exception:  # noqa: BLE001
                    running = None
                if running:
                    if now - self.down_since >= HUNG_S:
                        self.close_game(now, f"Dwarf Fortress has run for {int(now - self.down_since)} s without "
                                             "DFHack answering (hung)")
                    elif not getattr(self, "busy_said", False):
                        self.log("Revive: Dwarf Fortress is running but DFHack doesn't answer yet (still starting?): "
                                 "not starting a second copy; it is closed if it still hasn't answered in "
                                 f"{HUNG_S // 60} minutes.")
                        self.busy_said = True
                    return
                if running is None and not self.seen_up and now - self.down_since < START_BUSY_S:
                    # (can't tell its own process: any Dwarf Fortress, as before 0.105.48)
                    try:
                        anyone = df_running()
                    except Exception:  # noqa: BLE001
                        anyone = False
                    if anyone:
                        if not getattr(self, "busy_said", False):
                            self.log("Revive: Dwarf Fortress is running but DFHack doesn't answer yet (still "
                                     f"starting?): waiting up to {START_BUSY_S} s before starting it.")
                            self.busy_said = True
                        return
                if self._all_closed_hold(now):
                    return
                cmd = launch_command()
                if not cmd:
                    if self.last_launch == float("-inf"):
                        self.log("Revive: Dwarf Fortress isn't running and config.json has no \"df_launch\" "
                                 "command, so it can't be started again from here.")
                        self.last_launch = now
                    return
                self.last_launch = now
                try:
                    self.launcher(cmd)
                    self.log(f"{self._tag()}: Dwarf Fortress wasn't running for {int(now - self.down_since)} s: "
                             f"started it again ({cmd}).")
                except OSError as e:
                    self.log(f"Revive: couldn't start Dwarf Fortress ({e}).")
        elif state == "title":
            self.down_since = None
            self.busy_said = False        # (0.105.36, D7) said again the next time DF starts slowly
            self.title_since = self.title_since or now
            self.loads = [t for t in self.loads if now - t < 3600]
            own = now - self.last_launch < LAUNCH_EVERY_S     # (0.105.117) the keeper started this copy
            if now - self.title_since >= (TITLE_OWN_S if own else TITLE_S) and len(self.loads) < LOADS_PER_HOUR:
                if self.loading is not None:
                    return                    # (0.105.0) the last load still has time to come up
                LAST_DAMAGED.clear()
                folders, world = self.candidates()
                folders, skipped = self._skip_damaged(folders)
                failed = [f for f in folders if self._fails(f) >= LOAD_FAILS_MAX]
                folders = [f for f in folders if f not in failed]
                self._say_damaged(skipped, folders[0] if folders else None)
                if not folders:
                    # (0.105.0) every save failed: the newest copy in backups/
                    restored = self.restore(self.log) if self.restore else None
                    if not restored:
                        if not getattr(self, "none_said", False):
                            # (r14 k1 fixes) which were ruled out, and why
                            why = []
                            if failed:
                                why.append(f"failed to load {LOAD_FAILS_MAX} times: "
                                           + ", ".join(f"'{f}'" for f in failed))
                            if skipped:
                                why.append("not loadable (damaged, or no world.sav): "
                                           + ", ".join(f"'{f}'" for f, _ in skipped))
                            self.log("Revive: no save of the pinned fort is left to try ("
                                     + ("; ".join(why) or "none found") + ") and no backup copy to restore: "
                                     "left at the title.")
                            self.none_said = True
                        return
                    self.restored.append(restored)
                    folders = [restored]
                folder = folders[0]
                self.loads.append(now)
                # (0.100.1, review) the load goes on in steps inside the game after
                # this call returns: the next try waits a full TITLE_S from now
                self.title_since = now
                try:
                    # lua/ai-title.lua: Continue -> the world -> the save (DFHack's
                    # load-save was written for the old interface and fails on DF 50+);
                    # with the world known, the newest of the folders that is that world's
                    if world:
                        out = self._dfhack().run("ai-title", "load-match", world, "|".join(folders))
                        m = re.search(r'"folder"\s*:\s*"([^"]*)"', out)
                        folder = m.group(1) if m else folder
                    else:
                        out = self._dfhack().run("ai-title", "load", folder)
                    if '"ok":true' in out.replace(" ", ""):
                        self.loading = (folder, now)
                        self.late_load = None
                        self.log(f"{self._tag()}: the game sat at the title screen; loading the save '{folder}'.")
                    else:
                        self.log(f"Revive: couldn't load '{folder}' ({out.strip()[-200:]}).")
                        # (0.105.33) a lasting refusal (no save of the world among
                        # the folders, no save of that name, its world not listed)
                        # counts as a failed load: else it was tried all night and
                        # the backup restore was never reached
                        for f in refused_folders(out, folders, folder, bool(world)):
                            self._count_fail(f, "the title screen refused it")
                        if "two saves" in out:
                            # (r9, A10 #13) DF lists the user folder's saves beside a
                            # portable copy's own: same-named saves of another game are
                            # refused, and the fort falls back to a day-old backup; only
                            # the player can clear that folder (said hourly)
                            self._say_hourly("dup_names", now, "Revive: the title screen lists another game's "
                                             "saves under the same names as this fort's (DF shows the user save "
                                             "folder, %APPDATA%\\Bay 12 Games\\Dwarf Fortress\\save, beside "
                                             "this copy's own): they are not loaded. Move that folder's saves "
                                             "aside so the newest autosave can load.")
                except DFHackError as e:
                    self.log(f"Revive: couldn't load '{folder}' ({str(e)[:160]}).")
        elif state == "world":
            self.down_since = self.title_since = None
            self.busy_said = False
            if self.wrong_load:
                # (0.105.48, K17) a load of ours brought up another fort: the
                # overseer refuses it and keeps its heartbeat, so nothing else
                # moves; the game is closed (its pid only) and started again,
                # and the next save is tried. Said hourly while it can't be.
                import pin
                p = pin.current()
                site = getattr(self, "site", None)
                if not p or site in (None, "") or str(site) == str(p.get("site")):
                    self.wrong_load = None
                elif self.close_game(now, f"'{self.wrong_load}' brought up another fort (site {site})"):
                    self.wrong_load = None
                else:
                    self._say_hourly("wrong", now, f"Revive: another fort (site {site}, not the pinned "
                                     f"{p.get('site')}) is loaded from '{self.wrong_load}' and couldn't be closed "
                                     "yet: the overseer won't act on it. Close the game; the keeper starts it again.")
        # (0.100.1, review) running but not answering (a hang, not a crash):
        # dfhack-run times out every time, the overseer keeps its heartbeat,
        # and nothing ever recovered it. After HUNG_S of that, DF is closed;
        # the "down" branch starts it again and loads the fort.
        if state == "unknown":
            # (0.105.48, K17) only a dfhack-run that timed out (NoAnswer) comes here
            self.unknown_since = self.unknown_since or now
            if (self.seen_up and now - self.unknown_since >= HUNG_S and now - self.last_kill >= HUNG_KILL_EVERY_S
                    and os.name == "nt" and save_written_within(SAVE_QUIET_S)):
                if not getattr(self, "save_said", False):
                    self.log("Revive: Dwarf Fortress hasn't answered for a long while, but it is still writing its "
                             "save: left to finish.")
                    self.save_said = True
            elif self.seen_up and now - self.unknown_since >= HUNG_S:
                gone = int(now - self.unknown_since)
                self.close_game(now, f"Dwarf Fortress hasn't answered for {gone} s (hung)", safe_mid_save=True)
        else:
            self.unknown_since = None
            self.save_said = False

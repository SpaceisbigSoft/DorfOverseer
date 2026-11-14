"""Bringing the game back during a long unattended run (keeper --revive).

Two things can end a run that the overseer alone can't fix:
  * Dwarf Fortress closes or crashes: nothing answers dfhack-run. After
    DOWN_S (START_DOWN_S if it wasn't running when the keeper started) the game is started again with the command in config.json's
    "df_launch" (a path to Dwarf Fortress.exe, or a steam:// link for the
    DFHack entry); at most once every LAUNCH_EVERY_S.
  * The game is up but at the title screen (no world loaded): after TITLE_S
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
from dfhack import (PROJECT_ROOT, DFHack, DFHackError, GameNotRunning, configured_port,  # noqa: E501
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
DF_EXE = "Dwarf Fortress.exe"


def write_last_fort(df_path: str | None, save_dir: str | None, fort: str | None,
                    world: str | None = None) -> None:
    """The overseer, each cycle: where the fort's save lives (only when it changed)."""
    if not df_path or not save_dir:
        return
    data = {"df_path": df_path, "save_dir": save_dir, "fort": fort}
    if world:
        data["world"] = world
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
    # (0.105.0 review) a backup restored earlier ("AI restore <date>") is a candidate too
    cands = [root / d["save_dir"]] + sorted(root.glob("autosave*")) + sorted(root.glob(RESTORE_PREFIX + "*"))
    cands = [c for i, c in enumerate(cands) if c.is_dir() and c not in cands[:i]]
    cands.sort(key=save_mtime, reverse=True)
    return [c.name for c in cands], d.get("world")


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
    copies = backup.copies_of(p.get("world"), p.get("site"), p.get("save_dir"))
    root = save_root(p["df_path"], p["save_dir"]) or Path(p["df_path"]) / "save"
    for c in copies:
        name = f"{RESTORE_PREFIX} {c.name}"
        dest = root / name
        if dest.exists():
            continue                      # restored before (and failed, or it'd be loaded): an older one
        try:
            shutil.copytree(c, dest)
        except OSError as e:
            if log:
                log(f"Revive: couldn't copy the backup {c} into the game's saves ({e}).")
            return None
        if log:
            log(f"Revive: every save of the pinned fort failed to load; the backup copy {c.name} is now the "
                f"save '{name}'.")
        return name
    return None


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


def kill_command(port: int | None = None, run=None) -> list[str]:
    """(0.105.1) How to close this keeper's hung game: by the process id that
    listens on its DFHack port (a hung game still holds the port), so a second
    game on another port is never touched. Only when no process listens there
    and a single Dwarf Fortress runs, by name as before."""
    port = port or configured_port() or 5000
    run = run or subprocess.run
    try:
        out = run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=30).stdout or ""
        pid = _listening_pid(port, out)
        if pid:
            return ["taskkill", "/F", "/PID", str(pid)]
        lst = run(["tasklist", "/FI", f"IMAGENAME eq {DF_EXE}", "/FO", "CSV", "/NH"],
                  capture_output=True, text=True, timeout=30).stdout or ""
        if sum(1 for ln in lst.splitlines() if DF_EXE.lower() in ln.lower()) > 1:
            return ["cmd", "/c", "echo", f"two games run and none listens on port {port}: left alone"]
    except (OSError, subprocess.SubprocessError):
        pass
    return ["taskkill", "/F", "/IM", DF_EXE]


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
        self.loading: tuple[str, float] | None = None
        self.restore = restore_from_backup
        self.restored: list[str] = []
        self.df_running = lambda: df_running(exe=own_exe())   # (0.105.33; 0.105.42 its own game only)

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
                 "print(w .. ' SITE=' .. tostring(ok and dfhack.isMapLoaded() and s or ''))")

    def probe(self) -> str:
        """'down' (nothing answers), 'title' (no world loaded) or 'world'."""
        try:
            out = self._dfhack().run("lua", self.PROBE_LUA)
        except GameNotRunning:
            return "down"
        except DFHackError:
            return "unknown"
        m = re.search(r"SITE=(-?\d+)", out)
        self.site = m.group(1) if m else None
        return "world" if "WORLD-LOADED" in out else "title" if "NO-WORLD" in out else "unknown"

    def _load_failed(self, why: str) -> None:
        """(0.105.0) The load under way failed: counted against its folder."""
        folder = self.loading[0]
        self.loading = None
        self._count_fail(folder, why)

    def _count_fail(self, folder: str, why: str) -> None:
        n = self.load_fails[folder] = self.load_fails.get(folder, 0) + 1
        self.log(f"Revive: loading '{folder}' failed ({why}); {n} failed load(s) of it"
                 + (": it isn't tried again, the next older save is." if n >= LOAD_FAILS_MAX else "."))

    def _watch_load(self, state: str, now: float) -> None:
        if self.loading is None:
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
                         "the overseer won't act on it.")
                self._load_failed("another site")
                return
            self.loading = None
            self.load_fails.pop(folder, None)
        elif state == "down":
            self._load_failed("Dwarf Fortress closed")
        elif now - since >= LOAD_TIMEOUT_S:
            self._load_failed(f"no fort {LOAD_TIMEOUT_S // 60} minutes after")

    def tick(self) -> None:
        now = self.clock()
        if now - self.last_probe < (PROBE_EVERY_S if self.seen_up else START_PROBE_S):
            return
        self.last_probe = now
        state = self.probe()
        if state in ("title", "world"):
            self.seen_up = True
        self._watch_load(state, now)
        if state == "down":
            self.title_since = None
            self.down_since = self.down_since or now
            wait = DOWN_S if self.seen_up else START_DOWN_S
            if (not self.seen_up and now - self.down_since >= wait and now - self.down_since < START_BUSY_S
                    and now - self.last_launch >= LAUNCH_EVERY_S and self.df_running()):
                if not getattr(self, "busy_said", False):
                    self.log("Revive: Dwarf Fortress is running but DFHack doesn't answer yet (still starting?): "
                             f"waiting up to {START_BUSY_S} s before starting it.")
                    self.busy_said = True
                return
            if now - self.down_since >= wait and now - self.last_launch >= LAUNCH_EVERY_S:
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
                    self.log(f"Revive: Dwarf Fortress wasn't running for {int(now - self.down_since)} s: "
                             f"started it again ({cmd}).")
                except OSError as e:
                    self.log(f"Revive: couldn't start Dwarf Fortress ({e}).")
        elif state == "title":
            self.down_since = None
            self.busy_said = False        # (0.105.36, D7) said again the next time DF starts slowly
            self.title_since = self.title_since or now
            self.loads = [t for t in self.loads if now - t < 3600]
            if now - self.title_since >= TITLE_S and len(self.loads) < LOADS_PER_HOUR:
                if self.loading is not None:
                    return                    # (0.105.0) the last load still has time to come up
                folders, world = self.candidates()
                folders = [f for f in folders if self.load_fails.get(f, 0) < LOAD_FAILS_MAX]
                if not folders:
                    # (0.105.0) every save failed: the newest copy in backups/
                    restored = self.restore(self.log) if self.restore else None
                    if not restored:
                        if not getattr(self, "none_said", False):
                            self.log("Revive: no save of the pinned fort is left to try (each failed to load "
                                     f"{LOAD_FAILS_MAX} times) and no backup copy to restore: left at the title.")
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
                        self.log(f"Revive: the game sat at the title screen; loading the save '{folder}'.")
                    else:
                        self.log(f"Revive: couldn't load '{folder}' ({out.strip()[-200:]}).")
                        # (0.105.33) a lasting refusal (no save of the world among
                        # the folders, no save of that name, its world not listed)
                        # counts as a failed load: else it was tried all night and
                        # the backup restore was never reached
                        for f in refused_folders(out, folders, folder, bool(world)):
                            self._count_fail(f, "the title screen refused it")
                except DFHackError as e:
                    self.log(f"Revive: couldn't load '{folder}' ({str(e)[:160]}).")
        elif state == "world":
            self.down_since = self.title_since = None
            self.busy_said = False
        # (0.100.1, review) running but not answering (a hang, not a crash):
        # dfhack-run times out every time, the overseer keeps its heartbeat,
        # and nothing ever recovered it. After HUNG_S of that, DF is closed;
        # the "down" branch starts it again and loads the fort.
        if state == "unknown":
            self.unknown_since = self.unknown_since or now
            if (self.seen_up and now - self.unknown_since >= HUNG_S and now - self.last_kill >= HUNG_KILL_EVERY_S
                    and os.name == "nt" and save_written_within(SAVE_QUIET_S)):
                if not getattr(self, "save_said", False):
                    self.log("Revive: Dwarf Fortress hasn't answered for a long while, but it is still writing its "
                             "save: left to finish.")
                    self.save_said = True
            elif (self.seen_up and now - self.unknown_since >= HUNG_S and now - self.last_kill >= HUNG_KILL_EVERY_S
                    and os.name == "nt"):
                self.last_kill = now
                try:
                    r = subprocess.run(kill_command(), capture_output=True, text=True, timeout=30)
                    self.log(f"Revive: Dwarf Fortress hasn't answered for {int(now - self.unknown_since)} s "
                             f"(hung): closed it ({(r.stdout or r.stderr).strip()[:120]}); it's started again "
                             "once it's gone.")
                except (OSError, subprocess.SubprocessError) as e:
                    self.log(f"Revive: Dwarf Fortress seems hung, and couldn't be closed ({e}).")
        else:
            self.unknown_since = None
            self.save_said = False

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
from dfhack import CONFIG_PATH, PROJECT_ROOT, DFHack, DFHackError, GameNotRunning, save_root

LAST_FORT = Path(os.environ.get("DFAI_LOG_DIR") or PROJECT_ROOT / "logs") / "last-fort.json"
PROBE_EVERY_S = 60
DOWN_S = 180
# the game not running when the keeper starts (never seen up this run): start it
# almost at once, probing every START_PROBE_S
START_PROBE_S = 15
START_DOWN_S = 15
TITLE_S = 120
LAUNCH_EVERY_S = 900
LOADS_PER_HOUR = 3
HUNG_S = 1800                # (0.100.1) no answer this long (not down, not at the title): DF is closed
                             # (0.104.138: 30 min, was 15: Teacheroar's autosaves took up to 10)
SAVE_QUIET_S = 180           # (0.104.138) never while a save folder was written this recently
HUNG_KILL_EVERY_S = 3600     # at most once an hour
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
            return
        LAST_FORT.parent.mkdir(exist_ok=True)
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
    which world each save is; lua/ai-title.lua checks)."""
    try:
        d = json.loads(LAST_FORT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], None
    root = save_root(d["df_path"], d["save_dir"]) or Path(d["df_path"]) / "save"   # (0.99.13)
    from backup import folder_mtime
    cands = [root / d["save_dir"]] + sorted(root.glob("autosave*"))
    cands = [c for c in cands if c.is_dir()]
    cands.sort(key=folder_mtime, reverse=True)
    return [c.name for c in cands], d.get("world")


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


def launch_command() -> str | None:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cmd = cfg.get("df_launch")
    return cmd if isinstance(cmd, str) and cmd.strip() else None


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

    def _dfhack(self) -> DFHack:
        if self.df is None:
            self.df = DFHack.from_config()
        return self.df

    @staticmethod
    def _launch(cmd: str) -> None:
        if os.name == "nt":
            os.startfile(cmd)                    # an .exe or a steam:// link alike
        else:
            subprocess.Popen(cmd, shell=True)    # (tests and other systems)

    def probe(self) -> str:
        """'down' (nothing answers), 'title' (no world loaded) or 'world'."""
        try:
            out = self._dfhack().run("lua", "print(dfhack.isWorldLoaded() and 'WORLD-LOADED' or 'NO-WORLD')")
        except GameNotRunning:
            return "down"
        except DFHackError:
            return "unknown"
        return "world" if "WORLD-LOADED" in out else "title" if "NO-WORLD" in out else "unknown"

    def tick(self) -> None:
        now = self.clock()
        if now - self.last_probe < (PROBE_EVERY_S if self.seen_up else START_PROBE_S):
            return
        self.last_probe = now
        state = self.probe()
        if state in ("title", "world"):
            self.seen_up = True
        if state == "down":
            self.title_since = None
            self.down_since = self.down_since or now
            wait = DOWN_S if self.seen_up else START_DOWN_S
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
            self.title_since = self.title_since or now
            self.loads = [t for t in self.loads if now - t < 3600]
            if now - self.title_since >= TITLE_S and len(self.loads) < LOADS_PER_HOUR:
                folders, world = self.candidates()
                if not folders:
                    return
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
                        self.log(f"Revive: the game sat at the title screen; loading the save '{folder}'.")
                    else:
                        self.log(f"Revive: couldn't load '{folder}' ({out.strip()[-200:]}).")
                except DFHackError as e:
                    self.log(f"Revive: couldn't load '{folder}' ({str(e)[:160]}).")
        elif state == "world":
            self.down_since = self.title_since = None
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
                    r = subprocess.run(["taskkill", "/F", "/IM", DF_EXE], capture_output=True, text=True, timeout=30)
                    self.log(f"Revive: Dwarf Fortress hasn't answered for {int(now - self.unknown_since)} s "
                             f"(hung): closed it ({(r.stdout or r.stderr).strip()[:120]}); it's started again "
                             "once it's gone.")
                except (OSError, subprocess.SubprocessError) as e:
                    self.log(f"Revive: Dwarf Fortress seems hung, and couldn't be closed ({e}).")
        else:
            self.unknown_since = None
            self.save_said = False

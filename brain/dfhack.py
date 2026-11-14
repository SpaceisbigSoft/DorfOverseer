"""Talk to a running Dwarf Fortress + DFHack from Python.

For now this goes through dfhack-run.exe (the same tool you tested by hand).
Later we can swap in a direct connection to DFHack's remote server on port 5000
without changing the code that calls these functions.
"""

from __future__ import annotations

import json
import os
import errno
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"


def read_config(path: Path | None = None) -> dict:
    """(13c) config.json as a dict ({} when it is missing, unreadable or not
    an object). `path` defaults to CONFIG_PATH as it is at the call (tests
    point it elsewhere)."""
    from util import load_json
    return load_json(CONFIG_PATH if path is None else path, {})


def write_atomic(path: Path, text: str) -> None:
    """(0.100) Write a file whole or not at all: to a temporary file beside it,
    then swapped in. The keeper may kill a stuck overseer mid-write, and a
    half-written report, index or last-fort file lost history or split a
    fort's logs."""
    path = Path(path)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        # (review) Windows refuses the swap while another program has the
        # file open (the reviver reading last-fort.json, a virus scan): a
        # few short tries, then the error; the temporary file never stays
        for attempt in range(5):
            try:
                tmp.replace(path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def logs_dir() -> Path:
    """(13c) The logs folder: DFAI_LOG_DIR if set (tests/run_all.py points it
    at a temporary folder, so tests no longer write fake soak rows and probe
    files into the real logs), else DF-AI\\logs."""
    return Path(os.environ.get("DFAI_LOG_DIR") or PROJECT_ROOT / "logs")


def save_roots(df_path: str | Path | None) -> list[Path]:
    """(0.99.13) Where Dwarf Fortress keeps saves, most likely first: config's
    df_save_dir if set, DF's user folder (%APPDATA%\\Bay 12 Games\\Dwarf
    Fortress\\save, where the Steam game saves unless it runs portable), then
    the game's own folder (portable saves). The tools used only the last one,
    which on this PC holds 2023 saves: the backups copied those, and the test
    copies landed where the game doesn't look."""
    roots: list[Path] = []
    cfg = read_config()
    if cfg.get("df_save_dir"):
        roots.append(Path(cfg["df_save_dir"]))
    # (0.105.42) a portable copy (prefs/portable.txt) saves only in its own
    # folder: the user folder there holds another game's saves under the same
    # names ("autosave 2", "region4"), and on 13 Nov C's and D's keepers picked
    # A's newer one from it and loaded A's fort into their games
    if df_path and (Path(df_path) / "prefs" / "portable.txt").is_file():
        own = Path(df_path) / "save"
        if own.is_dir() and own not in roots:
            roots.append(own)
        return [r for r in roots if r.is_dir()]
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata) / "Bay 12 Games" / "Dwarf Fortress" / "save")
    if df_path:
        roots.append(Path(df_path) / "save")
    out: list[Path] = []
    for r in roots:
        if r.is_dir() and r not in out:
            out.append(r)
    return out


def save_root(df_path: str | Path | None, save_dir: str | None = None) -> Path | None:
    """The save folder that holds `save_dir` (the newest copy when both do),
    else the likeliest one."""
    roots = save_roots(df_path)
    if save_dir:
        having = [r for r in roots if (r / save_dir).is_dir()]
        if len(having) == 1:
            return having[0]
        if having:
            from backup import folder_mtime
            return max(having, key=lambda r: folder_mtime(r / save_dir))
    return roots[0] if roots else None


class DFHackError(RuntimeError):
    """Raised when DFHack can't be reached or a command fails."""


ACCESS_VIOLATION = {3221225477, -1073741819}   # 0xC0000005, unsigned and signed


class GameNotRunning(DFHackError):
    """Dwarf Fortress (with DFHack) isn't running, so nothing answered."""


class NotStarted(DFHackError):
    """(0.105.40 review) dfhack-run could not be started at all (the program
    gone, a command line too long): nothing reached the game."""


def not_started(e: OSError) -> bool:
    """(0.105.40 review) An OSError of starting the process itself: the
    program missing (FileNotFoundError), or the command line too long
    (Windows' error 206, POSIX E2BIG)."""
    return (isinstance(e, FileNotFoundError) or getattr(e, "winerror", None) == 206
            or getattr(e, "errno", None) == errno.E2BIG)


class NoAnswer(DFHackError):
    """(0.105.40 review) dfhack-run started but gave no answer in time: what
    it carried may have run."""


def configured_port(path: Path = CONFIG_PATH) -> int | None:
    """(0.105.1) The DFHack port this DF-AI folder talks to: config.json's
    "dfhack_port" (two games side by side: each DF-AI copy names its own
    game's port), else the DFHACK_PORT environment variable, else None (DFHack's
    default, 5000). DFHack's server and dfhack-run both read DFHACK_PORT first."""
    v = read_config(Path(path)).get("dfhack_port")
    if isinstance(v, int) and 0 < v < 65536:
        return v
    try:
        v = int(os.environ.get("DFHACK_PORT") or 0)
        return v if 0 < v < 65536 else None
    except ValueError:
        return None


def port_env(port: int | None) -> dict | None:
    """(0.105.1) The environment for dfhack-run and a game this folder starts:
    DFHACK_PORT set to its port (None: the inherited environment unchanged)."""
    if not port:
        return None
    env = dict(os.environ)
    env["DFHACK_PORT"] = str(port)
    return env


@dataclass
class DFHack:
    dfhack_run: Path
    timeout_s: float = 10.0
    port: int | None = None             # (0.105.1) config "dfhack_port"; None: DFHack's default

    @classmethod
    def from_config(cls, path: Path = CONFIG_PATH) -> "DFHack":
        if not path.exists():
            raise DFHackError(
                f"Missing {path.name}. Copy config.example.json to config.json "
                "and set the path to dfhack-run.exe."
            )
        cfg = json.loads(path.read_text(encoding="utf-8"))
        exe = Path(cfg["dfhack_run"])
        # (0.100, security pass) the program itself: a .bat or .cmd wrapper
        # would hand the JSON (game text in it) to cmd.exe to parse again
        if exe.suffix.lower() not in (".exe", ""):
            raise DFHackError(f"dfhack_run must be dfhack-run.exe itself, not {exe.name}")
        if not exe.exists():
            raise DFHackError(f"dfhack-run not found at: {exe}")
        return cls(dfhack_run=exe, timeout_s=float(cfg.get("timeout_s", 10.0)), port=configured_port(path))

    def run(self, *args: str, timeout: float | None = None) -> str:
        """Run a DFHack command or script in the live game and return its output.
        timeout: this call's own limit (the full report at a low frame rate
        takes longer than a command); default the config's timeout_s."""
        limit = timeout or self.timeout_s
        try:
            proc = subprocess.run(
                [str(self.dfhack_run), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=limit,
                env=port_env(self.port),        # (0.105.1) this folder's game, when two run
            )
        except subprocess.TimeoutExpired as e:
            raise NoAnswer(f"DFHack did not answer within {limit}s") from e
        except OSError as e:
            # (0.100) Windows couldn't start it (the program gone mid-run, a
            # command line over 32K): one failed call, not a crashed cycle.
            # (0.105.40 review) NotStarted only when the process itself could
            # not be made: nothing reached the game. Any other OSError (later,
            # talking to it) may come after the game ran the command
            if not_started(e):
                raise NotStarted(f"couldn't run dfhack-run: {e}") from e
            raise DFHackError(f"couldn't run dfhack-run: {e}") from e

        output = (proc.stdout or "") + (proc.stderr or "")
        # dfhack-run says "Could not connect" (exit 2) when nothing listens; on
        # Windows it can also crash outright when the game is closed (exit
        # 0xC0000005, an access violation, with no output: seen Oct 23)
        if ((proc.returncode == 2 and "Could not connect" in output)
                or (proc.returncode in ACCESS_VIOLATION and not output.strip())):
            raise GameNotRunning(
                "Dwarf Fortress isn't running (or DFHack isn't loaded). "
                "Start it from the DFHack entry in Steam."
            )
        if proc.returncode != 0:
            raise DFHackError(
                f"dfhack-run exited with code {proc.returncode}:\n{output.strip()}"
            )
        return output

    def run_json(self, *args: str, timeout: float | None = None) -> dict:
        """Run a script that prints one line of JSON and return it parsed."""
        output = self.run(*args, timeout=timeout) if timeout else self.run(*args)
        for line in reversed(output.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)
        raise DFHackError(f"No JSON in output of {' '.join(args)}:\n{output.strip()}")

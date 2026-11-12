"""The Python end of the bridge: ask the game for a fort report, pause or resume it.

Talks to lua/ai-bridge.lua running inside DFHack. Every call is logged to
logs/bridge.log so a session can be replayed and debugged later.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import time
from pathlib import Path

from dfhack import PROJECT_ROOT, DFHack, DFHackError, GameNotRunning, logs_dir  # noqa: F401

# Must match PROTOCOL in lua/ai-bridge.lua.
EXPECTED_PROTOCOL = 1

LOG_DIR = logs_dir()   # (13c) DFAI_LOG_DIR in tests


def _setup_logger() -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    log = logging.getLogger("bridge")
    if not log.handlers:
        # Capped: at most ~42 MB in total (bridge.log plus 20 older copies:
        # (0.100.1) a whole night's calls, for the morning's review).
        handler = logging.handlers.RotatingFileHandler(
            LOG_DIR / "bridge.log", maxBytes=2_000_000, backupCount=20, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    return log


REPORT_TIMEOUT_S = 30.0      # (0.100.1) the full report's own time limit
# (0.105.40, 13e) every bridge call's time, summed for this process (across
# reconnects): brain/perf.py turns it into the AI's ms per game day
CALL_MS = {"ms": 0.0, "calls": 0}


def note_call_ms(ms: float) -> None:
    CALL_MS["ms"] += ms
    CALL_MS["calls"] += 1


class BridgeError(DFHackError):
    """The bridge script answered, but with an error."""


class Bridge:
    def __init__(self, dfhack: DFHack | None = None) -> None:
        self.df = dfhack or DFHack.from_config()
        self.log = _setup_logger()
        self.version: dict | None = None
        self.out_dir: Path | None = None

    def _call(self, *args: str, timeout: float | None = None) -> dict:
        start = time.perf_counter()
        try:
            reply = (self.df.run_json("ai-bridge", *args, timeout=timeout) if timeout
                     else self.df.run_json("ai-bridge", *args))
        except DFHackError as e:
            self.log.error("%s -> %s", " ".join(args), e)
            raise
        ms = (time.perf_counter() - start) * 1000
        note_call_ms(ms)
        # The overseer checks status every 2 s; logging each one would fill the
        # log with noise. Everything else (reports, actions, events) is logged.
        level = logging.DEBUG if args and args[0] == "status" and reply.get("ok") else logging.INFO
        self.log.log(level, "%s -> %s (%.0f ms)", " ".join(args), json.dumps(reply), ms)
        if not reply.get("ok"):
            raise BridgeError(reply.get("error", "unknown error from ai-bridge"))
        return reply

    def handshake(self) -> dict:
        """Check versions. Call once before anything else."""
        info = self._call("version")
        if info.get("protocol") != EXPECTED_PROTOCOL:
            raise BridgeError(
                f"ai-bridge.lua speaks protocol {info.get('protocol')}, "
                f"but this Python code expects {EXPECTED_PROTOCOL}. "
                "Update both sides together."
            )
        self.version = info
        return info

    def state(self, include_units: bool = True, tier: str | None = None) -> dict:
        """Ask the game for a fort report and return it as a dict. tier="pulse"
        asks for the small one (date, threats, stocks, orders, projects, gates,
        moods, military, settings: no units); the default is the full daily report."""
        args = ["state"] if include_units else ["state", "--no-units"]
        if tier:
            args += ["--tier", tier]
        # (0.100.1, review) the full report may take longer than a command at
        # a low frame rate (23 timeouts in one night's log): a day was skipped
        reply = self._call(*args, timeout=REPORT_TIMEOUT_S if tier != "pulse" else None)
        path = Path(reply["file"])
        self.out_dir = path.parent          # where the game reads and writes our files
        state = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        state["_meta"] = {"build_ms": reply.get("build_ms"), "file": str(path)}
        return state

    def load_memory(self) -> dict | None:
        """The overseer's memory as stored in the loaded save, or None."""
        reply = self._call("memory", "raw", timeout=60)   # (0.104.62) long kinds undecoded
        if not reply.get("present"):
            return None
        data = json.loads(Path(reply["file"]).read_text(encoding="utf-8", errors="replace"))
        # (0.104.44) long texts come in files of their own
        kinds = data.get("kinds") if isinstance(data, dict) else None
        if isinstance(kinds, dict):
            for k, v in list(kinds.items()):
                # (0.104.62) a kind as the save keeps it, undecoded JSON ({fort, text})
                if isinstance(v, dict) and isinstance(v.get("raw"), str):
                    try:
                        got = json.loads(Path(v["raw"]).read_text(encoding="utf-8", errors="replace"))
                    except (OSError, ValueError):
                        got = None
                    if isinstance(got, dict) and isinstance(got.get("text"), str):
                        kinds[k] = {"fort": got.get("fort"), "text": got["text"]}
                    else:
                        del kinds[k]
                    continue
                if isinstance(v, dict) and isinstance(v.get("file"), str) and "text" not in v:
                    v["text"] = Path(v["file"]).read_text(encoding="utf-8", errors="replace")
        return data

    def save_memory(self, data: dict) -> bool:
        """Store the overseer's memory in the save (call state() first)."""
        if self.out_dir is None:
            return False
        tmp = self.out_dir / "memory-to-save.json"
        kinds = data.get("kinds") if isinstance(data, dict) else None
        if isinstance(kinds, dict) and all(isinstance(v, str) for v in kinds.values()):
            # (0.104.44) each text in a file of its own, read as it is in Lua
            files = {}
            for kind, text in kinds.items():
                name = f"memory-to-save.{kind}.txt"
                (self.out_dir / name).write_text(text, encoding="ascii", errors="replace")
                files[kind] = name
            data = {k: v for k, v in data.items() if k != "kinds"}
            data["kinds_files"] = files
        tmp.write_text(json.dumps(data), encoding="utf-8")
        return bool(self.act({"type": "save_memory"}).get("ok"))

    def events(self) -> list[dict]:
        """Collect events queued in-game since the last call (deaths, arrivals,
        invasions), oldest first. The queue is cleared."""
        reply = self._call("events")
        data = json.loads(Path(reply["file"]).read_text(encoding="utf-8", errors="replace"))
        return as_list(data.get("events"))

    def survey(self) -> dict:
        """The site for the master plan: the main stairs, soil levels, the
        dwarves' busiest level (bridge 0.32+; read-only)."""
        return self._call("survey")

    def map_info(self) -> dict:
        """Cavern, magma sea and underworld layers with their depths."""
        return self._call("map")

    def pause(self) -> None:
        self._call("pause")

    def status(self) -> dict:
        """Cheap check: is a fort loaded, is it paused, what's the date."""
        return self._call("status")

    def run_ticks(self, ticks: int) -> None:
        """Unpause; the game pauses itself again after `ticks` (1200 = one day)."""
        self._call("run", str(int(ticks)))

    def wait_for_run(
        self,
        ticks: int,
        poll_s: float = 0.5,
        on_stall=None,
        stall_after_s: float = 5.0,
        max_stall_s: float = 300.0,
        min_ticks_per_s: float = 5.0,
    ) -> dict:
        """Wait for a timed run (started with run_ticks) to finish.

        Returns the final status. status["interrupted"] is True if the game
        paused before the run was done (DF pauses itself for sieges, migrants
        and similar announcements, or the player paused it).

        "Stalled" means the game is unpaused but time isn't moving, which DF
        does while a popup or menu waits for a click. After `stall_after_s`
        seconds of that, on_stall() is called once (e.g. to tell the player).
        Stalled time doesn't count against the time limit, so the run carries
        on once the popup is closed. After `max_stall_s` the game is paused.

        The time limit scales with the run length: it only trips if the game
        runs slower than `min_ticks_per_s` (DF's speed is roughly its FPS; a
        big fort in a fight can drop to 20 or below, which is slow but fine).
        On any timeout the game is paused, so it is never left running untracked.
        """
        budget = ticks / min_ticks_per_s + 30  # seconds of actual running allowed
        last_tick, last_change, used, warned = None, time.monotonic(), 0.0, False
        while True:
            now = time.monotonic()
            st = self.status()
            if not st.get("in_fort"):
                raise BridgeError("the fort was unloaded while waiting")
            if st.get("paused"):
                st["interrupted"] = bool(st.get("run_ticks_remaining"))
                return st
            tick = (st["date"]["year"], st["date"]["tick"])
            if tick != last_tick:
                if last_tick is not None:
                    used += now - last_change
                last_tick, last_change, warned = tick, now, False
            else:
                stalled = now - last_change
                if stalled > stall_after_s and not warned:
                    warned = True
                    self.log.warning("game not advancing for %.0fs (popup or menu open?)", stalled)
                    if on_stall:
                        on_stall()
                if stalled > max_stall_s:
                    self.pause()
                    raise BridgeError(f"game stuck for {stalled:.0f}s (a popup or menu?); paused it")
            if used > budget:
                self.pause()
                raise BridgeError(f"run of {ticks} ticks did not finish in time; game paused")
            time.sleep(poll_s)

    def act(self, action: dict) -> dict:
        """Perform one action. Returns the game's answer.

        A refused action (bad values, not allowed) comes back with ok=False and
        rejected=True instead of raising, because the AI is expected to read
        the reason and try something else.
        """
        payload = json.dumps(action, separators=(",", ":"))
        start = time.perf_counter()
        reply = self.df.run_json("ai-bridge", "act", payload)
        ms = (time.perf_counter() - start) * 1000
        note_call_ms(ms)
        level = logging.INFO if reply.get("ok") else logging.WARNING
        self.log.log(level, "act %s -> %s (%.0f ms)", payload, json.dumps(reply), ms)
        if not reply.get("ok") and not reply.get("rejected"):
            raise BridgeError(reply.get("error", "action failed"))
        return reply


def as_dict(value) -> dict:
    """Lua turns empty tables into [] in JSON; treat those as empty dicts."""
    return value if isinstance(value, dict) else {}


def as_list(value) -> list:
    return value if isinstance(value, list) else []

"""Phase 0 connection test: can Python read the live game?

Run from the project folder, with Dwarf Fortress running (launched via DFHack):

    python brain/check_connection.py
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dfhack import DFHack, DFHackError  # noqa: E402

ROUNDS = 5


def main() -> int:
    try:
        df = DFHack.from_config()
        info = df.run_json("ai-ping")
    except DFHackError as e:
        print("FAILED:", e)
        print(
            "\nChecklist:\n"
            "  - Is Dwarf Fortress running, started with DFHack?\n"
            "  - Did you restart DF after the script-paths.txt change? (it is read at startup)\n"
            "  - Does `ai-ping` work when typed into the DFHack launcher in-game?"
        )
        return 1

    print("Connected to the game.")
    print(f"  DFHack version : {info['dfhack_version']}")
    print(f"  DF version     : {info['df_version']}")
    if info.get("map_loaded"):
        print(f"  Citizens       : {info['citizens']}")
        print(f"  Year           : {info['year']} (tick {info['year_tick']})")
    else:
        print("  No fortress loaded (load one to see citizens and the date).")

    times = []
    for _ in range(ROUNDS):
        start = time.perf_counter()
        df.run_json("ai-ping")
        times.append((time.perf_counter() - start) * 1000)
    print(
        f"\nRound trip over {ROUNDS} calls: "
        f"median {statistics.median(times):.0f} ms, worst {max(times):.0f} ms"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

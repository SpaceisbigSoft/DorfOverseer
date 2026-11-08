"""Phase 1 check: can Python change the game, safely and reversibly?

Run from the project folder, with your TEST fort loaded:

    python brain/tools/try_actions.py

What it does, in order:
  1. Pauses the game.
  2. Queues a tiny work order (brew 1 drink), then cancels it again.
  3. Tries four actions that SHOULD be refused, to prove the safety checks work.
  4. Lets exactly one in-game day pass, then confirms the game paused itself.

Net effect on your fort: one day passes. Nothing else is left changed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # (13c) brain/tools/ -> brain/

from bridge import Bridge, BridgeError  # noqa: E402
from dfhack import DFHackError  # noqa: E402
from util import date_tick  # noqa: E402

ONE_DAY = 1200  # ticks

passed = 0
failed = 0


def check(label: str, good: bool, detail: str = "") -> None:
    global passed, failed
    if good:
        passed += 1
    else:
        failed += 1
    mark = "OK  " if good else "FAIL"
    print(f"  [{mark}] {label}" + (f"  ({detail})" if detail else ""))


def date_str(d: dict) -> str:
    return f"{d['day']} {d['month']}, year {d['year']}"


def main() -> int:
    try:
        bridge = Bridge()
        info = bridge.handshake()
        status = bridge.status()
    except (DFHackError, BridgeError) as e:
        print("FAILED:", e)
        return 1

    print(f"Bridge {info['bridge_version']}; actions: {', '.join(info.get('actions', []))}; "
          f"{len(info.get('recipes', []))} work-order recipes")
    if not status.get("in_fort"):
        print("No fortress is loaded. Load your test fort and run this again.")
        return 1

    print("\n1. Pause")
    bridge.pause()
    status = bridge.status()
    check("game is paused", status.get("paused") is True)
    start_date = status["date"]
    print(f"     Date: {date_str(start_date)}")

    print("\n2. Queue a work order, then cancel it")
    r = bridge.act({"type": "work_order", "recipe": "brew_drink", "amount": 1})
    check("work order accepted", r.get("ok") is True, f"order id {r.get('order_id')}")
    if r.get("ok"):
        c = bridge.act({"type": "cancel_work_order", "order_id": r["order_id"]})
        check("work order cancelled again", c.get("cancelled") is True)

    print("\n3. Actions that must be refused")
    r = bridge.act({"type": "work_order", "recipe": "brew_drink", "amount": 99999})
    check("absurd amount refused", r.get("rejected") is True, r.get("error", ""))
    r = bridge.act({"type": "work_order", "recipe": "launch_catapults", "amount": 1})
    check("unknown recipe refused", r.get("rejected") is True, "only recipes from the approved list")
    r = bridge.act({"type": "tool", "name": "autolabor", "enabled": True})
    check("autolabor not allowed", r.get("rejected") is True, "it would rewrite every dwarf's labors")
    r = bridge.act({"type": "cancel_work_order", "order_id": 0})
    check("can't cancel a player's order", r.get("rejected") is True, r.get("error", ""))

    print("\n4. Let one in-game day pass")
    bridge.run_ticks(ONE_DAY)
    print("     Running... (the game pauses itself after one day)")
    try:
        status = bridge.wait_for_run(
            ONE_DAY,
            on_stall=lambda: print("     The game has stopped advancing. Is a popup or menu open in DF?\n"
                                   "     Close it and the run will carry on by itself."),
        )
    except BridgeError as e:
        check("game paused itself", False, str(e))
        bridge.pause()
        return 1
    end_date = status["date"]
    advanced = date_tick(end_date) - date_tick(start_date)
    check("game paused itself", status.get("paused") is True)
    if status.get("interrupted"):
        print(f"     DF paused early (after {advanced} ticks), probably for an announcement.")
        print("     That's normal game behavior, not a failure. Check the game, then rerun if you like.")
    else:
        check("about one day passed", ONE_DAY - 10 <= advanced <= ONE_DAY + 100, f"{advanced} ticks")
    print(f"     Date now: {date_str(end_date)}")

    print(f"\n{passed} passed, {failed} failed. Details are in logs\\bridge.log.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

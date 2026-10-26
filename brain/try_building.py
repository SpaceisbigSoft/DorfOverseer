"""Check the AI's building on your fort. By default changes NOTHING.

    python brain/try_building.py            where would each kind of level go?
    python brain/try_building.py --really   dig one small bedroom level (4 rooms)
                                            so you can watch it happen
    python brain/try_building.py --cancel N cancel AI project number N (while digging)

Use your TEST fort for --really.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bridge import Bridge, BridgeError  # noqa: E402
from dfhack import GameNotRunning  # noqa: E402

TRIES = [
    {"kind": "bedrooms", "rooms": 16, "room_size": 3},
    {"kind": "dining", "tables": 20},
    {"kind": "storage", "piles": ["food", "stone", "wood", "furniture"], "room_size": 7},
    {"kind": "workshops", "shops": ["Still", "Kitchen", "Masons"]},
    {"kind": "hospital", "beds": 8},
    {"kind": "barracks", "beds": 8},
    {"kind": "tombs", "coffins": 12},
    {"kind": "tavern", "tables": 8},
    {"kind": "library", "bookcases": 6},
    {"kind": "temple", "size": "shrine"},
    {"kind": "memorial", "name": "Test Beast"},
]


def act(bridge: Bridge, action: dict) -> dict:
    try:
        return bridge.act(action)
    except BridgeError as e:
        return {"ok": False, "error": str(e)}


def describe(r: dict) -> str:
    if not r.get("ok"):
        return f"NOT POSSIBLE: {r.get('error')}"
    if r.get("extends_stairs"):
        how = "stairs extended down to it"
    elif r.get("corridor"):
        how = f"beside the stairs, joined by a {r['corridor']}-tile corridor"
    else:
        how = "centred on the stairs"
    s = r.get("stair") or {}
    level = r.get("elevation", r["z"])     # the level number the game shows
    where = f"level {level} ({how}; staircase at x{s.get('x')} y{s.get('y')})"
    furn = ", ".join(f"{v} {k.lower()}" for k, v in sorted((r.get("furniture") or {}).items()))
    return f"{where}, {r['tiles']} tiles to dig" + (f"; furniture: {furn}" if furn else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--really", action="store_true", help="dig one small bedroom level")
    ap.add_argument("--cancel", type=int, metavar="N", help="cancel AI project N")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    try:
        bridge = Bridge()
        info = bridge.handshake()
    except GameNotRunning:
        print("Dwarf Fortress isn't running (start it from the DFHack entry in Steam).")
        return 1
    if "start_project" not in (info.get("actions") or []):
        print(f"The game has bridge {info.get('bridge_version')}; building needs 0.7.0. "
              "Restart Dwarf Fortress so it loads the new scripts.")
        return 1

    if args.cancel is not None:
        r = act(bridge, {"type": "cancel_project", "project_id": args.cancel})
        print("Cancelled." if r.get("ok") else f"Not cancelled: {r.get('error')}")
        return 0 if r.get("ok") else 1

    print("Where each kind of level would go (dry run, nothing is changed):\n")
    for t in TRIES:
        r = act(bridge, {"type": "start_project", "dry_run": True, **t})
        print(f"  {t['kind']:<10} {describe(r)}")

    if not args.really:
        print("\nNothing was changed. Run with --really to dig a small bedroom level on your TEST fort.")
        return 0

    print("\nDigging a 4-room bedroom level for real...")
    r = act(bridge, {"type": "start_project", "kind": "bedrooms", "rooms": 4, "room_size": 3})
    print(json.dumps(r, indent=1))
    if r.get("ok"):
        print(f"\nStarted project #{r['project_id']} on level {r.get('elevation', r['z'])}. "
              "Unpause and watch the miners. "
              "The overseer (--autopilot) furnishes it when the digging is done.\n"
              f"To undo the designations: python brain\\try_building.py --cancel {r['project_id']}")
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())

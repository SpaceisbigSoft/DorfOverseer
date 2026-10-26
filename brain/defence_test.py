"""The defence test: a few hostile invaders set down outside the fort, and
what the AI does about them, watched and written down. FOR A TEST SAVE ONLY:
they are real enemies and can kill dwarves.

    python brain\\defence_test.py --dry          where they would appear (nothing made)
    python brain\\defence_test.py [N] [RACE]     N invaders (1-10, default 3; RACE default GOBLIN)

Run the keeper in another window first (python brain\\keeper.py): it is the
AI that reacts. This script only makes the threat and watches, every 3
seconds, until the threat is gone or 15 minutes pass: threats on the map and
whether they can reach the dwarves, the AI gate lever, squads' kill orders,
citizens alive. Everything goes to logs/defence-test.json, with a short verdict.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

from bridge import Bridge  # noqa: E402

WATCH_S = 3
TIMEOUT_S = 15 * 60
QUIET_S = 60


def snapshot(b: Bridge) -> dict:
    st = b.state(include_units=False, tier="pulse")
    om = st.get("others_on_map") or {}
    mil = st.get("military") or {}
    return {
        "date": st.get("date"),
        "citizens": (st.get("dwarves") or {}).get("total"),
        "threats": len(om.get("threats") or []),
        "reach": om.get("threats_that_can_reach_dwarves"),
        "contained": om.get("contained_dangers"),
        "orders": sorted(q.get("name") or str(q.get("id")) for q in (mil.get("squads") or []) if q.get("ai_orders")),
        # (0.104.83) squads holding the main gate (a defend order) rather than out to kill
        "guarding": sorted(q.get("name") or str(q.get("id")) for q in (mil.get("squads") or []) if q.get("guarding")),
        "gates": [(g.get("id"), g.get("state")) for g in (mil.get("gates") or [])],
        "soldiers": mil.get("soldiers"),
    }


def main(argv: list[str]) -> int:
    dry = "--dry" in argv
    rest = [a for a in argv if not a.startswith("--")]
    n = int(rest[0]) if rest and rest[0].isdigit() else 3
    race = next((a.upper() for a in rest if not a.isdigit()), "GOBLIN")
    b = Bridge()
    args = ["test_threat", str(n), race] + (["--dry"] if dry else [])
    if dry:
        r = b._call(*args)
        print("would set down" if not r.get("refused") else "can't:", r.get("refused") or
              f"{r.get('count')} {r.get('race')} at x{r['spot']['x']} y{r['spot']['y']} z{r['spot']['z']} "
              f"(enemy civilisation {r.get('civ')})")
        return 0
    print("This makes REAL enemies that can kill dwarves. Use a test save (or a copy of yours).")
    if input("Type YES to go on: ").strip() != "YES":
        print("Stopped; nothing made.")
        return 1
    start = snapshot(b)
    r = b._call(*args)
    if r.get("refused") or not r.get("ok"):
        print("not made:", r.get("refused") or r.get("error"))
        return 1
    print(f"{r.get('count')} {r.get('race')} set down at x{r['spot']['x']} y{r['spot']['y']} z{r['spot']['z']}. "
          "Watching (Ctrl-C stops watching; the enemies stay)...")
    log = {"made": r, "start": start, "timeline": []}
    t0, last, quiet_since = time.monotonic(), None, None
    saw = {"reach": False, "orders": False, "gate_moved": False, "cleared": False}
    try:
        while time.monotonic() - t0 < TIMEOUT_S:
            snap = snapshot(b)
            changed = {k: v for k, v in snap.items() if k != "date" and (last is None or last.get(k) != v)}
            if changed:
                secs = int(time.monotonic() - t0)
                log["timeline"].append({"s": secs, **snap})
                print(f"[{secs:>4}s] " + ", ".join(f"{k} {v}" for k, v in changed.items()))
            saw["reach"] |= bool(snap["reach"])
            saw["orders"] |= bool(snap["orders"])
            saw["gate_moved"] |= bool(start["gates"]) and snap["gates"] != start["gates"]
            if snap["threats"] == 0:
                quiet_since = quiet_since or time.monotonic()
                if time.monotonic() - quiet_since >= QUIET_S:
                    saw["cleared"] = True
                    break
            else:
                quiet_since = None
            last = snap
            time.sleep(WATCH_S)
    except KeyboardInterrupt:
        print("stopped watching")
    end = log["timeline"][-1] if log["timeline"] else start
    lost = (start.get("citizens") or 0) - (end.get("citizens") or 0)
    verdict = [
        "the threat was gone within the watch" if saw["cleared"] else "the threat was still there when watching stopped",
        "the AI sent a squad (kill orders)" if saw["orders"] else "no squad was sent",
        ("the AI gate lever moved" if saw["gate_moved"] else "the AI gate lever didn't move")
        if start["gates"] else "no 'AI gate' lever in this fort",
        f"{lost} citizen(s) lost" if lost > 0 else "no citizens lost",
        "they could reach the dwarves" if saw["reach"] else "the game never said they could reach the dwarves",
    ]
    log["verdict"] = verdict
    out = ROOT / "logs" / "defence-test.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\n".join("- " + v for v in verdict))
    print(f"(all of it in {out}; the keeper's log has what the AI decided)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

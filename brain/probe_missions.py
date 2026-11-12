"""World-map missions, by hand (phase 13b: so the AI can learn to send one).
Read only: nothing in the game is changed.

    python brain\\probe_missions.py            what the World screen holds now
    python brain\\probe_missions.py --watch    watch for 3 minutes (--watch 300 for 5)
    python brain\\probe_missions.py --here World      (0.105.24) the mouse is on DF's World
                                                  button: the AI remembers where
    python brain\\probe_missions.py --here Diplomacy  the same for Diplomacy on a site's New mission
    python brain\\probe_missions.py --here Rescue     (0.105.39) the same for each goal's button on
                                                  New mission: Rescue, Recover, Explore, Raid,
                                                  Pillage, Tribute, Conquer (the same button may
                                                  carry several: show it under each name)

While it watches, send one mission by hand in DF: open the World screen,
go to Missions, start a new mission, pick an abandoned site (a ruin) and
"Explore" if you can (it starts no war), choose one squad, and confirm.
Every second the probe records what the screen holds, where the mouse is
and the focus; each change is printed and everything goes to
logs/probe-missions.json for the next round of work.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

from bridge import Bridge  # noqa: E402

OUT = ROOT / "logs" / "probe-missions.json"


def save(r) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(r, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"(all of it in {OUT})")


def changes(old: dict, new: dict) -> dict:
    """What differs between two samples, field by field (the screen's fields
    flattened into one level), for the printout."""
    def flat(r: dict) -> dict:
        out = {k: v for k, v in r.items() if k != "fields"}
        for k, v in (r.get("fields") or {}).items():
            out["screen." + k] = v
        return out
    a, b = flat(old or {}), flat(new or {})
    return {k: b.get(k) for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)}


def main(argv: list[str]) -> int:
    b = Bridge()
    if "--here" in argv:
        # (0.105.24) show the AI a button of the World screen once (lua/ai-mission-send.lua);
        # (0.105.39) names: World, Diplomacy, Rescue, Recover, Explore, Raid, Pillage, Tribute, Conquer
        i = argv.index("--here")
        name = argv[i + 1] if i + 1 < len(argv) else "World"
        print(json.dumps(b._call("mission_here", name), indent=1, ensure_ascii=False))
        return 0
    if "--watch" not in argv:
        r = b._call("probe_missions")
        print(json.dumps({k: v for k, v in r.items() if k != "fields"}, indent=1, ensure_ascii=False))
        print(f"{len(r.get('fields') or {})} screen fields" if r.get("screen") else "the World screen isn't open")
        save(r)
        return 0
    i = argv.index("--watch")
    seconds = int(argv[i + 1]) if i + 1 < len(argv) and argv[i + 1].isdigit() else 180
    print(f"watching for {seconds} s: send one mission by hand in DF now (Ctrl-C stops early)", flush=True)
    samples, last, start = [], None, time.time()
    try:
        while time.time() - start < seconds:
            r = b._call("probe_missions")
            d = changes(last, r) if last is not None else {"first": True}
            if d:
                t = round(time.time() - start, 1)
                samples.append({"t": t, "sample": r, "changed": d})
                keys = [k for k in d if k not in ("first",)]
                print(f"{t:6.1f}s  focus {r.get('focus')}  mouse {r.get('mouse')}  "
                      f"changed: {', '.join(keys[:8])}{' ...' if len(keys) > 8 else ''}", flush=True)
            last = r
            time.sleep(1)
    except KeyboardInterrupt:
        print("stopped")
    save({"seconds": round(time.time() - start, 1), "samples": samples})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""The title screen, for the keeper's --revive. Start Dwarf Fortress and leave
it at the title screen (no world loaded), then:

    python brain\\probe_title.py            what the title screen holds (read only)
    python brain\\probe_title.py --load     load the fort's newest save from it, step by step

Writes what DF's title screen holds to logs/title-probe.json (and where the
fort's save is listed on it), so loading a save from there can be written
for this version of DF.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

from dfhack import DFHack  # noqa: E402
import revive  # noqa: E402


def _last_json(raw: str):
    try:
        return json.loads(raw.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return raw[-2000:]


def try_load(df) -> int:
    import time
    folder = revive.save_to_load()
    print("loading:", folder)
    r = _last_json(df.run("ai-title", "load", folder or ""))
    print(r)
    log = {"start": r, "status": []}
    seen = 0
    for _ in range(45):
        time.sleep(2)
        try:
            st = _last_json(df.run("ai-title", "status"))
        except Exception as e:  # noqa: BLE001  (busy loading: DFHack may not answer)
            print("  (no answer:", str(e)[:80], ")")
            continue
        log["status"].append(st)
        if isinstance(st, dict):
            for step in (st.get("steps") or [])[seen:]:
                print("  step:", step)
            seen = len(st.get("steps") or [])
            if st.get("world_loaded"):
                print("WORLD LOADED")
                break
    path = ROOT / "logs" / "title-load.json"
    path.write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"(all of it in {path})")
    return 0


def main() -> int:
    df = DFHack.from_config()
    if "--load" in sys.argv[1:]:
        return try_load(df)
    out = {"probe": None, "load_dry": None}
    raw = df.run("ai-title", "probe")
    try:
        out["probe"] = json.loads(raw.strip().splitlines()[-1])
    except (ValueError, IndexError):
        out["probe"] = raw[-4000:]
    out["folder"] = revive.save_to_load()
    path = ROOT / "logs" / "title-probe.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    p = out["probe"] if isinstance(out["probe"], dict) else {}
    print("screens:", p.get("screens"), "| world loaded:", p.get("world_loaded"))
    print("the fort's save folder:", out["folder"])
    print(f"(all of it in {path})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

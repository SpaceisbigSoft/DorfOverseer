"""(0.105.0, 12b) DF's meeting screen (a diplomat or the outpost liaison), so
the AI can answer it. Read only, except --here, which only remembers where a
button is.

    python brain\\probe_meeting.py               what the meeting screen holds now
    python brain\\probe_meeting.py --watch       watch for 3 minutes (--watch 300 for 5)
    python brain\\probe_meeting.py --here Yes    the mouse is on the meeting's Yes button: remember it
                                                (likewise No, and Done on the requests screen)

The AI answers a meeting (agree to trade, peace and the elves' tree quota;
tribute by the Rules tab; the requests' wishes ticked) only through buttons
shown to it this way, once each. Every sample also goes to
logs/probe-meeting.json; the bridge keeps its own last samples in
dfhack-config/ai-overseer/meeting-probe.json.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

from bridge import Bridge  # noqa: E402

OUT = ROOT / "logs" / "probe-meeting.json"
BUTTONS = ("Yes", "No", "Done")


def save(r) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(r, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"(all of it in {OUT})")


def main(argv: list[str]) -> int:
    b = Bridge()
    if "--here" in argv:
        i = argv.index("--here")
        name = argv[i + 1] if i + 1 < len(argv) else "Yes"
        if name not in BUTTONS:
            print("buttons: " + ", ".join(BUTTONS))
            return 1
        r = b._call("meeting_here", name)
        print(f"{name} button remembered at {r.get('x')}, {r.get('y')}" if r.get("ok") else f"not done: {r.get('error')}")
        return 0 if r.get("ok") else 1
    if "--watch" not in argv:
        r = b._call("probe_meeting")
        print(json.dumps(r.get("state") or {"open": False}, indent=1, ensure_ascii=False))
        save(r)
        return 0
    i = argv.index("--watch")
    seconds = int(argv[i + 1]) if i + 1 < len(argv) and argv[i + 1].isdigit() else 180
    print(f"watching for {seconds} s: answer a meeting by hand in DF now (Ctrl-C stops early)", flush=True)
    samples, last, start = [], None, time.time()
    try:
        while time.time() - start < seconds:
            r = b._call("probe_meeting")
            key = json.dumps({k: r.get(k) for k in ("focus", "state", "ui")}, sort_keys=True, default=str)
            if key != last:
                t = round(time.time() - start, 1)
                samples.append({"t": t, "sample": r})
                st = r.get("state") or {}
                print(f"{t:6.1f}s  focus {r.get('focus')}  topic {st.get('topic')}  mouse {r.get('mouse')}", flush=True)
            last = key
            time.sleep(1)
    except KeyboardInterrupt:
        print("stopped")
    save({"seconds": round(time.time() - start, 1), "samples": samples})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

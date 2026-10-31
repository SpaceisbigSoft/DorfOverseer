"""DF's Justice screen, by hand (phase 12i: so the AI can learn to convict).
Read only: nothing in the game is changed.

    python brain\\probe_justice.py            what the Justice screen and the crimes hold now
    python brain\\probe_justice.py --watch    watch for 3 minutes (--watch 300 for 5)

While it watches, convict one case by hand in DF: open the Justice screen
(the info screen's Justice tab), pick an open case (a tantrum's "disorderly
behavior" is a good first one), and convict the dwarf it names. Every
second the probe records what the screen holds, where the mouse is and the
focus, and how many crimes are sentenced; each change is printed and
everything goes to logs/probe-justice.json for the next round of work.
(0.104.129; Teacheroar: 1,571 crimes, 399 waiting for a trial, 1 sentenced.)
The crimes whose record changes while it watches are printed one by one (0.104.130).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

from bridge import Bridge  # noqa: E402
from dfhack import DFHackError  # noqa: E402

OUT = ROOT / "logs" / "probe-justice.json"


def save(r, quiet: bool = False) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(r, indent=1, ensure_ascii=False), encoding="utf-8")
    if not quiet:
        print(f"(all of it in {OUT})")


def flat(r: dict) -> dict:
    """A sample's fields in one level ("justice.cases", "info.open", ...)."""
    out = {}
    for k, v in (r or {}).items():
        if k == "crimes_changed":
            continue                    # (printed on its own)
        if isinstance(v, dict) and k in ("info", "justice", "newest_sentenced"):
            for k2, v2 in v.items():
                out[f"{k}.{k2}"] = v2
        else:
            out[k] = v
    return out


def changes(old: dict, new: dict) -> dict:
    """What differs between two samples, field by field, for the printout."""
    a, b = flat(old), flat(new)
    return {k: b.get(k) for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)}


def main(argv: list[str]) -> int:
    b = Bridge()
    if "--watch" not in argv:
        r = b._call("probe_justice")
        print(json.dumps({k: v for k, v in r.items() if k not in ("info", "justice", "newest_sentenced")},
                         indent=1, ensure_ascii=False))
        print(f"{len(r.get('justice') or {})} justice fields, {len(r.get('info') or {})} info fields")
        save(r)
        return 0
    i = argv.index("--watch")
    seconds = int(argv[i + 1]) if i + 1 < len(argv) and argv[i + 1].isdigit() else 180
    print(f"watching for {seconds} s: convict one case by hand in DF's Justice screen now (Ctrl-C stops early)",
          flush=True)
    samples, last, start = [], None, time.time()
    # (0.104.130) a slow game, or the keeper talking to DFHack too, leaves a
    # call unanswered now and then: the watch waits and goes on, and saves
    # after every change (the first watch died on one timeout and kept nothing)
    try:
        while time.time() - start < seconds:
            try:
                r = b._call("probe_justice")
            except DFHackError as e:
                print(f"{round(time.time() - start, 1):6.1f}s  (no answer from the game: {e}; trying again)", flush=True)
                time.sleep(2)
                continue
            d = changes(last, r) if last is not None else {"first": True}
            if d or r.get("crimes_changed"):
                t = round(time.time() - start, 1)
                samples.append({"t": t, "sample": r, "changed": d})
                keys = [k for k in d if k != "first"]
                print(f"{t:6.1f}s  focus {r.get('focus')}  sentenced {r.get('sentenced')}  "
                      f"changed: {', '.join(keys[:8])}{' ...' if len(keys) > 8 else ''}", flush=True)
                for c in r.get("crimes_changed") or []:
                    print(f"         crime {c.get('id')} changed: {c.get('was')} -> {c.get('flags_now')}", flush=True)
                save({"seconds": round(time.time() - start, 1), "samples": samples}, quiet=True)
            last = r
            time.sleep(1)
    except KeyboardInterrupt:
        print("stopped")
    save({"seconds": round(time.time() - start, 1), "samples": samples})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

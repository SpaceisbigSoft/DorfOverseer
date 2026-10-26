"""The trade screen, by hand (for automatic trading). Open the trade screen at
the depot first (a caravan there, the broker present), then:

    python brain\\probe_trade.py              what the screen holds (read only)
    python brain\\probe_trade.py --here       show the AI the Trade button: you get
                                              8 seconds to click into DF and rest the
                                              mouse on the Trade button (don't click)
    python brain\\probe_trade.py --deal       the deal the AI would make (ticks nothing)
    python brain\\probe_trade.py --deal --tick   tick that deal on the screen
    python brain\\probe_trade.py --press      press Trade (what's ticked is traded)
    python brain\\probe_trade.py --call       send someone to the depot (anyone after a day)
    python brain\\probe_trade.py --here-depot show the AI the depot's Trade button: click the
                                              depot, then rest the mouse on its Trade button
    python brain\\probe_trade.py --open       open the trade screen (the trader must be there)

Each run writes logs/probe-trade.json.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

from bridge import Bridge  # noqa: E402
import planner  # noqa: E402


def save(r: dict) -> None:
    out = ROOT / "logs" / "probe-trade.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(r, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"(all of it in {out})")


def main(argv: list[str]) -> int:
    # "-tick" and "tick" work as well as "--tick"
    argv = ["--" + a.lstrip("-") for a in argv]
    unknown = [a for a in argv if a not in ("--here", "--here-depot", "--press", "--deal", "--tick", "--call", "--open")]
    if unknown:
        print("unknown option(s):", " ".join(unknown), "(use --here, --deal, --deal --tick, --press)")
        return 2
    b = Bridge()
    if "--here-depot" in argv:
        for n in range(8, 0, -1):
            print(f"click the trade depot in DF, then put the mouse on its Trade button (don't click)... {n}", flush=True)
            time.sleep(1)
        r = b._call("trade_here", "Depot")
        if r.get("x") is None:
            print("not remembered:", r.get("error"))
        else:
            print(f"the depot's Trade button remembered at x{r.get('x')} y{r.get('y')} (screen {r.get('screen')})")
        save(r)
        return 0
    if "--open" in argv:
        r = b.act({"type": "open_trade"})
        print(r)
        if r.get("clicking"):
            time.sleep(1)
            p = b._call("probe_trade")
            print("trade screen open now:", p.get("open"), "| the click:", p.get("last_open"))
        save(r)
        return 0
    if "--here" in argv:
        for n in range(8, 0, -1):
            print(f"put the mouse on DF's Trade button... {n}", flush=True)
            time.sleep(1)
        r = b._call("trade_here", "Trade")
        print(f"Trade button remembered at x{r.get('x')} y{r.get('y')} (screen {r.get('screen')})")
        save(r)
        return 0
    if "--call" in argv:
        r = b.act({"type": "call_trader", "wait_ticks": int(planner.PLANNER_CONFIG["trade_anyone_after_ticks"])})
        print(r)
        save(r)
        return 0
    if "--press" in argv:
        r = b._call("trade_press")
        if r.get("refused"):
            print("not pressed:", r["refused"])
        else:
            print(f"pressed Trade at {r.get('at')}: the merchants said {r.get('answer')}; "
                  f"{'TRADED' if r.get('traded') else 'nothing traded'} "
                  f"(ticked/goods before {r.get('before')}, after {r.get('after')}); screen now: {r.get('screen_now')}")
            if r.get("counter"):
                print("counter-offer:", r["counter"])
            if r.get("traded"):
                print("trade screen closed:", r.get("closed"))
        save(r)
        return 0
    if "--deal" in argv:
        state = b.state()
        citizens = int((state.get("dwarves") or {}).get("total") or 0)
        cfg = dict(planner.PLANNER_CONFIG)
        wants = planner.trade_wants(state, cfg, citizens)
        print("the fort wants:", ", ".join(f"{w['count']} {w['key']}" for w in wants) or "nothing")
        r = b.act({"type": "trade_deal", "wants": wants, "margin": cfg["trade_margin"],
                   "dry_run": "--tick" not in argv})
        if r.get("waiting") or not r.get("ok"):
            print("no deal:", r.get("error"))
        else:
            print(f"{'ticked' if not r.get('dry_run') else 'would tick'}: their goods worth {r.get('buy_value')} "
                  f"for {r.get('given')} of ours worth {r.get('give_value')}")
            for line in r.get("bought") or []:
                print("  buy", line)
            print("  give e.g.", "; ".join(r.get("given_sample") or []))
            print("Trade button known:", "yes" if r.get("calibrated") else "no (run with --here)")
        save(r)
        return 0
    r = b._call("probe_trade")
    print(f"trade screen open: {r.get('open')}, merchants ready: talker={r.get('havetalker')} "
          f"unloading={r.get('stillunloading')}, last answer {r.get('talkline')}")
    for side in r.get("sides") or []:
        print(f"{side.get('who')}: {side.get('count')} goods, {side.get('selected')} ticked "
              f"(worth {side.get('value_selected')}); e.g. {'; '.join(side.get('sample') or [])}")
    print("merchants have (useful to the fort):", r.get("merchants_have"))
    print("the fort can give:", r.get("fort_can_give"))
    print(f"mouse {r.get('mouse')}, screen {r.get('screen')}, 'Trade' read on screen at {r.get('trade_label')} "
          f"({r.get('truetype_tiles')} unreadable tiles); buttons known: {list((r.get('buttons') or {}).keys())}")
    if r.get("error") or r.get("deal_error"):
        print("error:", r.get("error") or r.get("deal_error"))
    save(r)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

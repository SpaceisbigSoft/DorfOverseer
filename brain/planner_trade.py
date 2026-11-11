"""planner_trade: caravans (split out of planner_industry in 0.105.25, 13c):
goods to the depot, what the fort buys and keeps, the margin, precious
metals kept from crafts. planner_industry re-exports every name here."""

from __future__ import annotations

from quirks import has_rule
from digest import _d, _l
from planner_core import *  # noqa: F401,F403

__all__ = ["_trade_rules", "PRECIOUS_METALS", "precious_metal", "trade_wants", "trade_margin_for", "keeps_treasures", "KEEP_TREASURES_GREED"]


def _trade_rules(s: dict, cfg: dict, citizens: int, proposals: list, notes: list,
                 traits: dict | None = None, memory=None) -> None:
    """Caravans: the fort's crafts taken to the depot while one is coming or
    there, the broker called, the trade screen opened and the deal made by
    the AI (0.105.35: a Needs you only when it can't open the screen);
    crafts made in quiet times so there is something to sell."""
    tr = _d(s.get("trade"))
    if not tr.get("depot"):
        return
    cs = [c for c in _l(tr.get("caravans")) if isinstance(c, dict)]
    # (0.103.18) Hermit Kingdom: no goods to the depot, no broker called, no
    # deal; the caravans come and go (the depot is still emptied after them)
    hermit = memory is not None and has_rule(getattr(memory, "culture", None), "no_trade")
    tv = ((traits or _traits(s)).get("trade", 0) or 0)
    # (0.105.13, 14.1 step 4b) Trade -50 or lower: the fort doesn't trade (the
    # Hermit hold at Trade -100 took goods to a caravan as the others did)
    no_trade = tv <= -50
    if hermit or no_trade:
        if cs:
            notes.append("a hermit kingdom: the caravan is left alone, nothing is traded" if hermit else
                         f"this fort doesn't trade (Trade {tv}): the caravan is left alone")
        cs = []
        hermit = True
    nd = _d(s.get("needs"))
    acq = unmet(s, "AcquireObject")
    # (0.103.9) rings, figurines and the like stay home while dwarves want
    # something to own and there aren't free ones for each (Enxah: 16 wanted,
    # every craft went to the depot, 163 there after the caravan left)
    keep_trinkets = acq >= cfg["needs_note_at"] and isinstance(nd.get("trinkets"), int) and nd["trinkets"] < acq
    if cs and (tr.get("goods") or 0) > 0:
        # (0.105.33) a grasping fort keeps its treasures home whatever its
        # Trade: the 0.105.13 "Trade 50+ sells them" turned Greed off in the one
        # fort that reached it (the Merchant city, Greed 80, Trade 120), so only
        # Gem-mad forts ever kept a gem back (8 Nov run)
        keep = keeps_treasures(traits or _traits(s), memory)
        # (0.104.78) the finished-goods piles full of crafts: more to the depot
        # at a time (40 a call while 1520 of 1522 tiles were used)
        fg = _d(_d(_d(s.get("logistics")).get("storage")).get("finished_goods"))
        full = int(fg.get("tiles") or 0) and int(fg.get("used") or 0) >= int(fg.get("tiles") or 0) * 0.95
        # (0.105.13) as many as Trade says: 40 at 0, 10 at -100, 120 at most
        per = cfg["bring_goods_full"] if full else max(10, min(120, round(40 * factor(traits or _traits(s), "trade"))))
        proposals.append(Proposal("trade", {"type": "bring_goods", "count": min(per, tr["goods"])}
                                  | ({"keep_treasures": True} if keep else {})
                                  | ({"keep_trinkets": True} if keep_trinkets else {}),
                                  f"a caravan from {cs[0].get('civ')} is "
                                  f"{ {'AtDepot': 'at the depot', 'Approaching': 'coming'}.get(str(cs[0].get('state')), 'coming') }: "
                                  f"take up to {min(per, tr['goods'])} crafts to the depot"
                                  + (" (the goods piles are full)" if full else ""), 3))
    trader = _d(tr.get("trader"))
    if cs and not trader.get("at_depot") and not _d(tr.get("screen")).get("open"):
        here = any(str(c.get("state")) == "AtDepot" for c in cs)
        proposals.append(Proposal("call_trader", {"type": "call_trader",
                                                  "wait_ticks": cfg["trade_anyone_after_ticks"]},
                                  f"a caravan from {cs[0].get('civ')} is {'at the depot' if here else 'coming'}: "
                                  + ("ask for the broker at the depot" if not trader.get("requested") else
                                     "the broker is asked for; if nobody comes within a day, anyone may trade"), 3))
    if not cs and (tr.get("at_depot") or 0) > 0 and not _d(tr.get("screen")).get("open"):
        # (0.103.9) the caravans have gone and the fort's goods sit in the
        # depot, where nobody can own or use them, until the next one
        proposals.append(Proposal("unload_depot", {"type": "unload_depot", "max": cfg["unload_depot_max"]},
                                  f"the caravans have gone and {tr['at_depot']} of the fort's goods sit in the "
                                  "depot: take them back out (stored again, there to own)", 4))
    if not cs and trader.get("anyone") and trader.get("anyone_by_ai", True):
        proposals.append(Proposal("call_trader", {"type": "call_trader",
                                                  "wait_ticks": cfg["trade_anyone_after_ticks"]},
                                  "the caravans have gone: the depot back to the broker only (if the AI opened it "
                                  "to anyone)", 8))
    screen = _d(tr.get("screen"))
    here = any(str(c.get("state")) == "AtDepot" for c in cs)
    if (here and trader.get("at_depot") and not screen.get("open") and trader.get("can_open")
            and trader.get("fresh", True)):
        proposals.append(Proposal("open_trade", {"type": "open_trade"},
                                  f"{'the broker' if not trader.get('anyone') else 'a trader'} is at the depot with "
                                  f"the caravan from {cs[0].get('civ')}: open the trade screen", 2))
    if screen.get("ready") and not hermit:
        wants = trade_wants(s, cfg, citizens)
        if not wants and screen.get("by_ai"):
            proposals.append(Proposal("close_trade", {"type": "close_trade"},
                                      "the fort needs nothing the caravan might sell: close the trade screen", 2))
        if wants and not screen.get("by_ai"):
            notes.append("the trade screen you opened is yours: the AI leaves the deal to you")
        elif wants:
            proposals.append(Proposal("trade_deal", {"type": "trade_deal", "wants": wants,
                                                     "margin": trade_margin_for(traits or _traits(s), cfg),
                                                     "press": True, "close": True},
                                      "the trade screen is open and the merchants are ready: buy "
                                      + ", ".join(f"{w['count']} {w['key'].lower()}" for w in wants[:4])
                                      + " with the fort's crafts", 2))
    elif screen.get("open") and screen.get("by_ai") and screen.get("unloading"):
        # opened before the merchants had unloaded: the screen holds time still,
        # so they never would. Closed; opened again once they're done.
        proposals.append(Proposal("close_trade", {"type": "close_trade", "unloading": True},
                                  "the trade screen opened while the merchants were still unloading (time stands "
                                  "still while it's open): close it and open it again once they're done", 2))
    elif here and trader.get("at_depot") and not trader.get("can_open"):
        # (0.105.35) kept a Needs you: DFHack can't open the trade screen, the
        # AI clicks the depot's Trade button, and only the player can show it
        # where that button is (once). What the AI does meanwhile is said.
        ask_player(notes, f"a caravan from {cs[0].get('civ')} is at the trade depot "
                          f"and {'the broker' if not trader.get('anyone') else 'a trader'} is there "
                          f"({tr.get('at_depot') or 0} of the fort's goods there), but the AI can't open the "
                          "trade screen: DFHack has no way to, and it hasn't been shown where the depot's Trade "
                          "button is. Meanwhile the AI keeps the goods at the depot and takes them back out when "
                          "the caravan leaves. Once the screen is open (by you), the AI ticks a deal and presses "
                          "Trade; to let it open the screen itself, show it the button once: "
                          "python brain\\probe_trade.py --here-depot")
    dw = _d(s.get("dwarves"))
    idle = (dw.get("idle_adults") or 0) / max(1, dw.get("adults") or 1)
    # (0.105.13) a trading fort (Trade 50+) makes goods to sell as its trade,
    # not only with idle hands
    merchant = tv >= 50
    if (_has_shop(s["buildings"], "Craftsdwarfs") and not young_fort(s, cfg) and (idle >= cfg["idle_share"] or merchant)
            and not stone_short(s, 10) and not hermit
            and not (memory is not None and has_rule(getattr(memory, "culture", None), "small_storage"))   # (0.103.19) Waste Not
            and (tr.get("goods") or 0) < citizens * 2 * factor(traits or {}, "trade")
            * (2 if memory is not None and has_rule(getattr(memory, "culture", None), "merchant_princes") else 1)
            and not queued(s, {"stone_crafts", "metal_crafts"})):
        # (0.104.95) a precious metal the fort has to spare first: its crafts sell
        # for 10-40 times rock's
        metal = precious_metal(s, cfg)
        if metal:
            proposals.append(Proposal("crafts", {"type": "work_order", "recipe": "metal_crafts", "amount": 3,
                                                 "material": f"INORGANIC:{metal}"},
                                      f"{round(100 * idle)}% of the dwarves are idle and there are only "
                                      f"{tr.get('goods') or 0} crafts to sell: make 3 of {metal.lower()} (worth far "
                                      "more than rock)", 6, True))
            return
        why = (f"a trading fort (Trade {tv})" if merchant and idle < cfg["idle_share"]
               else f"{round(100 * idle)}% of the dwarves are idle")
        proposals.append(Proposal("crafts", {"type": "work_order", "recipe": "stone_crafts", "amount": 10},
                                  f"{why} and there are only {tr.get('goods') or 0} "
                                  "crafts to sell: make some from rock", 6, True))


# (0.104.95) Metals worth far more as crafts than as anything the fort needs:
# a craft's value is its material's (DF: silver 10, gold 30, platinum 40, rock 1-3)
PRECIOUS_METALS = ("PLATINUM", "GOLD", "ROSE_GOLD", "ELECTRUM", "SILVER", "STERLING_SILVER", "BILLON")


def precious_metal(s: dict, cfg: dict) -> str | None:
    """The precious metal with the most bars over `precious_crafts_bars`, when
    the fort has a forge and fuel for it; None otherwise."""
    gear = _d(_d(s.get("military")).get("gear"))
    if not gear.get("forges") or int(_d(s.get("supplies")).get("fuel") or 0) < 3:
        return None
    bars = _d(gear.get("all_bars"))
    best = None
    for m in PRECIOUS_METALS:
        n = bars.get(m)
        if isinstance(n, (int, float)) and n - cfg["precious_crafts_bars"] >= 3 and (best is None or n > best[0]):
            best = (int(n), m)
    return best[1] if best else None


def trade_wants(s: dict, cfg: dict, citizens: int) -> list[dict]:
    """What the fort would buy from a caravan, most needed first: food and
    drink when short, then metal for gear, cloth, leather, thread, fuel, wood."""
    st, su = _d(s.get("stocks")), _d(s.get("supplies"))
    bars = _d(_d(_d(s.get("military")).get("gear")).get("bars"))
    citizens = max(1, citizens)
    wants: list[dict] = []
    # (0.105.24) what a strange mood waits for and the fort can't supply: first
    from planner_society import mood_trade_wants
    for w in mood_trade_wants(s):
        wants.append(w)

    # (0.105.31) a mood reserve the fort can't make (plant cloth: no fibre here)
    from planner_moods import reserve_trade_wants
    for w in reserve_trade_wants(s, cfg):
        if not any(x["key"] == w["key"] for x in wants):
            wants.append(w)

    def want(key: str, n: float) -> None:
        n = int(n)
        if n > 0 and not any(w["key"] == key for w in wants):
            wants.append({"key": key, "count": min(n, 500)})

    food = sum(int(st.get(k) or 0) for k in ("prepared_meals", "meat", "fish", "cheese", "eggs", "plants"))
    want("FOOD", citizens * cfg["established_food_per_dwarf"] - food)
    want("DRINK", citizens * cfg["trade_drink_per_dwarf"] - int(st.get("drink") or 0))
    if player_rules(s)["make_gear"]:
        want("BAR:STEEL", min(30, cfg["steel_want"] - int(bars.get("STEEL") or 0)))
        want("BAR:IRON", cfg["trade_bars_iron"] - int(bars.get("IRON") or 0))
    want("CLOTH", max(cfg["cloth_min"], citizens * cfg["cloth_per_dwarf"]) - int(st.get("cloth") or 0))
    want("SKIN_TANNED", cfg["trade_leather"] - int(st.get("leather") or 0))
    want("THREAD", cfg["trade_thread"] - int(st.get("thread") or 0))
    want("BAR:COAL", cfg["coke_when_fuel_below"] - int(su.get("fuel") or 0))
    want("WOOD", cfg["trade_wood"] - int(st.get("wood") or 0))
    if _d(_d(s.get("locations")).get("count")).get("HOSPITAL"):
        soap = int(su.get("soap") or 0)
        want("SOAP", cfg["soap_keep"] - soap)
        if soap < cfg["soap_keep"] and not su.get("tallow") and not su.get("fat"):
            want("TALLOW", cfg["soap_keep"] - soap)
    return wants


def trade_margin_for(traits: dict, cfg: dict) -> float:
    """Greed (generous - grasping): how much more the fort gives than it
    gets: 1.2 at 0, 1.35 at -100 (1.6 at most), 1.05 at +100 (never less;
    the merchants' own floor, learned in the game, still applies)."""
    g = traits.get("greed", 0) or 0
    return round(max(1.05, min(1.6, cfg["trade_margin"] - 0.15 * g / 100)), 2)


KEEP_TREASURES_GREED = 30      # (0.105.33) was 50: the Hermit hold (Greed 40) counts too


def keeps_treasures(traits: dict, memory=None) -> bool:
    """Greed +30 or more: gems and precious-metal goods stay home, never to
    the depot, and cut gems are hoarded, not set into crafts (_gems_rule).
    (0.103.15) Gem-mad too."""
    return ((_d(traits).get("greed", 0) or 0) >= KEEP_TREASURES_GREED
            or (memory is not None and has_rule(getattr(memory, "culture", None), "keep_gems")))

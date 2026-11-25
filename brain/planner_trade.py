"""planner_trade: caravans (split out of planner_industry in 0.105.25, 13c):
goods to the depot, what the fort buys and keeps, the margin, precious
metals kept from crafts. planner_industry re-exports every name here."""

from __future__ import annotations

from quirks import has_rule
from digest import _d, _l
from planner_core import *  # noqa: F401,F403

__all__ = ["_trade_rules", "PRECIOUS_METALS", "precious_metal", "trade_wants", "metal_trade_wants", "metal_buy_scale", "IRON_ORES", "trade_margin_for", "keeps_treasures", "KEEP_TREASURES_GREED"]


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
    # (r2 h5) the caravans really about, whatever the fort's way with them: the
    # depot is emptied only once they have gone (D, Trade -100, asked to
    # unload 50 times while one was there: "a caravan is coming or at the depot")
    real_cs = list(cs)
    _overstay_notes(tr, cfg, notes)
    _caravan_goods_rule(tr, cfg, proposals, notes)
    # (0.103.18) Hermit Kingdom: no goods to the depot, no broker called, no
    # deal; the caravans come and go (the depot is still emptied after them)
    hermit = memory is not None and has_rule(getattr(memory, "culture", None), "no_trade")
    tv = ((traits or _traits(s)).get("trade", 0) or 0)
    # (0.105.13, 14.1 step 4b) Trade -50 or lower: the fort doesn't trade (the
    # Hermit hold at Trade -100 took goods to a caravan as the others did)
    no_trade = tv <= -50
    mood_only = False
    if hermit or no_trade:
        # (R1 g6) a strange mood waiting on what the fort can't make (silk...):
        # a life at stake sets the no-trade way aside for those goods only, as
        # the no-slaughter ban is for a mood's bone (R-AD: D, the Hermit hold,
        # lost all 11 of its dead to failed moods, 3 of them for silk)
        from planner_moods import mood_trade_wants
        if cs and mood_trade_wants(s):
            mood_only = True
            notes.append(("a hermit kingdom" if hermit else f"this fort doesn't trade (Trade {tv})")
                         + ": the caravan is traded with only for what a strange mood waits for, a life at stake")
        elif cs:
            notes.append("a hermit kingdom: the caravan is left alone, nothing is traded" if hermit else
                         f"this fort doesn't trade (Trade {tv}): the caravan is left alone")
        if not mood_only:
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
        if mood_only:
            per = int(cfg.get("g6_mood_trade_goods", 10))      # (R1 g6) enough to pay for a mood's goods
        proposals.append(Proposal("trade", {"type": "bring_goods", "count": min(per, tr["goods"])}
                                  | ({"keep_treasures": True} if keep else {})
                                  | ({"keep_trinkets": True} if keep_trinkets else {}),
                                  f"a caravan from {cs[0].get('civ')} is "
                                  f"{ {'AtDepot': 'at the depot', 'Approaching': 'coming'}.get(str(cs[0].get('state')), 'coming') }: "
                                  f"take up to {min(per, tr['goods'])} crafts to the depot"
                                  + (" (the goods piles are full)" if full else ""), 3))
    trader = _d(tr.get("trader"))
    here = any(str(c.get("state")) == "AtDepot" for c in cs)
    # (r9, audit A8 #24) not once the AI has traded with (or been turned down
    # by) the caravan at the depot (fresh false): the call made a new
    # TradeAtDepot job all visit and kept the broker standing at the depot
    if (cs and not trader.get("at_depot") and not _d(tr.get("screen")).get("open")
            and not (here and trader.get("fresh") is False and len(cs) == 1)):
        proposals.append(Proposal("call_trader", {"type": "call_trader",
                                                  "wait_ticks": cfg["trade_anyone_after_ticks"]},
                                  f"a caravan from {cs[0].get('civ')} is {'at the depot' if here else 'coming'}: "
                                  + ("ask for the broker at the depot" if not trader.get("requested") else
                                     "the broker is asked for; if nobody comes within a day, anyone may trade"), 3))
    at_dep = int(tr.get("at_depot") or 0)
    busy = int(tr.get("at_depot_busy") or 0) if isinstance(tr.get("at_depot_busy"), int) else 0
    if not real_cs and at_dep > 0 and busy >= at_dep and not _d(tr.get("screen")).get("open"):
        # (item4) every one of the fort's goods left in the depot is on a job
        # (a hauler's): unload would leave them and only answer "being hauled
        # out" (B, 24 Nov: the same 4 on a job for hours, unload_depot refused
        # 107 times in 2 hours). Not asked; said, the stuck ones (on the job
        # 3+ days, lua/ai-trade.lua DEPOT_STUCK_TICKS) as a look in the game.
        stuck = int(tr.get("at_depot_stuck") or 0) if isinstance(tr.get("at_depot_stuck"), int) else 0
        if stuck > 0:
            notes.append(f"{stuck} of the fort's {at_dep} goods left in the trade depot have been on a hauling job "
                         "for 3+ days and never leave (a stuck job): look at the depot in the game (cancel the "
                         "job, or the item's way out may be blocked); the AI doesn't ask to unload them")
    elif not real_cs and at_dep > 0 and not _d(tr.get("screen")).get("open"):
        # (0.103.9) the caravans have gone and the fort's goods sit in the
        # depot, where nobody can own or use them, until the next one
        if busy > 0:
            at_dep -= busy        # (item4) the free ones only: a hauler is already carrying out the rest
        proposals.append(Proposal("unload_depot", {"type": "unload_depot", "max": cfg["unload_depot_max"]},
                                  f"the caravans have gone and {at_dep} of the fort's goods sit in the "
                                  "depot: take them back out (stored again, there to own)", 4))
    if not real_cs and ((trader.get("anyone") and trader.get("anyone_by_ai", True))
                        or trader.get("requested") or trader.get("job")):
        # (r2 h5) and the broker's call and its job ended (E: a dwarf stood at
        # the depot on the trade job with no caravan)
        proposals.append(Proposal("call_trader", {"type": "call_trader",
                                                  "wait_ticks": cfg["trade_anyone_after_ticks"]},
                                  "the caravans have gone: the broker's call ended (nobody kept waiting at the "
                                  "depot) and the depot back to the broker only (if the AI opened it to anyone)", 8))
    screen = _d(tr.get("screen"))
    here = any(str(c.get("state")) == "AtDepot" for c in cs)
    if (here and trader.get("at_depot") and not screen.get("open") and trader.get("can_open")
            and trader.get("fresh", True)):
        proposals.append(Proposal("open_trade", {"type": "open_trade"},
                                  f"{'the broker' if not trader.get('anyone') else 'a trader'} is at the depot with "
                                  f"the caravan from {cs[0].get('civ')}: open the trade screen", 2))
    if screen.get("ready") and (not hermit or mood_only):
        if mood_only:
            from planner_moods import mood_trade_wants
            wants = mood_trade_wants(s)                       # (R1 g6) the mood's goods, nothing else
        else:
            wants = trade_wants(s, cfg, citizens, traits or _traits(s))
        # (r2 h5) what any fort can use, bought when nothing the fort needs is
        # on sale (or it needs nothing): a fort with crafts at the depot sells
        # to every caravan (the screen was closed on "needs nothing", the deal
        # refused on "nothing the fort wants"), and the exports carry the
        # fort's name home. Never in a no-trade fort's mood-only deal.
        extra = [] if mood_only else [{"key": k, "count": int(n)}
                                      for k, n in (cfg.get("h5_trade_fallback_wants") or {}).items()
                                      if int(n) > 0 and not any(w["key"] == k for w in wants)]
        if not wants and extra:
            wants, extra = extra, []
        if not wants and screen.get("by_ai"):
            proposals.append(Proposal("close_trade", {"type": "close_trade"},
                                      "the fort needs nothing the caravan might sell: close the trade screen", 2))
        if wants and not screen.get("by_ai"):
            notes.append("the trade screen you opened is yours: the AI leaves the deal to you")
        elif wants:
            proposals.append(Proposal("trade_deal", {"type": "trade_deal", "wants": wants,
                                                     "margin": trade_margin_for(traits or _traits(s), cfg),
                                                     "press": True, "close": True}
                                      | ({"extra": extra} if extra else {}),
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
        last = _d(trader.get("last_open"))
        tried = (f" Its last try: {last.get('error') or ('clicked at ' + str(last.get('at')) + ' and no trade screen opened' if last.get('clicked') else 'nothing clicked')}."
                 if last else "")
        ask_player(notes, f"a caravan from {cs[0].get('civ')} is at the trade depot "
                          f"and {'the broker' if not trader.get('anyone') else 'a trader'} is there "
                          f"({tr.get('at_depot') or 0} of the fort's goods there), but the AI can't open the "
                          "trade screen: DFHack has no way to, it hasn't been shown where the depot's Trade "
                          "button is, its own guess of the place (0.105.47) missed, and it didn't find the button "
                          "by its word on the depot's sheet (r2)." + tried + " Meanwhile the AI keeps the goods at the depot and takes them back out when "
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
            and not queued(s, {"stone_crafts", "metal_crafts"})
            # (0.105.51) not beside the idle hands' own crafts this cycle
            and not any(_d(p.action).get("recipe") in ("stone_crafts", "metal_crafts") for p in proposals)):
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


def _overstay_notes(tr: dict, cfg: dict, notes: list) -> None:
    """(r2 h5) A caravan past its leaving whose merchants are still on the map
    after `h5_caravan_overstay_days` (B, y251: "will be leaving soon", never
    embarked, its merchants still there in y261 and no caravan for nine
    years): said, with what holds it (lua/ai-trade.lua overstays)."""
    for o in _l(tr.get("overstay")):
        if not isinstance(o, dict) or int(o.get("days") or 0) < int(cfg.get("h5_caravan_overstay_days", 7)):
            continue
        holds = "; ".join(str(h) for h in _l(o.get("holds"))) or "nothing seen holding it"
        notes.append(f"a caravan from {o.get('civ') or '?'} has stayed {o.get('days')} days past its leaving "
                     f"({o.get('merchants') or 0} merchant(s), {o.get('wagons') or 0} wagon(s) still on the map, "
                     f"state {o.get('state')}): held by {holds}. While it stays no other caravan comes "
                     "(and the fort's exports never reach home)")


def _caravan_goods_rule(tr: dict, cfg: dict, proposals: list, notes: list) -> None:
    """(item3) A caravan DF holds Leaving, its time run out, `caravan_goods_days`
    past its leaving with its goods still in the depot and none of its
    merchants at the depot packing them (B and C, 24 Nov: "The Moral Wire",
    2903 days, 115 goods, one merchant on the map who could walk to the depot
    and never did): its goods are taken out of the game as if packed
    (lua/ai-trade.lua clear_caravan_goods). Never given to the fort: that is
    theft, and DF holds it against the civilisation. Not while another caravan
    is coming or at the depot (its goods look the same). After it the stuck
    caravan's steps start again (planner_outside: its merchants have nothing
    left to wait for)."""
    if [c for c in _l(tr.get("caravans")) if isinstance(c, dict)]:
        return
    wait = int(cfg.get("caravan_goods_days", 30))
    for o in _l(tr.get("overstay")):
        if not isinstance(o, dict):
            continue
        ent = o.get("entity")
        goods = o.get("goods_in_depot")
        left = o.get("time_remaining")
        if (not isinstance(ent, int) or isinstance(ent, bool) or o.get("state") != "Leaving"
                or not isinstance(left, (int, float)) or left > 0 or int(o.get("days") or 0) < wait
                or not isinstance(goods, int) or goods <= 0):
            continue
        if int(o.get("in_depot") or 0) > 0:
            notes.append(f"a caravan from {o.get('civ') or '?'} has been leaving {o.get('days')} days with {goods} "
                         f"of its goods in the depot; {o.get('in_depot')} of its merchants are at the depot: "
                         "left to pack them")
            continue
        proposals.append(Proposal("caravan_goods",
                                  {"type": "clear_caravan_goods", "entity": ent,
                                   "max": int(cfg.get("caravan_goods_max", 200))},
                                  f"a caravan from {o.get('civ') or '?'} has been leaving {o.get('days')} days, its "
                                  f"time run out, with {goods} of its goods still in the depot and none of its "
                                  f"{o.get('merchants') or 0} merchant(s) coming for them: take its goods out of "
                                  "the game as if packed (never the fort's: that would be theft), so the depot is "
                                  "clear and its merchants have nothing left to wait for", 5))
        return


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


def trade_wants(s: dict, cfg: dict, citizens: int, traits: dict | None = None) -> list[dict]:
    """What the fort would buy from a caravan, most needed first: food and
    drink when short, then metal for gear (metal_trade_wants), cloth,
    leather, thread, fuel, wood."""
    st, su = _d(s.get("stocks")), _d(s.get("supplies"))
    if traits is None:
        traits = _traits(s) if isinstance(s.get("settings"), dict) else {}
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
    for key, n in metal_trade_wants(s, cfg, traits):
        want(key, n)
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


# (0.105.113 item10) the smelter's own wants from a caravan. All six forts
# asked for steel bars in 243 deals of 22-24 Nov and got 3: the caravans
# hardly carry them, while the forts sat on 41-64 iron bars and 2-7 flux
# stones (A 18) -- flux, not iron, holds their steel back.
IRON_ORES = ("HEMATITE", "MAGNETITE", "LIMONITE")
TRADE_FLUX_MIN = 10            # flux stones under this, steel short and iron at hand: bought
TRADE_FLUX_MAX = 20            # ... up to this many in all
TRADE_ORE_IRON = 15            # iron ore bought up to this, when the fort has none and few iron bars
TRADE_PIG_IRON = 10            # pig iron (half of steel's makings) bought while steel is short


def metal_buy_scale(traits: dict | None) -> float:
    """Greed (generous - grasping) on what the fort buys for its metal
    industry: 1.5 at -100 (a generous fort stocks up), 1 at 0, 0.5 at
    +100 (a grasping one buys only part of the shortfall), 0.25-2 at most."""
    g = _d(traits).get("greed", 0) or 0
    return max(0.25, min(2.0, 1 - 0.5 * g / 100))


def metal_trade_wants(s: dict, cfg: dict, traits: dict | None = None) -> list[tuple[str, int]]:
    """(0.105.113 item10) What the metal industry needs from a caravan, most
    needed first: steel and iron bars for gear (the Rules switch Make gear),
    pig iron, and for the smelter's own steel flux stone (steel short, iron
    at hand, flux under TRADE_FLUX_MIN) and iron ore (none in store or
    uncovered, few iron bars). Only with a forge or a smelter: a fort that
    can't work metal buys none. Each shortfall times metal_buy_scale (Greed);
    the deal's budget (what the fort's crafts at the depot pay for, at the
    Greed margin) is what it can afford."""
    if not player_rules(s)["make_gear"]:
        return []
    gear = _d(_d(s.get("military")).get("gear"))
    bars = _d(gear.get("bars"))
    furnaces = _d(_d(s.get("buildings")).get("furnaces"))
    smelter = bool(furnaces.get("Smelter") or furnaces.get("MagmaSmelter"))
    forge = bool(gear.get("forges")) or "forges" not in gear
    if not (forge or smelter):
        return []
    k = metal_buy_scale(traits)
    steel, iron = int(bars.get("STEEL") or 0), int(bars.get("IRON") or 0)
    pig = int(gear.get("pig_iron") or 0)
    ind = _d(s.get("industry"))
    flux = int(ind.get("flux_stock") or 0)
    by_ore = _d(ind.get("ore_stock_by"))
    iron_ore = sum(int(_d(by_ore.get(o)).get("n") or 0) for o in IRON_ORES)
    out: list[tuple[str, int]] = []

    def add(key: str, short: float, most: int | None = None) -> None:
        n = round(min(short, most) * k if most is not None else short * k)
        if n > 0:
            out.append((key, int(n)))

    steel_short = cfg["steel_want"] - steel
    add("BAR:STEEL", steel_short, 30)
    add("BAR:IRON", cfg["trade_bars_iron"] - iron)
    if smelter and steel_short > 0:
        add("BAR:PIG_IRON", TRADE_PIG_IRON - pig, TRADE_PIG_IRON)
        if flux < TRADE_FLUX_MIN and (iron > cfg["iron_keep"] or pig > 0 or iron_ore > 0):
            add("BOULDER:FLUX", TRADE_FLUX_MAX - flux)
    if (smelter and iron_ore == 0 and iron < cfg["trade_bars_iron"]
            and not _d(_d(ind.get("ores")).get("IRON")).get("tiles")):
        add("BOULDER:ORE_IRON", TRADE_ORE_IRON)
    return out


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

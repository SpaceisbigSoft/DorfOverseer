"""(0.105.0, phases 12b and 13b) The world outside the fort.

The `world` report (lua/ai-diplomacy.lua) says which civilisations the fort
knows, at war or peace, who has besieged it, the tribute asked or offered,
the caravans' trade agreements (what they'd pay more for), and the meeting
screen when it is open. From it:

  * a meeting with a diplomat or the liaison is answered with the AI's
    defaults (agree to trade, to the elves' tree quota, to peace; tribute by
    the Rules choice; the requests' wishes ticked), through buttons the
    player showed the AI once; until then it stays a Needs-you;
  * a caravan from a civilisation at war is not traded with (the goods stay
    home, the broker isn't called);
  * goods a caravan's agreement asks for at a good price are made for the
    next one (a work order while hands are idle);
  * the civilisations that besieged the fort are kept (a grudge list) and
    feed the Grudge-keepers quirk;
  * a messenger is appointed when the fort has the post, and a site not in
    contact is named for "Make contact" (13b) once one is free: the World
    screen's last steps (the messenger, the confirm) have never been seen, so
    the AI says what to send and watches the mission in the `missions` report.

Citizenship petitions are not answered: DFHack 53.16-r3 can't set the
standing orders, and agreeing to one in the save without DF's own steps is
not known to make the visitor a citizen.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (PLANNER_CONFIG, Proposal, TICKS_PER_DAY, TICKS_PER_YEAR, abs_tick, ask_player,
                          player_rules, queued, reachable_threats, young_fort, _traits)

__all__ = ["_meeting_answer_rule", "_world_notes", "_hostile_trade_filter", "_export_rule", "_messenger_rule",
           "_contact_rule", "grudge_facts", "note_grudges", "note_world", "export_wishes", "EXPORT_RECIPES",
           "TRIBUTE_POLICIES", "TRADE_ACTIONS", "meeting_wishes", "WISH_CATEGORIES"]

TRIBUTE_POLICIES = ("small", "pay", "refuse")
HOSTILE = ("TotalWar", "Skirmishing")
# the bridge's trade actions: none while only a hostile civ's caravan is here
TRADE_ACTIONS = ("bring_goods", "call_trader", "open_trade", "trade_deal")
# DF item types a trade agreement names -> the fort's recipe that makes one
EXPORT_RECIPES = {
    "CRAFTS": "stone_crafts", "FIGURINE": "stone_crafts", "TOTEM": "bone_crafts", "SCEPTER": "stone_crafts",
    "CROWN": "stone_crafts", "RING": "stone_ring", "EARRING": "stone_earring", "AMULET": "stone_amulet",
    "BRACELET": "stone_bracelet", "GOBLET": "stone_mugs", "BLOCKS": "stone_blocks", "TABLE": "stone_table",
    "CHAIR": "stone_chair", "DOOR": "stone_door", "CABINET": "stone_cabinet", "BOX": "stone_chest",
    "COFFIN": "stone_coffin", "STATUE": "stone_statue", "SLAB": "stone_slab", "BARREL": "wooden_barrel",
    "BIN": "wooden_bin", "BUCKET": "wooden_bucket", "CAGE": "wooden_cage", "SPLINT": "wooden_splint",
    "CRUTCH": "wooden_crutch", "CLOTH": "weave_plant_cloth",
}
# the fort's trade wants (planner_industry trade_wants keys) -> DF's request
# categories on the liaison's Requests screen (entity_sell_category)
WISH_CATEGORIES = {"FOOD": ("Meat", "Cheese"), "DRINK": ("Drinks",), "BAR:STEEL": ("MetalBars",),
                   "BAR:IRON": ("MetalBars",), "BAR:COAL": ("MetalBars",), "CLOTH": ("ClothPlant",),
                   "SKIN_TANNED": ("Leather",), "THREAD": ("ThreadPlant",), "WOOD": ("Wood",), "SOAP": ("Extracts",),
                   "TALLOW": ("Extracts",)}
EXPORT_MIN_PCT = 110            # a price this far over the usual (128 = 100%) is worth making for
EXPORT_AMOUNT = 5
EXPORT_MEMORY_DAYS = 336        # a caravan's wish kept a year, for the next caravan


def _world(s: dict) -> dict:
    return _d(s.get("world"))


def _seen(memory) -> dict:
    """The world's memory (memory.world_seen): grudges, export wishes, the
    last contact named. Read only (note_world writes it, before planning)."""
    ws = getattr(memory, "world_seen", None) if memory is not None else None
    return ws if isinstance(ws, dict) else {}


def note_world(s: dict, memory) -> None:
    """Bookkeeping before planning (planner.note_cycle): the grudge list, the
    caravans' export wishes, and when a contact was last named."""
    if memory is None:
        return
    if not isinstance(getattr(memory, "world_seen", None), dict):
        memory.world_seen = {}
    note_grudges(s, memory)
    memory.world_seen["export"] = export_wishes(s, memory)
    if _contact_site(s, memory) is not None:
        memory.world_seen["contact_said"] = abs_tick(s)


# --- meetings ---------------------------------------------------------------------

def _meeting_answer_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """DF's meeting screen is open: answer it (lua/ai-diplomacy.lua
    answer_meeting) with the Rules' tribute choice. A barony's holder is the
    player's. When the button to press hasn't been shown to the AI, say how."""
    m = _d(_world(s).get("meeting"))
    if not m.get("open"):
        return
    if m.get("land_holder"):
        ask_player(notes, "a meeting asks who should hold a barony: that choice is yours (DF's meeting screen)")
        return
    rules = player_rules(s)
    known = set(str(b) for b in _l(m.get("buttons")))
    need = "Done" if m.get("requests") else None
    if need is None and not {"Yes", "No"} <= known:
        need = "Yes and No"
    if need and not set(need.split(" and ")) <= known:
        return                     # the meetings' Needs-you (planner_society _meeting_notes) says how
    topic = m.get("topic") or "the meeting"
    action = {"type": "answer_meeting", "tribute": rules["tribute"]}
    if m.get("requests"):
        wishes = meeting_wishes(s, cfg)
        if wishes:
            action["wishes"] = wishes
    proposals.append(Proposal("meeting", action,
                              f"DF's meeting screen is open ({m.get('civ') or 'a diplomat'}, {topic}): answer it "
                              f"(trade and peace agreed, the tree quota kept, tribute: {rules['tribute']})", 0))


def meeting_wishes(s: dict, cfg: dict) -> list[str]:
    """The fort's wants as DF's request categories, most needed first (at
    most 8); empty: the bridge's defaults."""
    from planner_industry import trade_wants
    out: list[str] = []
    for w in trade_wants(s, cfg, max(1, int(_d(s.get("dwarves")).get("total") or 1))):
        for c in WISH_CATEGORIES.get(str(w.get("key")), ()):
            if c not in out:
                out.append(c)
    return out[:8]


# --- war and peace, tribute, the grudge list --------------------------------------

def note_grudges(s: dict, memory) -> None:
    """Keep every civilisation that has besieged the fort (memory.world_seen
    grudges: civ id -> {name, race, sieges, last_year})."""
    if memory is None:
        return
    g = memory.world_seen.setdefault("grudges", {})
    for e in _l(_world(s).get("sieges")):
        if not isinstance(e, dict) or not isinstance(e.get("id"), int):
            continue
        old = _d(g.get(str(e["id"])))
        g[str(e["id"])] = {"name": e.get("name") or old.get("name"), "race": e.get("race") or old.get("race"),
                           "sieges": max(int(e.get("n") or 0), int(old.get("sieges") or 0)),
                           "last_year": max(int(e.get("last_year") or -1), int(old.get("last_year") or -1))}


def grudge_facts(state: dict, memory) -> dict:
    """Facts for the quirks (brain/overseer.py world_facts): the sieges on the
    game's own record and the year of the last, and how many civs that
    besieged the fort it is still at war with."""
    g = _d(_seen(memory).get("grudges"))
    w = _world(state)
    civs = {c.get("id"): c for c in _l(w.get("civs")) if isinstance(c, dict)}
    out = {}
    if g:
        out["sieges_on_record"] = sum(int(_d(v).get("sieges") or 0) for v in g.values())
        last = max(int(_d(v).get("last_year") or -1) for v in g.values())
        year = _d(state.get("date")).get("year")
        if last >= 0 and isinstance(year, int):
            out["years_since_siege_on_record"] = max(0, year - last)
        if civs:
            out["grudge_civs"] = sum(1 for k in g if str(_d(civs.get(int(k))).get("relation")) in HOSTILE)
    return out


def _world_notes(s: dict, notes: list, memory=None) -> None:
    """War and peace in a line; tribute paid or taken; visitors from a civ
    at war (left alone unless hostile on the map)."""
    w = _world(s)
    if not w:
        return
    civs = [c for c in _l(w.get("civs")) if isinstance(c, dict)]
    war = [c for c in civs if c.get("relation") in HOSTILE]
    if war:
        notes.append("at war with " + ", ".join(f"{c.get('name')} ({str(c.get('race') or '?').lower()})"
                                                 for c in war[:4])
                     + (f" and {len(war) - 4} more" if len(war) > 4 else ""))
    for c in civs:
        if c.get("tribute"):
            notes.append(f"tribute: {c.get('name')} {c['tribute']} tribute"
                         + (f" ({c['tribute_season']})" if c.get("tribute_season") else ""))
        if c.get("peace_offered"):
            notes.append(f"{c.get('name')} have offered peace: the AI agrees when their diplomat meets the fort")
    if int(w.get("visitors_from_hostile") or 0) > 0:
        notes.append(f"{w['visitors_from_hostile']} visitor(s) from a civilisation at war are on the map: left "
                     "alone unless they turn hostile (only a threat gets a kill order)")


def _hostile_trade_filter(s: dict, proposals: list, notes: list) -> list:
    """No trade with a civilisation at war: while every caravan here is a
    hostile civ's (or a tribute caravan), the trade actions are dropped."""
    cars = [c for c in _l(_world(s).get("caravans")) if isinstance(c, dict)]
    if not cars:
        return proposals
    friendly = [c for c in cars if not c.get("hostile") and not c.get("tribute")]
    if friendly:
        return proposals
    drop = [p for p in proposals if p.action.get("type") in TRADE_ACTIONS]
    if not drop:
        return proposals
    hostile = [c for c in cars if c.get("hostile")]
    if hostile:
        notes.append(f"the caravan from {hostile[0].get('civ')} is from a civilisation at war with the fort: "
                     "not traded with")
    return [p for p in proposals if p not in drop]


# --- goods for export ---------------------------------------------------------------

def export_wishes(s: dict, memory) -> dict:
    """The caravans' wishes (item -> {pct, civ, tick}): what the report's
    agreements ask now, over what was kept (a year)."""
    now = abs_tick(s)
    wishes = dict(_d(_seen(memory).get("export")))
    for w in _l(_world(s).get("wanted")):
        if isinstance(w, dict) and isinstance(w.get("pct"), int) and w.get("item"):
            old = _d(wishes.get(w["item"]))
            if w["pct"] >= int(old.get("pct") or 0) or now - int(old.get("tick") or 0) > TICKS_PER_DAY * 28:
                wishes[w["item"]] = {"pct": w["pct"], "civ": w.get("civ"), "tick": now}
    return {k: v for k, v in wishes.items()
            if 0 <= now - int(_d(v).get("tick") or 0) <= EXPORT_MEMORY_DAYS * TICKS_PER_DAY}


def _export_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """A caravan's trade agreement pays more for some goods (DF's buy_prices):
    the best-paid one the fort can make is ordered for the next caravan,
    while hands are idle and nothing of it is queued. Kept a year."""
    wishes = export_wishes(s, memory)
    best = sorted(((int(_d(v).get("pct") or 0), k) for k, v in wishes.items()
                   if k in EXPORT_RECIPES and int(_d(v).get("pct") or 0) >= EXPORT_MIN_PCT), reverse=True)
    if not best or young_fort(s, cfg):
        return
    dw = _d(s.get("dwarves"))
    idle = (dw.get("idle_adults") or 0) / max(1, dw.get("adults") or 1)
    if idle < cfg["idle_share"]:
        return
    for pct, item in best:
        recipe = EXPORT_RECIPES[item]
        if queued(s, {recipe}):
            continue
        civ = _d(wishes.get(item)).get("civ")
        proposals.append(Proposal("export", {"type": "work_order", "recipe": recipe, "amount": EXPORT_AMOUNT},
                                  f"{civ or 'a caravan'}'s trade agreement pays {pct}% for "
                                  f"{item.lower().replace('_', ' ')}: make {EXPORT_AMOUNT} for the next caravan", 6, True))
        return


# --- 13b: the messenger and Make contact ----------------------------------------------

def _messenger_rule(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """The fort has a messenger's post and nobody holds it: appoint a
    talker who isn't a soldier, staff, a patient or another office's holder
    (lua/ai-nobles.lua). Not in a young fort."""
    rules = player_rules(s)
    if not rules["make_contact"] or not rules["appoint_nobles"] or young_fort(s, cfg):
        return
    o = _d(_d(_d(s.get("offices")).get("offices")).get("MESSENGER"))
    if not o or _l(o.get("held")) or int(o.get("vacant") or 0) <= 0 or o.get("appointable") is False:
        return
    proposals.append(Proposal("messenger", {"type": "appoint", "office": "MESSENGER"},
                              "the fort has a messenger's post and nobody holds it: appoint a good talker who "
                              "isn't needed at home (Make contact needs one)", 5))


def _contact_site(s: dict, memory) -> dict | None:
    """The site to name for Make contact now, or None: the switch on, the
    messenger home (no Diplomacy mission out), a site not in contact, no
    threat or siege near, and not named in the last season."""
    if not player_rules(s)["make_contact"]:
        return None
    ms = _d(s.get("missions"))
    if any(isinstance(c, dict) and c.get("goal") == "DIPLOMACY" for c in _l(ms.get("controllers"))):
        return None
    o = _d(_d(_d(s.get("offices")).get("offices")).get("MESSENGER"))
    if not _l(o.get("held")):
        return None
    # not in contact: DF's NoContact, or no diplomacy state at all (never met)
    sites = [x for x in _l(_d(ms.get("sites")).get("nearest"))
             if isinstance(x, dict) and x.get("relation") in ("NoContact", "unknown")]
    if not sites:
        return None
    if reachable_threats(s, _traits(s), PLANNER_CONFIG) or any(_d(e).get("active") for e in _l(_world(s).get("sieges"))):
        return None
    now = abs_tick(s)
    said = _seen(memory).get("contact_said")
    if isinstance(said, int) and 0 < now - said < TICKS_PER_YEAR // 4:     # (named this cycle: said)
        return None
    return min(sites, key=lambda x: (int(x.get("dist") or 999), int(x.get("id") or 0)))


def _contact_rule(s: dict, cfg: dict, notes: list, memory=None) -> None:
    """(13b) A site not in contact, nearest first, named for "Make contact"
    once the messenger is home, no Diplomacy mission is out and no threat or
    siege is near; the mission's way out and back watched in `missions`."""
    rules = player_rules(s)
    if not rules["make_contact"]:
        return
    ms = _d(s.get("missions"))
    out = [c for c in _l(ms.get("controllers")) if isinstance(c, dict) and c.get("goal") == "DIPLOMACY"]
    if out:
        c = out[0]
        notes.append(f"the messenger is {'on the way home from' if c.get('returning') else 'away to'} "
                     f"{c.get('site') or 'a site'} (Make contact): one mission at a time")
        return
    o = _d(_d(_d(s.get("offices")).get("offices")).get("MESSENGER"))
    if not _l(o.get("held")):
        return
    if reachable_threats(s, _traits(s), cfg) or any(_d(e).get("active") for e in _l(_world(s).get("sieges"))):
        if any(isinstance(x, dict) and x.get("relation") in ("NoContact", "unknown")
               for x in _l(_d(ms.get("sites")).get("nearest"))):
            notes.append("a site waits for Make contact, but not while a threat is near")
        return
    site = _contact_site(s, memory)
    if site is None:
        return
    ask_player(notes, f"Make contact (13b): the messenger ({_l(o.get('held'))[0]}) can go to "
                      f"{site.get('name') or 'site ' + str(site.get('id'))} ({site.get('dist')} tiles away), a site "
                      "not in contact: World screen, the site, Diplomacy, Make contact. The AI can't press those "
                      "buttons yet; send it by hand while python brain\\probe_missions.py --watch records the steps")

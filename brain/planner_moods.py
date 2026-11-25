"""planner_moods: strange moods (split out of planner_society in 0.105.25,
13c): the workshop a mood needs, then its materials: what lies free is left
to the dwarf, forbidden items freed, the AI's own orders that would use the
last of it cancelled, the rest made (or an animal butchered), what can't be
made named in Needs you and put on the caravans' list. planner_society
re-exports every name here."""

from __future__ import annotations

import math
import quirks
from quirks import has_rule
from digest import _d, _l
from planner_core import *  # noqa: F401,F403
import planner_farms
from planner_insane import INSANE_MOODS, insane_ids, insane_present  # (0.105.40b)
from planner_mood_help import (mood_want, dead_order, usable_thread, silk_route, webs_reach, free_items_skip,  # (0.105.47, J1)
                               TRADE_IF, request_detail)

__all__ = ["MOOD_WORKSHOPS", "_mood_rules", "mood_item_text", "MOOD_CONSUMERS", "MOOD_TRADE_KEYS", "_mood_make", "_mood_slaughter", "_mood_materials", "mood_counts_text", "mood_journal", "mood_trade_wants", "MOOD_BLOCKS", "mood_blocked", "MOOD_RESERVES", "mood_reserve_counts", "reserve_room", "RESERVE_BATCH", "note_reserve_swap", "_mood_reserve_rule", "reserve_trade_wants", "reserve_words", "MOOD_SHOP_KINDS", "mood_shops_missing",
           "mood_hospital_rule", "stitch_waiting", "mood_urgency"]   # (item2)


# A crafting mood's skill -> the workshop (or furnace) the dwarf must claim
# (DF's table, wiki "Strange mood"). (0.105.51) a tanner's mood claims a
# Leather works and a weaver's a Clothier's shop, not a Tanner's or a Loom (R3:
# A's Ber, a tanner, claimed nothing for 41 days while the AI built four
# Tanner's and the fort had no Leather works); a miner's, stonecutter's and
# stone carver's a Mason's, an engraver's a Craftsdwarf's (DF's skill names).
MOOD_WORKSHOPS = {
    "WOODCRAFT": "Craftsdwarfs", "STONECRAFT": "Craftsdwarfs", "BONECARVE": "Craftsdwarfs",
    "ENGRAVE_STONE": "Craftsdwarfs",
    "CARPENTRY": "Carpenters", "MASONRY": "Masons", "MINING": "Masons", "CUT_STONE": "Masons",
    "CARVE_STONE": "Masons", "CUTGEM": "Jewelers", "ENCRUSTGEM": "Jewelers",
    "FORGE_WEAPON": "MetalsmithsForge", "FORGE_ARMOR": "MetalsmithsForge",
    "FORGE_FURNITURE": "MetalsmithsForge", "METALCRAFT": "MetalsmithsForge",
    "CLOTHESMAKING": "Clothiers", "WEAVING": "Clothiers", "LEATHERWORK": "Leatherworks",
    "TANNER": "Leatherworks", "GLASSMAKER": "GlassFurnace", "BOWYER": "Bowyers", "MECHANICS": "Mechanics",
}


def _shop_coming(s: dict, need) -> bool:
    """(0.105.36, X1) A workshops level under way (not stuck furnishing,
    as _workshops_busy) that builds this kind of shop."""
    if not need:
        return False
    names = set(SHOP_ALIASES.get(need, (need,))) | {need}
    for p in _l(_d(s.get("projects")).get("open")):
        if not (isinstance(p, dict) and _workshops_busy([p])):
            continue
        sm = _d(p.get("summary"))
        shops = set(_l(sm.get("workshops"))) | set(_l(sm.get("shops"))) | set(_d(p.get("furniture")).keys())
        if shops & names:
            return True
    return False


def _mood_rules(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """A dwarf in a crafting mood needs the right workshop, then materials;
    without them the dwarf goes insane. Insanity itself is only reported:
    (0.105.24) a melancholy or stark raving dwarf stops drinking and DF lets
    nobody give them water (DF's doctors water only patients in bed, and the
    insane are no patients), a berserk one fights until killed; none of it
    can be undone. The only lever is the mood: get it its materials."""
    now = abs_tick(s)
    b = s["buildings"]
    for m in _l(s["moods"].get("list")):
        name, mood = m.get("name") or "a dwarf", m.get("mood")
        if mood == "Baby":
            continue                      # (older bridge) a baby being carried, not a mood
        if not m.get("craft"):
            # (0.105.40b) with the bridge's `insane` section the insane are said
            # there, with where they are and what the AI does (planner_insane)
            if mood in INSANE_MOODS and insane_present(s) and m.get("unit_id") in insane_ids(s):
                continue
            notes.append(f"{name} has gone {str(mood).lower()}: lost to the fort (this can't be undone)"
                         if mood in ("Melancholy", "Raving", "Berserk") else f"{name}: {mood}")
            continue
        days = (now - memory.moods_seen.get(str(m.get("unit_id")), now)) // TICKS_PER_DAY
        need = MOOD_WORKSHOPS.get(str(m.get("skill")))
        if m.get("workshop"):
            have, want = m.get("items_have"), m.get("items_needed")
            missing = [x for x in _l(m.get("missing")) if isinstance(x, dict)]
            # (0.105.24) a bridge that counts what the fort holds: act at once
            # (a mood fails in 30-40 days; 2-5 Nov a failed one was seen
            # waiting on its first request for most of them)
            counted = any(isinstance(x.get("avail"), dict) for x in missing)
            prog = _d(_d(getattr(memory, "mood_progress", None)).get(str(m.get("unit_id"))))
            stalled = ((now - prog["since"]) // TICKS_PER_DAY if isinstance(prog.get("since"), int)
                       else days)
            if missing and (counted or days >= cfg["mood_wait_days"]
                            or stalled >= cfg.get("mood_stall_days", 7)):
                _mood_materials(s, name, mood, missing, days, proposals, notes, cfg, memory=memory,
                                unit_id=m.get("unit_id"), stalled=stalled, thirst=m.get("thirst"))
            elif isinstance(have, int) and isinstance(want, int) and have < want and days >= 3:
                notes.append(f"{name}'s {mood.lower()} mood: gathering materials ({have}/{want}) for "
                             f"{days} days; if it stalls, DFHack's showmood says what's missing")
            continue
        # (0.105.36, X1) a mood's level waits only for a level that is
        # building its kind, not for any workshops level (a gems rule's
        # Jewelers held a mood's Carpenters up to 28 days): urgent levels
        # have a slot of their own in the builder, and priority 0 wins the
        # cycle's one workshops level (ONE_A_CYCLE)
        coming = _shop_coming(s, need)
        if need and not _has_shop(b, need):
            if coming:
                notes.append(f"{name} is in a {mood.lower()} mood and needs a {need}; a workshops level "
                             f"with a {need} is already being built")
            elif need in BUILDABLE_SHOPS:
                proposals.append(Proposal(
                    "mood", {"type": "start_project", "kind": "workshops", "shops": [need], "urgent": True, "mood": True},
                    f"{name} is in a {mood.lower()} mood and needs a {need} workshop, which the fort "
                    "doesn't have; without one they go insane", 0))
            else:
                # (0.105.35) no mood workshop today is outside BUILDABLE_SHOPS: kept
                # for a new one, said with what the AI does meanwhile
                ask_player(notes, f"{name} is in a {mood.lower()} mood and needs a {need}, which the fort "
                             "doesn't have and the AI's builder can't place (DFHack gives it no layout for one); "
                             "the AI keeps the mood's materials ready meanwhile, and the dwarf goes insane "
                             "without one")
        elif days >= cfg["mood_claim_days"]:
            # (0.105.35) nothing waits for the player: the fort's ones are taken
            # or out of the dwarf's walk, so another is built (one workshops
            # level at a time, never past the AI's cap for the kind)
            citizens = int(_d(s.get("dwarves")).get("total") or 0)
            what = f"{name} has been in a {mood.lower()} mood for {days} days without claiming a workshop"
            if need in BUILDABLE_SHOPS and not coming and shop_count(b, need) < shops_max(cfg, citizens):
                proposals.append(Proposal(
                    "mood", {"type": "start_project", "kind": "workshops", "shops": [need], "urgent": True, "mood": True},
                    f"{what}: the fort's {need} may be in use or out of the dwarf's walk, so another is "
                    "built; without one they go insane", 0))
            elif need and coming:
                notes.append(f"{what} ({need}); a workshops level with a {need} is already being built")
            elif (need in BUILDABLE_SHOPS and days >= cfg.get("mood_claim_cap_days", 6)
                  and str(m.get("unit_id")) not in _d(_d(getattr(memory, "mood_help", None)).get("cap_built"))):
                # (0.105.47, J1) the cap is for the AI's own building, not a life: one
                # more past it, once a mood (I7a: F's macabre Onol claimed no
                # Craftsdwarf's for 41 days and went mad, the AI building none)
                proposals.append(Proposal(
                    "mood", {"type": "start_project", "kind": "workshops", "shops": [need], "urgent": True,
                             "mood": True, "mood_unit": m.get("unit_id")},
                    f"{what}: the fort's {shop_count(b, need)} {need} (the AI's cap) are taken or out of the "
                    f"dwarf's walk, so one more is built past the cap; without one they go insane", 0))
            else:
                notes.append(f"{what}{' (' + need + ')' if need else ''}: DF lets the dwarf choose it, and the "
                             "AI has no more to build for it" + (f" ({shop_count(b, need)} stand, the AI's cap)"
                                                                 if need in BUILDABLE_SHOPS else ""))


def mood_item_text(x: dict) -> str:
    """'2 cloth (plant)', '1 bar of iron', '1 bone', in words.
    (0.105.24) "any stone, gem or metal" (material "rock" from an older
    bridge) and the item NONE of a bone or shell request read plainly: the
    log said "1 none (bone)", "1 rough gem of rock", "1 bar of rock (metal)"."""
    item = str(x.get("item") or "item").lower().replace("_", " ")
    flags = [f for f in _l(x.get("flags")) if isinstance(f, str)]
    if item == "none" and set(flags) & set(MOOD_BODY_FLAGS):
        item = next(f for f in flags if f in MOOD_BODY_FLAGS)
        flags = [f for f in flags if f != item]
    item = {"skin tanned": "leather", "corpsepiece": "bone or shell", "rough": "rough gem",
            "smallgem": "cut gem", "boulder": "stone", "wood": "log", "blocks": "block"}.get(item, item)
    q = int(x.get("quantity") or 1)
    if item == "cloth" and q >= 1000:
        q = math.ceil(q / 10000)             # (0.105.24) an older bridge: DF's cloth units
    what = f"{q} {item}" + ("s" if q > 1 and not item.endswith("s") else "")
    mat = str(x.get("material") or "")
    if mat and mat.lower() != "rock":
        what += f" of {mat.lower()}"
    kinds = [f for f in flags if f in ("bone", "shell", "metal", "plant", "silk", "leather",
                                       "yarn", "hard", "glass", "wood")]
    return what + (f" ({', '.join(kinds)})" if kinds else "")


# (0.105.113 item13) every AI order that uses leather: shoes, quivers, the flasks
# order's waterskins (0.105.26 seal fix), and the soldiers' leather gear (planner_leather's
# LEATHER_RECIPES). D, 24 Nov 03:27-03:47: each hide tanned for Cog's leather mood (four
# animals butchered for it) went within a minute into a leather_gear order for armour or
# a cap (the rule's leather_armor/leather_cap were in neither list), and Cog went berserk
MOOD_LEATHER_USES = ("leather_shoes", "leather_low_boots", "leather_quiver", "leather_waterskin",
                     "leather_armor", "leather_cap", "leather_leggings", "leather_gloves",
                     "leather_high_boots")

# (0.105.24) the AI's own orders that use up what a mood waits for: cancelled
# while the mood finds none free and another job holds it (cancelling an
# order drops its jobs nobody works, and their items with them)
MOOD_CONSUMERS = {"rough": ("cut_gems",), "cut_gem": ("encrust_goods",), "bone": ("bone_crafts",),
                  "cloth": ("cloth_bag", "yarn_bag", "silk_bag", "cloth_socks", "cloth_shoes"),
                  "leather": MOOD_LEATHER_USES,
                  "bar": ("metal_crafts", "metal_amulet", "metal_bracelet", "metal_ring", "metal_earring")}


# (0.105.26) the AI's other work orders that would use up what a waiting mood
# needs, held in select() while it waits (the bag, quiver, shoe, jewellery,
# crafts and cloth rules re-ordered what a mood had just cancelled); cloth and
# thread by the kind of thread a request names (none named: every kind)
MOOD_BLOCKS = {"rough": ("cut_gems",), "cut_gem": ("encrust_goods",), "bone": ("bone_crafts",),
               "leather": MOOD_LEATHER_USES,
               "bar": ("metal_crafts", "metal_amulet", "metal_bracelet", "metal_ring", "metal_earring")}
MOOD_CLOTH_BLOCKS = {"plant": ("cloth_bag", "cloth_socks", "cloth_shoes"), "silk": ("silk_bag",),
                     "yarn": ("yarn_bag",)}
MOOD_THREAD_BLOCKS = {"plant": ("weave_plant_cloth",), "silk": ("weave_silk_cloth",),
                      "yarn": ("weave_yarn_cloth",)}


def mood_blocks_of(x: dict) -> list:
    """(0.105.26; a helper since 0.105.99, verifier) The AI's recipes held
    while one mood request waits (mood_blocked): cloth and thread by the kind
    of thread it names (none named: every kind)."""
    kind = mood_kind(x)
    w = mood_want(x)                      # (0.105.112 item3)
    if w["what"] in ("cloth", "thread"):
        table = MOOD_CLOTH_BLOCKS if w["what"] == "cloth" else MOOD_THREAD_BLOCKS
        kinds = [k for k in table if k in w["fibres"]] or list(table)
        return [r for k in kinds for r in table[k]]
    return list(MOOD_BLOCKS.get(kind, ()))


def mood_blocked(s: dict) -> tuple[dict, dict]:
    """(0.105.26) What the fort's crafting moods wait for and don't have
    within reach, as ({recipe: what}, {material token: what}): the AI's
    other work orders of those recipes, or of those materials (a bar of a
    named metal), wait while a mood does."""
    recipes, mats = {}, {}
    for m in _l(_d(s.get("moods")).get("list")):
        if not isinstance(m, dict) or not m.get("craft"):
            continue
        for x in _l(m.get("missing")):
            if not isinstance(x, dict) or mood_on_hand(x) is True:
                continue
            kind, what = mood_kind(x), mood_item_text(x)
            for r in mood_blocks_of(x):
                recipes.setdefault(r, what)
            mat = str(x.get("material") or "").upper().replace(" ", "_")
            if kind == "bar" and mat and mat != "ROCK":
                mats.setdefault(mat if ":" in mat else "INORGANIC:" + mat, what)
    return recipes, mats


# what a caravan is asked for, for a mood the fort can't supply (lua/ai-trade.lua's categories)
MOOD_TRADE_KEYS = {"cloth": "CLOTH", "leather": "SKIN_TANNED", "log": "WOOD", "rough": "ROUGH",
                   "cut_gem": "SMALLGEM"}


def _mood_make(s: dict, x: dict, kind: str, memory, cfg: dict, mood: dict | None = None) -> tuple[list, str | None]:
    """(0.105.24) How the fort makes what a mood request asks for: a list of
    (action, why) to propose (empty when nothing is to be done now), and,
    when it can't be made here, the reason in words.

    (0.105.30) `mood` ({name, unit_id}): the dwarf whose mood it is; a life
    at stake sets the fort's no-slaughter ban aside for one animal (F, 8 Nov:
    a fey mood waited for 1 bone, the fort's bone out of the dwarf's walk, the
    Beast-friends ban held, and the dwarf went berserk). The bridge's count
    (x["avail"]) is read before "none" is said: stone the dwarf already holds,
    or a search cut short (`capped`), is no "no loose stone" (E, 8 Nov: said
    70 s before the artifact was made)."""
    st, su = _d(s.get("stocks")), _d(s.get("supplies"))
    b = _d(s.get("buildings"))
    q = int(x.get("quantity") or 1)
    if kind == "cloth" and q >= 1000:
        q = math.ceil(q / 10000)              # an older bridge: DF's cloth units
    q = max(1, min(10, q))
    flags = set(_l(x.get("flags")))
    want = mood_want(x)                   # (0.105.112 item3) read as mood_hospital reads it
    acts: list = []
    stuck = int(_d(mood).get("stalled") or 0) >= cfg.get("mood_stall_days", 7) or bool(_d(mood).get("urgent"))
    unwoven = ""
    dead: list[str] = []          # (0.105.47) the routes DF keeps cancelling, in words

    def order(recipe, amount, why, material=None):
        # (0.105.47, J1) an order whose jobs DF keeps cancelling for something
        # missing is a failed route, queued or not (I7a: F's weave, shear and
        # spin orders waited on until the dwarf went mad): the next is tried
        d = dead_order(s, recipe, cfg)
        if d:
            dead.append(d)
            return False
        # (0.105.99) a stalled mood waits only on the AI's own order of it: the player's or
        # DFHack's (the smelting library's SmeltOre orders wait for 100 charcoal) may never run
        if queued(s, {recipe}, ai_only=stuck):
            return True                    # already on order: wait for it
        a = {"type": "work_order", "recipe": recipe, "amount": max(1, int(amount))}
        if material:
            a["material"] = material
        acts.append((a, why))
        return True

    def dead_words():
        return ("; " + "; ".join(dict.fromkeys(dead))) if dead else ""

    def yarn_route():
        # shorn, then spun: dead when the shearing fails, or the spinning with no shearing left to wait on
        if not wool_route(s):
            return False
        if dead_order(s, "shear_creature", cfg):
            dead.append(dead_order(s, "shear_creature", cfg))
            return False
        if dead_order(s, "spin_thread", cfg) and not queued(s, {"shear_creature"}):
            dead.append(dead_order(s, "spin_thread", cfg))
            return False
        return True

    if kind == "cloth":
        # (0.105.47, J1) the thread DF will weave (a kind whose weaving is
        # cancelled for want of thread counts none); every kind's route is
        # tried in turn, silk too: webs collected at the Loom
        thread = usable_thread(s, cfg)
        kinds = list(want["fibres"]) or \
            sorted(("plant", "yarn", "silk"), key=lambda k: -int(thread.get(k) or 0))
        if not _has_shop(b, "Loom"):
            if _mood_shop(s, ("Loom",), acts, mood, "cloth woven"):
                return acts, None
            return acts, "no loom to weave it at"
        for k in kinds:
            if int(_d(su.get("thread_kinds")).get(k) or 0) > 0 and not thread.get(k):
                dead.append(dead_order(s, f"weave_{k}_cloth", cfg) or f"the {k} thread isn't woven")
        for k in kinds:
            # an older bridge (no thread by kind): plant thread where plants give
            # it or no wool comes in (0.104.36: a plant-cloth order where the
            # thread is all wool only cancels at the loom)
            old_plant = (not _d(su.get("thread_kinds")) and k == "plant" and int(st.get("thread") or 0) > 0
                         and (thread_plants_here(s) or not wool_route(s)))
            if int(thread.get(k) or 0) > 0 or old_plant:
                # (0.105.33) the weaving already on order while the mood has
                # stalled: the thread counted isn't woven (C, 8 Nov: 5 yarn
                # thread, the hospital's, "woven" 6 times and never; shearing
                # never tried): make the thread too
                waited = stuck and queued(s, {f"weave_{k}_cloth"})
                if not order(f"weave_{k}_cloth", q, f"weave {k} cloth"):
                    continue                       # DF won't weave it: that kind's thread is made below
                if not waited:
                    return acts, None
                kinds, unwoven = [k], f" (the {int(thread.get(k) or 0)} {k} thread counted is never woven)"
                break
        for k in kinds:
            if k == "plant" and thread_plants_here(s) and _has_shop(b, "Farmers"):
                if order("process_plants", 3, "process plants for thread (then weave it)"):
                    return acts, None
            if k == "yarn" and yarn_route():
                if (order("shear_creature", 1, "shear an animal for wool (then spin and weave it)")
                        and order("spin_thread", 1, "spin the wool into yarn")):
                    return acts, None
            if k == "silk" and silk_route(s, cfg):
                if order("collect_webs", cfg.get("mood_webs_collect", 5),
                         f"collect spider webs for silk thread ({webs_reach(s)} within a weaver's reach; then "
                         "weave it)"):
                    return acts, None
        k = kinds[0]
        return acts, (f"no {k} thread to weave" + (" (silk comes from spider webs: none a weaver can reach, "
                                                   "or a caravan's)" if k == "silk" else
                                                  " (no sheep, llama or alpaca with wool grown to shear)"
                                                  if k == "yarn" else "")
                      + unwoven + dead_words())
    if want["what"] == "thread":
        # (0.105.33) thread itself (mood_kind says "other"): by the request's
        # kind, the routes the cloth branch takes (B4: a plant-thread request
        # was told "no recipe makes it" with fibre plants and a farmer's)
        kinds = list(want["fibres"]) or \
            (["plant"] if thread_plants_here(s) else []) + (["yarn"] if wool_route(s) else []) \
            + (["silk"] if silk_route(s, cfg) else []) or ["plant"]
        for k in kinds:
            if k == "plant" and thread_plants_here(s) and _has_shop(b, "Farmers"):
                if order("process_plants", 3, "process plants for thread"):
                    return acts, None
            if k == "yarn" and yarn_route():
                if (order("shear_creature", 1, "shear an animal for wool (then spin it)")
                        and order("spin_thread", 1, "spin the wool into yarn")):
                    return acts, None
            if k == "silk" and silk_route(s, cfg):
                if order("collect_webs", cfg.get("mood_webs_collect", 5), "collect spider webs for silk thread"):
                    return acts, None
        k = kinds[0]
        return acts, {"plant": "no fibre plant to process for thread" + ("" if _has_shop(b, "Farmers")
                                                                        else " and no farmer's workshop"),
                      "yarn": "no sheep, llama or alpaca with wool grown to shear (or no farmer's workshop)",
                      "silk": "no silk thread (silk comes from spider webs: none a weaver can reach, or a "
                              "caravan's)"}.get(k, "no thread") + dead_words()
    if kind == "leather":
        hides = raw_hides(s)
        if hides > 0 and _has_shop(b, "Tanners"):
            if order("tan_hide", q, "tan a hide"):
                return acts, None
        why = "no hide to tan" + ("" if _has_shop(b, "Tanners") else " and no tanner's")
        # (R1 g6) the butcher's and the tanner's a mood's leather needs, built past the cap
        shop = _mood_shop(s, ("Butchers", "Tanners"), acts, mood, "an animal butchered and its hide tanned")
        if _mood_slaughter(s, memory, cfg, acts, "its hide tanned for leather", mood=mood) or shop:
            return acts, None
        return acts, why + "; " + _slaughter_why(s, memory, cfg, mood) + dead_words()
    if kind in ("bone", "shell"):
        if kind == "shell":
            return acts, "no shell (shells come from turtles and shellfish: fishing, or a caravan's)"
        shop = _mood_shop(s, ("Butchers",), acts, mood, "an animal butchered for its bones")
        if _mood_slaughter(s, memory, cfg, acts, "its bones for the mood", mood=mood) or shop:
            return acts, None
        return acts, "no bone the dwarf can use; " + _slaughter_why(s, memory, cfg, mood)
    if kind == "bar":
        furnaces = _d(b.get("furnaces"))
        magma = bool(furnaces.get("MagmaSmelter"))
        if not (furnaces.get("Smelter") or magma):
            ores = any(isinstance(v, dict) and int(v.get("n") or 0) > 0
                       for v in _d(_d(s.get("industry")).get("ore_stock_by")).values())
            if ores and _mood_shop(s, ("Smelter",), acts, mood, "ore smelted into a bar"):
                return acts, None
            return acts, "no smelter"
        if not magma and int(su.get("fuel") or 0) <= 0:
            # (0.105.112 item3) the fuel made first. D, 22-24 Nov: eight moods (forges, a
            # metalcrafter, craftsdwarfs) waited on bars with 84 ore stones, a smelter and a
            # wood furnace, fuel 0 and 19 logs no dwarf could walk to: "no fuel" was said and
            # nothing done; all eight went mad
            coal = sorted(((int(_d(v).get("n") or 0), k) for k, v in
                           _d(_d(s.get("stone_use")).get("economic")).items()
                           if k in MOOD_COAL and int(_d(v).get("n") or 0) > 0), reverse=True)
            if coal and order(MOOD_COAL[coal[0][1]], 1, f"make coke from {coal[0][1].lower().replace('_', ' ')} "
                                                    "(fuel to smelt the bar)"):
                return acts, None
            # (0.105.113 item13) the logs a dwarf can walk to (D: 19 logs, all on the surface out of
            # every dwarf's walk: the charcoal order stood): none, the fort's own reachable trees
            wood, logs = reach_wood(s), int(st.get("wood") or 0)
            if wood > 0 and _has_shop(b, "WoodFurnace"):
                if order("make_charcoal", min(2, wood), "burn wood into charcoal (fuel to smelt the bar)"):
                    return acts, None
            far = (f"the fort's {logs - wood} log(s) lie where no dwarf walks; " if logs > wood else "")
            lacts, lwhy = _mood_make(s, {"item": "WOOD", "quantity": 1}, "log", memory, cfg, mood=mood)
            if lacts or lwhy is None:
                acts.extend((a, far + how + " (wood for charcoal, the smelter's fuel)") for a, how in lacts)
                return acts, None
            return acts, "no fuel for the smelter (no coal, and no wood within reach to burn: " + far + lwhy \
                + ")" + dead_words()
        metal = str(x.get("material") or "").upper().replace(" ", "_")
        if metal == "ROCK":
            metal = ""
        by_ore = {k: v for k, v in _d(_d(s.get("industry")).get("ore_stock_by")).items()
                  if isinstance(v, dict) and int(v.get("n") or 0) > 0
                  and (not metal or metal in [str(m).upper() for m in _l(v.get("metals"))])}
        if not by_ore:
            return acts, f"no {metal.lower() + ' ' if metal else ''}ore to smelt"
        ore = max(sorted(by_ore), key=lambda k: int(by_ore[k].get("n") or 0))
        if order("smelt_ore", q, f"smelt {ore.lower()} ore", f"INORGANIC:{ore}"):
            return acts, None
        return acts, f"no {metal.lower() + ' ' if metal else ''}bar can be smelted" + dead_words()
    if kind == "glass_rough":
        furnaces = _d(b.get("furnaces"))
        if not (_has_shop(b, "GlassFurnace") or furnaces.get("MagmaGlassFurnace")):
            sand = bool(_l(su.get("sand_layers")) or int(su.get("sand_bags") or 0) > 0)
            if sand and _mood_shop(s, ("GlassFurnace",), acts, mood, "raw green glass made"):
                return acts, None
            return acts, "no glass furnace"
        if int(su.get("sand_bags") or 0) > 0 and (int(su.get("fuel") or 0) > 0 or furnaces.get("MagmaGlassFurnace")):
            if order("raw_green_glass", q, "make raw green glass"):
                return acts, None
        if int(su.get("empty_bags") or 0) > 0:
            # (0.105.47, J1) a sand zone first (I7a: F's Obok, "Collect sand: Need
            # valid, active sand collection zone" 31 times, the dwarf went mad)
            if "sand_zones" in su and int(su.get("sand_zones") or 0) <= 0:
                if _l(su.get("sand_layers")):
                    acts.append(({"type": "sand_zone"}, "a sand collection zone first (bags are filled there "
                                                        "for raw glass)"))
                    return acts, None
                return acts, "no sand on this map to collect for raw glass (no sand zone can be made)"
            if order("collect_sand", 2, "fill bags with sand for raw glass"):
                return acts, None
        return acts, "no bag of sand (or no fuel) for raw glass" + dead_words()
    if kind == "cut_gem":
        rg = _d(_d(s.get("trade")).get("rough_gem"))
        rough = max(int(rg.get("n") or 0), int(st.get("rough_gems") or 0))
        if (_has_shop(b, "Jewelers") and int(rg.get("n") or 0) > 0
                and str(rg.get("token", "")).startswith("INORGANIC:")):
            if order("cut_gems", q, "cut a gem", rg["token"]):
                return acts, None
        if not _has_shop(b, "Jewelers") and rough > 0:
            # (R1 g6) R-AD: rough gems by the hundred and no jeweller's for 1-2
            # game years (the project cap), while three moods died for one cut gem
            if _mood_shop(s, ("Jewelers",), acts, mood, f"one of the fort's {rough} rough gems cut"):
                return acts, None
            return acts, f"no jeweller's workshop to cut the fort's {rough} rough gems" + dead_words()
        return acts, "no rough gem to cut" + dead_words()
    if kind == "block" and not x.get("material") and not flags & {"metal", "glass", "wood"}:
        order("stone_blocks", q, "make stone blocks")
        return acts, None
    if kind == "rough":
        # (0.105.47, J1) the gem cutting waits meanwhile (mood_blocked; each gem counted for one request only)
        return acts, ("no rough gem the dwarf can reach (they come from mining gem veins, or a caravan's); "
                      "the AI's gem cutting waits meanwhile")
    if kind == "log":
        # (0.105.99) none within the dwarf's walk (D, 24 Nov: Nil's Fey mood counted 19 logs,
        # all where no dwarf walks, and went berserk on day 42): one of the fort's own
        # underground trees felled (the forestry's inside-only marking: no cavern, no surface)
        ins = _d(_d(s.get("forestry")).get("inside"))
        inside = int(ins.get("reachable") or 0)
        rm = ins.get("reach_marked")      # an older bridge: none, and the marked ones count
        marked = rm if isinstance(rm, int) and not isinstance(rm, bool) else int(ins.get("marked") or 0)
        if mood and inside > 0 and marked > 0:
            # (0.105.99, verifier) one already marked within reach: wait for its felling
            # (the mood's quarter-day cooldown marked another tree each time while the
            # first stood)
            return acts, None
        if mood and inside > 0:
            if not any(a.get("type") == "cavern_logging" for a, _ in acts):
                acts.append(({"type": "cavern_logging", "limit": 1, "inside_only": True},
                             f"fell one of the fort's own {inside} underground tree(s) within reach for a log"))
            return acts, None
        return acts, "no log within the dwarf's walk (trees felled, or a caravan's wood)"
    if kind == "stone":
        av = _d(x.get("avail"))
        if int(av.get("held") or 0) > 0:
            return acts, None                  # the dwarf holds stone that suits: it is on its way
        if av.get("capped"):
            return acts, None                  # the bridge's search was cut short: not known to be none
        if int(av.get("free") or 0) > 0 or int(av.get("forbidden") or 0) > 0:
            return acts, None                  # the fort has some (out of reach, or forbidden: said elsewhere)
        return acts, "no loose stone of the kind it wants"
    return acts, "no recipe makes it"


MOOD_COAL = {"COAL_BITUMINOUS": "coke_bituminous", "LIGNITE": "coke_lignite"}   # planner_industry_stone's COAL_STONES

MOOD_SLAUGHTER_MIN_TAME = 1     # (R1 g6) for a mood: any spare animal (the bridge keeps pets, named ones, a last pair)


def _mood_shop(s: dict, needs, acts: list, mood: dict | None, what: str) -> bool:
    """(R1 g6) The workshops a waiting mood's material is made at (a
    jeweller's for a cut gem, a butcher's for bone...), one workshops level
    past the AI's project cap (`mood`: the bridge's builder takes no slot for
    it). Only for a named mood (the reserves wait their turn). True when one
    is asked for now or already coming; False when every one stands, or the
    builder can't place it."""
    if not mood:
        return False
    b = _d(s.get("buildings"))
    missing = [n for n in needs if not _has_shop(b, n)]
    if not missing:
        return False
    coming = [n for n in missing if _shop_coming(s, n)]
    want = [n for n in missing if n not in coming and n in BUILDABLE_SHOPS]
    if not want:
        return bool(coming)
    if any(a.get("type") == "start_project" for a, _ in acts):
        return True
    a = {"type": "start_project", "kind": "workshops", "shops": want, "urgent": True, "mood": True}
    if mood.get("unit_id") is not None:
        a["mood_unit"] = mood.get("unit_id")
    acts.append((a, f"no {', '.join(want)}: one is built for it ({what}), past the AI's project cap, "
                    "a life being at stake"))
    return True


def _mood_slaughter(s: dict, memory, cfg: dict, acts: list, why: str, mood: dict | None = None) -> bool:
    """(0.105.24) One spare tame animal to the butcher for a mood's bone or
    leather (the slaughter rule's own guards: a butcher's, enough tame
    animals, never a fort of Beast-friends).

    (0.105.30) For a named mood (`mood`: {name, unit_id}) a life is at
    stake: the fort's no-slaughter ban is set aside, said so plainly, for one
    animal only, the oldest spare adult (lua: never a pet, a war or hunting
    animal, a child, a caged one or the last two of a kind; a male while the
    kind has more than one), and at most one a mood. True when an animal is
    asked for or already went for this mood (its bone or hide is coming)."""
    uid = None if not mood else mood.get("unit_id")
    if uid is not None and memory is not None and str(uid) in _d(getattr(memory, "mood_slaughter", None)):
        # this mood's animal went already: its bone or hide is coming. (R1 g6)
        # Another after `g6_mood_slaughter_again_days` while it still waits
        # (D's Uvash: the one alpaca butchered, the mood still failed)
        last = _d(getattr(memory, "mood_slaughter", None)).get(str(uid))
        again = int(cfg.get("g6_mood_slaughter_again_days", 8)) * TICKS_PER_DAY
        if not (isinstance(last, int) and 0 <= abs_tick(s) - last >= again):
            return True
    tame = int(_d(s.get("others_on_map")).get("tame_animals") or 0)
    banned = memory is not None and has_rule(getattr(memory, "culture", None), "no_slaughter")
    least = MOOD_SLAUGHTER_MIN_TAME if mood else cfg["slaughter_min_tame"]
    if not (tame >= least and _has_shop(_d(s.get("buildings")), "Butchers")):
        return False
    if banned and not mood:
        return False
    if any(a.get("type") == "slaughter_one" for a, _ in acts):
        return True
    if mood and marked_waiting(s) > 0:
        # (0.105.113 item13) an animal already waits for the butcher (the bridge refuses
        # another: "N animal(s) already wait for the butcher", E 79 times, D 6): its bone and
        # hide are coming, nothing proposed again; the next step instead: a butcher if
        # nobody butchers
        butchers = _d(_d(s.get("provisions")).get("butchery")).get("butchers")
        if butchers == 0 and not any(a.get("type") == "assign_labor" for a, _ in acts):
            acts.append(({"type": "assign_labor", "job": "BUTCHER", "count": 1},
                         f"{marked_waiting(s)} animal(s) wait for the butcher and nobody butchers: a dwarf "
                         "put on it"))
        return True
    if mood:
        # (R1 g6) `mood`: the bridge takes any spare tame animal (young or of a
        # small herd too), never a pet, a war or hunting animal, a named one, a
        # caged one or a kind's last breeding pair (R-AD: refused 93 times in D)
        a = {"type": "slaughter_one", "oldest": True, "mood": True}
        if uid is not None:
            a["mood_unit"] = uid
        who = mood.get("name") or "a dwarf"
        text = (f"a spare tame animal of the {tame} to the butcher (any kind, young too; never a pet, a war or "
                f"hunting animal, a named one or a kind's last breeding pair): {why}")
        if banned:
            text = (f"the fort's {_ban_name(memory)} ban is set aside to save {who}'s mood: one animal only, "
                    + text)
        acts.append((a, text))
    else:
        acts.append(({"type": "slaughter_one"}, f"one spare tame animal of the {tame} to the butcher: {why}"))
    return True


def marked_waiting(s: dict) -> int:
    """(0.105.113 item13) Tame animals marked for slaughter that can walk to a
    butcher's shop (the herd report's `marked_waiting`; an older bridge: every
    marked one, `marked`). One that can't (E: a peafowl in a pasture with no path
    to the shop, marked for days) gets no job and no longer blocks another."""
    h = _d(s.get("herd"))
    v = h.get("marked_waiting", h.get("marked"))
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


def reach_wood(s: dict) -> int:
    """(0.105.113 item13) Logs a dwarf can walk to (supplies.wood_reach), else
    (an older bridge) every log in stock."""
    v = _d(s.get("supplies")).get("wood_reach")
    if isinstance(v, int) and not isinstance(v, bool):
        return max(0, v)
    return max(0, int(_d(s.get("stocks")).get("wood") or 0))


def mood_wants_bar(s: dict) -> bool:
    """(0.105.113 item13) A crafting mood waits on a metal bar it doesn't have."""
    for m in _l(_d(s.get("moods")).get("list")):
        if isinstance(m, dict) and m.get("craft"):
            for x in _l(m.get("missing")):
                if isinstance(x, dict) and mood_kind(x) == "bar" and mood_on_hand(x) is not True:
                    return True
    return False


def raw_hides(s: dict) -> int:
    """(0.105.113 item13) Raw hides a tanner can take: the provisions report's
    count (lua/ai-provisions.lua real_hide: a hide, no skin-covered limb or
    skull), else the supplies' (any corpse piece of a skin that makes
    parchment). D's tan_hide orders stood 28 days and were cancelled nine times
    on hides no tanner takes."""
    v = _d(_d(s.get("provisions")).get("butchery")).get("hides")
    if isinstance(v, int) and not isinstance(v, bool):
        return max(0, v)
    return max(0, int(_d(s.get("supplies")).get("hides") or 0))


def _ban_name(memory) -> str:
    """The fort's trait whose rule bans slaughter, by name ("Beast-friends")."""
    try:
        qs = quirks.data()["quirks"]
        held = _d(_d(getattr(memory, "culture", None)).get("quirks"))
        for q in sorted(held):
            if q in qs and "no_slaughter" in (qs[q].get("rules") or []):
                return str(qs[q].get("name") or "no-slaughter")
    except Exception:              # noqa: BLE001  (a name only)
        pass
    return "no-slaughter"


def _slaughter_why(s: dict, memory, cfg: dict, mood: dict | None) -> str:
    """Why no animal can go to the butcher for it, in words."""
    tame = int(_d(s.get("others_on_map")).get("tame_animals") or 0)
    if not _has_shop(_d(s.get("buildings")), "Butchers"):
        return "no butcher's shop to butcher an animal at"
    least = MOOD_SLAUGHTER_MIN_TAME if mood else cfg["slaughter_min_tame"]
    if tame < least:
        return f"only {tame} tame animal(s), none to spare for the butcher"
    if not mood and memory is not None and has_rule(getattr(memory, "culture", None), "no_slaughter"):
        return "the fort never slaughters its animals"
    return "no spare tame animal to butcher"


def mood_counts_text(x: dict) -> str:
    """(0.105.30) One request with the bridge's count, compactly: "1 bone:
    3 free (1 in walk), 2 forbidden, 1 in other jobs"."""
    what = mood_item_text(x)
    av = x.get("avail")
    if not isinstance(av, dict):
        return f"{what}: no count from this bridge"
    n = lambda k: int(av.get(k) or 0)            # noqa: E731
    bits = [f"{n('free')} free ({n('reach')} in walk)"]
    for k, w in (("forbidden", "forbidden"), ("dump", "for the dump"), ("job", "in other jobs"),
                 ("other", "in use"), ("held", "carried by the dwarf"),
                 # (0.105.99) a trader's goods and the hospital's, counted apart (they were "in use")
                 ("trader", "a trader's goods"), ("hospital", "the hospital's"),
                 ("partial", "part-used (a mood takes whole cloth)")):
        if n(k):
            bits.append(f"{n(k)} {w}")
    if av.get("capped"):
        bits.append("search cut short")
    return f"{what}: " + ", ".join(bits)


# (0.105.99) a moody dwarf drinks nothing till the artifact is made (B, 24 Nov: Edzul died of
# thirst on day 43): past DFHack's "thirsty" (25000, lua/ai-thirst.lua THIRSTY), or stalled this
# many days, the mood's materials come first (priority 0; the AI's orders that would use them
# cancelled). Constants, not PLANNER_CONFIG keys (tests/test_r7_d6 pins that dict); a cfg of the
# same name overrides them.
MOOD_THIRST_URGENT = 25000
MOOD_URGENT_DAYS = 20


def _mood_materials(s: dict, name: str, mood: str, missing: list, days: int,
                    proposals: list, notes: list, cfg: dict | None = None, memory=None, unit_id=None,
                    stalled: int | None = None, thirst: int | None = None) -> None:
    """A mood gathering materials: get it what it waits for, and say exactly
    what the fort can't supply (a mood that never gets its materials ends in
    madness).

    (0.105.24) The overnight run (2-5 Nov, six forts): 103 of 231 moods
    failed; the AI had ordered only plant cloth (and blocks), and named the
    rest in Needs you from day 7, the dwarf's whole unmet list among it, so
    the notes said nothing about what the fort had. Now, with the bridge's
    count for each request (lua/ai-moods.lua: free within the dwarf's walk,
    forbidden or dumped, held by another job): what lies free is left to the
    dwarf; forbidden or dumped items are freed (mood_free_items); the AI's
    own orders that would use the last of it are cancelled; the rest is made
    (cloth woven by kind, a hide tanned, bars smelted, a gem cut, raw green
    glass, blocks; an animal butchered for bone or leather); what can't be
    made here goes on the caravans' list (0.105.35: a note, the trade rules
    buy it; no Needs you). From an older bridge (no count): day 3, then on
    day 7 its forbidden items freed and the rest asked of the caravans.

    (0.105.30) What the fort has out of the dwarf's walk is one Needs you,
    never "none" beside it (F, 8 Nov: "the fort has it, but where the dwarf
    can't walk" next to "no bone and no spare tame animal"); a mood that has
    fetched nothing for `mood_stall_days` (`stalled`, days) is said in Needs
    you with the bridge's count for each request, even when all of it reads
    on hand (D, 8 Nov: a secretive mood had no line for 40 days, then went
    berserk)."""
    cfg = cfg or PLANNER_CONFIG
    counted = any(isinstance(x.get("avail"), dict) for x in missing)
    ordered, lacking, freeing, far = [], [], False, []
    asks: list[str] = []
    who = {"name": name, "unit_id": unit_id, "stalled": stalled}
    taken = {p.action.get("order_id") for p in proposals if p.action.get("type") == "cancel_work_order"}
    # (0.105.99) a moody dwarf drinks nothing till the artifact is made (B, 24 Nov 00:18: Edzul
    # died of thirst on day 43 of a Secretive mood): thirsty (DF's counter past
    # `mood_thirst_urgent`) or stalled `mood_urgent_days`, the mood's materials come first
    thirsty = (isinstance(thirst, int) and not isinstance(thirst, bool)
               and thirst >= int(cfg.get("mood_thirst_urgent", MOOD_THIRST_URGENT)))
    urgent = thirsty or (stalled is not None and stalled >= int(cfg.get("mood_urgent_days", MOOD_URGENT_DAYS)))
    who["urgent"] = urgent
    prio = 0 if urgent else 1
    # (0.105.99) the requests the fort has nothing free in the dwarf's walk for: the true
    # blockers. B, 24 Nov: Edzul's first request (2 iron bars, free in a bin on a stockpile)
    # read "on hand" for 41 days and the AI smelted bars five times, while the plant cloth
    # (none of the fort's own: the 20 counted were the stuck caravan's) had nothing done
    blockers = [x for x in missing if mood_on_hand(x) is False]
    waiting: list[str] = []
    for i, x in enumerate(missing):
        kind = mood_kind(x)
        av = _d(x.get("avail"))
        here = mood_on_hand(x)
        if here:
            # (0.105.33) counted free within the dwarf's walk, but the first
            # request has waited `mood_stall_days`: what is counted isn't what
            # DF will take (B, 8 Nov: 1 bone "free 1, in reach 1" for 40 days,
            # 33 tame animals and a butcher's, nothing tried; the dwarf went
            # raving). Make it as if missing; never "none" said for it.
            if (i == 0 and stalled is not None and stalled >= cfg.get("mood_stall_days", 7)
                    and not blockers):      # (0.105.99) another request lacks: that one first
                acts, _ = _mood_make(s, x, kind, memory, cfg, mood=who)
                for a, how in acts:
                    if a.get("type") == "work_order" and any(p.action == a for p in proposals):
                        continue
                    if a.get("type") == "slaughter_one" and any(
                            p.action.get("type") == "slaughter_one" for p in proposals):
                        continue                   # (0.105.113 item13) one animal a cycle
                    proposals.append(Proposal(
                        "mood", a, f"{name}'s {mood.lower()} mood needs {mood_item_text(x)} (the one it is "
                        f"fetching now): the fort's counts it within the dwarf's walk, but nothing was "
                        f"fetched for {stalled} days, so more is made: {how}", prio, a.get("type") == "work_order"))
                    if a.get("type") == "work_order":
                        ordered.append(a.get("recipe"))
            continue                                   # free within reach: the dwarf will fetch it
        want = max(1, int(x.get("quantity") or 1))
        if counted and int(av.get("forbidden_reach") or 0) > 0:
            freeing = True
            if int(av.get("reach") or 0) + int(av.get("forbidden_reach") or 0) >= want:
                continue
        out_of_walk = counted and int(av.get("free") or 0) > int(av.get("reach") or 0)
        held_by_job = counted and int(av.get("job") or 0) > 0
        if held_by_job or (counted and urgent):
            # (0.105.99) urgent: the AI's orders that would use up what is made for the
            # mood go too, not only one holding the fort's last (B: the cloth woven for
            # the reserve went into clothing within minutes)
            # (0.105.99, verifier) the urgent cancel only of the orders select() then holds
            # while the mood waits (mood_blocked, mood_blocks_of): a plant-cloth mood's
            # cancel of the AI's silk or yarn bag order was placed again by the bag
            # rule, cancelled again, each cooldown (and a silk bag's job holds no plant cloth)
            held_r = set(mood_blocks_of(x))
            for o in _l(s.get("orders")):
                if (isinstance(o, dict) and o.get("by_ai") and o.get("recipe") in MOOD_CONSUMERS.get(kind, ())
                        and o.get("id") is not None and o.get("id") not in taken
                        and o.get("recipe") in held_r):
                    taken.add(o.get("id"))
                    proposals.append(Proposal("mood", {"type": "cancel_work_order", "order_id": o["id"]},
                                              f"{name}'s {mood.lower()} mood waits for {mood_item_text(x)} and "
                                              + ("another job holds the fort's last" if held_by_job else
                                                 ("the dwarf is thirsty (no moody dwarf drinks)" if thirsty else
                                                  f"has stalled {stalled} days") + "; this order would use it up")
                                              + f": cancel the AI's {o['recipe']} order (its jobs let go of it)",
                                              prio))
                    if held_by_job:
                        break
        extra = _mood_held_words(s, x, kind)
        acts, why = _mood_make(s, x, kind, memory, cfg, mood=who)
        for a, how in acts:
            if a.get("type") == "work_order" and any(p.action == a for p in proposals):
                continue
            if a.get("type") in ("slaughter_one", "assign_labor") and any(
                    p.action.get("type") == a.get("type") and p.action.get("job") == a.get("job")
                    for p in proposals):
                # (0.105.113 item13) one animal a cycle: a mood's bone and its leather asked one each
                # (D 20:01: the second refused "1 animal(s) already wait for the butcher")
                continue
            proposals.append(Proposal("mood", a, f"{name}'s {mood.lower()} mood needs {mood_item_text(x)}"
                                      + (" (the one it is fetching now)" if i == 0 else "")
                                      + (" (the fort's lies where the dwarf can't walk)" if out_of_walk else "")
                                      + (f" ({extra})" if extra else "")
                                      + (" (the dwarf is thirsty: no moody dwarf drinks)" if thirsty else "")
                                      + f": {how}", prio, a.get("type") == "work_order"))
            if a.get("type") == "work_order":
                ordered.append(a.get("recipe"))
        if acts:
            continue
        if why is None and not out_of_walk:
            # (0.105.99) on its way (an order already queued, or the bridge's search cut
            # short): said once the mood has stalled, with what holds the fort's (it was
            # silent: B's plant cloth "on order" 41 days)
            waiting.append(mood_item_text(x) + (f" ({extra})" if extra else ""))
            continue
        if why and extra:
            why = f"{why}; {extra}"
        if out_of_walk:
            # in the fort, but where the dwarf can't walk: never "none" (F, 8 Nov)
            far.append(mood_item_text(x) + (f" (none to be made here: {why})" if why else ""))
        elif why and not (counted and int(av.get("job") or 0) > 0):
            try:
                rw = reserve_words(s, cfg, x)          # (0.105.31) the reserve and what is being done
            except Exception:                        # noqa: BLE001  (words only)
                rw = ""
            lacking.append((mood_item_text(x), why + (f" ({rw})" if rw else ""), kind))
    first = mood_item_text(missing[0]) if missing else ""
    stall_noted = False
    # (0.105.35) nothing waits for the player: what the AI can do is done
    # (made, freed, cancelled, asked of the caravans, bought by the trade
    # rules); only what DF won't let it do stays in Needs you, with what the
    # AI does meanwhile
    if far:
        keyed = any(MOOD_TRADE_KEYS.get(mood_kind(x)) for x in missing)
        asks.append(f"{name}'s {mood.lower()} mood waits for {'; '.join(far)}: the fort has it, but "
                    "where the dwarf can't walk, and the AI can't carry it there (DF hauls only along a path "
                    "the dwarf can walk too)"
                    + (f"; meanwhile it is on the caravans' list, bought {TRADE_IF}" if keyed else "")
                    + ", or the dwarf goes insane")
    words = [w for w, _, _ in lacking]
    lack_at = None                        # (0.105.35) the index of the lacking note in notes
    if lacking and counted:
        # the bridge counted: none within the fort the mood can use, none made here
        lack_at = len(notes)
        notes.append(f"{name}'s {mood.lower()} mood (day {days}) needs what the fort can't supply: "
                     + "; ".join(f"{w}: {why}" for w, why, _ in lacking)
                     + ". " + _mood_trade_words(s, name, [k for _, _, k in lacking]))
    elif lacking and days >= cfg["mood_lacking_days"]:
        # (an older bridge, no count) what is forbidden or dumped is freed, the rest asked of the caravans
        if unit_id is not None and not freeing:
            freeing = True
        lack_at = len(notes)
        notes.append(f"{name}'s {mood.lower()} mood still lacks, after {days} days: {', '.join(words)}. "
                     f"The AI frees what lies forbidden or dumped; the rest is on the caravans' list, bought {TRADE_IF}")
    elif lacking:
        # (0.103.8) the dwarf may still be fetching it: Enxah's fisherdwarf
        # claimed the mason's on day 3, "lacked" rock that day and the next
        # (51 boulders about) and began the work on day 5
        notes.append(f"{name}'s {mood.lower()} mood: still gathering after {days} days, waiting on "
                     f"{', '.join(words)}")
    if stalled is not None and stalled >= cfg.get("mood_stall_days", 7) and missing:
        # (0.105.47, J1) with DF's flags of each request and where the counted items lie (I7a 7)
        counts = "; ".join(mood_counts_text(x) + (f" [{request_detail(x)}]" if request_detail(x) else "")
                           for x in missing)
        line = (f"no progress for {stalled} days; what the fort holds for each request: {counts}")
        if asks:
            asks[-1] += f" ({line})"
        elif lack_at is not None:
            notes[lack_at] += f" ({line})"
        else:
            # (0.105.35) the AI makes more of the first request (above) and frees
            # what lies forbidden in the dwarf's walk; DF says no more of why
            if unit_id is not None:
                freeing = True
            stall_noted = True
            notes.append(f"{name}'s {mood.lower()} mood has fetched nothing for {stalled} days although the fort "
                         f"seems to hold it ({counts}): the AI makes more of what it fetches first and frees "
                         "what lies forbidden in the dwarf's walk")
    # (0.105.47, J1) not asked again after "nothing forbidden" while the counts stay as they were
    if freeing and unit_id is not None and not free_items_skip(memory, unit_id, missing):
        proposals.append(Proposal("mood", {"type": "mood_free_items", "unit_id": unit_id, "max": 10},
                                  f"{name}'s {mood.lower()} mood can use items that lie forbidden or marked for "
                                  "the dump (or in a forbidden bin): free them", prio))
    for a in asks:
        ask_player(notes, a)
    if waiting and (urgent or (stalled is not None and stalled >= cfg.get("mood_stall_days", 7))):
        notes.append(f"{name}'s {mood.lower()} mood (day {days}) waits on {'; '.join(waiting)}: already on "
                     "order (the AI's own orders' jobs come first while it waits)")
    if thirsty:
        players = _mood_player_orders(s, blockers)
        notes.append(f"{name} is thirsty in a {mood.lower()} mood (DF lets no moody dwarf drink till the "
                     f"artifact is made): the mood's materials come first"
                     + (f"; the player's own orders use the same material ({players}): the AI cancels only its own"
                        if players else ""))
    if not lacking and not asks and not stall_noted and counted and (ordered or freeing):
        notes.append(f"{name}'s {mood.lower()} mood (day {days}): fetching {first}"
                     + (f"; ordered {', '.join(ordered)}" if ordered else "")
                     + ("; forbidden materials freed" if freeing else ""))


def _mood_held_words(s: dict, x: dict, kind: str) -> str:
    """(0.105.99) What holds the fort's items of a request the mood can't
    take, in words ('' when nothing): a trader's goods (B, 24 Nov: the 20
    plant cloth counted "other" were the stuck caravan's), the hospital's
    stock, part-used cloth, and the thread kept in the hospital's chests (B:
    its 15 thread, the fort's only, all there)."""
    av = _d(x.get("avail"))
    n = lambda k: int(av.get(k) or 0)            # noqa: E731
    bits = []
    if n("trader"):
        bits.append(f"the {n('trader')} counted are a trader's goods: the mood's only if bought {TRADE_IF}")
    if n("hospital"):
        bits.append(f"{n('hospital')} are the hospital's stock, which DF keeps for the hospital")
    if n("partial"):
        bits.append(f"{n('partial')} are part-used (a mood takes whole cloth only)")
    if kind == "cloth" or str(x.get("item") or "").upper() == "THREAD":
        su = _d(s.get("supplies"))
        hosp = int(_d(su.get("hospital")).get("thread") or 0)
        th = _d(su.get("thread_kinds"))
        if hosp > 0 and th and not any(int(v or 0) for v in th.values()):
            bits.append(f"the fort's {hosp} thread all lie in the hospital's chests (DF won't weave them)")
    return "; ".join(bits)


def _mood_player_orders(s: dict, blockers: list) -> str:
    """(0.105.99) The player's (or DFHack's) work orders that take the
    material a mood lacks, by DF's job name ('' when none): the bridge's
    `mat_cats` (B, 24 Nov: MakePants and MakeArmor orders not the AI's while
    Edzul waited on plant cloth). The AI cancels only its own orders."""
    want = set()
    for x in blockers:
        k = mood_kind(x)
        if k == "cloth":
            fib = set(mood_want(x)["fibres"])          # (0.105.112 item3)
            want |= {"cloth"} if "plant" in fib or not fib & {"silk", "yarn"} else set()
            want |= {f for f in ("silk", "yarn") if f in fib}
        elif k == "leather":
            want.add("leather")
    if not want:
        return ""
    jobs = {}
    for o in _l(s.get("orders")):
        if isinstance(o, dict) and not o.get("by_ai") and set(str(c) for c in _l(o.get("mat_cats"))) & want:
            j = str(o.get("job") or o.get("recipe") or "order")
            jobs[j] = jobs.get(j, 0) + 1
    return ", ".join(f"{n} {j}" for j, n in sorted(jobs.items()))


def _mood_trade_words(s: dict, name: str, kinds: list) -> str:
    """(R1 g6) Plainly, whether what a mood lacks can still be had: bought
    from a caravan on the map now, asked of the next one, or no way at all
    (R-CE: 9 dwarves went insane wanting silk, the notes promising a purchase
    no caravan was there to make)."""
    tr = _d(s.get("trade"))
    traded = [k for k in kinds if MOOD_TRADE_KEYS.get(k) or k == "bar"]
    if not traded:
        return (f"There is no way to get it here (no caravan sells it either): {name} will most likely go insane "
                "unless it turns up")
    if not tr.get("depot"):
        return (f"The fort has no trade depot, so no caravan can sell it either: there is no way to get it, and "
                f"{name} will most likely go insane")
    if any(isinstance(c, dict) for c in _l(tr.get("caravans"))):
        return "A caravan is on the map: it is first on the AI's list to buy from it"
    return (f"No caravan is on the map, so there is no way to get it now: it is first on the next caravan's list "
            f"(bought {TRADE_IF}), and {name} goes insane if none comes in time")


def mood_trade_wants(s: dict) -> list[dict]:
    """(0.105.24) What the moods wait for and the fort doesn't have within
    reach, as caravan wants (first on the list: a life hangs on it)."""
    out, seen = [], set()
    for m in _l(_d(s.get("moods")).get("list")):
        if not isinstance(m, dict) or not m.get("craft") or not m.get("workshop"):
            continue
        for x in _l(m.get("missing")):
            if not isinstance(x, dict) or mood_on_hand(x) is not False:
                continue
            av = _d(x.get("avail"))
            if int(av.get("forbidden_reach") or 0) or int(av.get("job") or 0):
                continue
            key = MOOD_TRADE_KEYS.get(mood_kind(x))
            # (R1 g6) cloth and thread of the fibre asked (a silk mood was "sold"
            # the cheapest cloth: plant): CLOTH:SILK, THREAD:YARN... (lua/ai-trade.lua)
            w = mood_want(x)                    # (0.105.112 item3) the one reading of the want
            fibre = list(w["fibres"])
            if w["what"] == "cloth" and len(fibre) == 1:
                key = "CLOTH:" + fibre[0].upper()
            elif w["what"] == "thread":
                key = "THREAD" + (":" + fibre[0].upper() if len(fibre) == 1 else "")
            if not key and mood_kind(x) == "bar" and x.get("material") and str(x["material"]).lower() != "rock":
                key = "BAR:" + str(x["material"]).upper().replace(" ", "_")
            if key and key not in seen:
                seen.add(key)
                out.append({"key": key, "count": max(1, min(10, int(x.get("quantity") or 1)))})
    return out


MOOD_JOURNAL_KEYS = ("free", "reach", "forbidden", "forbidden_reach", "dump", "job", "other", "held",
                     "trader", "hospital", "partial")      # (0.105.99) the last three apart


def mood_journal(s: dict, memory) -> list[dict]:
    """(0.105.30) Each crafting mood's requests and what the fort holds for
    them, once a game day, compactly, for the journal (D, 8 Nov: a mood
    failed with no line from the AI, and nothing showed why). Marks the day
    in memory.mood_logged."""
    out = []
    today = abs_tick(s) // TICKS_PER_DAY
    logged = _d(getattr(memory, "mood_logged", None)) if memory is not None else {}
    for m in _l(_d(s.get("moods")).get("list")):
        if not isinstance(m, dict) or not m.get("craft"):
            continue
        uid = str(m.get("unit_id"))
        if logged.get(uid) == today:
            continue
        prog0 = _d(_d(getattr(memory, "mood_progress", None)).get(uid))
        stalled_long = (isinstance(prog0.get("since"), int)
                        and (abs_tick(s) - prog0["since"]) // TICKS_PER_DAY >= PLANNER_CONFIG.get("mood_stall_days", 7))
        reqs = []
        for x in _l(m.get("missing")):
            if not isinstance(x, dict):
                continue
            r = {"what": mood_item_text(x), "on_hand": mood_on_hand(x)}
            av = x.get("avail")
            if isinstance(av, dict):
                r["avail"] = {k: int(av[k]) for k in MOOD_JOURNAL_KEYS if isinstance(av.get(k), int) and av[k]}
                if av.get("capped"):
                    r["avail"]["capped"] = True
            if stalled_long:
                # (0.105.47, J1) after the stall: DF's flags and where the counted items lie (I7a 7)
                r["flags"] = [str(f) for f in _l(x.get("flags"))][:12]
                spots = [sp for sp in _l(_d(av).get("spots")) if isinstance(sp, dict)]
                if spots:
                    r["spots"] = spots[:3]
            reqs.append(r)
        seen = _d(getattr(memory, "moods_seen", None)).get(uid)
        prog = _d(_d(getattr(memory, "mood_progress", None)).get(uid))
        e = {"unit_id": m.get("unit_id"), "name": m.get("name"), "mood": m.get("mood"),
             "skill": m.get("skill"), "workshop": m.get("workshop"),
             "have": m.get("items_have"), "needed": m.get("items_needed"), "requests": reqs}
        if isinstance(seen, int):
            e["day"] = (abs_tick(s) - seen) // TICKS_PER_DAY
        if isinstance(prog.get("since"), int):
            e["stalled"] = (abs_tick(s) - prog["since"]) // TICKS_PER_DAY
        # (0.105.99) DF's thirst counter: the digest can say "dying of thirst in a mood"
        th = m.get("thirst")
        if isinstance(th, int) and not isinstance(th, bool):
            e["thirst"] = th
            if th >= int(PLANNER_CONFIG.get("mood_thirst_urgent", MOOD_THIRST_URGENT)):
                e["thirsty"] = True
        out.append(e)
        logged[uid] = today
    if memory is not None:
        memory.mood_logged = logged
    return out


# --- (0.105.31) the mood reserves ------------------------------------------------
#
# F (the Garden fort), 8 Nov: two dwarves died after failed strange moods, the
# latest a weaver wanting 3 plant cloth while the fort had 2, no plant thread
# and no fibre crop on any plot. A mood lasts about 40 days, too short to
# grow fibre from scratch, so the fort keeps a few of each common mood
# material on hand: made by the existing recipes (a fibre crop on a plot, its
# plants processed for thread before the still takes them, the thread woven;
# a hide tanned; a gem cut; blocks), and the AI's other orders that would use
# one up (the ones mood_blocked holds for a waiting mood) wait while the
# fort is at or under its reserve. Never a slaughter for a reserve.
# (0.105.51) R3, 15 Nov, 14 deaths after failed moods (silk 6, yarn 3,
# leather 3, a bone 1, green glass 1; a workshop of the wrong kind 1): silk
# and yarn kept apart, raw green glass and bars made by the mood's own
# routes, and one spare animal to the butcher when the leather is short and
# no hide is at hand (the slaughter rule's own guards); the mood workshops
# kept standing (_mood_shops_step).

# reserve -> (config key, words, the AI's orders that use it up)
MOOD_RESERVES = {
    "plant_cloth": ("reserve_plant_cloth", "plant cloth", MOOD_CLOTH_BLOCKS["plant"]),
    # (0.105.51) silk and yarn apart: a mood asks one kind (R3: a yarn-met
    # "silk or yarn" reserve while the silk moods died)
    "silk_cloth": ("reserve_silk_cloth", "silk cloth", MOOD_CLOTH_BLOCKS["silk"]),
    "yarn_cloth": ("reserve_yarn_cloth", "yarn cloth", MOOD_CLOTH_BLOCKS["yarn"]),
    "leather": ("reserve_leather", "leather", MOOD_BLOCKS["leather"]),
    "bones": ("reserve_bones", "bones", MOOD_BLOCKS["bone"]),
    "rough_gems": ("reserve_rough_gems", "rough gems", MOOD_BLOCKS["rough"]),
    "cut_gems": ("reserve_cut_gems", "cut gems", MOOD_BLOCKS["cut_gem"]),
    "bars": ("reserve_bars", "metal bars", MOOD_BLOCKS["bar"]),
    "blocks": ("reserve_blocks", "blocks", ()),
    "logs": ("reserve_logs", "logs", ()),
    "green_glass": ("reserve_green_glass", "raw green glass", ("glass_crafts", "glass_blocks", "glass_window")),
}


def _int_or_none(v):
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def mood_reserve_counts(s: dict) -> dict:
    """What the fort holds of each reserve's material (None: not reported)."""
    su, st, nd = _d(s.get("supplies")), _d(s.get("stocks")), _d(s.get("needs"))
    ck = su.get("cloth_kinds")
    ck = ck if isinstance(ck, dict) else None
    return {
        "plant_cloth": _int_or_none(ck.get("plant")) if ck else None,
        "silk_cloth": _int_or_none(ck.get("silk")) if ck else None,
        "yarn_cloth": _int_or_none(ck.get("yarn")) if ck else None,
        "leather": _int_or_none(st.get("leather")),
        "bones": _int_or_none(nd.get("bones")),
        "rough_gems": _int_or_none(st.get("rough_gems")),
        "cut_gems": _int_or_none(st.get("cut_gems")),
        "bars": _int_or_none(st.get("metal_bars")),
        "blocks": _int_or_none(st.get("blocks")),
        "logs": _int_or_none(st.get("wood")),
        "green_glass": _int_or_none(su.get("green_glass")),      # (0.105.51) an older bridge: None
    }


# (0.105.31 reserve fixes) the reserve rule tops a reserve up when the fort
# is AT or under it, to RESERVE_BATCH over it: select() holds the other
# orders at or under the line and caps them at what lies over it, so an
# order waits only while nothing can be made (no hides, thread, plants)
RESERVE_BATCH = 2


def reserve_room(s: dict, cfg: dict) -> dict:
    """(0.105.31 reserve fixes) {recipe: (room, words)}: how many of a
    reserve's material lie over its line (0 or less: the order is held, else
    its amount is capped at it). Reserves turned off or not reported: absent."""
    out = {}
    counts = mood_reserve_counts(s)
    for k, (key, words, recipes) in MOOD_RESERVES.items():
        want, have = int(cfg.get(key) or 0), counts.get(k)
        if want > 0 and have is not None:
            for r in recipes:
                if r not in out or have - want < out[r][0]:
                    out[r] = (have - want, f"the {have} {words} kept for strange moods (a reserve of {want})")
    return out


def _fibre_seeds(s: dict) -> list:
    """The fibre crops the fort has seeds of (names), and whether one grows now."""
    crops = _d(_d(s.get("farms")).get("crops"))
    return [str(_d(c).get("name") or k) for k, c in sorted(crops.items())
            if _d(c).get("thread") and int(_d(c).get("seeds") or 0) > 0]


def _fibre_planted(s: dict) -> bool:
    crops = _d(_d(s.get("farms")).get("crops"))
    return any(_d(c).get("thread") and int(_d(c).get("planted") or 0) > 0 for c in crops.values())


def _plant_cloth_route(s: dict) -> str:
    """How plant cloth comes now: 'thread', 'plants', 'crop' (planted),
    'seeds' (fibre seeds, none planted), or 'none'."""
    su = _d(s.get("supplies"))
    if int(_d(su.get("thread_kinds")).get("plant") or 0) > 0:
        return "thread"
    if int(su.get("thread_plants") or 0) > 0:
        return "plants"
    if _fibre_planted(s):
        return "crop"
    if _fibre_seeds(s):
        return "seeds"
    return "none"


def reserve_words(s: dict, cfg: dict, x: dict) -> str:
    """(0.105.31) For a mood's Needs you: the reserve of what it asks and
    what is being done about it ('' when no reserve is kept of it)."""
    kind = mood_kind(x)
    flags = set(mood_want(x)["fibres"])   # (0.105.112 item3) the fibres as every mood rule reads them
    counts = mood_reserve_counts(s)
    if kind == "cloth" and ("plant" in flags or not flags & {"silk", "yarn"}):
        want, have = int(cfg.get("reserve_plant_cloth") or 0), counts["plant_cloth"]
        if not want:
            return ""
        av = _d(x.get("avail"))
        seen = sum(int(av.get(k) or 0) for k in ("free", "forbidden", "dump", "job", "other", "held"))
        bits = [f"the fort's reserve of plant cloth for moods is {have if have is not None else '?'} of {want}"]
        if have and isinstance(x.get("avail"), dict) and seen == 0:
            bits.append(f"(the {have} counted may be newer than the mood's count, or not fit for it)")
        route = _plant_cloth_route(s)
        bits.append({"thread": "plant thread at hand is woven",
                     "plants": "the fibre plants in store are processed for thread before the still brews them",
                     "crop": "a fibre crop grows on the farms (too slow for this mood)",
                     "seeds": f"a fibre crop ({', '.join(_fibre_seeds(s))}) is set on the farms "
                              "(too slow for this mood)",
                     "none": "no fibre crop, seed or plant here: plant cloth and seeds are asked of the caravans"}[route])
        return "; ".join(bits)
    key = {"leather": "leather", "bone": "bones", "rough": "rough_gems", "cut_gem": "cut_gems",
           "bar": "bars", "block": "blocks", "log": "logs", "glass_rough": "green_glass"}.get(kind)
    if kind == "cloth":
        key = "silk_cloth" if "silk" in flags else "yarn_cloth" if "yarn" in flags else None
    if key:
        ckey, words, _ = MOOD_RESERVES[key]
        want, have = int(cfg.get(ckey) or 0), counts.get(key)
        if want and have is not None and have < want:
            return f"the fort's reserve of {words} for moods is {have} of {want}"
    return ""


def reserve_trade_wants(s: dict, cfg: dict) -> list[dict]:
    """(0.105.31) A plant-cloth reserve the fort can't make (no fibre crop,
    seed or plant): plant cloth and seeds on the caravans' list.
    (0.105.51) and a silk or yarn cloth reserve short with no way to make it
    here (no webs a weaver reaches; no animal to shear): cloth asked of the
    caravans too (R3: silk 0 all run in every fort, webs out of reach)."""
    out = []
    counts = mood_reserve_counts(s)
    want, have = int(cfg.get("reserve_plant_cloth") or 0), counts["plant_cloth"]
    if want and have is not None and have < want and _plant_cloth_route(s) == "none":
        out += [{"key": "CLOTH", "count": want - have}, {"key": "SEEDS", "count": 5}]
    # (R1 g6) each fibre asked by its own key (CLOTH:SILK, CLOTH:YARN): a
    # silk reserve met by the merchants' cheapest cloth was no silk
    for k, made, key in (("silk_cloth", _silk_made_here(s, cfg), "CLOTH:SILK"),
                         ("yarn_cloth", _yarn_made_here(s, cfg), "CLOTH:YARN")):
        w, h = int(cfg.get(MOOD_RESERVES[k][0]) or 0), counts.get(k)
        if w and h is not None and h < w and not made:
            out.append({"key": key, "count": w - h})
    return out


def _silk_made_here(s: dict, cfg: dict) -> bool:
    """(0.105.51) Silk cloth can come here: silk thread DF will weave, or webs a weaver reaches."""
    return bool(int(usable_thread(s, cfg).get("silk") or 0) > 0 or silk_route(s, cfg))


def _yarn_made_here(s: dict, cfg: dict) -> bool:
    """(0.105.51) Yarn cloth can come here: yarn thread DF will weave, or an animal to shear and spin."""
    return bool(int(usable_thread(s, cfg).get("yarn") or 0) > 0 or wool_route(s))


def _noted_key(s: dict, what: str) -> str:
    """(0.105.33) memory.reserve_noted's value for a note: the note and the
    season, so each is said again each season (one string shared by two notes
    said each only once in a fort's life)."""
    return f"{what}:{_season_index(s)}"


# (item1) B, 24 Nov: process_plants ordered 14 times in 2 hours, the thread
# never seen (thread_kinds.plant 0): each order's thread hauled straight to
# the hospital's chests (DF keeps thread there for sutures). Processing is
# ordered only below the line (not topped up at it), and after
# PROCESS_FRUITLESS orders in a row that raised neither the free plant thread
# nor the plant cloth, it waits PROCESS_PAUSE_DAYS.
PROCESS_FRUITLESS = 3
PROCESS_PAUSE_DAYS = 28


def _plant_counts(s: dict) -> list:
    su = _d(s.get("supplies"))
    return [int(_d(su.get("thread_kinds")).get("plant") or 0), int(_d(su.get("cloth_kinds")).get("plant") or 0)]


def _process_ok(s: dict, memory, cfg: dict, head: str, notes: list) -> bool:
    """(item1) process_plants may be ordered now: not paused, and the last
    orders (each judged when the next is due) raised the thread or cloth."""
    if memory is None:
        return True
    rp = memory.reserve_process
    now = abs_tick(s)
    until = rp.get("paused_until")
    if isinstance(until, int):
        if now < until:
            return False
        rp.pop("paused_until", None)
        rp["fruitless"] = 0
        rp.pop("last", None)
    last, cur = rp.get("last"), _plant_counts(s)
    if isinstance(last, list) and len(last) == 2:
        rp["fruitless"] = 0 if (cur[0] > last[0] or cur[1] > last[1]) else int(rp.get("fruitless") or 0) + 1
        rp["last"] = cur              # judged once: a second look this cycle compares like with like
    if int(rp.get("fruitless") or 0) >= int(cfg.get("reserve_process_fruitless", PROCESS_FRUITLESS)):
        days = int(cfg.get("reserve_process_pause_days", PROCESS_PAUSE_DAYS))
        rp["paused_until"] = now + days * TICKS_PER_DAY
        h = _d(_d(s.get("supplies")).get("hospital"))
        hk = _d(h.get("thread_kinds"))
        hosp = int((hk.get("plant") if "plant" in hk else h.get("thread")) or 0)
        where = (f"the hospital's chests hold {hosp} plant thread" if hosp > 0 else "none of it is seen free")
        notes.append(f"{head}: {rp['fruitless']} orders to process fibre plants in a row brought no free plant "
                     f"thread or cloth ({where}: DF hauls new thread to the hospital's stock for sutures), so "
                     f"no fibre plants are processed for {days} days")
        return False
    return True


def _process_placed(s: dict, memory) -> None:
    """(item1) a process_plants order placed: the counts it is judged against."""
    if memory is not None:
        memory.reserve_process["last"] = _plant_counts(s)


def _mood_reserve_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """(0.105.31) Keep a few of each common mood material (MOOD_RESERVES):
    one step a cycle, plant cloth first (the commonest failed request)."""
    if young_fort(s, cfg):
        return
    counts = mood_reserve_counts(s)
    su, b = _d(s.get("supplies")), _d(s.get("buildings"))
    FOR = "kept for strange moods, which can't wait for it to be grown or made"

    def gap(k):
        # (0.105.31 reserve fixes) at the line too, up to a batch over it:
        # the other orders wait at the line, so stopping there held them for good
        key = MOOD_RESERVES[k][0]
        want, have = int(cfg.get(key) or 0), counts.get(k)
        return (want + RESERVE_BATCH - have if want > 0 and have is not None and have <= want else 0), have, want

    def order(recipe, n, why, material=None):
        if queued(s, {recipe}):
            return False
        a = {"type": "work_order", "recipe": recipe, "amount": max(1, int(n))}
        if material:
            a["material"] = material
        proposals.append(Proposal("mood_reserve", a, why, 5, True))
        return True

    n, have, want = gap("plant_cloth")
    if n:
        head = f"{have} plant cloth, a reserve of {want} {FOR}"
        thread = _d(su.get("thread_kinds"))
        route = _plant_cloth_route(s)
        if route == "thread" and _has_shop(b, "Loom"):
            if order("weave_plant_cloth", min(n, int(thread.get("plant") or 0)), f"{head}: weave plant cloth"):
                return
        elif route == "plants" and _has_shop(b, "Farmers"):
            # (0.105.31 reserve fixes) never the drink's plants: not while drink
            # is urgent, nor when the brewable plants left (less the brew
            # orders' jobs) would fall to the drink line (a plant for each dwarf)
            keep_ok, why_not = _plants_spare(s, cfg, n)
            if not keep_ok:
                if memory is not None and getattr(memory, "reserve_noted", "") != _noted_key(s, "plant_cloth_drink"):
                    memory.reserve_noted = _noted_key(s, "plant_cloth_drink")
                    notes.append(f"{head}: the fibre plants aren't processed for thread while {why_not}")
            elif (have < want and not queued(s, {"process_plants"})          # (item1) judged when the last is done
                  and _process_ok(s, memory, cfg, head, notes) and order(
                    "process_plants", n, f"{head}: process the fibre plants for thread before the still brews them")):
                _process_placed(s, memory)
                return
        elif route == "seeds" and _swap_off(s, memory):
            pass        # (0.105.31 reserve fixes) no fibre crop grows on the plots this season
        elif route == "seeds" and planner_farms.drink_known_short(s, cfg):
            # (0.105.31 reserve fixes) no brewable plot goes to fibre while drink is short
            if memory is not None and getattr(memory, "reserve_noted", "") != _noted_key(s, "plant_cloth_drink"):
                memory.reserve_noted = _noted_key(s, "plant_cloth_drink")
                notes.append(f"{head}: no plot goes to a fibre crop while drink is short")
        elif route == "seeds" and farm_plots_any(s) and memory is not None and not memory.farm_crops_player:
            proposals.append(Proposal("mood_reserve", {"type": "set_farm_crops", "thread": True,
                                                       "drink": False},
                                      f"{head}, and no plot grows a fibre crop: one plot grows "
                                      f"{', '.join(_fibre_seeds(s))} (its plants processed for thread)", 5))
            return
        elif route == "none" and memory is not None and getattr(memory, "reserve_noted", "") != _noted_key(s, "plant_cloth"):
            memory.reserve_noted = _noted_key(s, "plant_cloth")
            notes.append(f"{head}: no fibre crop, seed or plant here, so plant cloth and seeds are on the "
                         "caravans' list")
    # (0.105.51) silk and yarn each kept (R3: 6 of the 14 deaths wanted silk, 3 yarn)
    n, have, want = gap("silk_cloth")
    if n:
        head = f"{have} silk cloth, a reserve of {want} {FOR}"
        thread = usable_thread(s, cfg)           # (0.105.47, J1) thread DF will weave
        if int(thread.get("silk") or 0) > 0 and _has_shop(b, "Loom") and not dead_order(s, "weave_silk_cloth", cfg):
            if order("weave_silk_cloth", min(n, int(thread.get("silk") or 0)), f"{head}: weave silk cloth"):
                return
        # (0.105.47, J1) no thread to weave: silk from the webs a weaver can reach
        # (I7a: silk cloth 0 in A all run; 20 moods died on silk, no route)
        elif silk_route(s, cfg) and not queued(s, {"weave_silk_cloth"}):
            if order("collect_webs", min(int(cfg.get("mood_webs_collect", 5)), n + 1),
                     f"{head}: collect spider webs for silk thread ({webs_reach(s)} within a weaver's reach), "
                     "then weave it"):
                return
    n, have, want = gap("yarn_cloth")
    if n:
        head = f"{have} yarn cloth, a reserve of {want} {FOR}"
        thread = usable_thread(s, cfg)
        if int(thread.get("yarn") or 0) > 0 and _has_shop(b, "Loom") and not dead_order(s, "weave_yarn_cloth", cfg):
            if order("weave_yarn_cloth", min(n, int(thread.get("yarn") or 0)), f"{head}: weave yarn cloth"):
                return
        elif (wool_route(s) and not dead_order(s, "shear_creature", cfg) and not dead_order(s, "spin_thread", cfg)
              and not queued(s, {"weave_yarn_cloth"})):
            # (0.105.51) no yarn thread: an animal shorn and its wool spun (then woven)
            sheared = order("shear_creature", 1, f"{head}: shear an animal for wool (then spun and woven)")
            spun = order("spin_thread", 1, f"{head}: spin the wool into yarn thread")
            if sheared or spun:
                return
    n, have, want = gap("leather")
    if n and raw_hides(s) > 0 and _has_shop(b, "Tanners"):
        if order("tan_hide", min(n, raw_hides(s)), f"{have} leather, a reserve of {want} {FOR}: "
                                                                 "tan a hide"):
            return
    elif n and _has_shop(b, "Tanners") and not _reserve_slaughter_recent(s, memory, cfg):
        # (0.105.51) no hide: one spare tame animal to the butcher before a mood
        # asks (R3: A's Kadôl, E's ònul and F's Zefon died wanting leather, the
        # animal for it slaughtered 10-20 days into the mood). The slaughter
        # rule's own guards: enough tame animals, a butcher's, never a fort
        # that bans it, never a pet, war or hunting animal, a child or one of
        # the last two of a kind; never while an animal waits for the butcher.
        acts: list = []
        if _mood_slaughter(s, memory, cfg, acts, "its hide tanned for leather " + FOR):
            for a, why in acts:
                proposals.append(Proposal("mood_reserve", dict(a, oldest=True),
                                          f"{have} leather, a reserve of {want}: {why}", 5))
            return
    # (R1 g6) bones: bone comes only from a carcass, so below a few the
    # ordinary slaughter rule sends one spare animal (its own guards: enough
    # tame animals, a butcher's, never a fort that bans it; never a young one,
    # a pet, a war or hunting animal, or one of the last two of a kind)
    bones, bones_min = counts.get("bones"), int(cfg.get("g6_reserve_bones_min", 2))
    if (bones is not None and bones < bones_min and _has_shop(b, "Butchers")
            and not _reserve_slaughter_recent(s, memory, cfg)):
        acts = []
        if _mood_slaughter(s, memory, cfg, acts, f"its bones {FOR}"):
            for a, why in acts:
                proposals.append(Proposal("mood_reserve", dict(a, oldest=True),
                                          f"{bones} bones, under the {bones_min} kept: {why}", 5))
            # no return: a refused slaughter (no spare animal) mustn't hold the gems and bars back
    n, have, want = gap("cut_gems")
    rough, rough_keep = counts.get("rough_gems"), int(cfg.get("reserve_rough_gems") or 0)
    rg = _d(_d(s.get("trade")).get("rough_gem"))
    # (R1 g6) at least `g6_reserve_cut_gems_min` cut gem whenever a rough gem
    # lies about, the rough gems' own reserve or not (a mood asks "1 cut gem",
    # any kind: 763 requests in the 15-16 Nov run, none of a named stone)
    cut_min = int(cfg.get("g6_reserve_cut_gems_min", 1))
    spare = (rough - rough_keep) if rough is not None else 0
    if have is not None and have < cut_min and rough:
        spare = max(spare, min(rough, cut_min - have))
    if (n and rough is not None and spare > 0 and _has_shop(b, "Jewelers")
            and str(rg.get("token", "")).startswith("INORGANIC:")):
        if order("cut_gems", min(n, spare), f"{have} cut gems, a reserve of {want} {FOR}: cut "
                                            "a rough gem" + (" (its own reserve kept)" if rough > rough_keep else ""),
                 rg["token"]):
            return
    # (0.105.51) raw green glass and metal bars, by the mood's own routes
    for key, kind, item in (("green_glass", "glass_rough", {"item": "ROUGH", "material": "green glass"}),
                            ("bars", "bar", {"item": "BAR"})):
        n, have, want = gap(key)
        if not n:
            continue
        acts, _why = _mood_make(s, dict(item, quantity=n), kind, None, cfg)
        if acts:
            for a, how in acts:
                proposals.append(Proposal("mood_reserve", a, f"{have} {MOOD_RESERVES[key][1]}, a reserve of {want} "
                                          f"{FOR}: {how}", 5, a.get("type") == "work_order"))
            return
    if _mood_shops_step(s, cfg, proposals):
        return
    n, have, want = gap("blocks")
    if n and _has_shop(b, "Masons") and int(_d(s.get("stocks")).get("boulders") or 0) > 0:
        order("stone_blocks", n, f"{have} blocks, a reserve of {want} {FOR}: make stone blocks")


RESERVE_SLAUGHTER_DAYS = 14     # (0.105.51) one animal for the leather reserve at most this often


def _reserve_slaughter_recent(s: dict, memory, cfg: dict) -> bool:
    """(0.105.51) An animal went to the butcher for the leather reserve lately
    (memory.mood_help reserve_slaughter), or one is marked for it now: its
    hide is coming, no other goes."""
    if any(int(_d(k).get("marked") or 0) > 0 for k in _l(_d(s.get("herd")).get("kinds"))):
        return True
    last = _d(getattr(memory, "mood_help", None)).get("reserve_slaughter") if memory is not None else None
    days = int(cfg.get("reserve_slaughter_days", RESERVE_SLAUGHTER_DAYS))
    return isinstance(last, int) and 0 <= abs_tick(s) - last < days * TICKS_PER_DAY


# (0.105.51) the workshops DF sends a strange mood to, kept standing where
# the fort works the craft's material but lacks the mood's shop: a mood waits
# for no level to be dug (R3: A, E and F had no Leather works when a tanner's
# or leatherworker's mood came; A's glass furnace level, begun on the mood's
# first day, was not dug in 40). Only these: the AI's other rules build the
# common shops (the basic ladder, the industries) before moods begin.
MOOD_SHOP_KINDS = {"Leatherworks": "Tanners", "Clothiers": "Loom", "GlassFurnace": "sand",
                   "Jewelers": "rough"}      # (R1 g6) a cut gem is asked by any mood (R-AD: 3 deaths)
MOOD_SHOPS_MIN_CITIZENS = 20        # DF's strange moods begin at 20 citizens


def mood_shops_missing(s: dict) -> list:
    """The mood workshop kinds the fort has none of (and none coming) while it
    works their material: a Tanner's, a Loom, sand on the map."""
    b = _d(s.get("buildings"))
    su = _d(s.get("supplies"))
    sand = bool(_l(su.get("sand_layers")) or int(su.get("sand_bags") or 0) > 0 or int(su.get("sand_zones") or 0) > 0)
    out = []
    rough = int(_d(s.get("stocks")).get("rough_gems") or 0) > 0
    for kind, source in MOOD_SHOP_KINDS.items():
        works = sand if source == "sand" else rough if source == "rough" else _has_shop(b, source)
        if works and kind in BUILDABLE_SHOPS and not _has_shop(b, kind) and not _shop_coming(s, kind):
            out.append(kind)
    return out


def _mood_shops_step(s: dict, cfg: dict, proposals: list) -> bool:
    """(0.105.51) One workshops level with every mood workshop the fort lacks
    (not urgent: the builder's ordinary turn)."""
    if int(_d(s.get("dwarves")).get("total") or 0) < MOOD_SHOPS_MIN_CITIZENS or not player_rules(s)["mood_workshops"]:
        return False
    if any(isinstance(p, dict) and p.get("kind") == "workshops" and _workshops_busy([p])
           for p in _l(_d(s.get("projects")).get("open"))):
        return False                   # a workshops level under way first
    missing = mood_shops_missing(s)
    if not missing:
        return False
    proposals.append(Proposal("mood_reserve", {"type": "start_project", "kind": "workshops", "shops": missing},
                              f"no {', '.join(missing)}: a strange mood of that craft claims only its own kind "
                              "of workshop, and fails in about 40 days, too short to dig and build one; one of "
                              "each kept standing", 5))
    return True


def _plants_spare(s: dict, cfg: dict, n: int) -> tuple[bool, str]:
    """(0.105.31 reserve fixes) May n fibre plants be processed for thread?
    Not while drink is urgent, nor when the brewable plants left after it
    (and after the open brew orders) stay no higher than the drink line,
    a brewable plant for each dwarf (drink_short's). Of the fibre plants,
    only the brewable ones count against it (the bridge's
    thread_brewable_plants; an older bridge: all of them)."""
    if planner_farms.drink_known_short(s, cfg):
        return False, "drink is short"
    su = _d(s.get("supplies"))
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    brewable = brewable_counts(s)[0]
    overlap = su.get("thread_brewable_plants")
    overlap = int(overlap) if isinstance(overlap, int) else int(su.get("thread_plants") or 0)
    left = brewable - queued(s, {"brew_drink"}) - min(n, overlap)
    if overlap > 0 and left <= citizens:
        return False, (f"the brewable plants left ({max(0, left)}) would be no more than the drink "
                       f"keeps ({citizens}, one a dwarf)")
    return True, ""


def _season_index(s: dict) -> int | None:
    d = _d(s.get("date"))
    if not isinstance(d.get("year"), int) or not isinstance(d.get("tick"), int):
        return None
    return abs_tick(s) // (TICKS_PER_YEAR // 4)


def _swap_off(s: dict, memory) -> bool:
    """(0.105.31 reserve fixes) The fibre swap changed nothing this season
    (no fibre crop the fort has seeds of grows on its plots now)."""
    if memory is None:
        return False
    i = _season_index(s)
    return i is not None and getattr(memory, "reserve_swap_off", None) == i


def note_reserve_swap(p, r: dict, state: dict, memory) -> None:
    """(0.105.31 reserve fixes) After the mood reserve's fibre swap: when the
    bridge changed nothing and says why (`thread_none`), the swap waits for
    the next season (it was asked again every 2 days)."""
    a = _d(getattr(p, "action", None))
    if getattr(p, "rule", "") != "mood_reserve" or a.get("type") != "set_farm_crops" or not a.get("thread"):
        return
    if _d(r).get("ok") is True and int(_d(r).get("changed") or 0) == 0 and _d(r).get("thread_none"):
        memory.reserve_swap_off = _season_index(state)


def farm_plots_any(s: dict) -> bool:
    return bool([p for p in _l(_d(s.get("farms")).get("plot_list")) if isinstance(p, dict) and not p.get("dead")])


# --- (item2) the hospital's thread and cloth for a waiting mood ------------------------
#
# B (24 Nov) and others: every thread in the fort lay in the hospital's chests (its
# location's supply quota), so a mood wanting cloth or thread never had it: the loom wove
# nothing and the mood can't take the hospital's (lua/ai-moods.lua counts it 'hospital').
# Edzul died of thirst in his mood, Udib went raving. While a mood waits and the hospital
# holds the fort's only cloth or thread of its kind, the bridge (lua/ai-mood-help.lua
# hospital_release) sets the hospital's thread (and cloth) quota to 0 and sets as much as
# the mood lacks out of its chests: the cloth itself, or thread for the loom (the cloth
# rules then weave it: usable_thread trusts thread set out after the weave's cancels). Once
# no mood waits on cloth or thread the quotas are put back (from the save's site data, so a
# reload doesn't leave them at 0). Patients waiting for sutures or dressings keep the
# hospital's stock from a fresh mood; an urgent one (thirsty, or stalled MOOD_URGENT_DAYS)
# still gets it.
COOLDOWN_KEYS.setdefault("mood_hospital", "mood_cooldown_ticks")     # a quarter day: each step paces itself
STEER_PROTECTED.add("mood_hospital")        # a life on it, and the quotas must come back
LIMIT_EXEMPT.add("mood_hospital")
AGENDA_THEMES.setdefault("mood_hospital", "materials for a strange mood")
HOSPITAL_FIBRES = ("silk", "yarn", "plant")


def _cloth_or_thread(x: dict) -> str | None:
    """'cloth' or 'thread' for a mood request of either, else None (mood_want's reading)."""
    w = mood_want(x)["what"]
    return w if w in ("cloth", "thread") else None


def _fibre_of(x: dict) -> str:
    """(0.105.112 item3) the fibre as the mood rule reads it (mood_want), not a reading of its own."""
    return mood_want(x)["fibre"]


def _by_fibre(counts, fibre: str) -> int:
    c = _d(counts)
    if fibre == "any":
        return sum(int(v or 0) for v in c.values() if isinstance(v, int))
    return int(c.get(fibre) or 0)


def stitch_waiting(s: dict) -> int:
    """Patients waiting for sutures or dressings now (the health report's
    stitch_wait; the patient list from an older bridge)."""
    h = _d(s.get("health"))
    v = h.get("stitch_wait")
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    return sum(1 for p in _l(h.get("patients"))
               if isinstance(p, dict) and {"suture", "dressing"} & set(_l(p.get("needs"))))


def mood_urgency(s: dict, m: dict, memory, cfg: dict) -> tuple[bool, bool, int]:
    """(urgent, thirsty, stalled days) for a mood, as _mood_rules and
    _mood_materials read them (0.105.99): thirsty past `mood_thirst_urgent`
    or stalled `mood_urgent_days`."""
    now = abs_tick(s)
    uid = str(m.get("unit_id"))
    seen = _d(getattr(memory, "moods_seen", None)).get(uid, now)
    days = (now - seen) // TICKS_PER_DAY if isinstance(seen, int) else 0
    prog = _d(_d(getattr(memory, "mood_progress", None)).get(uid))
    stalled = (now - prog["since"]) // TICKS_PER_DAY if isinstance(prog.get("since"), int) else days
    thirst = m.get("thirst")
    thirsty = (isinstance(thirst, int) and not isinstance(thirst, bool)
               and thirst >= int(cfg.get("mood_thirst_urgent", MOOD_THIRST_URGENT)))
    return thirsty or stalled >= int(cfg.get("mood_urgent_days", MOOD_URGENT_DAYS)), thirsty, stalled


def _hospital_requests(s: dict) -> list:
    """Every gathering crafting mood's cloth and thread requests: [(mood, request, 'cloth'|'thread')]."""
    out = []
    for m in _l(_d(s.get("moods")).get("list")):
        if not (isinstance(m, dict) and m.get("craft") and m.get("workshop")):
            continue
        for x in _l(m.get("missing")):
            what = _cloth_or_thread(x) if isinstance(x, dict) else None
            if what:
                out.append((m, x, what))
    return out


def _hospital_share(s: dict, x: dict, what: str, cfg: dict) -> dict | None:
    """What the hospital is to set out for one request ({cloth: n} or
    {thread: n}), None when the fort has its own or the hospital none."""
    if mood_on_hand(x) is not False:
        return None                              # on hand (or an older bridge: no count)
    av = _d(x.get("avail"))
    n = lambda k: int(av.get(k) or 0)            # noqa: E731
    q = int(x.get("quantity") or 1)
    if what == "cloth" and q >= 1000:
        q = math.ceil(q / 10000)                 # an older bridge: DF's cloth units
    lack = min(10, max(1, q)) - n("reach") - n("held") - n("forbidden_reach")   # the forbidden are freed
    if lack <= 0:
        return None
    fibre = _fibre_of(x)
    hosp = _d(_d(s.get("supplies")).get("hospital"))
    if what == "thread":
        return {"thread": min(lack, n("hospital"))} if n("hospital") > 0 else None
    if n("hospital") > 0:
        return {"cloth": min(lack, n("hospital"))}
    # (0.105.113 item13) whole thread only: the loom weaves no part-used thread (a suture's
    # leftover, the bridge's thread_short; B: the hospital's thread 97% of a whole one)
    free = max(0, _by_fibre(usable_thread(s, cfg), fibre)
               - _by_fibre(_d(_d(s.get("supplies")).get("thread_short")), fibre))
    if free >= lack:
        return None                              # the fort's own thread: the loom weaves it
    kinds = hosp.get("thread_kinds")
    held = _by_fibre(kinds, fibre) if isinstance(kinds, dict) else int(hosp.get("thread") or 0)
    held = max(0, held - _by_fibre(hosp.get("thread_short"), fibre))
    if held <= 0 or not _has_shop(_d(s.get("buildings")), "Loom"):
        return None                              # (no loom: the mood rule builds one first)
    return {"thread": min(lack - free, held)}


def mood_hospital_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """(item2) A waiting mood's cloth or thread out of the hospital's stock,
    the hospital's quotas at 0 meanwhile; put back once no mood waits."""
    hold = _d(_d(s.get("mood_help")).get("hospital_hold"))
    reqs = _hospital_requests(s)
    if not reqs:
        if int(hold.get("locations") or 0) > 0:
            proposals.append(Proposal("mood_hospital", {"type": "hospital_release", "restore": True},
                                      "no strange mood waits on cloth or thread now: the hospital's thread and "
                                      "cloth quotas the AI set to 0 for one are put back as they were", 2))
        return
    if not _d(_d(s.get("locations")).get("count")).get("HOSPITAL") and not hold:
        return
    stitch = stitch_waiting(s)
    found = []
    from planner_mood_help import hospital_none_skip
    for m, x, what in reqs:
        share = _hospital_share(s, x, what, cfg)
        if share and hospital_none_skip(s, memory, "thread" if "thread" in share else "cloth", _fibre_of(x)):
            # (0.105.112 item3) the hospital answered "nothing of that kind" for these very
            # counts (B, Sigun: its yarn thread all part-used, asked four times in 9 minutes)
            share = None
        if share:
            urgent, thirsty, stalled = mood_urgency(s, m, memory, cfg)
            found.append((not urgent, m, x, what, share, urgent, thirsty, stalled))
    found.sort(key=lambda f: f[0])               # the urgent first
    for _, m, x, what, share, urgent, thirsty, stalled in found:
        name, mood = m.get("name") or "a dwarf", str(m.get("mood") or "strange").lower()
        fibre = _fibre_of(x)
        give = "thread" if "thread" in share else "cloth"
        n = share[give]
        why = (f"{name}'s {mood} mood waits for {mood_item_text(x)} and the hospital holds the fort's only "
               f"{'' if fibre == 'any' else fibre + ' '}{give} the mood can use")
        if stitch and not urgent:
            notes.append(f"{why}, but {stitch} patient(s) wait for sutures or dressings: the hospital keeps it "
                         f"while the mood is fresh (it is set out if the dwarf grows thirsty or the mood stalls "
                         f"{int(cfg.get('mood_urgent_days', MOOD_URGENT_DAYS))} days)")
            continue
        a = {"type": "hospital_release", give: n, "kind": fibre}
        if give == "thread" and what == "thread" and mood_want(x)["part_ok"]:
            a["part_ok"] = True       # (0.105.112 item3) a thread mood takes a 90%-full thread; the loom doesn't
        proposals.append(Proposal(
            "mood_hospital", a,
            f"{why}: {n} {give} set out of its chests for it"
            + (" (the loom weaves it)" if what == "cloth" and give == "thread" else "")
            + f", and the hospital's thread{' and cloth' if give == 'cloth' else ''} quota set to 0 while it waits "
              "(put back after)"
            + (f"; {stitch} patient(s) wait for sutures or dressings, but the mood is urgent ("
               + ("the dwarf is thirsty" if thirsty else f"stalled {stalled} days") + ")" if stitch else ""),
            0 if urgent else 1))
        return                                   # one a cycle: the next mood after the cooldown

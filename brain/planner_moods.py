"""planner_moods: strange moods (split out of planner_society in 0.105.25,
13c): the workshop a mood needs, then its materials: what lies free is left
to the dwarf, forbidden items freed, the AI's own orders that would use the
last of it cancelled, the rest made (or an animal butchered), what can't be
made named in Needs you and put on the caravans' list. planner_society
re-exports every name here."""

from __future__ import annotations

import math
from quirks import has_rule
from digest import _d, _l
from planner_core import *  # noqa: F401,F403

__all__ = ["MOOD_WORKSHOPS", "_mood_rules", "mood_item_text", "MOOD_CONSUMERS", "MOOD_TRADE_KEYS", "_mood_make", "_mood_slaughter", "_mood_materials", "mood_trade_wants", "MOOD_BLOCKS", "mood_blocked"]


# A crafting mood's skill -> the workshop (or furnace) the dwarf must claim.
MOOD_WORKSHOPS = {
    "WOODCRAFT": "Craftsdwarfs", "STONECRAFT": "Craftsdwarfs", "BONECARVE": "Craftsdwarfs",
    "CARPENTRY": "Carpenters", "MASONRY": "Masons", "CUTGEM": "Jewelers", "ENCRUSTGEM": "Jewelers",
    "FORGE_WEAPON": "MetalsmithsForge", "FORGE_ARMOR": "MetalsmithsForge",
    "FORGE_FURNITURE": "MetalsmithsForge", "METALCRAFT": "MetalsmithsForge",
    "CLOTHESMAKING": "Clothiers", "WEAVING": "Loom", "LEATHERWORK": "Leatherworks",
    "TANNER": "Tanners", "GLASSMAKER": "GlassFurnace", "BOWYER": "Bowyers", "MECHANICS": "Mechanics",
}


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
            if missing and (counted or days >= cfg["mood_wait_days"]):
                _mood_materials(s, name, mood, missing, days, proposals, notes, cfg, memory=memory,
                                unit_id=m.get("unit_id"))
            elif isinstance(have, int) and isinstance(want, int) and have < want and days >= 3:
                notes.append(f"{name}'s {mood.lower()} mood: gathering materials ({have}/{want}) for "
                             f"{days} days; if it stalls, DFHack's showmood says what's missing")
            continue
        if need and not _has_shop(b, need):
            building = _workshops_busy([p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)])
            if building:
                notes.append(f"{name} is in a {mood.lower()} mood and needs a {need}; a workshops level "
                             "is already being built")
            elif need in BUILDABLE_SHOPS:
                proposals.append(Proposal(
                    "mood", {"type": "start_project", "kind": "workshops", "shops": [need], "urgent": True},
                    f"{name} is in a {mood.lower()} mood and needs a {need} workshop, which the fort "
                    "doesn't have; without one they go insane", 1))
            else:
                ask_player(notes, f"{name} is in a {mood.lower()} mood and needs a {need}, which the fort "
                             "doesn't have and the AI can't build: build one, or they go insane")
        elif days >= cfg["mood_claim_days"]:
            ask_player(notes, f"{name} has been in a {mood.lower()} mood for {days} days without claiming a "
                         f"workshop{' (' + need + ')' if need else ''}: is one free and reachable?")


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


# (0.105.24) the AI's own orders that use up what a mood waits for: cancelled
# while the mood finds none free and another job holds it (cancelling an
# order drops its jobs nobody works, and their items with them)
MOOD_CONSUMERS = {"rough": ("cut_gems",), "cut_gem": ("encrust_goods",), "bone": ("bone_crafts",),
                  "cloth": ("cloth_bag", "yarn_bag", "silk_bag", "cloth_socks", "cloth_shoes"),
                  "leather": ("leather_shoes", "leather_low_boots", "leather_quiver"),
                  "bar": ("metal_crafts", "metal_amulet", "metal_bracelet", "metal_ring", "metal_earring")}


# (0.105.26) the AI's other work orders that would use up what a waiting mood
# needs, held in select() while it waits (the bag, quiver, shoe, jewellery,
# crafts and cloth rules re-ordered what a mood had just cancelled); cloth and
# thread by the kind of thread a request names (none named: every kind)
MOOD_BLOCKS = {"rough": ("cut_gems",), "cut_gem": ("encrust_goods",), "bone": ("bone_crafts",),
               "leather": ("leather_shoes", "leather_low_boots", "leather_quiver"),
               "bar": ("metal_crafts", "metal_amulet", "metal_bracelet", "metal_ring", "metal_earring")}
MOOD_CLOTH_BLOCKS = {"plant": ("cloth_bag", "cloth_socks", "cloth_shoes"), "silk": ("silk_bag",),
                     "yarn": ("yarn_bag",)}
MOOD_THREAD_BLOCKS = {"plant": ("weave_plant_cloth",), "silk": ("weave_silk_cloth",),
                      "yarn": ("weave_yarn_cloth",)}


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
            flags = set(str(f) for f in _l(x.get("flags")))
            item = str(x.get("item") or "").upper()
            if kind == "cloth" or item == "THREAD":
                table = MOOD_CLOTH_BLOCKS if kind == "cloth" else MOOD_THREAD_BLOCKS
                kinds = [k for k in table if k in flags] or list(table)
                found = [r for k in kinds for r in table[k]]
            else:
                found = list(MOOD_BLOCKS.get(kind, ()))
            for r in found:
                recipes.setdefault(r, what)
            mat = str(x.get("material") or "").upper().replace(" ", "_")
            if kind == "bar" and mat and mat != "ROCK":
                mats.setdefault(mat if ":" in mat else "INORGANIC:" + mat, what)
    return recipes, mats


# what a caravan is asked for, for a mood the fort can't supply (lua/ai-trade.lua's categories)
MOOD_TRADE_KEYS = {"cloth": "CLOTH", "leather": "SKIN_TANNED", "log": "WOOD", "rough": "ROUGH",
                   "cut_gem": "SMALLGEM"}


def _mood_make(s: dict, x: dict, kind: str, memory, cfg: dict) -> tuple[list, str | None]:
    """(0.105.24) How the fort makes what a mood request asks for: a list of
    (action, why) to propose (empty when nothing is to be done now), and,
    when it can't be made here, the reason in words."""
    st, su = _d(s.get("stocks")), _d(s.get("supplies"))
    b = _d(s.get("buildings"))
    q = int(x.get("quantity") or 1)
    if kind == "cloth" and q >= 1000:
        q = math.ceil(q / 10000)              # an older bridge: DF's cloth units
    q = max(1, min(10, q))
    flags = set(_l(x.get("flags")))
    acts: list = []

    def order(recipe, amount, why, material=None):
        if queued(s, {recipe}):
            return True                    # already on order: wait for it
        a = {"type": "work_order", "recipe": recipe, "amount": max(1, int(amount))}
        if material:
            a["material"] = material
        acts.append((a, why))
        return True

    if kind == "cloth":
        thread = _d(su.get("thread_kinds"))
        kinds = [k for k in ("silk", "yarn", "plant") if k in flags] or \
            sorted(("plant", "yarn", "silk"), key=lambda k: -int(thread.get(k) or 0))
        if not _has_shop(b, "Loom"):
            return acts, "no loom to weave it at"
        for k in kinds:
            # an older bridge (no thread by kind): plant thread where plants give
            # it or no wool comes in (0.104.36: a plant-cloth order where the
            # thread is all wool only cancels at the loom)
            old_plant = (not thread and k == "plant" and int(st.get("thread") or 0) > 0
                         and (thread_plants_here(s) or not wool_route(s)))
            if int(thread.get(k) or 0) > 0 or old_plant:
                order(f"weave_{k}_cloth", q, f"weave {k} cloth")
                return acts, None
        k = kinds[0]
        if k == "plant" and thread_plants_here(s) and _has_shop(b, "Farmers"):
            order("process_plants", 3, "process plants for thread (then weave it)")
            return acts, None
        if k == "yarn" and wool_route(s):
            order("shear_creature", 1, "shear an animal for wool (then spin and weave it)")
            order("spin_thread", 1, "spin the wool into yarn")
            return acts, None
        return acts, (f"no {k} thread to weave" + (" (silk comes from webs or caravans)" if k == "silk" else
                                                  " (no sheep, llama or alpaca to shear)" if k == "yarn" else ""))
    if kind == "leather":
        if int(su.get("hides") or 0) > 0 and _has_shop(b, "Tanners"):
            order("tan_hide", q, "tan a hide")
            return acts, None
        why = "no hide to tan" + ("" if _has_shop(b, "Tanners") else " and no tanner's")
        if _mood_slaughter(s, memory, cfg, acts, "its hide tanned for leather"):
            return acts, None
        return acts, why
    if kind in ("bone", "shell"):
        if kind == "shell":
            return acts, "no shell (shells come from turtles and shellfish: fishing, or a caravan's)"
        if _mood_slaughter(s, memory, cfg, acts, "its bones for the mood"):
            return acts, None
        return acts, "no bone and no spare tame animal to butcher"
    if kind == "bar":
        furnaces = _d(b.get("furnaces"))
        magma = bool(furnaces.get("MagmaSmelter"))
        if not (furnaces.get("Smelter") or magma):
            return acts, "no smelter"
        if not magma and int(su.get("fuel") or 0) <= 0:
            return acts, "no fuel for the smelter"
        metal = str(x.get("material") or "").upper().replace(" ", "_")
        if metal == "ROCK":
            metal = ""
        by_ore = {k: v for k, v in _d(_d(s.get("industry")).get("ore_stock_by")).items()
                  if isinstance(v, dict) and int(v.get("n") or 0) > 0
                  and (not metal or metal in [str(m).upper() for m in _l(v.get("metals"))])}
        if not by_ore:
            return acts, f"no {metal.lower() + ' ' if metal else ''}ore to smelt"
        ore = max(sorted(by_ore), key=lambda k: int(by_ore[k].get("n") or 0))
        order("smelt_ore", q, f"smelt {ore.lower()} ore", f"INORGANIC:{ore}")
        return acts, None
    if kind == "glass_rough":
        furnaces = _d(b.get("furnaces"))
        if not (_has_shop(b, "GlassFurnace") or furnaces.get("MagmaGlassFurnace")):
            return acts, "no glass furnace"
        if int(su.get("sand_bags") or 0) > 0 and (int(su.get("fuel") or 0) > 0 or furnaces.get("MagmaGlassFurnace")):
            order("raw_green_glass", q, "make raw green glass")
            return acts, None
        if int(su.get("empty_bags") or 0) > 0:
            order("collect_sand", 2, "fill bags with sand for raw glass")
            return acts, None
        return acts, "no bag of sand (or no fuel) for raw glass"
    if kind == "cut_gem":
        rg = _d(_d(s.get("trade")).get("rough_gem"))
        if (_has_shop(b, "Jewelers") and int(rg.get("n") or 0) > 0
                and str(rg.get("token", "")).startswith("INORGANIC:")):
            order("cut_gems", q, "cut a gem", rg["token"])
            return acts, None
        return acts, "no rough gem to cut"
    if kind == "block" and not x.get("material") and not flags & {"metal", "glass", "wood"}:
        order("stone_blocks", q, "make stone blocks")
        return acts, None
    if kind == "rough":
        return acts, "no rough gem (they come from mining gem veins, or a caravan's)"
    if kind == "log":
        return acts, "no log (trees felled, or a caravan's wood)"
    if kind == "stone":
        return acts, "no loose stone"
    return acts, "no recipe makes it"


def _mood_slaughter(s: dict, memory, cfg: dict, acts: list, why: str) -> bool:
    """(0.105.24) One spare tame animal to the butcher for a mood's bone or
    leather (the slaughter rule's own guards: a butcher's, enough tame
    animals, never a fort of Beast-friends)."""
    tame = int(_d(s.get("others_on_map")).get("tame_animals") or 0)
    if (tame >= cfg["slaughter_min_tame"] and _has_shop(_d(s.get("buildings")), "Butchers")
            and not (memory is not None and has_rule(getattr(memory, "culture", None), "no_slaughter"))):
        if not any(a.get("type") == "slaughter_one" for a, _ in acts):
            acts.append(({"type": "slaughter_one"}, f"one spare tame animal of the {tame} to the butcher: {why}"))
        return True
    return False


def _mood_materials(s: dict, name: str, mood: str, missing: list, days: int,
                    proposals: list, notes: list, cfg: dict | None = None, memory=None, unit_id=None) -> None:
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
    made here goes into Needs you at once, named, and on the caravans' list.
    From an older bridge (no count) as before: day 3, then Needs you on day 7."""
    cfg = cfg or PLANNER_CONFIG
    counted = any(isinstance(x.get("avail"), dict) for x in missing)
    ordered, lacking, freeing, far = [], [], False, []
    taken = {p.action.get("order_id") for p in proposals if p.action.get("type") == "cancel_work_order"}
    for i, x in enumerate(missing):
        kind = mood_kind(x)
        av = _d(x.get("avail"))
        here = mood_on_hand(x)
        if here:
            continue                                   # free within reach: the dwarf will fetch it
        want = max(1, int(x.get("quantity") or 1))
        if counted and int(av.get("forbidden_reach") or 0) > 0:
            freeing = True
            if int(av.get("reach") or 0) + int(av.get("forbidden_reach") or 0) >= want:
                continue
        if counted and int(av.get("free") or 0) > int(av.get("reach") or 0):
            far.append(mood_item_text(x))              # in the fort, but where the dwarf can't walk
        if counted and int(av.get("job") or 0) > 0:
            for o in _l(s.get("orders")):
                if (isinstance(o, dict) and o.get("by_ai") and o.get("recipe") in MOOD_CONSUMERS.get(kind, ())
                        and o.get("id") is not None and o.get("id") not in taken):
                    taken.add(o.get("id"))
                    proposals.append(Proposal("mood", {"type": "cancel_work_order", "order_id": o["id"]},
                                              f"{name}'s {mood.lower()} mood waits for {mood_item_text(x)} and "
                                              f"another job holds the fort's last: cancel the AI's {o['recipe']} "
                                              "order (its jobs let go of it)", 1))
                    break
        acts, why = _mood_make(s, x, kind, memory, cfg)
        for a, how in acts:
            if a.get("type") == "work_order" and any(p.action == a for p in proposals):
                continue
            proposals.append(Proposal("mood", a, f"{name}'s {mood.lower()} mood needs {mood_item_text(x)}"
                                      + (" (the one it is fetching now)" if i == 0 else "") + f": {how}",
                                      1, a.get("type") == "work_order"))
            if a.get("type") == "work_order":
                ordered.append(a.get("recipe"))
        if why and not acts and not (counted and int(av.get("job") or 0) > 0):
            lacking.append((mood_item_text(x), why, kind))
    if freeing and unit_id is not None:
        proposals.append(Proposal("mood", {"type": "mood_free_items", "unit_id": unit_id, "max": 10},
                                  f"{name}'s {mood.lower()} mood can use items that lie forbidden or marked for "
                                  "the dump: free them", 1))
    first = mood_item_text(missing[0]) if missing else ""
    if far:
        ask_player(notes, f"{name}'s {mood.lower()} mood waits for {', '.join(far)}: the fort has it, but "
                   "where the dwarf can't walk: open the way, or bring it in, or the dwarf goes insane")
    if not lacking:
        if counted and (ordered or freeing):
            notes.append(f"{name}'s {mood.lower()} mood (day {days}): fetching {first}"
                         + (f"; ordered {', '.join(ordered)}" if ordered else "")
                         + ("; forbidden materials freed" if freeing else ""))
        return
    words = [w for w, _, _ in lacking]
    if counted:
        # the bridge counted: none within the fort the mood can use, none made here
        ask_player(notes, f"{name}'s {mood.lower()} mood (day {days}) needs what the fort can't supply: "
                   + "; ".join(f"{w}: {why}" for w, why, _ in lacking)
                   + ". Buy it from a caravan (asked for), or the dwarf goes insane")
    elif days < cfg["mood_lacking_days"]:
        # (0.103.8) the dwarf may still be fetching it: Enxah's fisherdwarf
        # claimed the mason's on day 3, "lacked" rock that day and the next
        # (51 boulders about) and began the work on day 5
        notes.append(f"{name}'s {mood.lower()} mood: still gathering after {days} days, waiting on "
                     f"{', '.join(words)}")
    else:
        ask_player(notes, f"{name}'s {mood.lower()} mood still lacks, after {days} days: {', '.join(words)}. "
                   "The fort probably has none the dwarf can reach or use: make it, dig it, buy it from a "
                   "caravan, or unforbid it, or the dwarf goes insane")


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
            if not key and mood_kind(x) == "bar" and x.get("material") and str(x["material"]).lower() != "rock":
                key = "BAR:" + str(x["material"]).upper().replace(" ", "_")
            if key and key not in seen:
                seen.add(key)
                out.append({"key": key, "count": max(1, min(10, int(x.get("quantity") or 1)))})
    return out

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

__all__ = ["MOOD_WORKSHOPS", "_mood_rules", "mood_item_text", "MOOD_CONSUMERS", "MOOD_TRADE_KEYS", "_mood_make", "_mood_slaughter", "_mood_materials", "mood_counts_text", "mood_journal", "mood_trade_wants", "MOOD_BLOCKS", "mood_blocked", "MOOD_RESERVES", "mood_reserve_counts", "reserve_blocked", "reserve_room", "RESERVE_BATCH", "note_reserve_swap", "_mood_reserve_rule", "reserve_trade_wants", "reserve_words"]


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
            prog = _d(_d(getattr(memory, "mood_progress", None)).get(str(m.get("unit_id"))))
            stalled = ((now - prog["since"]) // TICKS_PER_DAY if isinstance(prog.get("since"), int)
                       else days)
            if missing and (counted or days >= cfg["mood_wait_days"]
                            or stalled >= cfg.get("mood_stall_days", 7)):
                _mood_materials(s, name, mood, missing, days, proposals, notes, cfg, memory=memory,
                                unit_id=m.get("unit_id"), stalled=stalled)
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
                  "leather": ("leather_shoes", "leather_low_boots", "leather_quiver",
                           "leather_waterskin"),          # (0.105.26 seal fix) the flasks order too
                  "bar": ("metal_crafts", "metal_amulet", "metal_bracelet", "metal_ring", "metal_earring")}


# (0.105.26) the AI's other work orders that would use up what a waiting mood
# needs, held in select() while it waits (the bag, quiver, shoe, jewellery,
# crafts and cloth rules re-ordered what a mood had just cancelled); cloth and
# thread by the kind of thread a request names (none named: every kind)
MOOD_BLOCKS = {"rough": ("cut_gems",), "cut_gem": ("encrust_goods",), "bone": ("bone_crafts",),
               "leather": ("leather_shoes", "leather_low_boots", "leather_quiver",
                           "leather_waterskin"),          # (0.105.26 seal fix) the flasks order too
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
        if _mood_slaughter(s, memory, cfg, acts, "its hide tanned for leather", mood=mood):
            return acts, None
        return acts, why + "; " + _slaughter_why(s, memory, cfg, mood)
    if kind in ("bone", "shell"):
        if kind == "shell":
            return acts, "no shell (shells come from turtles and shellfish: fishing, or a caravan's)"
        if _mood_slaughter(s, memory, cfg, acts, "its bones for the mood", mood=mood):
            return acts, None
        return acts, "no bone the dwarf can use; " + _slaughter_why(s, memory, cfg, mood)
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
        av = _d(x.get("avail"))
        if int(av.get("held") or 0) > 0:
            return acts, None                  # the dwarf holds stone that suits: it is on its way
        if av.get("capped"):
            return acts, None                  # the bridge's search was cut short: not known to be none
        if int(av.get("free") or 0) > 0 or int(av.get("forbidden") or 0) > 0:
            return acts, None                  # the fort has some (out of reach, or forbidden: said elsewhere)
        return acts, "no loose stone of the kind it wants"
    return acts, "no recipe makes it"


MOOD_SLAUGHTER_MIN_TAME = 3     # (0.105.30) for a mood: the bridge keeps the last two of a kind anyway


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
        return True                                   # this mood's one animal went already
    tame = int(_d(s.get("others_on_map")).get("tame_animals") or 0)
    banned = memory is not None and has_rule(getattr(memory, "culture", None), "no_slaughter")
    least = MOOD_SLAUGHTER_MIN_TAME if mood else cfg["slaughter_min_tame"]
    if not (tame >= least and _has_shop(_d(s.get("buildings")), "Butchers")):
        return False
    if banned and not mood:
        return False
    if any(a.get("type") == "slaughter_one" for a, _ in acts):
        return True
    if mood:
        a = {"type": "slaughter_one", "oldest": True}
        if uid is not None:
            a["mood_unit"] = uid
        who = mood.get("name") or "a dwarf"
        text = f"the oldest spare tame animal of the {tame} to the butcher: {why}"
        if banned:
            text = (f"the fort's {_ban_name(memory)} ban is set aside to save {who}'s mood: one animal only, "
                    + text)
        acts.append((a, text))
    else:
        acts.append(({"type": "slaughter_one"}, f"one spare tame animal of the {tame} to the butcher: {why}"))
    return True


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
                 ("other", "in use"), ("held", "carried by the dwarf")):
        if n(k):
            bits.append(f"{n(k)} {w}")
    if av.get("capped"):
        bits.append("search cut short")
    return f"{what}: " + ", ".join(bits)


def _mood_materials(s: dict, name: str, mood: str, missing: list, days: int,
                    proposals: list, notes: list, cfg: dict | None = None, memory=None, unit_id=None,
                    stalled: int | None = None) -> None:
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
    From an older bridge (no count) as before: day 3, then Needs you on day 7.

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
    who = {"name": name, "unit_id": unit_id}
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
        out_of_walk = counted and int(av.get("free") or 0) > int(av.get("reach") or 0)
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
        acts, why = _mood_make(s, x, kind, memory, cfg, mood=who)
        for a, how in acts:
            if a.get("type") == "work_order" and any(p.action == a for p in proposals):
                continue
            proposals.append(Proposal("mood", a, f"{name}'s {mood.lower()} mood needs {mood_item_text(x)}"
                                      + (" (the one it is fetching now)" if i == 0 else "")
                                      + (" (the fort's lies where the dwarf can't walk)" if out_of_walk else "")
                                      + f": {how}", 1, a.get("type") == "work_order"))
            if a.get("type") == "work_order":
                ordered.append(a.get("recipe"))
        if acts:
            continue
        if out_of_walk:
            # in the fort, but where the dwarf can't walk: never "none" (F, 8 Nov)
            far.append(mood_item_text(x) + (f" (none to be made here: {why})" if why else ""))
        elif why and not (counted and int(av.get("job") or 0) > 0):
            try:
                rw = reserve_words(s, cfg, x)          # (0.105.31) the reserve and what is being done
            except Exception:                        # noqa: BLE001  (words only)
                rw = ""
            lacking.append((mood_item_text(x), why + (f" ({rw})" if rw else ""), kind))
    if freeing and unit_id is not None:
        proposals.append(Proposal("mood", {"type": "mood_free_items", "unit_id": unit_id, "max": 10},
                                  f"{name}'s {mood.lower()} mood can use items that lie forbidden or marked for "
                                  "the dump: free them", 1))
    first = mood_item_text(missing[0]) if missing else ""
    if far:
        asks.append(f"{name}'s {mood.lower()} mood waits for {'; '.join(far)}: the fort has it, but "
                    "where the dwarf can't walk: open the way, or bring it in, or the dwarf goes insane")
    words = [w for w, _, _ in lacking]
    if lacking and counted:
        # the bridge counted: none within the fort the mood can use, none made here
        asks.append(f"{name}'s {mood.lower()} mood (day {days}) needs what the fort can't supply: "
                    + "; ".join(f"{w}: {why}" for w, why, _ in lacking)
                    + ". Buy it from a caravan (asked for), or the dwarf goes insane")
    elif lacking and days >= cfg["mood_lacking_days"]:
        asks.append(f"{name}'s {mood.lower()} mood still lacks, after {days} days: {', '.join(words)}. "
                    "The fort probably has none the dwarf can reach or use: make it, dig it, buy it from a "
                    "caravan, or unforbid it, or the dwarf goes insane")
    elif lacking:
        # (0.103.8) the dwarf may still be fetching it: Enxah's fisherdwarf
        # claimed the mason's on day 3, "lacked" rock that day and the next
        # (51 boulders about) and began the work on day 5
        notes.append(f"{name}'s {mood.lower()} mood: still gathering after {days} days, waiting on "
                     f"{', '.join(words)}")
    if stalled is not None and stalled >= cfg.get("mood_stall_days", 7) and missing:
        counts = "; ".join(mood_counts_text(x) for x in missing)
        line = (f"no progress for {stalled} days; what the fort holds for each request: {counts}")
        if asks:
            asks[-1] += f" ({line})"
        else:
            asks.append(f"{name}'s {mood.lower()} mood has fetched nothing for {stalled} days although the fort "
                        f"seems to hold it ({counts}): is the way from the workshop to it open (a door, a "
                        "burrow, a forbidden or flooded path)? Or the dwarf goes insane")
    for a in asks:
        ask_player(notes, a)
    if not lacking and not asks and counted and (ordered or freeing):
        notes.append(f"{name}'s {mood.lower()} mood (day {days}): fetching {first}"
                     + (f"; ordered {', '.join(ordered)}" if ordered else "")
                     + ("; forbidden materials freed" if freeing else ""))


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


MOOD_JOURNAL_KEYS = ("free", "reach", "forbidden", "forbidden_reach", "dump", "job", "other", "held")


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

# reserve -> (config key, words, the AI's orders that use it up)
MOOD_RESERVES = {
    "plant_cloth": ("reserve_plant_cloth", "plant cloth", MOOD_CLOTH_BLOCKS["plant"]),
    "animal_cloth": ("reserve_animal_cloth", "silk or yarn cloth", MOOD_CLOTH_BLOCKS["silk"] + MOOD_CLOTH_BLOCKS["yarn"]),
    "leather": ("reserve_leather", "leather", MOOD_BLOCKS["leather"]),
    "bones": ("reserve_bones", "bones", MOOD_BLOCKS["bone"]),
    "rough_gems": ("reserve_rough_gems", "rough gems", MOOD_BLOCKS["rough"]),
    "cut_gems": ("reserve_cut_gems", "cut gems", MOOD_BLOCKS["cut_gem"]),
    "bars": ("reserve_bars", "metal bars", MOOD_BLOCKS["bar"]),
    "blocks": ("reserve_blocks", "blocks", ()),
    "logs": ("reserve_logs", "logs", ()),
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
        "animal_cloth": (int(ck.get("silk") or 0) + int(ck.get("yarn") or 0)) if ck else None,
        "leather": _int_or_none(st.get("leather")),
        "bones": _int_or_none(nd.get("bones")),
        "rough_gems": _int_or_none(st.get("rough_gems")),
        "cut_gems": _int_or_none(st.get("cut_gems")),
        "bars": _int_or_none(st.get("metal_bars")),
        "blocks": _int_or_none(st.get("blocks")),
        "logs": _int_or_none(st.get("wood")),
    }


def reserve_blocked(s: dict, cfg: dict) -> dict:
    """{recipe: words}: the AI's orders that would use up a mood reserve the
    fort is at or under (held in select(), as mood_blocked's are)."""
    out = {}
    counts = mood_reserve_counts(s)
    for k, (key, words, recipes) in MOOD_RESERVES.items():
        want, have = int(cfg.get(key) or 0), counts.get(k)
        if want > 0 and have is not None and have <= want:
            for r in recipes:
                out.setdefault(r, f"the {have} {words} kept for strange moods (a reserve of {want})")
    return out


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
    flags = set(str(f) for f in _l(x.get("flags")))
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
           "bar": "bars", "block": "blocks", "log": "logs"}.get(kind)
    if key and kind != "cloth":
        ckey, words, _ = MOOD_RESERVES[key]
        want, have = int(cfg.get(ckey) or 0), counts.get(key)
        if want and have is not None and have < want:
            return f"the fort's reserve of {words} for moods is {have} of {want}"
    return ""


def reserve_trade_wants(s: dict, cfg: dict) -> list[dict]:
    """(0.105.31) A plant-cloth reserve the fort can't make (no fibre crop,
    seed or plant): plant cloth and seeds on the caravans' list."""
    want, have = int(cfg.get("reserve_plant_cloth") or 0), mood_reserve_counts(s)["plant_cloth"]
    if not want or have is None or have >= want or _plant_cloth_route(s) != "none":
        return []
    return [{"key": "CLOTH", "count": want - have}, {"key": "SEEDS", "count": 5}]


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
                if memory is not None and getattr(memory, "reserve_noted", "") != "plant_cloth_drink":
                    memory.reserve_noted = "plant_cloth_drink"
                    notes.append(f"{head}: the fibre plants aren't processed for thread while {why_not}")
            elif order("process_plants", n, f"{head}: process the fibre plants for thread before the still "
                                            "brews them"):
                return
        elif route == "seeds" and _swap_off(s, memory):
            pass        # (0.105.31 reserve fixes) no fibre crop grows on the plots this season
        elif route == "seeds" and _drink_short_any(s, cfg):
            # (0.105.31 reserve fixes) no brewable plot goes to fibre while drink is short
            if memory is not None and getattr(memory, "reserve_noted", "") != "plant_cloth_drink":
                memory.reserve_noted = "plant_cloth_drink"
                notes.append(f"{head}: no plot goes to a fibre crop while drink is short")
        elif route == "seeds" and farm_plots_any(s) and memory is not None and not memory.farm_crops_player:
            proposals.append(Proposal("mood_reserve", {"type": "set_farm_crops", "thread": True,
                                                       "drink": False},
                                      f"{head}, and no plot grows a fibre crop: one plot grows "
                                      f"{', '.join(_fibre_seeds(s))} (its plants processed for thread)", 5))
            return
        elif route == "none" and memory is not None and getattr(memory, "reserve_noted", "") != "plant_cloth":
            memory.reserve_noted = "plant_cloth"
            notes.append(f"{head}: no fibre crop, seed or plant here, so plant cloth and seeds are on the "
                         "caravans' list")
    n, have, want = gap("animal_cloth")
    if n:
        thread = _d(su.get("thread_kinds"))
        for k in ("silk", "yarn"):
            if int(thread.get(k) or 0) > 0 and _has_shop(b, "Loom"):
                if order(f"weave_{k}_cloth", min(n, int(thread.get(k) or 0)),
                         f"{have} silk or yarn cloth, a reserve of {want} {FOR}: weave {k} cloth"):
                    return
                break
    n, have, want = gap("leather")
    if n and int(su.get("hides") or 0) > 0 and _has_shop(b, "Tanners"):
        if order("tan_hide", min(n, int(su.get("hides") or 0)), f"{have} leather, a reserve of {want} {FOR}: "
                                                                 "tan a hide"):
            return
    n, have, want = gap("cut_gems")
    rough, rough_keep = counts.get("rough_gems"), int(cfg.get("reserve_rough_gems") or 0)
    rg = _d(_d(s.get("trade")).get("rough_gem"))
    if (n and rough is not None and rough > rough_keep and _has_shop(b, "Jewelers")
            and str(rg.get("token", "")).startswith("INORGANIC:")):
        if order("cut_gems", min(n, rough - rough_keep), f"{have} cut gems, a reserve of {want} {FOR}: cut "
                                                         "a rough gem (its own reserve kept)", rg["token"]):
            return
    n, have, want = gap("blocks")
    if n and _has_shop(b, "Masons") and int(_d(s.get("stocks")).get("boulders") or 0) > 0:
        order("stone_blocks", n, f"{have} blocks, a reserve of {want} {FOR}: make stone blocks")


def _drink_short_any(s: dict, cfg: dict) -> bool:
    from planner_farms import drink_short, drink_known_short
    return drink_known_short(s, cfg) or (isinstance(_d(s.get("stocks")).get("drink"), (int, float))
                                         and drink_short(s, cfg))


def _plants_spare(s: dict, cfg: dict, n: int) -> tuple[bool, str]:
    """(0.105.31 reserve fixes) May n fibre plants be processed for thread?
    Not while drink is urgent, nor when the brewable plants left after it
    (and after the open brew orders) stay no higher than the drink line,
    a brewable plant for each dwarf (drink_short's). Of the fibre plants,
    only the brewable ones count against it (the bridge's
    thread_brewable_plants; an older bridge: all of them)."""
    if _drink_short_any(s, cfg):
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

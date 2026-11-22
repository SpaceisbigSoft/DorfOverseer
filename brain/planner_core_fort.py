"""planner_core_fort: part of planner_core (split out of planner_core.py in r7, which re-exports every
name): readers of the fort's state: shops and recipes, the order watchdog, moods, care, locations,
idle dwarves, the agenda, food and gear."""

from __future__ import annotations
import json
from quirks import has_rule
from digest import _d, _l
from planner_config import PLANNER_CONFIG
from planner_core_base import abs_tick, GEAR_METALS, SHOP_ALIASES, stuck_days, TICKS_PER_DAY, TICKS_PER_YEAR
from planner_core_rules import player_rules


# Where a work order's jobs are done (for saying why one doesn't move).
JOB_SHOPS = {"MakeCrafts": "Craftsdwarfs", "MakeAmulet": "Craftsdwarfs", "MakeBracelet": "Craftsdwarfs",
             "MakeRing": "Craftsdwarfs", "MakeEarring": "Craftsdwarfs", "SmeltOre": "Smelter", "MakeCharcoal": "WoodFurnace",
             "BrewDrink": "Still", "PrepareMeal": "Kitchen", "ConstructBin": "Carpenters",
             "ConstructBed": "Carpenters", "MakeBarrel": "Carpenters", "ConstructBucket": "Carpenters",
             "MakeWeapon": "MetalsmithsForge", "MakeArmor": "MetalsmithsForge", "MakeHelm": "MetalsmithsForge",
             "MakePants": "MetalsmithsForge", "MakeGloves": "MetalsmithsForge",
             "ConstructMechanisms": "Mechanics", "ConstructBlocks": "Masons", "WeaveCloth": "Loom",
             "MakeLargePot": "Craftsdwarfs", "ConstructChest": "Masons", "ConstructCabinet": "Masons",
             "ConstructDoor": "Masons", "ConstructTable": "Masons", "ConstructThrone": "Masons",
             "ConstructStatue": "Masons", "ConstructCoffin": "Masons", "ConstructArmorStand": "Masons",
             "ConstructWeaponRack": "Masons", "ConstructSlab": "Masons",
             "MakeAsh": "WoodFurnace", "MakeLye": "Ashery", "MAKE_SOAP_FROM_TALLOW": "SoapMaker",
             "CollectSand": "GlassFurnace", "MakeWindow": "GlassFurnace",       # (0.104.95)
             "RENDER_FAT": "Kitchen"}


# The AI's own recipes made by a reaction, by where they're made.
RECIPE_SHOPS = {"pig_iron": "Smelter", "steel": "Smelter", "coke_bituminous": "Smelter",
                **{f"alloy_{m}": "Smelter" for m in ("bronze", "bismuth_bronze", "brass", "electrum", "billon",
                                                     "black_bronze", "rose_gold", "sterling_silver")},   # (0.105.40 M7)
                "coke_lignite": "Smelter", "smelt_ore": "Smelter", "brew_drink": "Still",
                "brew_drink_from_fruit": "Still", "make_mead": "Still", "make_charcoal": "WoodFurnace",
                "weave_plant_cloth": "Loom", "weave_yarn_cloth": "Loom", "weave_silk_cloth": "Loom",
                "cloth_rope": "Clothiers", "yarn_rope": "Clothiers", "silk_rope": "Clothiers",
                "metal_chain": "MetalsmithsForge", "process_plants": "Farmers", "make_quicklime": "Kiln",
                "make_plaster_powder": "Kiln", "make_milk_of_lime": "Ashery", "make_parchment": "Tanners",
                "make_quire": "Craftsdwarfs",
                # (0.104.87) sewn at a clothier's (an order for one the fort hasn't waits)
                "cloth_bag": "Clothiers", "silk_bag": "Clothiers", "yarn_bag": "Clothiers",
                # (0.104.95) glass is made at a glass furnace, precious metal crafts at the forge
                "collect_sand": "GlassFurnace", "metal_crafts": "MetalsmithsForge",
                "metal_amulet": "MetalsmithsForge", "metal_bracelet": "MetalsmithsForge",   # (0.104.137)
                "metal_ring": "MetalsmithsForge", "metal_earring": "MetalsmithsForge",
                "tan_hide": "Tanners", "raw_green_glass": "GlassFurnace"}   # (0.105.24) a strange mood's leather and glass
RECIPE_SHOPS["collect_webs"] = "Loom"        # (0.105.47, J1) webs collected for silk thread


# (0.100.1, overnight run) the workshop a recipe is made at, where it's sure:
# an order for a workshop the fort doesn't have never moves (130 brew jobs and
# meals and beds waited five years with no still, kitchen or carpenter, were
# cancelled as stuck and ordered again: 338 cancels in a night)
WOOD_ELSEWHERE = {"wooden_crossbow": "Bowyers", "wooden_bolts": "Bowyers", "wooden_cups": "Craftsdwarfs",
                  "wood_crafts": "Craftsdwarfs", "bone_crafts": "Craftsdwarfs",
                  "bone_bolts": "Craftsdwarfs"}      # (r2h4) bone bolts: carved at the craftsdwarf's


def recipe_shop(recipe) -> str | None:
    r = str(recipe or "")
    if r in RECIPE_SHOPS:
        return RECIPE_SHOPS[r]
    if r in WOOD_ELSEWHERE:
        return WOOD_ELSEWHERE[r]
    if r.startswith("brew_"):
        return "Still"
    if r.startswith("prepare_") and r.endswith("_meal"):
        return "Kitchen"
    if r.startswith("wooden_"):
        return "Carpenters"
    if r.startswith("glass_"):
        return "GlassFurnace"
    return None


def brewable_counts(s: dict) -> tuple[int, int]:
    """(0.105.23) (plants, fruit) a still can brew: the bridge's brewable
    counts (0.99.5: each material's DRINK_MAT, items not in a job) when it
    sends them, the raw stocks otherwise."""
    st, sup = _d(s.get("stocks")), _d(s.get("supplies"))
    if isinstance(sup.get("brewable_plants"), int):
        return int(sup["brewable_plants"] or 0), int(sup.get("brewable_growths") or 0)
    return int(st.get("plants") or 0), int(st.get("plant_growths") or 0)


def brew_recipe(s: dict) -> str | None:
    """(13c) The brew recipe a still can do now: from plants if any can be
    brewed, else from fruit, else None. (0.105.23) From fruit when there is
    more of it than of plants: B (the Monastery) had 4 brewable plants, and a
    brew of 10 from plants found 4 and stood still."""
    plants, fruit = brewable_counts(s)
    # (an older bridge's raw growths are mostly leaves, not fruit: plants first then)
    counted = isinstance(_d(s.get("supplies")).get("brewable_plants"), int)
    if plants > 0 and (plants >= fruit or not counted):
        return "brew_drink"
    return "brew_drink_from_fruit" if fruit > 0 else None


def _watchdog_notes(s: dict, memory, cfg: dict, notes: list) -> None:
    """Work that has stopped without anyone saying so (0.48's fort: smelting
    orders that could never start, crafts the trade code couldn't see):
    work orders whose count hasn't moved in 2 weeks are named, with the
    likely reason when it's a missing workshop; the AI's own after 4 weeks
    are Needs you. And a population unchanged for a year is said."""
    now = abs_tick(s)
    shops = {**_d(_d(s.get("buildings")).get("workshops")), **_d(_d(s.get("buildings")).get("furnaces"))}
    stuck_note, stuck_you = [], []
    by_id = {str(o.get("id")): o for o in _l(s.get("orders")) if isinstance(o, dict)}
    for k, w in memory.order_watch.items():
        if not isinstance(w, dict) or not isinstance(w.get("since"), int) or not (w.get("left") or 0) > 0:
            continue
        days = stuck_days(w, now)           # (r1g8) less the alarm's days
        if days < cfg["order_stuck_days"]:
            continue
        shop = JOB_SHOPS.get(str(w.get("job")))
        state = order_job_state(by_id.get(str(k))) if jobs_reported(s) else ""   # (0.104.13) what its job is doing
        # (0.105.35) what the AI does about it, not "check ..." for the player
        why = (f"the fort has no {shop}" if shop and not _has_shop(_d(s.get("buildings")), shop)
               else state or "its workshop, workers or materials hold it")
        why += (f"; the AI cancels it at {cfg['order_stuck_you_days']} days" if w.get("by_ai")
                and days < cfg["order_stuck_you_days"] else "" if w.get("by_ai") else "; the player's order: left as it is")
        text = f"{w.get('what')} ({w.get('left')} left, {'the AI' if w.get('by_ai') else 'yours'}) for {days} days: {why}"
        if w.get("by_ai") and days >= cfg["order_stuck_you_days"]:
            if _stuck_before(memory, w.get("what"), now, cfg):
                stuck_you.append(text)       # cancelled once already and stuck again
            # (else _stuck_orders_rule cancels it)
        else:
            stuck_note.append(text)
    if stuck_note:
        notes.append(f"{len(stuck_note)} work order(s) haven't moved: " + "; ".join(sorted(stuck_note)[:3]))
    if stuck_you:
        # (0.105.35) said, not Needs you: _stuck_again_rule cancels them again
        # and each is held longer (stuck_hold_days, doubled up to 112 days)
        notes.append(f"{len(stuck_you)} of the AI's work order(s) got stuck again after a cancel: "
                     + "; ".join(sorted(stuck_you)[:3])
                     + " (the AI cancels each again and holds it longer before ordering it again)")
    pw = _d(memory.pop_watch)
    cap = _d(s.get("society")).get("pop_cap")
    if isinstance(pw.get("since"), int) and now - pw["since"] >= TICKS_PER_YEAR and (not cap or pw.get("pop", 0) < cap):
        notes.append(f"the fort has had {pw.get('pop')} dwarves for a year or more"
                     + (f" (population cap {cap})" if cap else "")
                     + ": migrants come to a fort that grows richer (crafts for the caravans, built rooms)"
                     + ("; the AI sets the population cap itself" if player_rules(s)["set_pop_cap"]
                        else "; the population cap is the player's (its Rules switch is off)"))


def jobs_reported(s: dict) -> bool:
    """(0.104.13) The bridge counts each AI order's jobs (from 0.104.13)."""
    try:
        return tuple(int(x) for x in str(s.get("bridge_version") or "0").split(".")[:3]) >= (0, 104, 13)
    except ValueError:
        return False


def order_job_state(o: dict) -> str:
    """(0.104.13) What an order's jobs are doing, from the bridge's count of
    them (call only when `jobs_reported`)."""
    if not isinstance(o, dict) or not o.get("by_ai"):
        return ""
    j = o.get("jobs")
    if not isinstance(j, dict):
        return ("no job made from it yet (no free workshop of its kind, or the game finds no material for it)"
                if o.get("active") else "")
    if (j.get("suspended") or 0) > 0:
        return f"its job is suspended at the workshop ({j.get('suspended')} of {j.get('n')})"
    if (j.get("working") or 0) > 0:
        return "a dwarf is on it now"
    who = []
    if j.get("permitted"):                       # (0.104.125) the workshop's worker profile
        who.append(f"only {j['permitted']} named dwarf(s) may work there")
    if j.get("min_skill") or j.get("max_skill"):
        who.append(f"its workers' skill is limited to {j.get('min_skill') or 0}-{j.get('max_skill') or 'any'}")
    return (f"{j.get('n')} job(s) wait at the workshop for a worker with the labour"
            + (f" ({'; '.join(who)})" if who else ""))


def masons_jammed(s: dict) -> int:
    """(0.104.32) Unworked engrave-slab jobs (autoslab's, waiting for blank
    slabs) on a mason's bench whose job list is full (10): Enxah's held 7 of
    the 10, so neither the slabs they wait for nor enough coffins could get
    on. The bench jobs then lift that many to make room."""
    worst = 0
    for w in _l(_d(s.get("order_desk")).get("workshops")):
        if not isinstance(w, dict) or w.get("type") != "Masons" or not isinstance(w.get("job_list"), list):
            continue
        jl = w["job_list"]
        if len(jl) < 10:
            return 0                            # a mason's bench with room: nothing to lift
        if any(isinstance(j, dict) and j.get("type") == "ConstructSlab" and not j.get("order") for j in jl):
            return 0                            # (0.104.33) blank slabs already on the bench: let them come
        stuck = sum(1 for j in jl if isinstance(j, dict) and j.get("type") == "EngraveSlab" and not j.get("worker"))
        worst = max(worst, stuck)
    return worst


def stuck_hold_days(sc: dict, cfg: dict) -> int:
    """(0.104.37) How long a recipe cancelled as stuck waits: 28 days, doubled
    each time it got stuck again soon after (to 112)."""
    n = int(_d(sc).get("n") or 1)
    return min(cfg["stuck_retry_max_days"], cfg["stuck_retry_days"] * 2 ** max(0, n - 1))


def _stuck_before(memory, what, now: int, cfg: dict) -> bool:
    """The AI cancelled an order for this as stuck not long ago."""
    c = _d(_d(getattr(memory, "stuck_cancelled", None)).get(str(what)))
    return isinstance(c.get("tick"), int) and now - c["tick"] < cfg["stuck_again_days"] * TICKS_PER_DAY


def stone_short(s: dict, n: int) -> bool:
    """Fewer than n boulders of stone the masons and crafters may use (only
    known with a bridge from 0.51: otherwise False)."""
    su = s.get("stone_use")
    return isinstance(su, dict) and isinstance(su.get("usable"), int) and su["usable"] < n


def _office_held(s: dict, code: str) -> bool:
    return bool(_l(_d(_d(_d(s.get("offices")).get("offices")).get(code)).get("held")))


def tantrums_recent(s: dict, memory, days: int = 28) -> int:
    if memory is None:
        return 0
    now = abs_tick(s)
    return sum(1 for t in memory.tantrums if isinstance(t, list) and isinstance(t[0], int)
               and 0 <= now - t[0] < days * TICKS_PER_DAY)


def justice_held(s: dict) -> bool:
    """Does someone hold the sheriff's or captain of the guard's office?"""
    offices = _d(_d(s.get("offices")).get("offices"))
    return any(_l(_d(offices.get(c)).get("held")) for c in ("SHERIFF", "CAPTAIN_OF_THE_GUARD"))


def manager_needs_office(s: dict) -> bool:
    """(0.100.2) The fort has a manager who has no office, and no free office
    to give them."""
    nr = _d(s.get("noble_rooms"))
    if (_d(nr.get("free")).get("office") or 0) > 0:
        return False                           # the noble rooms rule gives it
    return any(isinstance(n, dict) and n.get("office") == "MANAGER" and "office" in _l(n.get("needs"))
               for n in _l(nr.get("nobles")))


def suites_short(s: dict) -> int:
    """Nobles still wanting a bedroom or office with no free one to give:
    a suites level is dug for them (a bedroom and an office each, max 8)."""
    nr = _d(s.get("noble_rooms"))
    free = _d(nr.get("free"))
    short = 0
    for kind in ("bedroom", "office"):
        want = sum(1 for n in _l(nr.get("nobles")) if isinstance(n, dict) and kind in _l(n.get("needs")))
        short = max(short, want - (free.get(kind) or 0))
    return max(0, min(8, short))


def wool_route(s: dict) -> bool:
    """(0.104.28) Thread can come from shorn animals: tame ones that can be
    shorn and a farmer's workshop to shear and spin at.
    (0.105.47, J1) with wool grown now (the bridge's `shearable_ready`, when
    it reports it): I7a, "Shear animal: No creature" 250 times in F while the
    shearable count said yes."""
    su = _d(s.get("supplies"))
    ready = su.get("shearable_ready")
    n = ready if isinstance(ready, int) and not isinstance(ready, bool) else su.get("shearable")
    return int(n or 0) > 0 and _has_shop(_d(s.get("buildings")), "Farmers")


# (0.105.24) what a strange mood asks for, in kinds the AI can act on
MOOD_BODY_FLAGS = ("bone", "shell", "horn", "pearl", "ivory", "tooth")


def mood_kind(x: dict) -> str:
    """One of a mood request's kinds: cloth, leather, bone, shell, bar,
    rough, glass_rough, cut_gem, stone, block, log, other."""
    item = str(_d(x).get("item") or "").upper()
    flags = set(str(f) for f in _l(_d(x).get("flags")))
    mat = str(_d(x).get("material") or "").lower()
    if item == "CLOTH":
        return "cloth"
    if item == "SKIN_TANNED":
        return "leather"
    if item in ("NONE", "CORPSEPIECE", "") and flags & set(MOOD_BODY_FLAGS):
        return "shell" if "shell" in flags and "bone" not in flags else "bone"
    if item == "BAR":
        return "bar"
    if item == "ROUGH":
        return "glass_rough" if ("glass" in mat or "glass" in flags) else "rough"
    if item == "SMALLGEM":
        return "cut_gem"
    if item == "BOULDER":
        return "stone"
    if item == "BLOCKS":
        return "block"
    if item == "WOOD":
        return "log"
    return "other"


def mood_on_hand(x: dict) -> bool | None:
    """(0.105.24) The bridge's count for a mood request (lua/ai-moods.lua):
    True when enough lies free within the dwarf's walk, False when not, None
    from an older bridge (no count)."""
    av = _d(x).get("avail")
    if not isinstance(av, dict):
        return None
    want = max(1, int(_d(x).get("quantity") or 1))
    # (0.105.30) what the dwarf already carries that suits it counts too
    return bool(av.get("enough")) or int(av.get("reach") or 0) + int(av.get("held") or 0) >= want


def mood_waits(s: dict) -> set:
    """(0.105.24) The kinds the fort's crafting moods wait for and don't have
    within reach (from a bridge that counts; every unmet kind from an older
    one): the gem cutters, bone carvers and the like leave them alone."""
    out = set()
    for m in _l(_d(s.get("moods")).get("list")):
        if not isinstance(m, dict) or not m.get("craft"):
            continue
        for x in _l(m.get("missing")):
            if isinstance(x, dict) and mood_on_hand(x) is not True:
                out.add(mood_kind(x))
    return out


def thread_plants_here(s: dict) -> bool:
    """(0.104.11) Plants in stock that give thread (the bridge counts them
    from 0.104.11; an older one: any plant may)."""
    su = _d(s.get("supplies"))
    if "thread_plants" in su:
        return int(su.get("thread_plants") or 0) > 0
    return int(_d(s.get("stocks")).get("plants") or 0) > 0


SOCIAL_NEEDS = ("Socialize", "BeWithFriends", "MakeMerry", "DrinkAlcohol")


def care_waiting(s: dict) -> int:
    """Patients with a treatment waiting (diagnosis, surgery, ...): infected
    wounds alone don't count (0.88.3)."""
    h = _d(s.get("health"))
    if isinstance(h.get("waiting"), int):          # (0.104.133) the full count: the list stops at 30
        return h["waiting"]
    return sum(1 for p in _l(h.get("patients")) if isinstance(p, dict) and _l(p.get("needs")))


def unmet(s: dict, *names: str) -> int:
    """Citizens distracted by any of these needs (the bridge's `needs` report)."""
    n = _d(_d(s.get("needs")).get("needs"))
    return sum(int(_d(n.get(k)).get("distracted") or 0) for k in names)


def recently_home(s: dict, memory) -> list:
    """(0.104.138) Units the AI sent home in the last 168 days (newest 100),
    for the bridge's fill to pass over: swapped, or (0.104.164) released."""
    if memory is None:
        return []
    now = abs_tick(s)
    # (0.104.164) and those released for stress or a baby (the fill drafted
    # one back once he was merely unhappy; they never counted as swaps)
    sent = dict(_d(getattr(memory, "released", None)))
    for k, v in _d(getattr(memory, "swapped", None)).items():
        if isinstance(v, int) and v > (sent.get(k) if isinstance(sent.get(k), int) else -1):
            sent[k] = v
    rows = sorted(((t, k) for k, t in sent.items()
                   if isinstance(t, int) and 0 <= now - t < 168 * TICKS_PER_DAY), reverse=True)[:100]
    out = [int(k) for _, k in rows if str(k).isdigit()]
    # (0.105.47) and those stress care sent home for good ("never draft"),
    # first: kept until a long time passes or their mood rises (planner_training)
    from planner_training import never_draft_ids
    never = never_draft_ids(s, memory)
    return (never + [i for i in out if i not in set(never)])[:100]


# DF keeps some location supplies in larger units (abstract_building_contents)
LOCATION_UNITS = {"thread": 15000, "cloth": 10000, "powder": 150, "soap": 150}


def _location(s: dict, kind: str) -> dict | None:
    """The first location of this kind in the bridge's `locations.list` (0.83+)."""
    for e in _l(_d(s.get("locations")).get("list")):
        if isinstance(e, dict) and e.get("type") == kind:
            return e
    return None


def _location_short(loc: dict, keys) -> dict:
    """{supply: (have, want)} in whole items, for what a location keeps less of than it wants."""
    out = {}
    have, want = _d(loc.get("have")), _d(loc.get("want"))
    for k in keys:
        u = LOCATION_UNITS.get(k, 1)
        h, w = int(have.get(k) or 0) // u, int(want.get(k) or 0) // u
        if w > 0 and h < w:
            out[k] = (h, w)
    return out


def _real_locations(counts: dict, key: str, memory, listing: list | None = None) -> int:
    """(0.102.5) Locations of a kind, not counting the AI's stop-gap one laid
    over the dining hall: a proper hall still comes through the ladder.
    (0.103.13) The bridge marks one laid over a dining hall (`over_dining`):
    the memory of the stop-gap was lost with a reload (Enxah: quick_locations
    {} in the save, so its 49 dwarves longing to pray got no shrine)."""
    quick = _d(getattr(memory, "quick_locations", None))
    kind = {"TEMPLE": "temple", "INN_TAVERN": "tavern"}.get(key)
    rows = [x for x in _l(listing) if isinstance(x, dict) and x.get("type") == key]
    if rows:
        marked = any(x.get("over_dining") for x in rows)
        return max(0, sum(1 for x in rows if not x.get("over_dining")) - (1 if kind in quick and not marked else 0))
    return max(0, int(counts.get(key) or 0) - (1 if kind in quick else 0))


STALE_PROJECT_DAYS = 28


def _workshops_busy(open_: list) -> bool:
    """A workshops project is under way (the AI starts one at a time). One
    stuck furnishing for STALE_PROJECT_DAYS or more doesn't count (0.86:
    region2's second forge waited 104 days for an anvil, and every new
    workshop, the kiln among them, waited behind it)."""
    return any(isinstance(p, dict) and p.get("kind") == "workshops"
               and (_d(p.get("furnish")).get("days") or 0) < STALE_PROJECT_DAYS for p in open_)


def shop_count(b: dict, name: str) -> int:
    """How many workshops (or furnaces) of a kind stand, under any of its names."""
    places = {**_d(b.get("workshops")), **_d(b.get("furnaces"))}
    return sum(int(places.get(n, 0) or 0) for n in SHOP_ALIASES.get(name, (name,)))


def shops_max(cfg: dict, citizens: int) -> int:
    """(0.99.4) The most workshops of one kind the AI builds: 3 for a small
    fort, one for every 50 dwarves once that is more (5 at 228: region2's 3
    stills, all brewing, couldn't keep 228 dwarves in drink)."""
    return max(cfg["shops_max_each"], -(-int(citizens or 0) // 50))


def _has_shop(b: dict, name: str) -> bool:
    places = {**_d(b.get("workshops")), **_d(b.get("furnaces"))}
    return any(places.get(n, 0) > 0 for n in SHOP_ALIASES.get(name, (name,)))


# Food a dwarf can eat or cook: raw (cookable) and everything (with meals,
# and fish still to be cleaned). Stock names as the bridge counts them.
RAW_FOOD = ("meat", "fish", "plants", "plant_growths", "cheese", "eggs")
ALL_FOOD = ("prepared_meals", "raw_fish") + RAW_FOOD


def _idle_free_known(s: dict) -> bool:
    free = _d(s.get("dwarves")).get("idle_free")
    return isinstance(free, int) and not isinstance(free, bool)


def _idle_share(s: dict) -> float:
    """The share of the fort's working adults with nothing to do. (0.105.33)
    From the bridge's `idle_free` (no job, no social activity, not in a
    squad) over the adults outside the squads: prayer, the tavern and reading
    are not idleness, and soldiers are never idle. An older bridge's report
    has no idle_free: its idle_adults over all adults, as before."""
    dw = _d(s.get("dwarves"))
    free = dw.get("idle_free")
    if _idle_free_known(s):
        squads = dw.get("in_squads")
        squads = squads if isinstance(squads, int) and not isinstance(squads, bool) else 0
        return max(0, free) / max(1, int(dw.get("adults") or 0) - max(0, squads))
    return (dw.get("idle_adults") or 0) / max(1, dw.get("adults") or 1)


# (0.105.33 fix) The idle-driven rules' lines were set for the old measure
# (idle_adults/adults); on the stricter one (_idle_share) the truly idle run
# at 12-23% and the rules almost stopped. PLANNER_CONFIG now holds the lines
# for the stricter measure, set to fire as often over the 8 Nov run's season
# states as the old ones did on the old measure (polish 47 states before and
# after, blocks 54/53, garden 60/59, idle_train 34/34, its off line 53/53).
# These are the old lines, for a report with no idle_free (an older bridge):
# there _idle_share is still the old measure.
IDLE_OLD_LINES = {"polish_idle_share": 0.3, "garden_idle_share": 0.2, "idle_blocks_share": 0.25,
                  "idle_train_share": 0.4, "idle_train_off_share": 0.25}


def idle_line(s: dict, cfg: dict, key: str) -> float:
    """(0.105.33 fix) An idle rule's line (`key` in IDLE_OLD_LINES) for the
    measure _idle_share gives this report: cfg's own on the stricter one;
    on the old one, scaled to the old line (a tuned value keeps its lean)."""
    v = cfg[key]
    if _idle_free_known(s):
        return v
    return v * IDLE_OLD_LINES[key] / PLANNER_CONFIG[key]


def levels_done(state: dict):
    """(0.105.33) How many levels the fort has finished, ever: the bridge's
    `done_total` (it never stops counting), else its `finished`, which stops
    at the 20 closed projects it keeps (the polish gate stuck there for good).
    None when the report has neither."""
    pr = _d(state.get("projects"))
    n = pr.get("done_total")
    if isinstance(n, int) and not isinstance(n, bool):
        return n
    return pr.get("finished")


def _lever_state(lever: dict):
    """(0.105.33) A gate lever's reported state (0 or 1, as DF keeps it), or None."""
    v = _d(lever).get("state")
    if isinstance(v, bool):
        return int(v)
    return v if isinstance(v, int) else None


def update_idle(s: dict, memory, cfg: dict) -> None:
    """(0.84; called by note_cycle, before planning) The running average of
    the idle share (memory.idle_avg: the count of idle dwarves jumps from
    cycle to cycle; live, 0.83: over 40%, under 25% and back within three
    game days, so the rotation sent a squad off duty and back), and the band
    on it (memory.idle_hands): on from `idle_train_share` (20%), off only
    under `idle_train_off_share` (14%), since the dwarves who then train
    aren't idle any more. (0.105.33 fix: were 40% / 25% on the old idle
    measure, which counted prayer and the tavern as idle.)"""
    share = _idle_share(s)
    avg = memory.idle_avg
    if isinstance(avg, (int, float)):
        share = (1 - cfg["idle_avg_weight"]) * avg + cfg["idle_avg_weight"] * share
    memory.idle_avg = round(share, 4)
    memory.idle_hands = (share >= idle_line(s, cfg, "idle_train_share")
                         or (memory.idle_hands and share >= idle_line(s, cfg, "idle_train_off_share")))


# What a rule works toward, in a few words (the season's agenda)
AGENDA_THEMES = {
    "arms": "arm and armour the soldiers", "uniform": "dress the squads", "barracks_assign": "house the squads",
    "squad_fill": "fill the squads", "grandeur": "dress the halls", "quick_temple": "a place to pray", "quick_tavern": "a tavern", "stress_care": "care for dwarves near breaking", "squad_trim": "send extra soldiers back to work", "unload_depot": "empty the depot after the caravans", "needs_finery": "jewellery to wear", "good_cooks": "the best cooks to the kitchen", "squad_make": "raise a new squad", "uniform_adopt": "dress the squads", "staff": "staff the hospital, library and tavern", "tavern": "stock the tavern", "kiln": "plaster and paper", "anvil": "an anvil for a new forge", "petitions": "answer petitions", "residency": "answer petitions to stay", "citizenship": "answer citizenship petitions", "train": "train the soldiers",
    "build": "build the fort's next level", "furniture": "furnish the new levels",
    "steel": "make steel", "alloy": "alloy bronze and finer metals", "smelt": "smelt the ore", "ore": "mine ore", "fuel": "make fuel",
    "trade": "trade with the caravans", "trade_deal": "trade with the caravans", "crafts": "make goods to sell",
    "gems": "cut gems", "encrust": "set gems into crafts", "drink": "keep the drink flowing",
    "needs_meal": "cook good meals", "needs_craft": "let dwarves craft",
    "food": "keep the fort fed", "farms": "farm", "hospital": "stock the hospital", "soap": "make soap",
    "feeder": "shorten the hauling", "labor": "put idle hands to work", "labor_trim": "take the extra hands off fishing", "well": "find water for a well", "well_lid": "close the cavern well's stairs", "well_shaft": "a gate in the cavern well's shaft", "planned_parts": "parts the planned buildings wait for", "comfort": "shoes and cups for the fort", "mothers": "mothers home from the squads", "dead_units": "clear old dead from the unit list", "herd": "keep the herds the fort's size",
    "stuck_order": "clear stuck work", "unsuspend": "resume suspended work", "stray_gear": "hand out lost gear", "assign_weapons": "arm the soldiers", "assign_kit": "armour the soldiers", "soldier_swap": "let the keen train", "temple_chest": "a chest for the temple", "instrument_orders": "clear the instrument backlog", "pair_chairs": "seat dwarves together", "recreation": "time off for the unhappiest", "hospital_burrow": "keep the wounded in the hospital", "calm_burrow": "keep a tantrum away from the others", "dairy": "milk and cheese", "eggs": "nest boxes for the hens", "war_animals": "train war animals", "gate_guard": "hold the gate", "gate_dogs": "war dogs at the gate", "gem_cutting": "cut the rough gems", "stairwell": "a new stairwell", "animal_trainer": "an animal trainer", "nest_box_order": "make nest boxes", "library_chest": "a chest for the library", "orphan_jobs": "clear jobs whose order is gone", "slabs_free": "free the memorial slabs", "water_traffic": "keep paths off the ice", "jail_size": "a bigger jail", "jail_more": "another jail", "break_fights": "break up the fights among the fort's own", "burial": "bury the dead", "rooms": "mend the rooms' walls", "coffins": "coffins for the tombs", "order_slots": "free the workshop's order slots", "fat_ban": "keep fat for soap", "jail_urgent": "a jail against the beatings", "tavern_urgent": "a tavern for company", "quarry": "quarry stone", "cloth": "weave cloth",
}
AGENDA_THEMES["vermin"] = "keep cats against the vermin"     # (0.104.168)
AGENDA_THEMES["food_store"] = AGENDA_THEMES["food_barrels"] = AGENDA_THEMES["food_store_level"] = "keep the food from rotting"   # (0.105.40b)
AGENDA_THEMES["artifact_display"] = AGENDA_THEMES["artifact_furniture"] = AGENDA_THEMES["artifact_pedestals"] = "show the fort's artifacts"   # (item 12)
AGENDA_THEMES["traction_rest"] = "care for the injured"       # (0.105.24)

AGENDA_THEMES["cups_home"] = "shoes and cups for the fort"      # (0.104.168)

AGENDA_THEMES.update({"soap_rush": "make soap", "infected_rest": "care for the infected",   # (0.104.168)
                      "doctor_post": "more doctors"})
AGENDA_THEMES.update({"booze_variety": "drinks of more kinds", "mood": "materials for a strange mood"})   # (0.105.24)


def agenda(proposals: list, notes: list, limit: int = 5) -> list[str]:
    """The season's goals: what the most urgent proposals work toward (by
    rule, most urgent first, each once), then what the player is asked."""
    out = []
    for p in sorted(proposals, key=lambda p: p.priority):
        theme = AGENDA_THEMES.get(p.rule)
        if theme and theme not in out:
            out.append(theme)
        if len(out) >= limit:
            break
    asks = [n[6:].split(":")[0] for n in notes if isinstance(n, str) and n.startswith("[you] ")]
    if asks and len(out) < limit:
        out.append("ask you: " + asks[0][:60])
    return out


def food_per_dwarf(s: dict) -> float:
    """Meals and raw food (meat, fish, plants, fruit and leaves, cheese,
    eggs) a dwarf. (0.39.0 read 'meals', which the bridge doesn't send: meals
    never counted, so the fort always looked hungry and kept gathering.)"""
    st = _d(s.get("stocks"))
    citizens = max(1, _d(s.get("dwarves")).get("total", 0) or 0)
    total = sum(int(st.get(k, 0) or 0) for k in ALL_FOOD)
    return round(total / citizens, 1)


WINTER_STOCK = {"autumn": 1.5, "winter": 1.25}     # food and drink kept, x the usual


def winter_factor(s: dict, memory=None) -> float:
    """Food and drink are stocked up in autumn (crops stop, water may freeze)
    and kept higher through winter; more where the water freezes."""
    season = _d(s.get("date")).get("season")
    f = WINTER_STOCK.get(season, 1.0)
    # (0.103) a Frozen Hold lays in its winter stores from midsummer
    if season == "summer" and memory is not None and has_rule(getattr(memory, "culture", None), "early_winter_stores"):
        f = WINTER_STOCK["winter"]
    if f > 1 and memory is not None and getattr(memory, "climate_freezes", False):
        f += 0.25
    return f


def young_fort(s: dict, cfg: dict) -> bool:
    """A young fort: few dwarves and food not yet secure (food first, small
    and plain). A small fort that is fed (farms, food and drink well in hand)
    is not young however few its dwarves: 0.44's fort sat at 18 dwarves for a
    year, "young" all that time, so it made no crafts to sell, its wealth
    stayed low and no migrants came."""
    pop = _d(s.get("dwarves")).get("total", 0) or 0
    if not 0 < pop < cfg["young_fort"]:
        return False
    return not established(s, cfg)


def established(s: dict, cfg: dict) -> bool:
    """Farms, and food and drink well in hand for every dwarf."""
    pop = max(1, _d(s.get("dwarves")).get("total", 0) or 0)
    drink = (_d(s.get("stocks")).get("drink") or 0) / pop
    return (has_farms(s) and food_per_dwarf(s) >= cfg["established_food_per_dwarf"]
            and drink >= cfg["established_drink_per_dwarf"])


def has_farms(s: dict) -> bool:
    built = _d(_d(s.get("buildings")).get("other")).get("FarmPlot", 0)
    return bool(built or _d(s.get("farms")).get("plots"))


def _best_metal(s: dict, items: int, wanted: str | None = None) -> str | None:
    """INORGANIC:<metal> for gear: the mandate's own metal if named, else the
    best weapon-grade metal with enough bars (2 per item, to be safe)."""
    if wanted and str(wanted).startswith("INORGANIC:"):
        return wanted
    bars = _d(_d(_d(s.get("military")).get("gear")).get("bars"))
    m = next((x for x in GEAR_METALS if (bars.get(x) or 0) >= 2 * items), None)
    return f"INORGANIC:{m}" if m else None


def spare_sig(gear: dict) -> str:
    """(0.104.138) The spare gear counts, as one string to compare."""
    return json.dumps(sorted((str(k), v) for k, v in _d(gear.get("spare")).items()))


def _weapon_gaps(gear: dict) -> bool:
    """(0.104.60) Soldiers on duty with places whose weapon entry is empty
    while free weapons (or crossbows) lie on the game's unassigned list."""
    free_w = (sum(int(v or 0) for k, v in _d(gear.get("spare_weapons")).items()
                  if isinstance(v, (int, float)) and k != "ITEM_WEAPON_PICK")      # a pick is a miner's tool
              + int(gear.get("spare_crossbows") or 0))
    if isinstance(gear.get("weapon_gaps_fillable"), int) and gear["weapon_gaps_fillable"] <= 0:
        return False                 # (0.104.138) the bridge's own dry run fills none
    return int(gear.get("weapon_gaps") or 0) > 0 and free_w > 0 and int(gear.get("on_duty") or 0) > 0

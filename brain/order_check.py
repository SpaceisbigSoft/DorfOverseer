"""order_check (0.105.46, I3): the order loop. Before the AI places a work
order: its inputs (bars of its metal, logs, stone, thread, cloth, plants,
leather) net of what the AI's open orders already claim, fuel (or a magma
workshop), a free workshop of its kind and a citizen with the labour. And
after an order of the AI's was cancelled as stuck: a memory per recipe (and
material) of what was missing then, so it isn't ordered again until that
changes or `order_miss_days` pass.

Why (the run check, 12-13 Nov, 24 h over six forts): metal_helm ordered 67
times and cancelled as stuck 16, stone_blocks 46/27, metal_greaves 34/15,
gauntlets 38/15, shields 30/11, boots 30/11, weave_plant_cloth 69/11, mail
shirts 73/9 ... Most were the copy cancels of _stuck_orders_rule: two or
three orders of one recipe in different metals, or of one metal whose bars
another order had taken, the older stuck, cancelled, placed again. Each
rule checked "bars >= need" by itself; none counted the bars the open
orders already claim.

Used by planner.select() for every work order any rule proposes (one
place, so every rule that orders is covered: the drink, food and mood rules'
own orders are left to them), and by planner.record() when a stuck order is
cancelled. Also: `approve_orders` (planner_orders._approve_rule) placed 674
times (30 a game year): every AI order waited 3 days for a manager who never
came to it. Once the AI has approved its own orders, its new orders are
approved as they are placed (`approve` on the work_order action).
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import GEAR_METALS, PLANNER_CONFIG, SHOP_ALIASES, TICKS_PER_DAY, _has_shop

__all__ = ["order_feasible", "order_needs", "snapshot", "miss_key", "order_gate", "note_order_loop",
           "approve_on_place", "hold_lifted", "approve_repeat", "ORDER_CHECK_EXEMPT"]

# rules whose orders are not checked here: the fort's drink and food (their
# rules pick the recipe by what can be brewed or cooked), a strange mood's
# materials (a life on it) and the well's parts
ORDER_CHECK_EXEMPT = {"drink", "drink_fruit", "food", "well_parts", "mood", "mood_reserve", "mandate"}

WORKSHOP_JOBS_MAX = 10          # DF's jobs a workshop holds

# kind-metal recipes and the bars one item takes (planner_config gear_bars for
# the soldiers' kit; 1 elsewhere: a lower bound, so nothing is held wrongly)
GEAR_KEY = {"metal_battle_axe": "weapons", "metal_spear": "weapons", "metal_mace": "weapons",
            "metal_pick": "weapons", "metal_mail_shirt": "body", "metal_breastplate": "body",
            "metal_helm": "helms", "metal_shield": "shields", "metal_greaves": "pants",
            "metal_high_boots": "boots", "metal_gauntlets": "gloves"}
METAL_RECIPES = set(GEAR_KEY) | {"metal_bolts", "metal_chain", "metal_anvil", "metal_crafts", "metal_amulet",
                                 "metal_bracelet", "metal_ring", "metal_earring", "metal_table", "metal_chair",
                                 "metal_door", "metal_cabinet", "metal_chest", "metal_coffin",
                                 "metal_armor_stand", "metal_weapon_rack", "ballista_arrowheads",
                                 "metal_trap_blades"}
WOOD_RECIPES = {"wheelbarrow", "wood_crafts", "ballista_parts", "catapult_parts", "ballista_arrows",
                "make_charcoal"}
CLOTH_KIND = {"cloth_bag": "plant", "cloth_rope": "plant", "cloth_shoes": "plant", "cloth_socks": "plant",
              "yarn_bag": "yarn", "yarn_rope": "yarn", "silk_bag": "silk", "silk_rope": "silk"}
THREAD_KIND = {"weave_plant_cloth": "plant", "weave_yarn_cloth": "yarn", "weave_silk_cloth": "silk"}
# made with fuel unless at the magma workshop of its kind (coke and charcoal
# are the fuel; sand is only collected)
FUEL_SHOPS = {"MetalsmithsForge": "MagmaForge", "Smelter": "MagmaSmelter", "GlassFurnace": "MagmaGlassFurnace",
              "Kiln": "MagmaKiln"}
NO_FUEL = {"make_charcoal", "collect_sand", "coke_bituminous", "coke_lignite"}
# the labour each workshop's work calls for (df.unit_labor tokens)
SHOP_LABOUR = {"Masons": "MASON", "Mechanics": "MECHANIC", "Carpenters": "CARPENTER", "Bowyers": "BOWYER",
               "Loom": "WEAVER", "Clothiers": "CLOTHESMAKER", "Leatherworks": "LEATHER",
               "Farmers": "PROCESS_PLANT", "Smelter": "SMELT", "GlassFurnace": "GLASSMAKER",
               "WoodFurnace": "BURN_WOOD", "Kiln": "POTTERY", "Jewelers": "CUT_GEM"}
ARMOUR = {"metal_mail_shirt", "metal_breastplate", "metal_helm", "metal_shield", "metal_greaves",
          "metal_high_boots", "metal_gauntlets"}
WEAPONS = {"metal_battle_axe", "metal_spear", "metal_mace", "metal_pick", "metal_bolts", "ballista_arrowheads",
           "metal_trap_blades"}
CRAFTS = {"metal_crafts", "metal_amulet", "metal_bracelet", "metal_ring", "metal_earring"}


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _shop_of(recipe: str) -> str | None:
    from planner_orders import order_shop        # (recipe_shop, then stone at the mason's or crafter's)
    shop = order_shop(recipe)
    if shop:
        return shop
    if recipe in METAL_RECIPES or recipe.startswith("metal_"):
        return "MetalsmithsForge"
    if recipe == "mechanisms":
        return "Mechanics"
    if recipe.startswith("leather_"):
        return "Leatherworks"
    if recipe.startswith("cloth_") or recipe.startswith("silk_") or recipe.startswith("yarn_"):
        return "Clothiers"
    if recipe in ("ballista_parts", "catapult_parts", "ballista_arrows"):
        return "Siege"
    if recipe == "wheelbarrow":
        return "Carpenters"
    return None


def _labour_of(recipe: str, shop: str | None) -> str | None:
    if shop in ("MetalsmithsForge", "MagmaForge"):
        if recipe in ARMOUR:
            return "FORGE_ARMOR"
        if recipe in WEAPONS:
            return "FORGE_WEAPON"
        if recipe in CRAFTS:
            return "METAL_CRAFT"
        return "FORGE_FURNITURE"
    if shop == "Craftsdwarfs":
        if recipe.startswith("wood") or recipe == "wooden_cups":
            return "WOOD_CRAFT"
        if recipe.startswith("bone"):
            return "BONE_CARVE"
        if recipe.startswith("stone_"):
            return "STONE_CRAFT"
        return None
    return SHOP_LABOUR.get(shop or "")


def order_needs(recipe, action: dict | None = None, cfg: dict = PLANNER_CONFIG) -> dict:
    """What an order of this recipe takes: {input: (key, per item) or None,
    fuel: bool, shop: name or None, labour: token or None}. `key` names the
    stock: "bars:IRON", "boulders", "wood", "thread:plant", "cloth:yarn",
    "thread_plants", "leather"."""
    r = str(recipe or "")
    a = _d(action)
    need: dict = {"input": None, "fuel": False, "shop": _shop_of(r), "labour": None}
    if r in METAL_RECIPES:
        mat = str(a.get("material") or "")
        metal = mat.split(":", 1)[1] if mat.upper().startswith("INORGANIC:") else ""
        per = int(_d(cfg.get("gear_bars")).get(GEAR_KEY.get(r, ""), 1) or 1)
        need["input"] = (f"bars:{metal.upper()}" if metal else "bars", per)
    elif r.startswith("stone_") or r == "mechanisms":
        need["input"] = ("boulders", 1)
    elif r.startswith("wooden_") or r in WOOD_RECIPES:
        need["input"] = ("wood", 1)
    elif r in THREAD_KIND:
        need["input"] = (f"thread:{THREAD_KIND[r]}", 1)
    elif r in CLOTH_KIND:
        need["input"] = (f"cloth:{CLOTH_KIND[r]}", 1)
    elif r == "process_plants":
        need["input"] = ("thread_plants", 1)
    elif r.startswith("leather_"):
        need["input"] = ("leather", 1)
    shop = need["shop"]
    need["fuel"] = bool(shop in FUEL_SHOPS and r not in NO_FUEL)
    need["labour"] = _labour_of(r, shop)
    return need


def _gross(key: str, s: dict) -> int | None:
    """How much of an input the fort has (None: the report doesn't say)."""
    st, su = _d(s.get("stocks")), _d(s.get("supplies"))
    gear = _d(_d(s.get("military")).get("gear"))
    if key.startswith("bars:"):
        if "error" in gear:
            return None
        if "all_bars" in gear:                   # every metal (furniture in silver...)
            bars = _d(gear.get("all_bars"))
        elif "bars" in gear:
            # the weapon-grade ones only (all_bars is left out when the fort has
            # no bars at all, and by a bridge before 0.104.95): another metal is
            # unknown unless there are no bars of any kind
            bars = _d(gear.get("bars"))
            if bars and key[5:] not in bars and key[5:] not in GEAR_METALS:
                return None
        else:
            return None
        return int(bars.get(key[5:]) or 0)
    if key == "bars":
        return _int(st.get("metal_bars"))
    if key == "boulders":
        usable = _int(_d(s.get("stone_use")).get("usable"))
        return usable if usable is not None else _int(st.get("boulders"))
    if key == "wood":
        return _int(st.get("wood"))
    if key.startswith("thread:"):
        kinds = _d(su.get("thread_kinds"))
        return _int(kinds.get(key[7:])) if kinds else _int(st.get("thread"))
    if key.startswith("cloth:"):
        kinds = _d(su.get("cloth_kinds"))
        return _int(kinds.get(key[6:])) if kinds else _int(st.get("cloth"))
    if key == "thread_plants":
        v = _int(su.get("thread_plants"))
        return v if v is not None else _int(st.get("plants"))
    if key == "leather":
        return _int(st.get("leather"))
    return None


def _claimed(key: str, s: dict, cfg: dict, extra=(), exclude_id=None) -> int:
    """The input the AI's open orders (and this cycle's chosen ones, `extra`:
    work_order actions) will take: what's left of each times its per item."""
    total = 0
    rows = [o for o in _l(s.get("orders")) if isinstance(o, dict) and o.get("by_ai")
            and o.get("id") != exclude_id]
    for o in rows:
        n = needs_of_row(o, cfg)
        if n["input"] and n["input"][0] == key:
            total += max(0, int(o.get("amount_left") or 0)) * n["input"][1]
    for a in extra:
        n = order_needs(a.get("recipe"), a, cfg)
        if n["input"] and n["input"][0] == key:
            total += max(0, int(a.get("amount") or 0)) * n["input"][1]
    return total


def needs_of_row(o: dict, cfg: dict = PLANNER_CONFIG) -> dict:
    return order_needs(o.get("recipe"), {"material": o.get("material")}, cfg)


def _free_shops(shop: str, s: dict) -> int | None:
    """Built, reachable workshops of the kind open to orders, with room for a
    job (None: the report doesn't list that kind: furnaces, an older bridge)."""
    kinds = SHOP_ALIASES.get(shop, (shop,))
    rows = [w for w in _l(_d(s.get("order_desk")).get("workshops"))
            if isinstance(w, dict) and str(w.get("type")) in kinds]
    if not rows:
        return None
    return sum(1 for w in rows if w.get("built", True) and not w.get("unreachable") and not w.get("blocked")
               and int(w.get("jobs") or 0) < WORKSHOP_JOBS_MAX)


def _holders(labour: str, s: dict) -> int | None:
    """Citizens with the labour, where the report says (an AI order's waiting
    job, the labour's waiting work); None: not said."""
    best = None
    for o in _l(s.get("orders")):
        j = _d(_d(o).get("jobs"))
        if j.get("labor") == labour and _int(j.get("holders")) is not None:
            best = max(best or 0, j["holders"])
    for w in _l(_d(s.get("labor")).get("waiting")):
        if isinstance(w, dict) and w.get("labor") == labour and _int(w.get("holders")) is not None:
            best = max(best or 0, w["holders"])
    return best


def _fuel(s: dict) -> int | None:
    return _int(_d(s.get("supplies")).get("fuel"))


def snapshot(recipe, s: dict, action: dict | None = None, cfg: dict = PLANNER_CONFIG) -> dict:
    """The numbers an order of this recipe turns on, now (None: unknown)."""
    n = order_needs(recipe, action, cfg)
    shop = n["shop"]
    b = _d(s.get("buildings"))
    known = b.get("workshops") is not None or b.get("furnaces") is not None
    return {"inputs": _gross(n["input"][0], s) if n["input"] else None,
            "fuel": _fuel(s) if n["fuel"] else None,
            "workshop": (None if not shop or not known else
                         (0 if not _has_shop(b, shop) else _free_shops(shop, s))),
            "labour": _holders(n["labour"], s) if n["labour"] else None}


def _label(key: str) -> str:
    if key.startswith("bars:"):
        return f"{key[5:].replace('_', ' ').lower()} bars"
    if ":" in key:                                   # thread:plant -> plant thread
        kind, sort = key.split(":", 1)
        return f"{sort} {kind}"
    return {"bars": "metal bars", "boulders": "stone the masons may use", "wood": "logs",
            "thread_plants": "plants that give thread"}.get(key, key)


def order_feasible(recipe, s: dict, action: dict | None = None, cfg: dict = PLANNER_CONFIG,
                   extra=(), exclude_id=None) -> dict:
    """{"ok": True} or {"ok": False, "missing": "inputs"|"fuel"|"workshop"|
    "labour", "what": words}. Unknown counts never hold an order."""
    n = order_needs(recipe, action, cfg)
    r = str(recipe or "")
    if n["input"]:
        key, per = n["input"]
        have = _gross(key, s)
        if have is not None:
            free = have - _claimed(key, s, cfg, extra, exclude_id)
            if free < per:
                label = _label(key)
                return {"ok": False, "missing": "inputs", "key": key, "have": have,
                        "what": f"{have} {label}, {have - free} of them claimed by the AI's open orders "
                                f"(one {r.replace('_', ' ')} takes {per})"}
    shop = n["shop"]
    b = _d(s.get("buildings"))
    known = b.get("workshops") is not None or b.get("furnaces") is not None
    if shop and known:
        if not _has_shop(b, shop):
            return {"ok": False, "missing": "workshop", "what": f"no {shop} workshop"}
        free = _free_shops(shop, s)
        if free == 0:
            return {"ok": False, "missing": "workshop",
                    "what": f"no free {shop} workshop (each is full, blocked to orders or out of reach)"}
    if n["fuel"]:
        magma = FUEL_SHOPS.get(shop or "")
        has_magma = magma and int({**_d(b.get("workshops")), **_d(b.get("furnaces"))}.get(magma) or 0) > 0
        fuel = _fuel(s)
        if not has_magma and fuel is not None and fuel <= 0:
            return {"ok": False, "missing": "fuel", "what": "no charcoal or coke (and no magma workshop of its kind)"}
    if n["labour"]:
        h = _holders(n["labour"], s)
        if h == 0:
            return {"ok": False, "missing": "labour", "what": f"no citizen has the {n['labour']} labour"}
    return {"ok": True}


def miss_key(recipe, material=None) -> str:
    return f"{recipe}|{str(material or '').upper()}"


def _book(memory) -> dict:
    book = getattr(memory, "order_loop", None)
    if not isinstance(book, dict):
        book = {}
        try:
            memory.order_loop = book
        except AttributeError:
            pass
    book.setdefault("misses", {})
    return book


def _changed(rec: dict, now_snap: dict) -> bool:
    """The thing that was missing when the order was cancelled has grown."""
    was = _d(rec.get("snap"))
    miss = rec.get("missing")

    def up(k, much=False):
        a, b = _int(was.get(k)), _int(now_snap.get(k))
        if a is None or b is None:
            return False
        return b >= a * 1.25 + 1 if much else b > a
    if miss in ("inputs", "fuel", "workshop", "labour"):
        return up(miss)
    # nothing visibly missing at the cancel: a workshop, fuel or a worker more,
    # or a quarter more of the input (a log more among 600 isn't a change)
    return up("workshop") or up("labour") or up("fuel") or up("inputs", much=True)


def _miss_for(memory, recipe, material) -> dict | None:
    misses = _d(_d(getattr(memory, "order_loop", None)).get("misses"))
    rec = misses.get(miss_key(recipe, material))
    if not isinstance(rec, dict) and material:
        rec = misses.get(miss_key(recipe))         # booked without its material (an older bridge)
    return rec if isinstance(rec, dict) else None


def hold_lifted(p, s: dict, memory, cfg: dict = PLANNER_CONFIG) -> bool:
    """The older recipe hold (stuck_cancelled) gives way once what was missing
    at the cancel has come (bars arrived): booked here and changed since."""
    a = p.action
    rec = _miss_for(memory, a.get("recipe"), a.get("material"))
    return bool(rec) and _changed(rec, snapshot(a.get("recipe"), s, a, cfg))


def order_gate(p, s: dict, memory, cfg: dict, now: int, allowed=()) -> str | None:
    """None: the order may go. Else why it's held (select() lists it)."""
    a = p.action
    if a.get("type") != "work_order" or p.rule in ORDER_CHECK_EXEMPT:
        return None
    if not cfg.get("order_check", True):
        return None
    recipe = str(a.get("recipe"))
    extra = [q.action for q in allowed if q.action.get("type") == "work_order"]
    chk = order_feasible(recipe, s, a, cfg, extra=extra)
    if not chk["ok"]:
        return f"{p.rule}: no {recipe} order: {chk['what']}"
    rec = _miss_for(memory, recipe, a.get("material"))
    if rec and isinstance(rec.get("tick"), int):
        days = (now - rec["tick"]) // TICKS_PER_DAY
        wait = int(cfg.get("order_miss_days", 56))
        if 0 <= days < wait and not _changed(rec, snapshot(recipe, s, a, cfg)):
            what = rec.get("what") or "nothing the report shows"
            return (f"{p.rule}: the AI's {recipe} order was cancelled as stuck {days} day(s) ago ({what}): "
                    f"ordered again once that changes, or in {wait - days} day(s)")
    return None


def approve_on_place(memory, cfg: dict, now: int) -> bool:
    """The AI approved its own orders not long ago (the manager doesn't get to
    them): its new ones are approved as they're placed."""
    t = _d(getattr(memory, "order_loop", None)).get("approved")
    return isinstance(t, int) and 0 <= now - t < int(cfg.get("approve_on_place_days", 112)) * TICKS_PER_DAY


def approve_repeat(memory, waiting_ids, cfg: dict, now: int) -> bool:
    """The orders waiting now are the very ones the AI approved within
    `approve_after_days`: the approval didn't hold, approving again is a loop."""
    book = _d(getattr(memory, "order_loop", None))
    t = book.get("approved")
    ids = {str(i) for i in _l(book.get("approved_ids"))}
    return (isinstance(t, int) and 0 <= now - t < int(cfg.get("approve_after_days", 3)) * TICKS_PER_DAY
            and bool(waiting_ids) and {str(i) for i in waiting_ids} <= ids)


def note_order_loop(p, r: dict, s: dict, memory, now: int, cfg: dict = PLANNER_CONFIG) -> None:
    """record(): a stuck cancel of the AI's order books what was missing then
    (and the snapshot); an approve_orders that went through books its time and
    the orders it approved."""
    a = p.action
    if r.get("ok") is not True or memory is None or r.get("dry_run"):
        return
    book = _book(memory)
    if a.get("type") == "approve_orders":
        book["approved"] = now
        book["approved_ids"] = [str(o.get("id")) for o in _l(s.get("orders"))
                                if isinstance(o, dict) and o.get("by_ai") and o.get("validated") is False][:200]
        return
    if a.get("type") != "cancel_work_order" or not (p.rule == "stuck_order" or a.get("stuck")):
        return
    o = next((o for o in _l(s.get("orders")) if isinstance(o, dict) and o.get("id") == a.get("order_id")), None)
    recipe = (o or {}).get("recipe") or a.get("stuck")
    if not recipe:
        return
    material = (o or {}).get("material")
    act = {"recipe": recipe, "material": material}
    chk = order_feasible(recipe, s, act, cfg, exclude_id=a.get("order_id"))
    jobs = _d((o or {}).get("jobs"))
    why = chk.get("what") if not chk["ok"] else (jobs.get("why") or "")
    if not why and o:
        from planner_core import order_job_state
        why = order_job_state(o)
    book["misses"][miss_key(recipe, material)] = {
        "tick": now, "missing": chk.get("missing"), "what": str(why or "")[:160],
        "snap": snapshot(recipe, s, act, cfg)}
    # bounded: the oldest dropped past 200 recipes
    if len(book["misses"]) > 200:
        for k in sorted(book["misses"], key=lambda k: _d(book["misses"][k]).get("tick") or 0)[:-200]:
            book["misses"].pop(k, None)

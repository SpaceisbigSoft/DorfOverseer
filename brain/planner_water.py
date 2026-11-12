"""(0.105.0) Water works and magma: the moat (W3), the pump stack (W4), the
muddied farm level (W5) and magma workshops, built a step at a time by the
bridge (lua/ai-waterworks.lua, the `water_work` action). (0.105.37 E3) W7:
the done pump stack's power, a water wheel on the river or a windmill, joined
to its top pump by axles and gears, switched on and off by a lever-worked
gear to keep the reservoir filled (no dwarf at the pumps); begun at Guided
and Architect only (at Scripts nothing new is proposed).

Each work is planned by the bridge with a dry run first: the path its water
(or magma) would take, walked tile by tile; a citizen, workshop, bed,
stockpile or the fort's inside in the way refuses it, with where. The planner
decides which works the fort wants (the sliders, the Rules tab, what the
water survey found) and asks for the next step of each one already begun,
one cycle apart. Every work has a floodgate on a lever as its emergency stop:
the planner shuts it when the bridge reports a leak or dwarves in deep water.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (EMERGENCY, LIMIT_EXEMPT, LOOP_EXEMPT, NO_COOLDOWN, PLANNER_CONFIG, STEER_PROTECTED,
                          TICKS_PER_YEAR, Proposal, player_rules, young_fort, _traits)

# (0.105.35) the pump labour given at most once a fortnight (assign_labor adds
# dwarves each time; the bridge holds the stack after its own stall wait)
PLANNER_CONFIG.setdefault("waterworks_pump_labor_cooldown_ticks", 14 * 1200)

__all__ = ["_waterworks_rule", "LEAK_WATCH_HOLDS", "leak_watch_hold", "WORK_WORDS", "STAGE_WORDS", "moat_wanted", "magma_shop_wanted",
           "irrigation_wanted", "pump_wanted", "river_found", "near_river_found", "far_args", "magma_choice", "power_wanted", "power_line"]

WORK_WORDS = {"moat": "the moat", "pump": "the pump stack", "irrigation": "the muddied farm level",
              "magma": "the magma workshop", "power": "the pump stack's power"}
STAGE_WORDS = {"planned": "planned (its water's path checked)", "digging": "being dug",
               "building": "its floodgate, lever and buildings being built", "linking": "its lever being linked",
               "filling": "filling", "drying": "drying", "finishing": "being finished", "done": "done",
               "held": "held", "retired": "retired",
               "running": "running (the pumps powered)"}
MAGMA_ORDER = ("MagmaForge", "MagmaSmelter", "MagmaGlassFurnace")


def _design_mode(s: dict) -> str:
    """(0.105.37 E3) The Design setting (planner_design.mode_of): new works
    of W7 begin only at Guided and Architect."""
    try:
        from planner_design import mode_of
        return mode_of(s)
    except Exception:  # noqa: BLE001
        m = _d(_d(s).get("settings")).get("design")
        return m if m in ("scripts", "guided", "architect") else "scripts"


MAGMA_STAIR_MAX = 60       # (0.105.38 review) lua/ai-waterworks.lua's: levels of stair down to the magma at most
FAR_REACH_DEFAULT = -1     # (0.105.38 review) water_far_reach's default: the map's width (0: far sources off)
JOB_MAX_DEFAULT = 600      # water_job_max's (0: no far works)
SEGMENT_DEFAULT = 40       # water_dig_segment's


def far_on(cfg: dict | None) -> bool:
    """(0.105.38 review) Far sources on: water_far_reach not 0 and
    water_job_max not 0 (each 0 turns them off)."""
    cfg = cfg or {}
    return (_int(cfg.get("water_far_reach"), FAR_REACH_DEFAULT) != 0
            and _int(cfg.get("water_job_max"), JOB_MAX_DEFAULT) != 0)


def _int(v, default: int) -> int:
    if isinstance(v, bool):
        return default
    if isinstance(v, float) and v.is_integer():      # (review) 0.0 from a JSON config is 0
        return int(v)
    return v if isinstance(v, int) else default


def near_river_found(s: dict) -> bool:
    """(0.105.38 review) A river or brook in the survey's near box (as before
    0.105.38): the moat's feed is a short channel (40 tiles at most), so only
    a near river counts for it."""
    return any(isinstance(b, dict) and b.get("kind") == "river" and int(b.get("tiles") or 0) > 0
               for b in _l(_d(s.get("water")).get("bodies")))


def river_found(s: dict, cfg: dict | None = None) -> bool:
    """A river or brook near the fort, or (0.105.38) anywhere on the map by
    the whole-map survey (a far one is reached by a long axle run; not when
    far sources are off), or (review) a river frozen over since a survey
    saw it (a winter survey: still a river for a water wheel over a windmill)."""
    w = _d(s.get("water"))
    if near_river_found(s) or w.get("frozen_river") is True:
        return True
    return far_on(cfg) and any(isinstance(b, dict) and b.get("flow") == "flowing" and int(b.get("tiles") or 0) > 0
                               for b in _l(w.get("waters")))


def far_args(cfg: dict) -> dict:
    """(0.105.38) The far-source settings an action carries, only those off
    their defaults (the bridge's defaults are the same: the map's width, 600,
    40). (review) 0 is sent too: water_far_reach 0 turns far sources off,
    water_job_max 0 allows no far work."""
    out = {}
    r = _int(cfg.get("water_far_reach"), FAR_REACH_DEFAULT)
    if r >= 0:
        out["far_reach"] = r
    j = _int(cfg.get("water_job_max"), JOB_MAX_DEFAULT)
    if j != JOB_MAX_DEFAULT and j >= 0:
        out["job_max"] = j
    g = _int(cfg.get("water_dig_segment"), SEGMENT_DEFAULT)
    if g != SEGMENT_DEFAULT and g > 0:
        out["segment"] = g
    return out


def _fort_z_low(w: dict):
    z = _d(w.get("middle")).get("z_low")
    return z if isinstance(z, int) and not isinstance(z, bool) else None


def _too_deep(z_low, z) -> bool:
    return z_low is not None and isinstance(z, int) and not isinstance(z, bool) and z_low - (z + 1) > MAGMA_STAIR_MAX


def near_magma_too_deep(s: dict) -> bool:
    """(0.105.38 review) The near box's highest magma lies deeper than a
    stair reaches (MAGMA_STAIR_MAX levels under the fort's lowest)."""
    w = _d(s.get("water"))
    return _too_deep(_fort_z_low(w), _d(_d(w.get("magma")).get("top_nearest")).get("z"))


def magma_choice(s: dict, cfg: dict) -> tuple[str, bool]:
    """(0.105.38) Which magma a workshop can be dug to, from the whole-map
    survey: ("near", False) the near box's highest magma (as before); ("pipe"
    / "sea" / ..., opens) the cheapest magma body (a pipe before the sea)
    with whether its way opens a cavern, which only the cavern switch allows;
    ("", False) none. (0.105.38 review) Magma deeper than MAGMA_STAIR_MAX
    under the fort's lowest level is left out (the bridge would refuse it
    "too deep" every time), and so is a body the survey found blocked. The
    switch: Never, none that opens a cavern; Always, any; AI decides (a
    workshop is wanted, or this is not called): one that opens a cavern only
    when no other way to magma is left and armed soldiers enough stand
    ready (the cavern well's soldier test, not its water test).
    The bridge walks the planned dig again for a cavern (the survey's
    estimate is a straight shaft from the fort's middle)."""
    w = _d(s.get("water"))
    z_low = _fort_z_low(w)

    def too_deep(z) -> bool:
        return _too_deep(z_low, z)

    top = _d(_d(w.get("magma")).get("top_nearest"))
    if top and not too_deep(top.get("z")):
        return "near", False
    if not far_on(cfg):
        return "", False
    rank = {"pipe": 0, "volcano": 0, "pool": 0, "surface": 1, "cavern": 2, "sea": 3}
    mode = player_rules(s)["open_caverns"]
    cands = []
    for b in _l(w.get("waters")):
        if not isinstance(b, dict) or b.get("kind") != "magma" or b.get("blocked"):
            continue
        z = _d(b.get("top")).get("z", _d(b.get("nearest")).get("z"))
        if too_deep(z):
            continue
        opens = bool(b.get("opens_cavern")) or b.get("magma") == "cavern"
        cost = b.get("reach") if isinstance(b.get("reach"), int) else int(b.get("reach_through") or b.get("d") or 10 ** 6) * 3 // 2
        cands.append(((rank.get(b.get("magma"), 2), cost), str(b.get("magma") or "magma"), opens))
    shut = [c for c in cands if not c[2]]
    if mode == "always":
        pool = cands
    elif mode == "ai":
        # (0.105.38 review) the AI opens a cavern for magma only when no other
        # way is left and armed soldiers enough stand ready for what comes
        # out (the cavern well's soldier test; no water test), found or not
        from planner_wells import cavern_soldiers_ready
        pool = shut or (cands if cavern_soldiers_ready(s, cfg)[0] else [])
    else:
        pool = shut
    if not pool:
        return "", False
    best = min(pool, key=lambda c: c[0])
    return best[1], best[2]


def moat_wanted(s: dict, cfg: dict) -> str | None:
    """Why a moat (None: not wanted): Fortification high enough, a river
    near the fort (the survey's near box: (0.105.38 review) a far river found
    by the whole-map survey doesn't count, the bridge feeds a moat from a near
    one only), a surface gate scanned, no threat near (no digging under fire)."""
    tr = _traits(s)
    if (tr.get("fortification", 0) or 0) < cfg["moat_fortification"]:
        return None
    if not near_river_found(s):
        return None
    ents = [e for e in _l(_d(s.get("entrances")).get("entrances")) if isinstance(e, dict) and e.get("kind") == "surface"]
    if not ents:
        return None
    return "Fortification is high and a river runs near the fort's gate"


def magma_shop_wanted(s: dict) -> str | None:
    """The magma workshop the fort lacks first (the forge, the smelter, the
    glass furnace), when it already has the plain one it would replace."""
    b = _d(s.get("buildings"))
    have = {**_d(b.get("workshops")), **_d(b.get("furnaces"))}
    plain = {"MagmaForge": "MetalsmithsForge", "MagmaSmelter": "Smelter", "MagmaGlassFurnace": "GlassFurnace"}
    for shop in MAGMA_ORDER:
        if not have.get(shop) and have.get(plain[shop]):
            return shop
    return None


def irrigation_wanted(s: dict, memory) -> str | None:
    """No soil for farms (the farm scan failed) and the fort short of farm tiles."""
    if memory is None or not getattr(memory, "farm_failure", ""):
        return None
    return f"no soil for a farm ({memory.farm_failure})"


def pump_wanted(s: dict, cfg: dict) -> str | None:
    """No well and no cistern possible, and still water only below the fort."""
    w = _d(s.get("water"))
    wells = _d(_d(s.get("buildings")).get("other")).get("Well", 0)
    if wells or isinstance(w.get("cistern_status"), dict):
        return None
    c = _d(w.get("cistern"))
    if not c.get("none"):
        return None
    dw = _d(_d(s.get("map")).get("dwarves"))
    low = dw.get("z_bottom")
    pools = [b for b in _l(w.get("bodies")) if isinstance(b, dict) and b.get("kind") == "pool"]
    if not isinstance(low, int) or not any(int(_d(b.get("nearest")).get("z") or 10 ** 6) < low for b in pools):
        return None
    return "the fort has no well, no cistern site, and still water only below it"


def power_wanted(s: dict, works: dict, cfg: dict | None = None) -> str | None:
    """(0.105.37 E3) Why the pump stack wants power (None: it doesn't): the
    stack done (built, its reservoir filled once by hand) and not shut; a
    water wheel when a river runs near, else a windmill (the bridge finds out
    whether the map's wind turns it)."""
    pump = _d(_d(works).get("pump"))
    if pump.get("stage") != "done" or pump.get("shut"):
        return None
    if river_found(s, cfg if cfg is not None else PLANNER_CONFIG):
        return "the pump stack is worked by hand and a river runs near the fort"
    return "the pump stack is worked by hand"


def power_line(row: dict) -> str:
    """(0.105.37 E3) The power's numbers in words, for its note."""
    row = _d(row)
    src = {"wheel": "water wheel", "windmill": "windmill"}.get(row.get("source"), "")
    bits = []
    if src:
        n = row.get("wheels")
        bits.append(f"{n} {src}s" if isinstance(n, int) and n > 1 else f"a {src}")
    if isinstance(row.get("need"), int) and isinstance(row.get("have"), int):
        bits.append(f"{row['have']} power for {row['need']} needed")
    if isinstance(row.get("power"), int) and isinstance(row.get("power_need"), int):
        bits.append(f"the machine at {row['power']}/{row['power_need']}")
    if row.get("stage") == "running":
        bits.append("on" if row.get("engaged") else "off")
        if row.get("paused"):
            bits.append(f"paused ({row['paused']}; the pumps worked by hand)")
    return ", ".join(bits)


# (0.105.37 fix) The running power's check (the reservoir kept between 3/7 and
# 5/7, the wheel watched): a monitor asked every cycle. Its answer is always
# "waiting", so as an ordinary rule the refusal book and the 2-day cooldown
# held it (the power switched off up to 2 days late, the reservoir over-filled
# under power). Its own rule, outside the refusal book, the cooldown, the
# action limit and the loop guard, as an emergency rule.
POWER_RUN_RULE = "waterworks_power_run"
for _s in (EMERGENCY, NO_COOLDOWN, LIMIT_EXEMPT, LOOP_EXEMPT, STEER_PROTECTED):
    _s.add(POWER_RUN_RULE)


# (0.105.36) the bridge's RETIRE_MAX (lua/ai-waterworks.lua): retired this often, never begun again
WATERWORKS_RETIRE_MAX = 2

# (v35 fix) holds that watch for water still coming in: never retired
LEAK_WATCH_HOLDS = ("water is still getting in", "the floodgate is gone")


def leak_watch_hold(row: dict) -> bool:
    """(v35 fix) A held work whose hold watches for water still getting in
    (the farm room still wet) or whose floodgate is gone: retiring it would
    stop the watch while water may still flow into the fort."""
    why = str(_d(row).get("why") or "")
    return any(w in why for w in LEAK_WATCH_HOLDS)


def _work_notes(id_: str, row: dict, s: dict, proposals: list, notes: list, flooding: bool = False,
                now: int | None = None) -> bool:
    """A work under way: its line, and its next step (True: one asked; a
    leak-watch hold asks for a re-check but isn't busy: works elsewhere go on).
    (0.105.33) A work its emergency stop shut waits: no step is asked (the
    next one would open the floodgate again) until the flood is over, then
    it is asked to open again (`reopen`; the bridge waits a few days more)."""
    kind = row.get("kind")
    stage = row.get("stage")
    words = WORK_WORDS.get(kind, kind)
    if kind == "magma" and row.get("shop"):
        words = f"the {row['shop']} over the magma"
    line = f"{words}: {STAGE_WORDS.get(stage, stage)}"
    if row.get("depth") is not None and stage in ("filling", "done"):
        line += f", {row['depth']}/7 deep"
    if row.get("gate"):
        line += f", floodgate {row['gate']}"
    if kind == "power" and power_line(row):        # (0.105.37 E3)
        line += f", {power_line(row)}"
    if row.get("why"):
        line += f" ({row['why']})"
    notes.append(line)
    step = {"type": "water_work", "kind": kind}
    if kind == "magma" and row.get("shop"):
        step["shop"] = row["shop"]
    if stage == "held" and leak_watch_hold(row):
        # (v35 fix) water may still be getting in, or no floodgate is left to
        # shut: never retired (retiring stops the watch); kept watched, its
        # floodgate shut if it is open
        gone = "floodgate is gone" in str(row.get("why") or "")
        notes.append(f"{words} is held ({row.get('why')}): the AI keeps it watched and doesn't retire it while "
                     "water may still get in" + (" (a new floodgate is placed where it stood)" if gone else ""))
        if row.get("gate") == "open":
            proposals.append(Proposal(f"waterworks_{kind}", dict(step, shut=True, why="held: water still getting in"),
                                      f"{words} is held with its floodgate open ({row.get('why')}): shut it", 2))
        else:
            # (0.105.36) looked at again (the bridge answers "waiting", so the
            # refusal book asks every few days): the floodgate placed again if
            # it is gone, the room's wet tiles counted; un-held once dry
            proposals.append(Proposal(f"waterworks_{kind}", dict(step, recheck=True, why="recheck: the leak watch"),
                                      f"{words} is held ({row.get('why')}): look again"
                                      + (": place a new floodgate where it stood" if gone else
                                         ": un-held once it is dry"), 6))
        return False                     # (0.105.36) not busy: works elsewhere go on
    if stage == "held":
        # (0.105.35) nothing waits for the player: a held work (a leak, a lost
        # link, a floodgate shut again and again, a floor dried without mud)
        # is retired by the AI, its floodgate shut for good; the bridge keeps
        # it from being begun again for the retry wait, and for good after twice
        act = dict(step, retire=True, why=str(row.get("why") or "held")[:110])
        proposals.append(Proposal(f"waterworks_{kind}", act,
                                  f"{words} is held ({row.get('why')}): retire it, its floodgate shut for good "
                                  "(planned afresh after a while, at most twice; the old site only if its dry run "
                                  "passes again)", 4))
        return True
    if row.get("shut") and stage != "retired":
        notes.append(f"{words}: its floodgate was shut ({row['shut']})")
        if flooding:
            return True
        act = dict(step, reopen=True, why="reopen: no dwarves in deep water now")
        proposals.append(Proposal(f"waterworks_{kind}", act,
                                  f"{words}: the flood is over: open its floodgate again", 5))
        return True
    if kind == "power" and stage == "running":
        # (0.105.37 E3) the power kept on and off by the reservoir's depth, its
        # source and shaft watched: asked each cycle, not busy (works elsewhere go on)
        proposals.append(Proposal(POWER_RUN_RULE, step, f"{words}: running: the reservoir and the power check"
                                  + (f" (paused: {row['paused']})" if row.get("paused") else ""), 6))
        return False
    if stage in ("done", "retired"):
        # (0.105.0 review) a done work with its floodgate open: the bridge's done
        # step looks for a leak (and shuts it); it answers "waiting", so the
        # refusal book asks again every couple of days
        if stage == "done" and row.get("gate") == "open":
            proposals.append(Proposal("waterworks_check", step, f"{words}: done: the leak check", 7))
        return False
    # (0.105.36) the bridge sets the screw pumps to "Start pump manually"
    # (`manual`: how many); then the labour is given, once as pumping starts
    # and again when the reservoir stalls
    fresh = (isinstance(row.get("manual_since"), int) and isinstance(now, int)
             and 0 <= now - row["manual_since"] < 3 * 1200)
    if kind == "pump" and stage == "filling" and row.get("manual") and (row.get("stalled") or fresh):
        # (0.105.35) nothing waits for the player: the AI gives the pump operator labour itself
        n = max(1, min(6, int(row.get("lift") or 1)))
        proposals.append(Proposal("waterworks_pump_labor", {"type": "assign_labor", "job": "OPERATE_PUMP", "count": n},
                                  (f"the pump stack's reservoir isn't rising" if row.get("stalled") else
                                   f"the pump stack's {row.get('manual')} screw pump(s) are set to be worked by hand")
                                  + f": put {n} dwarf(s) on the pump operator labour (one a pump)", 3))
    for part, key in (("floodgate", "floodgates_free"), ("mechanisms", "mechanisms_free")):
        if row.get(key) == 0 and stage == "building":
            notes.append(f"{words} waits for {part} (none free)")
    proposals.append(Proposal(f"waterworks_{kind}", step, f"{words}: {STAGE_WORDS.get(stage, stage)}: the next step", 5))
    return True


def _waterworks_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """W3-W5 and magma workshops: the works under way stepped on; a new one
    started when the fort wants it and the Rules allow it."""
    ww = _d(s.get("waterworks"))
    if ww.get("error"):
        return
    rules_ = player_rules(s)
    works = {k: v for k, v in _d(ww.get("works")).items() if isinstance(v, dict)}
    refused = {k: v for k, v in _d(ww.get("refused")).items() if isinstance(v, dict)}
    # the emergency stop: dwarves in deep water near a work with an open floodgate
    h = _d(s.get("hazards"))
    flooded = len(_l(h.get("wet")))
    flooding = flooded >= cfg["flood_wet_dwarves"]
    if flooding:
        for id_, row in works.items():
            if ((row.get("gate") == "open" or (row.get("kind") == "power" and row.get("engaged")))   # (0.105.37 E3) the power too
                    and row.get("stage") != "retired" and not (row.get("kind") == "power" and row.get("shut"))):
                act = {"type": "water_work", "kind": row.get("kind"), "shut": True, "why": "dwarves in deep water"}
                if row.get("shop"):
                    act["shop"] = row["shop"]
                proposals.append(Proposal("waterworks_shut", act,
                                          f"{flooded} dwarves in deep water: "
                                          + (f"switch off {WORK_WORDS['power']}" if row.get("kind") == "power" else
                                             f"shut {WORK_WORDS.get(row.get('kind'))}'s floodgate"), 0))
    now = int(_d(s.get("date")).get("year") or 0) * TICKS_PER_YEAR + int(_d(s.get("date")).get("tick") or 0)
    busy = False
    for id_, row in sorted(works.items()):
        busy = _work_notes(id_, row, s, proposals, notes, flooding, now) or busy
    for id_, r in sorted(refused.items()):
        notes.append(f"{WORK_WORDS.get(id_.split(':')[0], id_)} not built: {r.get('why')}")
    if busy or not rules_["water_works"]:
        return
    if young_fort(s, cfg) or _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return

    def retry_ok(id_: str) -> bool:
        r = refused.get(id_)
        # (0.105.36) retired RETIRE_MAX (2) times: the bridge never begins it
        # again, so it is skipped and the next kind is looked at
        if r and isinstance(r.get("retired"), int) and r["retired"] >= WATERWORKS_RETIRE_MAX:
            return False
        wait = cfg["waterworks_retry_ticks"]
        if isinstance(r, dict) and r.get("later"):
            # (0.105.38 review) a search cut short by its time budget: soon again
            wait = cfg.get("waterworks_later_retry_ticks", 3 * 1200)
        elif id_.startswith("magma:"):
            # (0.105.38 review) a refused magma workshop: once a season, not
            # every cycle (the deep magma stays deep)
            wait = max(wait, cfg.get("waterworks_magma_retry_ticks", 84 * 1200))
        return not r or not isinstance(r.get("tick"), int) or now - r["tick"] >= wait

    def started(id_: str) -> bool:
        return id_ in works and works[id_].get("stage") != "retired"

    tr = _traits(s)
    eng = tr.get("engineering", 0) or 0
    # (1) the moat
    why = moat_wanted(s, cfg)
    if why and rules_["moat"] and not started("moat") and retry_ok("moat"):
        act = {"type": "water_work", "kind": "moat", **far_args(cfg)}
        if eng < cfg["moat_drawbridge_engineering"]:
            act["plain"] = True
        proposals.append(Proposal("waterworks_moat", act,
                                  f"{why}: dig a moat across the gate's approach, fed from the river through a "
                                  "floodgate (lever \"AI moat\"), crossed by a "
                                  + ("plain bridge" if act.get("plain") else "drawbridge the gate watcher works"), 6))
        return
    # (2) a magma workshop
    shop = magma_shop_wanted(s)
    mg = _d(_d(s.get("water")).get("magma"))
    # (0.105.38) the whole-map survey's magma bodies count too (a pipe found
    # far off; the magma sea): the cheapest, a pipe before the sea
    choice, opens = magma_choice(s, cfg) if shop else ("", False)
    if shop and rules_["magma_workshops"] and (mg or choice) and eng > -150:
        id_ = f"magma:{shop}"
        if not choice:
            if near_magma_too_deep(s):
                notes.append(f"magma was found, but deeper than a stair reaches ({MAGMA_STAIR_MAX} levels under "
                             "the fort): no magma workshop (the next survey says where)")
            else:
                notes.append("magma was found, but only in a cavern or by an older survey: no magma workshop "
                             "(the next survey says where)")
        elif not started(id_) and retry_ok(id_):
            from planner_building import magma_access
            acc = magma_access(_d(s.get("water")), s.get("map"))
            if choice == "near" and acc and acc.startswith("cavern:") and not any(
                    isinstance(b, dict) and b.get("kind") == "magma" and not b.get("opens_cavern")
                    for b in _l(_d(s.get("water")).get("waters"))):
                notes.append("no magma workshop: the magma lies beneath a cavern (reaching it would open the cavern)")
            else:
                act = {"type": "water_work", "kind": "magma", "shop": shop, **far_args(cfg)}
                if choice != "near" and (opens or player_rules(s)["open_caverns"] == "always"):
                    # the cavern switch allows it (Always, or the AI's call:
                    # no other way to magma); the bridge walks the planned dig
                    act["open_caverns"] = True
                where = "the magma" if choice == "near" else f"the magma {choice}"
                proposals.append(Proposal("waterworks_magma", act,
                                          f"dig a {shop} over {where}: a pit fed through a floodgate "
                                          "(lever \"AI magma\"), its service stair under a locked hatch"
                                          + (" (its way opens a cavern: the cavern switch allows it)" if opens else ""), 6))
                return
    # (3) irrigation
    why = irrigation_wanted(s, memory)
    if why and rules_["irrigation"] and not started("irrigation") and retry_ok("irrigation"):
        proposals.append(Proposal("waterworks_irrigation", {"type": "water_work", "kind": "irrigation", **far_args(cfg)},
                                  f"{why}: dig a farm room in stone, let a little water in through a floodgate "
                                  "(lever \"AI irrigation\") to muddy it, let it dry, then lay farm plots", 5))
        return
    # (4) pumps
    why = pump_wanted(s, cfg)
    if why and eng >= cfg["pump_engineering"] and not started("pump") and retry_ok("pump"):
        proposals.append(Proposal("waterworks_pump", {"type": "water_work", "kind": "pump", **far_args(cfg)},
                                  f"{why}: a screw pump stack lifts it to a reservoir under the fort "
                                  "(a dwarf works the pumps)", 6))
        return
    # (5) (0.105.37 E3) W7: the pump stack's power, at Guided and Architect
    why = power_wanted(s, works, cfg)
    if (why and eng >= cfg["pump_engineering"] and not started("power") and retry_ok("power")
            and _design_mode(s) != "scripts"):
        source = "wheel" if river_found(s, cfg) else "windmill"
        proposals.append(Proposal("waterworks_power", {"type": "water_work", "kind": "power", "source": source,
                                                       **far_args(cfg)},
                                  f"{why}: power it with a "
                                  + ("water wheel on the river" if source == "wheel" else "windmill")
                                  + ", joined to its top pump by axles and gears through solid rock, switched by a "
                                  "lever (\"AI pump power\") to keep the reservoir filled (no dwarf at the pumps)", 6))

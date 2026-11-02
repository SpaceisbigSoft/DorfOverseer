"""(0.105.0) Water works and magma: the moat (W3), the pump stack (W4), the
muddied farm level (W5) and magma workshops, built a step at a time by the
bridge (lua/ai-waterworks.lua, the `water_work` action).

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
from planner_core import Proposal, ask_player, player_rules, young_fort, _traits

__all__ = ["_waterworks_rule", "WORK_WORDS", "STAGE_WORDS", "moat_wanted", "magma_shop_wanted",
           "irrigation_wanted", "pump_wanted", "river_found"]

WORK_WORDS = {"moat": "the moat", "pump": "the pump stack", "irrigation": "the muddied farm level",
              "magma": "the magma workshop"}
STAGE_WORDS = {"planned": "planned (its water's path checked)", "digging": "being dug",
               "building": "its floodgate, lever and buildings being built", "linking": "its lever being linked",
               "filling": "filling", "drying": "drying", "finishing": "being finished", "done": "done",
               "held": "held", "retired": "retired"}
MAGMA_ORDER = ("MagmaForge", "MagmaSmelter", "MagmaGlassFurnace")


def river_found(s: dict) -> bool:
    return any(isinstance(b, dict) and b.get("kind") == "river" and int(b.get("tiles") or 0) > 0
               for b in _l(_d(s.get("water")).get("bodies")))


def moat_wanted(s: dict, cfg: dict) -> str | None:
    """Why a moat (None: not wanted): Fortification high enough, a river
    found, a surface gate scanned, no threat near (no digging under fire)."""
    tr = _traits(s)
    if (tr.get("fortification", 0) or 0) < cfg["moat_fortification"]:
        return None
    if not river_found(s):
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


def _work_notes(id_: str, row: dict, s: dict, proposals: list, notes: list) -> bool:
    """A work under way: its line, and its next step (True: one asked)."""
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
    if row.get("why"):
        line += f" ({row['why']})"
    notes.append(line)
    step = {"type": "water_work", "kind": kind}
    if kind == "magma" and row.get("shop"):
        step["shop"] = row["shop"]
    if stage == "held":
        ask_player(notes, f"{words} is held: {row.get('why')}. Mend it, or the AI retires it "
                          "(its floodgate stays shut)")
        return False
    if stage in ("done", "retired"):
        if stage == "done" and row.get("gate") == "open" and kind in ("magma", "pump", "irrigation"):
            pass      # the bridge's done step watches for leaks
        return False
    if row.get("stalled"):
        ask_player(notes, "the pump stack's reservoir isn't rising: give a dwarf the pump operator labour "
                          "(or the pumps lack power)")
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
    if flooded >= cfg["flood_wet_dwarves"]:
        for id_, row in works.items():
            if row.get("gate") == "open" and row.get("stage") not in ("done", "retired"):
                act = {"type": "water_work", "kind": row.get("kind"), "shut": True, "why": "dwarves in deep water"}
                if row.get("shop"):
                    act["shop"] = row["shop"]
                proposals.append(Proposal("waterworks_shut", act,
                                          f"{flooded} dwarves in deep water: shut {WORK_WORDS.get(row.get('kind'))}'s floodgate", 0))
    busy = False
    for id_, row in sorted(works.items()):
        busy = _work_notes(id_, row, s, proposals, notes) or busy
    for id_, r in sorted(refused.items()):
        notes.append(f"{WORK_WORDS.get(id_.split(':')[0], id_)} not built: {r.get('why')}")
    if busy or not rules_["water_works"]:
        return
    if young_fort(s, cfg) or _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return
    now = int(_d(s.get("date")).get("year") or 0) * 403200 + int(_d(s.get("date")).get("tick") or 0)

    def retry_ok(id_: str) -> bool:
        r = refused.get(id_)
        return not r or not isinstance(r.get("tick"), int) or now - r["tick"] >= cfg["waterworks_retry_ticks"]

    def started(id_: str) -> bool:
        return id_ in works and works[id_].get("stage") != "retired"

    tr = _traits(s)
    eng = tr.get("engineering", 0) or 0
    # (1) the moat
    why = moat_wanted(s, cfg)
    if why and rules_["moat"] and not started("moat") and retry_ok("moat"):
        act = {"type": "water_work", "kind": "moat"}
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
    if shop and rules_["magma_workshops"] and mg and eng > -150:
        id_ = f"magma:{shop}"
        if not mg.get("top_nearest"):
            notes.append("magma was found, but only in a cavern or by an older survey: no magma workshop "
                         "(the next survey says where)")
        elif not started(id_) and retry_ok(id_):
            from planner_building import magma_access
            acc = magma_access(_d(s.get("water")), s.get("map"))
            if acc and acc.startswith("cavern:"):
                notes.append("no magma workshop: the magma lies beneath a cavern (reaching it would open the cavern)")
            else:
                proposals.append(Proposal("waterworks_magma", {"type": "water_work", "kind": "magma", "shop": shop},
                                          f"dig a {shop} over the magma: a pit fed through a floodgate "
                                          "(lever \"AI magma\"), its service stair under a locked hatch", 6))
                return
    # (3) irrigation
    why = irrigation_wanted(s, memory)
    if why and rules_["irrigation"] and not started("irrigation") and retry_ok("irrigation"):
        proposals.append(Proposal("waterworks_irrigation", {"type": "water_work", "kind": "irrigation"},
                                  f"{why}: dig a farm room in stone, let a little water in through a floodgate "
                                  "(lever \"AI irrigation\") to muddy it, let it dry, then lay farm plots", 5))
        return
    # (4) pumps
    why = pump_wanted(s, cfg)
    if why and eng >= cfg["pump_engineering"] and not started("pump") and retry_ok("pump"):
        proposals.append(Proposal("waterworks_pump", {"type": "water_work", "kind": "pump"},
                                  f"{why}: a screw pump stack lifts it to a reservoir under the fort "
                                  "(a dwarf works the pumps)", 6))

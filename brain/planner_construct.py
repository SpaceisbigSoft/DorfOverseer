"""planner_construct (0.105.30, construction G4): the keeper builds, not only
digs. The brain's side of docs/construction (the spec's G4):

- `_hall_rule`: one surface hall a fort (`place_hall`, lua/ai-builder-halls.lua),
  a field hall for the Garden fort (Surface 50+), a market hall by the depot
  for the Merchant city (Surface 30+ with Trade 80+). One stage a call; a
  stage starts only when the last one's planned tiles are built, the fort's
  planned construction tiles stay under `hall_max_planned`, and its blocks are
  free (any material after `hall_block_wait_ticks`).
- `_construction_blocks_rule`: stone blocks for what the keep, the hall, the
  wings and the soil floors still need, outside the idle-hands cap.
- `_wings_rule` (called from planner_gates after the gatehouse): two wall arms
  from a standing gatehouse, once per entrance (the War-hold).
- `cavern_wall_style`: the Hermit's `sealed` gate style for narrow cavern
  openings (planner_gates._gate_rules).
- `_soil_floor_rule` (called from planner_building's project steps): block
  floors over the soil of a finished dining hall, tavern, temple, library or
  memorial, once per project.
- `note_construct_cycle` / `note_construct`: the bookkeeping (note_cycle and
  record()), kept in `memory.construct`.

Every rule here is quiet with the in-game halt, the construction switch off
on the Rules tab (settings `construct`), a crisis, a threat that can reach
the dwarves, a siege held off at the gates, the alarm up or the gates
watched (`construct_quiet`). Each has its own cooldown (`<rule>_cooldown_ticks`)
and its actions back off through note_refusal like any other; a stage that
keeps "succeeding" without moving is caught by the loop limit."""

from __future__ import annotations

import math

import customs
import masterplan
from quirks import has_rule
from digest import _d, _l
from planner_core import *  # noqa: F401,F403

__all__ = ["HALL_STAGES", "HALL_OPEN", "KEEP_OPEN", "HALL_MAX_INTERIOR", "SOIL_FLOOR_KINDS",
           "construct_quiet", "hall_kind", "hall_status", "keep_wanted", "keep_open", "hall_open",
           "keep_failures", "planned_constructions", "hall_next", "hall_opts", "hall_blocks_needed", "_hall_rule", "_construction_blocks_rule",
           "wings_wanted", "_wings_rule", "cavern_wall_style", "soil_floor_wanted", "_soil_floor_rule",
           "note_construct_cycle", "note_construct", "construct_memory"]

# The hall's stages (lua/ai-builder-halls.lua place_hall), in order.
HALL_STAGES = ("clearing", "walls", "floor", "roof", "furnish", "zone", "done")
# A project "builds" (one at a time) from its clearing to its roof.
HALL_OPEN = ("clearing", "walls", "floor", "roof")
KEEP_OPEN = ("clearing", "walls", "stair", "roof")
# 9x7 footprint, 7x5 interior: under ai-gates LEDGE_MAX (120), so a dwarf eating
# there never seeds a second "fort" for the gates (the spec asserts 63)
HALL_MAX_INTERIOR = 63
SOIL_FLOOR_KINDS = ("dining", "tavern", "temple", "library", "memorial")
# planned tiles per hall stage when the bridge doesn't say (28 walls, 35
# interior floor, 35 roof + the stair)
_STAGE_PLANNED_KEYS = {"walls": ("walls_planned",), "floor": ("floor_planned",),
                       "roof": ("roof_planned",), "clearing": ()}


def construct_memory(memory) -> dict:
    """memory.construct, made a dict if it isn't one (an old save)."""
    c = getattr(memory, "construct", None)
    if not isinstance(c, dict):
        c = {}
        try:
            memory.construct = c
        except AttributeError:
            pass
    return c


def construct_quiet(s: dict, memory, traits: dict, cfg: dict, rules_: dict | None = None) -> str | None:
    """Why no construction may start now (None: it may). The halt, the Rules
    tab, a crisis, the alarm, threats that can reach the dwarves, a siege
    held off at the gates, or a threat seen in the last few days."""
    if s.get("halted") is True:
        return "halted in the game"
    st = s.get("settings") if isinstance(s.get("settings"), dict) else {}
    if st.get("construct") is False or _d(rules_).get("construct") is False:
        return "building above ground is off on the Rules tab"
    if memory is not None and _d(getattr(memory, "crisis", None)).get("why"):
        return "the fort is in crisis"
    o = _d(s.get("others_on_map"))
    if o.get("threats_that_can_reach_dwarves") or reachable_threats(s, traits, cfg):
        return "threats can reach the dwarves"
    if held_off_threats(s):
        return "a siege is held off at the gates"
    if s.get("civ_alert") or _d(s.get("entrances")).get("armed") or (
            memory is not None and getattr(memory, "ai_alert_raised", False)):
        return "the alarm is up"
    last = getattr(memory, "last_threat_tick", None) if memory is not None else None
    if isinstance(last, int) and 0 <= abs_tick(s) - last < cfg["construct_quiet_ticks"]:
        return "a threat was about only days ago"
    return None


def keep_wanted(traits: dict, cfg: dict, memory=None) -> bool:
    """The keep's own trait test (_keep_rule)."""
    if masterplan.underground_only(traits):
        return False
    return traits.get("surface", 0) >= cfg["keep_surface_min"] or (
        memory is not None and has_rule(getattr(memory, "culture", None), "keep_above"))


def keep_open(s: dict) -> str | None:
    """The keep's stage while it builds (clearing to roof), else None."""
    k = _d(s.get("buildings")).get("keep")
    if isinstance(k, dict) and k.get("stage") in KEEP_OPEN:
        return k["stage"]
    return None


def hall_status(s: dict) -> dict | None:
    """The fort's surface hall (halls_status, in buildings.halls): one a fort
    this round. The bridge may send the status itself or {list = {...}}."""
    h = _d(s.get("buildings")).get("halls")
    if isinstance(h, list):
        h = next((x for x in h if isinstance(x, dict)), None)
    if not isinstance(h, dict) or h.get("error"):
        return None
    if isinstance(h.get("list"), list):
        x = next((x for x in h["list"] if isinstance(x, dict)), None)
        if x is None:
            return None
        return {**{k: v for k, v in h.items() if k != "list"}, **x}
    return h if h.get("stage") else None


def hall_open(s: dict) -> str | None:
    h = hall_status(s)
    if h and h.get("stage") in HALL_OPEN:
        return h["stage"]
    return None


def keep_failures(memory) -> int:
    """How often the keep was refused in a row (F: 133)."""
    if memory is None:
        return 0
    key = refusal_key(Proposal("keep", {"type": "place_keep"}, "", 7))
    return int(_d(_d(getattr(memory, "refusals", None)).get(key)).get("n") or 0)


def planned_constructions(s: dict) -> int:
    """Construction tiles placed and not yet built: buildingplan's waiting
    walls and floors (get_buildings) or the constructions survey."""
    b = _d(s.get("buildings"))
    a = _d(b.get("being_built")).get("Construction")
    c = _d(_d(s.get("constructions")).get("planned")).get("n")
    return max(int(a) if isinstance(a, int) else 0, int(c) if isinstance(c, int) else 0)


def hall_kind(s: dict, traits: dict, cfg: dict) -> str | None:
    """field_hall (the Garden fort) or market_hall (the Merchant city), or None."""
    if masterplan.underground_only(traits) or customs.has(traits, "hidden_hold"):
        return None
    surface, trade = traits.get("surface", 0) or 0, traits.get("trade", 0) or 0
    depot = bool(_d(_d(s.get("buildings")).get("other")).get("TradeDepot"))
    if surface >= cfg["hall_merchant_surface_min"] and trade >= cfg["hall_merchant_trade_min"] and depot:
        return "market_hall"
    if surface >= cfg["hall_surface_min"]:
        return "field_hall"
    return None


def _stage_planned(h: dict) -> int:
    stage = h.get("stage")
    keys = _STAGE_PLANNED_KEYS.get(stage)
    if keys is None:
        keys = ("walls_planned", "floor_planned", "roof_planned")
    return sum(int(h.get(k) or 0) for k in keys if isinstance(h.get(k), int))


def _next_tiles(h: dict | None, traits: dict, cfg: dict) -> tuple[str, int]:
    """The stage the next call places and its construction tiles."""
    tiles = cfg["hall_stage_tiles"]
    stage = h.get("stage") if h else None
    if stage in (None, "clearing"):
        nxt = "walls"
    elif stage == "walls":
        nxt = "floor" if (traits.get("craftsmanship", 0) or 0) >= cfg["hall_floor_craftsmanship"] else "roof"
    elif stage == "floor":
        nxt = "roof"
    else:
        nxt = {"roof": "furnish", "furnish": "zone", "zone": "done"}.get(stage, "done")
    need = h.get("next_tiles") if h else None          # the bridge's own count for that stage, where sent
    if isinstance(need, int) and need >= 0:
        return nxt, need
    return nxt, int(tiles.get(nxt, 0))


def hall_blocks_needed(s: dict, cfg: dict, citizens: int, traits: dict, memory=None) -> int:
    """Blocks the hall still needs (halls_status blocks_needed, else its
    stages' tiles left), while a hall is wanted and may build."""
    if not hall_kind(s, traits, cfg) or construct_quiet(s, memory, traits, cfg):
        return 0
    if young_fort(s, cfg) or citizens < cfg["hall_min_citizens"]:
        return 0
    h = hall_status(s)
    if h and h.get("stage") == "done":
        return 0
    n = h.get("blocks_needed") if h else None
    if isinstance(n, int):
        return max(0, n)
    d = hall_next(s, cfg, citizens, traits, memory)
    if not d or d[0] == "note" and not h:
        return 0                                   # the keep goes first, say
    order = ("walls", "floor", "roof")
    stage = h.get("stage") if h else None
    left = [x for x in order if stage in (None, "clearing") or order.index(x) > (
        order.index(stage) if stage in order else 99)]
    if "floor" in left and (traits.get("craftsmanship", 0) or 0) < cfg["hall_floor_craftsmanship"]:
        left.remove("floor")
    return sum(int(cfg["hall_stage_tiles"].get(x, 0)) for x in left)


def hall_next(s: dict, cfg: dict, citizens: int, traits: dict, memory=None, rules_: dict | None = None):
    """What the hall does now: None (nothing, quietly), ("note", text),
    ("short", stage, tiles, text): ready but for free blocks, or
    ("go", kind, stage, tiles, why)."""
    kind = hall_kind(s, traits, cfg)
    h = hall_status(s)
    if h and h.get("kind") in ("field_hall", "market_hall") and kind:
        kind = h["kind"]                       # the hall standing keeps its kind
    if not kind or (h and h.get("stage") == "done"):
        return None
    if construct_quiet(s, memory, traits, cfg, rules_):
        return None
    if h:
        stage = h.get("stage")
        if stage == "clearing" and h.get("trees_left"):
            return ("note", f"the {kind.replace('_', ' ')}: the woodcutters fell {h['trees_left']} tree(s) "
                            "in the way of its walls")
        left = _stage_planned(h)
        if left > 0:
            return ("note", f"the {kind.replace('_', ' ')}: {left} {stage} tile(s) still to build")
    if young_fort(s, cfg) or citizens < cfg["hall_min_citizens"]:
        return None
    ks = keep_open(s)
    if ks and not (h and h.get("stage") in HALL_OPEN):
        return ("note", f"the {kind.replace('_', ' ')} waits for the keep ({ks}): one building above ground "
                        "at a time")
    if (not h and not ks and keep_wanted(traits, cfg, memory)
            and not isinstance(_d(s.get("buildings")).get("keep"), dict)
            and keep_failures(memory) < cfg["hall_keep_failures"]):
        return None                            # the keep goes first; the hall once it fails 3 times
    stage, tiles = _next_tiles(h, traits, cfg)
    planned = planned_constructions(s)
    if tiles and planned + tiles > cfg["hall_max_planned"]:
        return ("note", f"the {kind.replace('_', ' ')} waits: {planned} construction tile(s) already wait "
                        f"to be built (at most {cfg['hall_max_planned']} at once)")
    if tiles:
        free = free_stock(s, "blocks")
        if free < tiles:
            st = _d(s.get("stocks"))
            any_ = free + int(st.get("boulders") or 0) + int(st.get("wood") or 0)
            since = _d(construct_memory(memory).get("hall_short")) if memory is not None else {}
            waited = (isinstance(since.get("since"), int) and since.get("stage") == stage
                      and abs_tick(s) - since["since"] >= cfg["hall_block_wait_ticks"])
            if not (waited and any_ >= tiles):
                return ("short", stage, tiles,
                        f"the {kind.replace('_', ' ')} waits for {tiles} blocks for its {stage} "
                        f"({free} free)" + (": building stone, blocks or logs are short too"
                                            if waited else ""))
    if not h:
        why = (f"Surface ambition: a {'market hall by the trade depot' if kind == 'market_hall' else 'hall by the fields'}, "
               "a walled and roofed dining hall above ground (9 by 7, one door)")
    else:
        why = {"clearing": f"the {kind.replace('_', ' ')}: the trees are down, raise its walls and door",
               "walls": f"the {kind.replace('_', ' ')}: its walls stand, lay its floor or roof",
               "floor": f"the {kind.replace('_', ' ')}: its floor is laid, put a roof over it",
               "roof": f"the {kind.replace('_', ' ')}: its roof is built, furnish it",
               "furnish": f"the {kind.replace('_', ' ')}: furnished, make it a dining hall",
               "zone": f"the {kind.replace('_', ' ')}: call it finished"}.get(
            h.get("stage"), f"the {kind.replace('_', ' ')}: its next step")
    return ("go", kind, stage, tiles, why)


def _hall_rule(s: dict, cfg: dict, citizens: int, traits: dict, proposals: list, notes: list,
               memory=None, rules_: dict | None = None) -> None:
    """(0.105.30, construction 3.1) The surface hall, one stage a call."""
    d = hall_next(s, cfg, citizens, traits, memory, rules_)
    if not d:
        return
    if d[0] in ("note", "short"):
        notes.append(d[-1])
        return
    _, kind, stage, tiles, why = d
    proposals.append(Proposal("hall", {"type": "place_hall", "kind": kind, **hall_opts(traits, cfg)}, why, 7))


def hall_opts(traits: dict, cfg: dict) -> dict:
    """(0.105.30, construction seams) What the sliders give the hall
    (place_hall's opts, spec 3.1): glass windows with Grandeur 40+, a block
    floor over the soil with Craftsmanship 40+, a statue with Grandeur 40+
    (the bridge places windows and the statue only when free ones lie in
    stock)."""
    g = traits.get("grandeur", 0) or 0
    c = traits.get("craftsmanship", 0) or 0
    return {"windows": g >= cfg["hall_windows_grandeur"],
            "floor": c >= cfg["hall_floor_craftsmanship"],
            "statue": g >= cfg["hall_statue_grandeur"]}


def wings_wanted(traits: dict, cfg: dict) -> bool:
    """The War-hold: Fortification 100+, Surface above -50, not hidden."""
    return ((traits.get("fortification", 0) or 0) >= cfg["wings_fortification"]
            and (traits.get("surface", 0) or 0) > cfg["wings_surface_above"]
            and not masterplan.underground_only(traits)
            and not customs.has(traits, "hidden_hold"))


def _wings_pending(s: dict, memory, cfg: dict, traits: dict) -> list:
    """Entrances with a standing gatehouse and no wings yet (nor a refusal
    still waiting out gate_retry_ticks)."""
    if not wings_wanted(traits, cfg):
        return []
    now = abs_tick(s)
    done = _d(construct_memory(memory).get("wings")) if memory is not None else {}
    out = []
    for e in _l(_d(s.get("entrances")).get("entrances")):
        if not (isinstance(e, dict) and e.get("gatehouse") == "standing"):
            continue
        if e.get("wings") in ("standing", "planned"):
            continue
        spot = f"{e.get('x')},{e.get('y')},{e.get('z')}"
        if spot in done:
            continue
        if memory is not None:
            when = memory.gate_failure_ticks.get("wings:" + spot)
            if "wings:" + spot in memory.gate_failures and isinstance(when, int) \
                    and 0 <= now - when < cfg["gate_retry_ticks"]:
                continue
        out.append((e, spot))
    return out


def _wings_rule(s: dict, memory, cfg: dict, es: list, now: int, traits: dict, proposals: list,
                notes: list | None = None) -> None:
    """(0.105.30, construction 3.2) Two wall arms from the gatehouse's front
    corners (lua/ai-gates.lua build_wings), once per entrance. Never hidden,
    never during an alert or a siege; one a cycle."""
    if construct_quiet(s, memory, traits, cfg):
        return
    pend = _wings_pending(s, memory, cfg, traits)
    if not pend:
        return
    e, spot = pend[0]
    proposals.append(Proposal("wings", {"type": "build_wings", "entrance_id": e.get("id")},
                              f"a fortified fort (Fortification {int(traits.get('fortification', 0)):+d}): "
                              f"wall arms of up to {cfg['wings_len']} tiles from the gatehouse at x{e.get('x')} "
                              f"y{e.get('y')}, a funnel to its drawbridge", 6))


def cavern_wall_style(e: dict, traits: dict, cfg: dict, memory, style: str, now: int | None = None) -> str:
    """(0.105.30, construction 3.4) The Hermit hold walls a narrow cavern
    opening for good (`sealed`: walls, no door) instead of `style`. The
    bridge refuses it with a citizen beyond, a cavern well or water plan on
    that layer, or a walk to a citizen cut: a refused spot keeps the usual
    style for `cavern_wall_retry_ticks`."""
    if not (e.get("kind") == "cavern" and isinstance(e.get("width"), int)
            and 0 < e["width"] <= cfg["cavern_wall_max_width"]):
        return style
    if not ((traits.get("fortification", 0) or 0) >= cfg["cavern_wall_fortification"]
            and (traits.get("surface", 0) or 0) <= cfg["cavern_wall_surface_max"]
            and (traits.get("outsiders", 0) or 0) <= cfg["cavern_wall_outsiders_max"]):
        return style
    spot = f"{e.get('x')},{e.get('y')},{e.get('z')}"
    refused = _d(construct_memory(memory).get("sealed_refused")) if memory is not None else {}
    when = refused.get(spot)
    if isinstance(when, int) and (not isinstance(now, int) or 0 <= now - when < cfg["cavern_wall_retry_ticks"]):
        return style
    return "sealed"


def soil_floor_wanted(traits: dict, cfg: dict) -> bool:
    return ((traits.get("grandeur", 0) or 0) >= cfg["soil_floor_grandeur"]
            or (traits.get("craftsmanship", 0) or 0) >= cfg["soil_floor_craftsmanship"])


def _soil_candidates(s: dict, memory, cfg: dict) -> list:
    """(project id, kind, soil tiles or None) for finished projects of the
    kinds that get floors, not floored yet nor given up on. The bridge's
    soil_floor_report, where sent (projects.soil_floors or
    constructions.soil_floors), says which have soil and how much."""
    c = construct_memory(memory) if memory is not None else {}
    done = set(str(x) for x in _l(c.get("floored")))
    tries = _d(c.get("floor_tries"))
    rep = _d(s.get("projects")).get("soil_floors")
    if rep is None:
        rep = _d(s.get("constructions")).get("soil_floors")
    known: dict = {}
    if isinstance(rep, dict):
        rep = [{"project_id": k, "tiles": v} for k, v in rep.items()]
    for r in _l(rep):
        if isinstance(r, dict) and r.get("project_id") is not None:
            known[str(r["project_id"])] = r
    out = []
    for p in _l(_d(s.get("projects")).get("decorating")):
        if not (isinstance(p, dict) and p.get("kind") in SOIL_FLOOR_KINDS and p.get("id") is not None):
            continue
        pid = str(p["id"])
        if pid in done or int(tries.get(pid) or 0) >= cfg["soil_floor_tries"]:
            continue
        r = known.get(pid)
        tiles = r.get("tiles") if r else None
        if r is not None and isinstance(tiles, int) and tiles <= 0:
            continue                           # no soil there: nothing to floor
        out.append((p["id"], p.get("kind"), tiles if isinstance(tiles, int) else None))
    return out


def _soil_floor_rule(s: dict, traits: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """(0.105.30, construction 3.3) Block floors over the soil of a finished
    hall (soil can't be smoothed), once per project, one a cycle. Blocks only:
    it waits until the free blocks cover the tiles."""
    if not soil_floor_wanted(traits, cfg) or construct_quiet(s, memory, traits, cfg):
        return
    cands = _soil_candidates(s, memory, cfg)
    if not cands:
        return
    pid, kind, tiles = cands[0]
    need = min(tiles, cfg["soil_floor_max_tiles"]) if isinstance(tiles, int) else cfg["soil_floor_max_tiles"]
    free = free_stock(s, "blocks")
    if free < need:
        notes.append(f"the {kind} level #{pid}: its soil floor waits for {need} blocks ({free} free)")
        return
    planned = planned_constructions(s)
    if planned + need > cfg["hall_max_planned"]:
        notes.append(f"the {kind} level #{pid}: its soil floor waits ({planned} construction tile(s) "
                     "already wait to be built)")
        return
    proposals.append(Proposal("soil_floor", {"type": "floor_rooms", "project_id": pid},
                              f"the {kind} level #{pid} is finished: block floors over its soil (soil can't be "
                              "smoothed or engraved)", 7))


def _construction_blocks_rule(s: dict, cfg: dict, citizens: int, traits: dict, proposals: list, notes: list,
                              memory=None) -> None:
    """(0.105.30, construction 3.6) Stone blocks for what is to be built: the
    keep, the hall, the wings and the soil floors. Outside the idle-hands cap
    (500); at most construct_blocks_max_jobs jobs, and only from stone the
    masons may use. Not when idle hands already order blocks this cycle."""
    if s.get("halted") is True or any(
            p.action.get("type") == "work_order" and p.action.get("recipe") == "stone_blocks" for p in proposals):
        return
    if memory is not None and _d(getattr(memory, "crisis", None)).get("why"):
        return
    st_ = s.get("settings") if isinstance(s.get("settings"), dict) else {}
    if st_.get("construct") is False:
        return
    need, what = 0, []
    k = _d(s.get("buildings")).get("keep")
    if keep_wanted(traits, cfg, memory) and isinstance(k, dict) and k.get("stage") != "done":
        n = k.get("blocks_needed")
        if isinstance(n, int) and n > 0:
            need += n
            what.append("the keep")
    n = hall_blocks_needed(s, cfg, citizens, traits, memory)
    if n > 0:
        need += n
        what.append("the hall")
    if memory is not None:
        w = len(_wings_pending(s, memory, cfg, traits))
        if w and not construct_quiet(s, memory, traits, cfg):
            need += w * cfg["wings_blocks"]
            what.append("the wings")
    if soil_floor_wanted(traits, cfg):
        for _pid, _k, tiles in _soil_candidates(s, memory, cfg)[:1]:
            need += min(tiles, cfg["soil_floor_max_tiles"]) if isinstance(tiles, int) else cfg["soil_floor_max_tiles"]
            what.append("soil floors")
    if need <= 0:
        return
    per_job = cfg["blocks_per_job"]
    have = free_stock(s, "blocks") + queued(s, {"stone_blocks"}) * per_job
    want = math.ceil(need * cfg["construct_blocks_margin"])
    if have >= want:
        return
    gap = want - have
    jobs = min(cfg["construct_blocks_max_jobs"], math.ceil(gap / per_job))
    usable = _d(s.get("stone_use")).get("usable")
    stone = usable if isinstance(usable, int) else int(_d(s.get("stocks")).get("boulders") or 0)
    if stone < math.ceil(gap / per_job):
        notes.append(f"{', '.join(what)} want(s) {need} blocks ({have} free or ordered), but only {stone} "
                     "usable stone for the masons")
        return
    proposals.append(Proposal("construct_blocks", {"type": "work_order", "recipe": "stone_blocks", "amount": jobs},
                              f"{', '.join(what)} want(s) {need} blocks to build with ({have} free or ordered): "
                              f"make {jobs * per_job}", 6, True))


def note_construct_cycle(s: dict, memory, cfg: dict) -> None:
    """Before planning: when the hall began to wait for blocks (its stage),
    so after hall_block_wait_ticks it builds with any material."""
    c = construct_memory(memory)
    now = abs_tick(s)
    traits = _traits(s)
    citizens = max(1, _d(s.get("dwarves")).get("total", 0) or 0)
    d = hall_next(s, cfg, citizens, traits, memory)
    if d and d[0] == "short":
        old = _d(c.get("hall_short"))
        if old.get("stage") != d[1] or not isinstance(old.get("since"), int):
            c["hall_short"] = {"stage": d[1], "since": now}
    elif d is None and c.get("hall_short") and not hall_kind(s, traits, cfg):
        c.pop("hall_short", None)                    # no hall wanted any more
    # (a "go" keeps it until the stage is placed: note_construct)


def note_construct(p, r: dict, state: dict, memory, now: int) -> None:
    """After acting (planner.record): the wings built once per entrance, a
    sealed gate's refusal, the soil floors once per project, the hall's
    block wait reset when a stage is placed."""
    a = _d(getattr(p, "action", None))
    t = a.get("type")
    ok = r.get("ok")
    if a.get("dry_run") or r.get("halted"):
        return
    c = construct_memory(memory)
    if t == "place_hall" and ok is True:
        c.pop("hall_short", None)
    elif t == "build_wings":
        spot = _entrance_spot(state, a.get("entrance_id"))
        if not spot:
            return
        if ok is True or r.get("nothing_to_do"):
            c.setdefault("wings", {})[spot] = now
            memory.gate_failures.pop("wings:" + spot, None)
            memory.gate_failure_ticks.pop("wings:" + spot, None)
        else:
            memory.gate_failures["wings:" + spot] = str(r.get("error") or "no answer from the game")[:300]
            memory.gate_failure_ticks["wings:" + spot] = now
    elif t == "fortify_entrance" and a.get("style") == "sealed" and ok is False:
        spot = _entrance_spot(state, a.get("entrance_id"))
        if spot:
            c.setdefault("sealed_refused", {})[spot] = now
    elif t == "floor_rooms" and a.get("project_id") is not None:
        pid = str(a["project_id"])
        if ok is True or r.get("nothing_to_do"):
            fl = [x for x in _l(c.get("floored")) if str(x) != pid]
            c["floored"] = (fl + [pid])[-200:]
            _d(c.get("floor_tries")).pop(pid, None)
        elif ok is False and not r.get("timed_out"):
            tries = c.setdefault("floor_tries", {})
            tries[pid] = int(tries.get(pid) or 0) + 1

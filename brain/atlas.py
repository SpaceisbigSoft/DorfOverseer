"""The atlas: where things are, and where things happened.

    atlas.survey_due(state, memory)              # first day, each season, or something new found
    atlas.survey(state, memory)                  # -> discoveries, in words
    atlas.note_registry(state, memory)           # the AI's projects, checked against the game's list
    atlas.note_actions(results, state, memory)   # gates, doors, pastures, farm plots the AI made
    atlas.note_events(state, memory, events)     # deaths, floods, cave-ins, threats at a gate, with x, y, z
    atlas.consolidate(memory, now)               # events over a year old become clusters
    atlas.notable(memory)                        # "the surface gate x31 y140: 3 deaths, 5 threats"

Kept in memory.atlas:
  survey     map size, layers (caverns, magma, underworld) and when each was first found,
             the levels the dwarves use, soil and farms, last surveyed
  plan       the master plan's home (empty until milestone 4)
  registry   id -> what the AI built: kind, variant (its style), era, elevation, bounds
             ("b": [x1, y1, x2, y2, z]), when (tick), status and when that last changed
  entrances  "x,y,z" -> kind, width, first seen, gate history, and counts of what happened there
  events     located events from the last year: kind, x, y, z, tick, what, near
  clusters   older events summed up by kind and place

The registry is how later milestones know a wall is the AI's own to take down,
and the located events are what will judge a gate or a farm.
"""

from __future__ import annotations

from digest import _d, _l, normalize

DAY = 1200
YEAR_TICKS = 403200
SEASON_TICKS = YEAR_TICKS // 4
MAX_EVENTS = 150
MAX_CLUSTERS = 80
MAX_REGISTRY = 400
GATE_NEAR = 12            # tiles: a threat this close to an entrance is "at the gate"
GATE_NEAR_Z = 3
PLACE_CELL = 16           # events away from any entrance or building are grouped on a 16x16 grid
EVENT_KINDS = {"death": "a citizen died", "kill": "an enemy died", "beast_slain": "a great beast was slain",
               "threat_at_gate": "a threat came to the gate", "beast_seen": "a great beast was seen",
               "flood": "a flood", "cave_in": "a cave-in", "ghost": "a ghost"}
REPORT_TOPICS = {"flood": "flood", "cave_in": "cave_in", "ghost": "ghost"}
GATE_ACTIONS = ("fortify_entrance", "build_gate_doors")


def _state(memory) -> dict:
    a = memory.atlas if isinstance(memory.atlas, dict) else {}
    memory.atlas = a
    for k, default in (("survey", {}), ("plan", {}), ("registry", {}), ("entrances", {}),
                       ("events", []), ("clusters", []), ("seen", {})):
        if not isinstance(a.get(k), type(default)):
            a[k] = default
    return a


def _now(state: dict) -> int:
    d = state["date"]
    return d["year"] * YEAR_TICKS + d["tick"]


def _date(state: dict) -> str:
    d = _d(state.get("date"))
    return f"{d.get('day')} {d.get('month')} y{d.get('year')}"


def _offset(s: dict) -> int:
    return _d(s.get("map")).get("elevation_offset") or 0


def spot_key(x, y, z) -> str:
    return f"{x},{y},{z}"


def _era(memory) -> dict:
    eras = (memory.culture or {}).get("eras") if isinstance(memory.culture, dict) else None
    if isinstance(eras, list) and eras:
        return {"era": len(eras), "era_title": eras[-1].get("title")}
    return {"era": 0}


# --- survey -------------------------------------------------------------------------

def _layers_key(s: dict) -> str:
    return ";".join(f"{l.get('name')}:{bool(l.get('discovered'))}"
                    for l in _l(_d(s.get("map")).get("layers")) if isinstance(l, dict))


def survey_due(state: dict, memory) -> bool:
    a = _state(memory)
    sv = a["survey"]
    s = normalize(state)
    now = _now(state)
    if not sv or not isinstance(sv.get("tick"), int) or sv["tick"] > now:
        return True
    if now // SEASON_TICKS != sv["tick"] // SEASON_TICKS:
        return True
    return bool(_d(s.get("map")).get("layers")) and _layers_key(s) != sv.get("layers_key")


def survey(state: dict, memory) -> list[str]:
    """Take stock of the site. Returns what's new, in words (for the chronicle)."""
    a = _state(memory)
    s = normalize(state)
    sv = a["survey"]
    old_layers = {l.get("name"): l for l in _l(sv.get("layers")) if isinstance(l, dict)}
    mp = _d(s.get("map"))
    off = _offset(s)
    found = []
    layers = []
    for l in _l(mp.get("layers")):
        if not isinstance(l, dict) or not l.get("name"):
            continue
        prev = old_layers.get(l["name"]) or {}
        entry = {"name": l["name"], "z_top": l.get("z_top"), "z_bottom": l.get("z_bottom"),
                 "discovered": bool(l.get("discovered")), "found": prev.get("found")}
        if entry["discovered"] and not entry["found"]:
            entry["found"] = _date(state)
            if old_layers:                     # not on the very first look
                found.append(f"{_layer_words(l['name'])} was found"
                             + (f" at elevation {l['z_top'] + off}" if isinstance(l.get("z_top"), int) else ""))
        layers.append(entry)
    if layers or "map" not in s["_errors"]:
        sv["layers"] = layers or sv.get("layers", [])
    if mp.get("size"):
        sv["size"] = mp.get("size")
    sv["elevation_offset"] = off
    dz = _d(mp.get("dwarves"))
    if isinstance(dz.get("z_bottom"), int):
        sv["fort_z"] = [dz["z_bottom"] + off, dz.get("z_top", dz["z_bottom"]) + off]
    if "farms" not in s["_errors"]:
        f = _d(s.get("farms"))
        sv["farms"] = {"plots": f.get("plots") or 0, "tiles": f.get("tiles") or 0}
    if "locations" not in s["_errors"] and isinstance(s.get("locations"), dict):
        sv["locations"] = _d(s["locations"].get("count"))
    sv["layers_key"] = _layers_key(s)
    sv["tick"] = _now(state)
    sv["date"] = _date(state)
    sv.setdefault("first", _date(state))
    found += note_entrances(state, memory)
    return found


def _layer_words(name: str) -> str:
    return {"Cavern1": "the first cavern", "Cavern2": "the second cavern", "Cavern3": "the third cavern",
            "MagmaSea": "the magma sea", "Underworld": "the underworld"}.get(name, name)


def note_entrances(state: dict, memory) -> list[str]:
    """Keep each entrance the gate scan finds; the scan itself lives only in the
    game's memory and is rebuilt after a reload."""
    a = _state(memory)
    s = normalize(state)
    if "entrances" in s["_errors"]:
        return []
    ent = _d(s.get("entrances"))
    if not ent.get("scanned"):
        return []
    off = _offset(s)
    out = []
    seen = set()
    for e in _l(ent.get("entrances")):
        if not isinstance(e, dict) or not isinstance(e.get("x"), int):
            continue
        k = spot_key(e["x"], e["y"], e["z"])
        seen.add(k)
        rec = a["entrances"].get(k)
        if not isinstance(rec, dict):
            rec = a["entrances"][k] = {"kind": e.get("kind"), "first": _date(state), "gates": [],
                                       "threats": 0, "deaths": 0, "kills": 0,
                                       "elevation": e["z"] + off}
        was_closed = rec.get("closed_by")
        rec["width"] = e.get("width")
        rec["sealed"] = bool(e.get("sealed"))
        rec["doors"] = sum(1 for q in _l(e.get("equipment")) if isinstance(q, dict) and q.get("kind") == "door")
        rec["last_seen"] = _date(state)
        # an entrance the AI walled to a gate that is wide open again: someone
        # (a siege, or you) took it down. Only a scan made after the gate was
        # built can say so (the game rescans the entrances weekly, not after walling).
        gid = "gate:" + k
        reg = a["registry"].get(gid)
        scanned = ent.get("scanned_tick")
        if isinstance(reg, dict) and (rec["sealed"] or rec["doors"] > 0):
            reg.pop("doors_later", None)            # its doors came
        if isinstance(reg, dict) and reg.get("status") == "built" and not rec["sealed"] and rec["doors"] == 0 \
                and not e.get("closing") and isinstance(scanned, int) and scanned > (reg.get("tick") or 0) \
                and reg.get("variant") != "deep water" and not reg.get("doors_later"):
            # (a water gate builds nothing; a gate whose doors wait on its walls isn't open, it's unfinished)
            reg["status"] = "open again"
            reg["changed"] = _date(state)
            out.append(f"the {reg.get('variant') or ''} gate at {_where(rec, k)} stands open again".replace("  ", " "))
        rec["closed_by"] = was_closed
        rec.pop("gone", None)
    # entrances a full scan no longer finds (filled in, walled off by the
    # player, or never real: 0.39 took the shade of trees for the fort)
    # (0.100, review) a scan cut short by its size limit didn't see them all
    for k, rec in ({} if ent.get("capped") else a["entrances"]).items():
        if k not in seen and isinstance(rec, dict) and not rec.get("gone"):
            rec["gone"] = _date(state)
    return out


def _where(rec: dict, k: str) -> str:
    x, y, _z = k.split(",")
    el = rec.get("elevation")
    return f"the {rec.get('kind') or ''} entrance x{x} y{y}".replace("  ", " ") + (f" (elevation {el})" if el is not None else "")


# --- the registry ------------------------------------------------------------------------

def note_registry(state: dict, memory) -> list[str]:
    """The AI's own projects from the game (lua/ai-builder.lua registry_report),
    into the registry. Returns status changes in words."""
    a = _state(memory)
    s = normalize(state)
    if "registry" in s["_errors"] or not isinstance(s.get("registry"), list):
        return []
    if not s["registry"] and "projects" in s["_errors"]:
        return []                          # can't tell what's gone from nothing at all
    off = _offset(s)
    out = []
    seen = set()
    for p in s["registry"]:
        if not isinstance(p, dict) or p.get("id") is None:
            continue
        rid = f"project:{p['id']}"
        seen.add(rid)
        status = {"dig": "digging", "furnish": "furnishing", "decorate": "decorating",
                  "done": "built", "cancelled": "cancelled"}.get(p.get("phase"), p.get("phase") or "?")
        rec = a["registry"].get(rid)
        if not isinstance(rec, dict):
            rec = a["registry"][rid] = {"kind": p.get("kind"), "variant": variant_of(p.get("style")),
                                        "tick": _now(state), **_era(memory)}
        rec["elevation"] = p.get("elevation") if p.get("elevation") is not None else (
            p["z"] + off if isinstance(p.get("z"), int) else None)
        b = p.get("bounds")
        if isinstance(b, dict) and all(isinstance(b.get(k), int) for k in ("x1", "y1", "x2", "y2", "z")):
            rec["b"] = [b["x1"], b["y1"], b["x2"], b["y2"], b["z"]]
        elif isinstance(p.get("z"), int) and "b" not in rec:
            rec["z"] = p["z"]
        if p.get("name"):
            rec["name"] = p.get("name")
        if p.get("district"):                  # the master plan's district it was meant for
            rec["district"] = str(p["district"])[:40]
            rec["in_district"] = p.get("in_district") is True
        if rec.get("status") != status:
            if rec.get("status") and status == "built":
                out.append(f"a {_kind_words(rec)} level was finished at elevation {rec.get('elevation')}")
            rec["status"] = status
            rec["changed"] = _date(state)
    # projects the game no longer lists while they were still being made (the
    # game keeps only the last 20 finished ones, so a built level dropping off
    # its list is not news). The open-projects section counts too, so a report
    # without a registry (an older bridge) loses nothing.
    pr = _d(s.get("projects"))
    for p in _l(pr.get("open")) + _l(pr.get("decorating")):
        if isinstance(p, dict) and p.get("id") is not None:
            seen.add(f"project:{p['id']}")
    for rid, rec in a["registry"].items():
        if rid.startswith("project:") and rid not in seen and isinstance(rec, dict) \
                and rec.get("status") in ("digging", "furnishing", "decorating"):
            rec["status"] = "gone"
            rec["changed"] = _date(state)
    _trim_registry(a)
    return out


FINISH = ["rough", "smoothed floors", "smoothed", "engraved"]


def variant_of(style) -> str | None:
    """A level's style (culture.layout_style) as a short design name:
    'pillared, engraved, 2 statues, entry door'."""
    if isinstance(style, str):
        return style[:60]
    if not isinstance(style, dict) or not style:
        return None
    parts = [str(style.get("hall") or "plain")]
    sm = style.get("smooth")
    if isinstance(sm, int) and 0 <= sm < len(FINISH):
        parts.append(FINISH[sm])
    if style.get("statues"):
        parts.append(f"{style['statues']} statue{'s' if style['statues'] != 1 else ''}")
    if style.get("entry_door"):
        parts.append("entry door")
    return ", ".join(parts)


def _kind_words(rec: dict) -> str:
    k = str(rec.get("kind") or "?")
    return k[:-1] if k.endswith("s") and k not in ("farms",) else ("farm" if k == "farms" else k)


def _trim_registry(a: dict) -> None:
    reg = a["registry"]
    if len(reg) <= MAX_REGISTRY:
        return
    # the oldest gone or cancelled entries go first, then the oldest of all
    order = sorted(reg, key=lambda k: (reg[k].get("status") not in ("gone", "cancelled"), reg[k].get("tick", 0)))
    for k in order[:len(reg) - MAX_REGISTRY]:
        del reg[k]


def note_actions(results, state: dict, memory) -> list[str]:
    """What the AI made outside its projects: gates, doors, pastures, farm plots, wells."""
    from planner import _entrance_spot          # (planner imports nothing from here)
    a = _state(memory)
    s = normalize(state)
    off = _offset(s)
    out = []
    for p, r in results:
        act = p.action if isinstance(p.action, dict) else {}
        t = act.get("type")
        # a gate already gone (taken down by hand or by the game): done with it
        if (t == "clear_gate" and isinstance(r, dict) and r.get("ok") is False
                and "nothing of that gate is left" in str(r.get("error")) and isinstance(act.get("spot"), str)):
            for prefix in ("gate:", "doors:"):
                rec = a["registry"].get(prefix + act["spot"])
                if isinstance(rec, dict):
                    rec["status"], rec["changed"] = "taken down", _date(state)
            continue
        if not isinstance(r, dict) or r.get("ok") is not True:
            continue
        base = {"tick": _now(state), "status": "built", "changed": _date(state), **_era(memory)}
        if t == "clear_gate" and isinstance(act.get("spot"), str):
            for prefix in ("gate:", "doors:"):
                rec = a["registry"].get(prefix + act["spot"])
                if isinstance(rec, dict):
                    rec["status"], rec["changed"] = "taken down", _date(state)
            out.append(f"the gate at the old entrance {act['spot']} (not a real one: the shade of a tree) is being "
                       f"taken down ({r.get('removed', 0)} pieces)")
            continue
        if t in GATE_ACTIONS:
            spot = _entrance_spot(state, act.get("entrance_id"))
            if not spot:
                continue
            x, y, z = (int(v) for v in spot.split(","))
            rid = ("gate:" if t == "fortify_entrance" else "doors:") + spot
            variant = (r.get("style") or act.get("style") or "plain") if t == "fortify_entrance" else "doors"
            a["registry"][rid] = dict(base, kind="gate" if t == "fortify_entrance" else "doors", variant=variant,
                                      elevation=z + off, b=[x, y, x, y, z])
            rec = a["entrances"].setdefault(spot, {"kind": None, "first": _date(state), "gates": [],
                                                   "threats": 0, "deaths": 0, "kills": 0, "elevation": z + off})
            moved = r.get("moved_in") if isinstance(r.get("moved_in"), int) else None
            if moved:
                a["registry"][rid]["moved_in"] = moved
                ln = _d(r.get("line"))
                if all(isinstance(ln.get(c), int) for c in ("x", "y", "z")):
                    a["registry"][rid]["b"] = [ln["x"], ln["y"], ln["x"], ln["y"], ln["z"]]
            if r.get("hatches"):
                a["registry"][rid]["variant"] = "hatch"
            pieces = [str(k) for k in (r.get("pieces") or []) if isinstance(k, str)][:80]
            if pieces:
                a["registry"][rid]["pieces"] = pieces            # (so it can be taken down exactly)
            if t == "fortify_entrance" and (r.get("doors_later") or r.get("support_walls")):
                a["registry"][rid]["doors_later"] = True
            if r.get("water_gate") or r.get("shore"):
                a["registry"][rid]["variant"] = "deep water" if r.get("water_gate") else f"{variant}, on the shore"
            if isinstance(r.get("water"), str):
                rec["water"] = r["water"][:200]          # what the AI found when it looked at the water
            rec.setdefault("gates", []).append({"date": _date(state), "style": variant, "by": p.rule})
            del rec["gates"][:-8]
            if t == "fortify_entrance":
                how = ("closed with a hatch over the stairs" if r.get("hatches")
                       else (f"walled to a drawbridge gate" + (f", its lever placed at x{_d(r.get('lever')).get('x')} "
                             f"y{_d(r.get('lever')).get('y')} (linked once both are built)" if r.get("lever")
                             else " (no lever placed yet)")) if r.get("bridge")
                       else (f"left to its water, which walkers don't path through ({r.get('water')}; checked "
                             "again each season, in case it freezes or dries)") if r.get("water_gate")
                       else f"walled to a {variant} gate along the dry shore of its water ({r.get('water')})"
                       if r.get("shore")
                       else f"walled to a {variant} gate" + (f" {moved} tile(s) further in" if moved else ""))
                out.append(f"{_where(rec, spot)} was {how}")
        elif t == "found_fort" and not act.get("dry_run"):
            out.append(f"the fort's first staircase was laid out beside {r.get('near') or 'the dwarves'} at "
                       f"x{r.get('x')} y{r.get('y')}, {r.get('levels')} level(s) down"
                       + (" to the first rock" if r.get("rock") else ""))
        elif t == "place_traps":
            spot = _entrance_spot(state, act.get("entrance_id"))
            if spot:
                spot = _nearest_entrance(a, spot) or spot      # with its gate's record, not 2 tiles off
                x, y, z = (int(v) for v in spot.split(","))
                a["registry"]["traps:" + spot] = dict(base, kind="traps", variant=str(act.get("kind")),
                                                      count=r.get("traps"), elevation=z + off, b=[x, y, x, y, z])
                rec = a["entrances"].get(spot)
                out.append(f"{r.get('traps')} {act.get('kind')} trap(s) went in behind the gate at "
                           + (_where(rec, spot) if isinstance(rec, dict) else f"x{x} y{y}"))
        elif t == "link_lever" and not act.get("dry_run"):
            rid = f"lever:{act.get('lever_id')}>{act.get('target_id')}"
            a["registry"][rid] = dict(base, kind="lever_link", variant=str(r.get("target") or "bridge").lower(),
                                      status="linking", lever=act.get("lever_id"), target=act.get("target_id"))
            out.append(f"a mechanic was sent to link lever {act.get('lever_id')} to the "
                       f"{str(r.get('target') or 'bridge').lower()} {act.get('target_id')}")
        elif t == "make_pasture":
            x, y, z = r.get("x"), r.get("y"), r.get("z")
            rid = f"pasture:{_now(state)}"
            while rid in a["registry"]:
                rid += "+"
            rec = dict(base, kind="pasture", variant=None, tiles=act.get("tiles") or r.get("tiles"))
            if isinstance(x, int) and isinstance(y, int) and isinstance(z, int):
                rec.update(elevation=z + off, b=[x, y, x + (r.get("w") or 1) - 1, y + (r.get("h") or 1) - 1, z])
            a["registry"][rid] = rec
        elif t == "farm_plots":
            for i, pl in enumerate(_l(r.get("placed"))):
                if not isinstance(pl, dict) or not isinstance(pl.get("x"), int):
                    continue
                el = pl.get("elevation")
                z = el - off if isinstance(el, int) else None
                a["registry"][f"plots:{pl['x']},{pl['y']},{el}"] = dict(
                    base, kind="farm plot", variant=None, elevation=el,
                    b=[pl["x"], pl["y"], pl["x"] + (pl.get("w") or 1) - 1, pl["y"] + (pl.get("h") or 1) - 1, z])
    _trim_registry(a)
    return out


# --- located events -----------------------------------------------------------------------

def _nearest_entrance(a: dict, spot: str, reach: int = 3) -> str | None:
    """The atlas entrance (or gate record) within reach of this spot on its
    level, nearest first: walls move an entrance's first tile a little."""
    try:
        x, y, z = (int(v) for v in spot.split(","))
    except ValueError:
        return None
    cands = list(a["entrances"]) + [k.split(":", 1)[1] for k in a["registry"] if k.startswith(("gate:", "doors:"))]
    best, best_d = None, None
    for k in cands:
        try:
            ex, ey, ez = (int(v) for v in k.split(","))
        except ValueError:
            continue
        d = max(abs(ex - x), abs(ey - y))
        if ez == z and d <= reach and (best_d is None or d < best_d or (d == best_d and k == spot)):
            best, best_d = k, d
    return best


def _near(a: dict, x: int, y: int, z: int) -> str | None:
    """The place an event belongs to: an entrance within reach, or something
    the AI built that holds the spot."""
    best, best_d = None, None
    for k in a["entrances"]:
        try:
            ex, ey, ez = (int(v) for v in k.split(","))
        except ValueError:
            continue
        if abs(ez - z) <= GATE_NEAR_Z:
            d = max(abs(ex - x), abs(ey - y))
            if d <= GATE_NEAR and (best_d is None or d < best_d):
                best, best_d = "entrance:" + k, d
    if best:
        return best
    for rid, rec in a["registry"].items():
        b = bounds(rec)
        if b and b["z"] == z and b["x1"] - 1 <= x <= b["x2"] + 1 and b["y1"] - 1 <= y <= b["y2"] + 1:
            return rid
    return None


def bounds(rec) -> dict | None:
    """A registry entry's box, {x1, y1, x2, y2, z} in map tiles, or None.
    (Stored as a short list "b": [x1, y1, x2, y2, z] to keep the save small.)"""
    b = rec.get("b") if isinstance(rec, dict) else None
    if isinstance(b, list) and len(b) == 5 and all(isinstance(v, int) for v in b):
        return dict(zip(("x1", "y1", "x2", "y2", "z"), b))
    return None


def _add(a: dict, state: dict, kind: str, x, y, z, what: str = "") -> dict | None:
    if not all(isinstance(v, int) for v in (x, y, z)):
        return None
    near = _near(a, x, y, z)
    ev = {"k": kind, "x": x, "y": y, "z": z, "t": _now(state)}
    if what:
        ev["what"] = what[:60]
    if near:
        ev["near"] = near
        if near.startswith("entrance:"):
            rec = a["entrances"].get(near[len("entrance:"):])
            if isinstance(rec, dict):
                field = {"death": "deaths", "kill": "kills", "beast_slain": "kills",
                         "threat_at_gate": "threats"}.get(kind)
                if field:
                    rec[field] = rec.get(field, 0) + 1
    a["events"].append(ev)
    del a["events"][:-MAX_EVENTS]
    return ev


def note_events(state: dict, memory, events: list[dict]) -> int:
    """Record where things happened. Returns how many located events were added."""
    from culture import beast_name, is_great_beast
    a = _state(memory)
    s = normalize(state)
    n = 0
    for e in events or []:
        if not isinstance(e, dict):
            continue
        k = e.get("kind")
        if k == "death":
            if e.get("own_civ") and not e.get("animal"):
                kind = "death"
            elif e.get("hostile") and is_great_beast(e):
                kind = "beast_slain"
            elif e.get("hostile"):
                kind = "kill"
            else:
                continue
            n += _add(a, state, kind, e.get("x"), e.get("y"), e.get("z"), str(e.get("name") or "")) is not None
        elif k == "arrival" and "ghost" in str(e.get("name") or "").lower():
            # a ghost rising: where it appeared (often by its unburied body)
            n += _add(a, state, "ghost", e.get("x"), e.get("y"), e.get("z"), str(e.get("name") or "")) is not None
        elif k == "report" and e.get("topic") in REPORT_TOPICS:
            n += _add(a, state, REPORT_TOPICS[e["topic"]], e.get("x"), e.get("y"), e.get("z"),
                      str(e.get("text") or "")) is not None
    # threats at the gates, and great beasts seen, once per creature
    if "others_on_map" not in s["_errors"]:
        seen = a["seen"]
        now = _now(state)
        for t in _l(_d(s.get("others_on_map")).get("threats")):
            if not isinstance(t, dict) or t.get("id") is None:
                continue
            pos = _d(t.get("pos"))
            x, y, z = pos.get("x"), pos.get("y"), pos.get("z")
            if not all(isinstance(v, int) for v in (x, y, z)):
                continue
            # a named great beast (forgotten beast, titan, megabeast), not every demon below
            named = '"' in str(t.get("name") or "") and t.get("layer") != "Underworld"
            if t.get("great_danger") and named:
                if f"beast:{t['id']}" not in seen:
                    n += _add(a, state, "beast_seen", x, y, z, beast_name(str(t.get("name") or ""))) is not None
                seen[f"beast:{t['id']}"] = now       # still here: not news again while it lingers
            near = _near(a, x, y, z)
            if near and near.startswith("entrance:"):
                if f"gate:{t['id']}:{near}" not in seen:
                    n += _add(a, state, "threat_at_gate", x, y, z, str(t.get("name") or "")) is not None
                seen[f"gate:{t['id']}:{near}"] = now
        # forget creatures not seen for a season (or from a later, unloaded save)
        for key in [k for k, v in seen.items() if not isinstance(v, int) or v > now or now - v > SEASON_TICKS]:
            del seen[key]
    return n


# --- ageing and finding it again ---------------------------------------------------------

def _place_of(ev: dict) -> str:
    if ev.get("near"):
        return ev["near"]
    return f"area:{ev.get('x', 0) // PLACE_CELL * PLACE_CELL},{ev.get('y', 0) // PLACE_CELL * PLACE_CELL},{ev.get('z')}"


def consolidate(memory, now: int) -> int:
    """Events over a year old are summed into clusters by kind and place.
    Returns how many were folded in."""
    a = _state(memory)
    keep, old = [], []
    for ev in a["events"]:
        if not isinstance(ev, dict):
            continue
        if ev.get("t", 0) > now:
            continue                         # from a later save that was not kept
        (old if now - ev.get("t", 0) > YEAR_TICKS else keep).append(ev)
    clusters = {(c.get("k"), c.get("place")): c for c in a["clusters"] if isinstance(c, dict)}
    for ev in old:
        key = (ev.get("k"), _place_of(ev))
        year = ev.get("t", 0) // YEAR_TICKS
        c = clusters.get(key)
        if c is None:
            c = clusters[key] = {"k": key[0], "place": key[1], "n": 0, "y0": year, "y1": year}
        c["n"] += 1
        c["y0"], c["y1"] = min(c["y0"], year), max(c["y1"], year)
    a["events"] = keep
    # a later save was dropped: clusters from years that haven't happened go
    a["clusters"] = sorted((c for c in clusters.values() if c.get("y0", 0) <= now // YEAR_TICKS),
                           key=lambda c: (-c["n"], -c["y1"]))[:MAX_CLUSTERS]
    return len(old)


def _place_words(a: dict, place: str) -> str:
    if place.startswith("entrance:"):
        k = place[len("entrance:"):]
        return _where(_d(a["entrances"].get(k)), k)
    if place.startswith("area:"):
        x, y, z = place[len("area:"):].split(",")
        off = _d(a.get("survey")).get("elevation_offset") or 0
        try:
            el = int(z) + off
        except ValueError:
            el = z
        return f"around x{x} y{y} (elevation {el})"
    rec = _d(a["registry"].get(place))
    if rec:
        return f"the {_kind_words(rec)} level at elevation {rec.get('elevation')}" if place.startswith("project:") \
            else f"the AI's {rec.get('kind')} at elevation {rec.get('elevation')}"
    return place


def notable(memory, limit: int = 4) -> list[str]:
    """The places with the most history, in words: recent events and clusters together."""
    a = _state(memory)
    tally: dict[str, dict] = {}
    years: dict[str, list] = {}
    for ev in a["events"]:
        if isinstance(ev, dict):
            p = _place_of(ev)
            tally.setdefault(p, {})
            tally[p][ev["k"]] = tally[p].get(ev["k"], 0) + 1
            years.setdefault(p, []).append(ev.get("t", 0) // YEAR_TICKS)
    for c in a["clusters"]:
        p = c.get("place")
        tally.setdefault(p, {})
        tally[p][c["k"]] = tally[p].get(c["k"], 0) + c.get("n", 0)
        years.setdefault(p, []).extend([c.get("y0", 0), c.get("y1", 0)])
    weight = {"death": 3, "beast_slain": 2, "flood": 2, "cave_in": 2, "threat_at_gate": 1, "kill": 1,
              "beast_seen": 1, "ghost": 1}
    ranked = sorted(tally.items(), key=lambda kv: -sum(weight.get(k, 1) * n for k, n in kv[1].items()))
    out = []
    for place, kinds in ranked[:limit]:
        parts = ", ".join(f"{n} {_plural(k, n)}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]))
        ys = years.get(place) or []
        span = f" (years {min(ys)} to {max(ys)})" if ys and min(ys) != max(ys) else (f" (year {ys[0]})" if ys else "")
        out.append(f"{_place_words(a, place)}: {parts}{span}")
    return out


def _plural(kind: str, n: int) -> str:
    words = {"death": "death", "kill": "enemy killed", "beast_slain": "great beast slain",
             "threat_at_gate": "threat at the gate", "beast_seen": "great beast seen", "flood": "flood",
             "cave_in": "cave-in", "ghost": "ghost"}
    w = words.get(kind, kind)
    if n == 1:
        return w
    return {"enemy killed": "enemies killed", "great beast slain": "great beasts slain",
            "threat at the gate": "threats at the gate", "great beast seen": "great beasts seen"}.get(w, w + "s")


def built(memory, kind: str | None = None, status: str | None = "built") -> list[dict]:
    """What the AI built (for the builder and design learning later)."""
    a = _state(memory)
    return [dict(v, id=k) for k, v in a["registry"].items()
            if isinstance(v, dict) and (kind is None or v.get("kind") == kind)
            and (status is None or v.get("status") == status)]

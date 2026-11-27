"""(F2d) One final gate: the player's "never" rules, read once more right
before an action goes to the game.

`select` used to feed `bridge.act` directly; the "never" rules sat in single
rules and in the Lua handlers, and the strategist's proposals joined after
plan()'s own filters. This is the last line, not the rule: every rule and
Lua check that enforces these stays where it is (the gate duplicates them).

NEVER is a table of (name, predicate(action, state, memory) -> reason|None).
gate(actions, state, memory) -> (passed, blocked): each item a Proposal (its
`.action`) or a bare action dict; blocked is a list of (item, name, reason).
A proposal of the strategist's (its reason "strategist: ...", or the action
marked by="strategist") is shown to the predicates with by="strategist" (a
copy: the action sent is never changed). A predicate that raises passes the
action (the rule and the bridge still hold) and is told in `errors`.

Seeded from the player's standing rules (handoff "standing rules" and the
code that enforces each):
  never_kill_citizen   the insane are never killed (handoff, 24 Nov 22:36;
                       planner_insane), no kill order on any citizen: as
                       ai-military-duty kill_target_ok, a berserk one or a
                       citizen changed into a beast (a were) is DF's enemy
  never_sealed_in      no gate shut or way walled that leaves no way to the
                       map edge, unless a live danger is present
                       (planner_way_out.live_cause / sealed)
  gates_close_late     no gate or bridge shut with no danger within 12 tiles,
                       unless every citizen is inside or a great beast is on
                       the map (planner_gates' arm line; the gate watcher)
  guard_in_every_fort  no trim or release taking a fort of guard_min_adults+
                       adults below guard_min_soldiers (planner_military_squads)
  strategist_no_cheats no cheat-capable action from the strategist: units
                       made or called (call_migrants, test threats), the
                       thirst reset (insane_water), raw Lua, probes, merchants
                       teleported or goods taken out of the game
  bridge_no_citizen    no bridge moved while the state shows one of the
                       fort's own on, beside or crossing it (0.105.128, R32 a:
                       ai-werecells own_near, ai-gates-watch bridge_watch);
                       the report carries no unit positions at bridges today,
                       so this reads what it has and the Lua holds stay the guard
"""

from __future__ import annotations

from digest import _d, _l

__all__ = ["NEVER", "gate", "never_step", "blocked_line", "CHEAT_ACTIONS", "danger_near_gates", "great_beast_on_map"]

CLOSE_TILES = 12                      # the gate watcher's own (IMMINENT): "the danger is 12 tiles away"
GREAT_KINDS = {"Megabeast", "Titan", "ForgottenBeast", "SemiMegabeast"}

# The catalog's cheat-capable actions (lua/ai-bridge-catalog.lua): fine from the
# planner's own rules where the player asked for them, never from the strategist
CHEAT_ACTIONS = {
    "call_migrants",          # a migrant wave forced (DFHack's force Migrants): units made
    "insane_water",           # the insane's thirst and hunger timers set back
    "thirst_probe",           # a probe
    "free_caravan",           # merchants teleported to the map's edge or dismissed
    "clear_caravan_goods",    # goods taken out of the game
    "test_threat",            # invaders set down (ai-spawn; a probe command today)
}
CHEAT_WORDS = ("probe", "spawn", "lua", "create_unit", "eval")


from util import int_or_none as _int  # noqa: E402  (util's helper)


def _pos(r) -> tuple | None:
    """(x, y, z) of a row: its own x/y/z or its pos."""
    r = _d(r)
    p = _d(r.get("pos")) or r
    x, y, z = _int(p.get("x")), _int(p.get("y")), _int(p.get("z"))
    return (x, y, z) if None not in (x, y, z) else None


def _from_strategist(item, action: dict) -> bool:
    if action.get("by") == "strategist":
        return True
    reason = getattr(item, "reason", None)
    return isinstance(reason, str) and reason.startswith("strategist:")


# --- what the state says ---------------------------------------------------

def _threats(s: dict) -> list:
    return [t for t in _l(_d(s.get("others_on_map")).get("threats")) if isinstance(t, dict)]


def great_beast_on_map(s: dict) -> bool:
    """A megabeast, titan or forgotten beast on the map (the threats rows)."""
    for t in _threats(s):
        if set(_l(t.get("kinds"))) & GREAT_KINDS or t.get("great_danger") is True:
            return True
    return False


def _entrances(s: dict) -> list:
    return [e for e in _l(_d(s.get("entrances")).get("entrances")) if isinstance(e, dict)]


def danger_near_gates(s: dict, tiles: int = CLOSE_TILES) -> bool | None:
    """A danger within `tiles` of a gate: the way_out report's nearest, or a
    threat's position against the entrances'. None when nothing can be told."""
    near = _d(_d(s.get("way_out")).get("cause")).get("nearest")
    if isinstance(near, (int, float)) and not isinstance(near, bool) and near <= tiles:
        return True
    gates = [p for p in (_pos(e) for e in _entrances(s)) if p]
    rows = [t for t in _threats(s) if (t.get("hostile") or t.get("invader") or t.get("great_danger"))
            and not t.get("caged")]
    told = isinstance(near, (int, float)) and not isinstance(near, bool)
    for t in rows:
        p = _pos(t)
        if not p:
            continue
        for g in gates:
            told = True
            if abs(p[2] - g[2]) <= 3 and max(abs(p[0] - g[0]), abs(p[1] - g[1])) <= tiles:
                return True
    if told or (gates and not rows):
        return False
    return None


def _all_inside(s: dict) -> bool:
    out = _d(s.get("entrances")).get("citizens_outside")
    return _int(out) == 0


def _lever_ids(piece: dict) -> set:
    ids = {piece.get("lever_id"), piece.get("drive_lever")} | set(_l(piece.get("levers")))
    return {i for i in ids if _int(i) is not None}


def _pieces(e: dict) -> list:
    return [p for p in _l(e.get("equipment")) + _l(e.get("outer")) if isinstance(p, dict)]


def _entrance_of_lever(s: dict, lever) -> dict | None:
    for e in _entrances(s):
        if any(lever in _lever_ids(p) for p in _pieces(e)):
            return e
    return None


def _lever_row(s: dict, lever) -> dict:
    for g in _l(_d(s.get("military")).get("gates")):
        if isinstance(g, dict) and g.get("id") == lever:
            return g
    return {}


def _pull_closes(action: dict, s: dict, memory) -> bool:
    """A pull_gate that would shut: as planner_military_gatelever reads it,
    the lever's gate not shut and not shut by the AI before."""
    if action.get("type") != "pull_gate":
        return False
    lever = action.get("lever_id")
    if getattr(memory, "gate_closed_by_ai", False):
        return False
    row = _lever_row(s, lever)
    if row.get("shut") is True:
        return False
    e = _entrance_of_lever(s, lever)
    if e is not None and e.get("closed") is True:
        return False
    return True


def _closes_gate(action: dict, s: dict, memory) -> bool:
    return _pull_closes(action, s, memory)


def _live_danger(s: dict, memory) -> bool:
    if int(_d(s.get("others_on_map")).get("threats_that_can_reach_dwarves") or 0) > 0:
        return True
    try:
        from planner_core import PLANNER_CONFIG
        from planner_way_out import live_cause
        why, _hard = live_cause(s, PLANNER_CONFIG, memory)
        return bool(why)
    except Exception:  # noqa: BLE001  (no cause read: the near-gate danger alone)
        return bool(danger_near_gates(s))


# --- the predicates ---------------------------------------------------------

def never_kill_citizen(action: dict, s: dict, memory) -> str | None:
    if action.get("type") != "squad_orders" or action.get("clear") is True:
        return None
    targets = [i for i in _l(action.get("kill")) if _int(i) is not None]
    if not targets:
        return None
    insane = {}
    for r in _l(_d(s.get("insane")).get("list")):
        if isinstance(r, dict) and _int(r.get("id")) is not None:
            insane[r["id"]] = r
    citizens = {u.get("id") for u in _l(s.get("units")) if isinstance(u, dict)}
    enemy = set()          # DF's enemy: a berserk one, one changed into a beast
    for r in _l(_d(s.get("hazards")).get("berserk")):
        if isinstance(r, dict):
            enemy.add(r.get("id"))
    for r in _l(_d(s.get("killers")).get("list")):
        if not isinstance(r, dict):
            continue
        if r.get("citizen"):
            citizens.add(r.get("id"))
        if r.get("berserk") or r.get("changed"):
            enemy.add(r.get("id"))
    for t in _threats(s):
        if t.get("transformed"):
            enemy.add(t.get("id"))
    for i in targets:
        r = insane.get(i)
        if r is not None and str(r.get("mood") or r.get("kind") or "").lower() != "berserk" and i not in enemy:
            return f"unit {i} is insane ({r.get('kind') or r.get('mood') or 'insane'}): the insane are never killed"
        if (i in citizens or r is not None) and i not in enemy:
            return f"unit {i} is a citizen: no kill order on the fort's own"
    return None


def never_sealed_in(action: dict, s: dict, memory) -> str | None:
    t = action.get("type")
    walls = t == "fortify_entrance" and action.get("style") == "sealed"
    if not walls and not _closes_gate(action, s, memory):
        return None
    if walls:
        e = next((x for x in _entrances(s) if x.get("id") == action.get("entrance_id")), None)
    else:
        e = _entrance_of_lever(s, action.get("lever_id"))
    if e is None or e.get("kind") != "surface":
        return None                        # a cavern opening, or a gate the state can't place
    others = [x for x in _entrances(s) if x.get("kind") == "surface" and x.get("id") != e.get("id")
              and x.get("closed") is not True]
    if others:
        return None
    if walls:
        # a wall stands after the danger has gone: never on the last way out
        return f"walling entrance {e.get('id')} for good leaves no way to the map edge"
    if _live_danger(s, memory):
        return None
    return (f"shutting entrance {e.get('id')} leaves every way to the map edge shut "
            "and no live danger is present")


def gates_close_late(action: dict, s: dict, memory) -> str | None:
    if not _closes_gate(action, s, memory):
        return None
    if _all_inside(s) or great_beast_on_map(s):
        return None
    near = danger_near_gates(s)
    if near is not False:
        return None             # a danger near, or the state can't tell: the close goes
    return (f"no danger within {CLOSE_TILES} tiles of a gate, citizens outside and no great beast "
            "on the map: gates close late")


def guard_in_every_fort(action: dict, s: dict, memory) -> str | None:
    t = action.get("type")
    if t == "squad_trim":
        n = _int(action.get("count")) or 0
    elif t == "squad_release":
        n = 1
    else:
        return None
    if n <= 0 or action.get("dry_run"):
        return None
    try:
        from planner_core import PLANNER_CONFIG
        min_adults = int(PLANNER_CONFIG.get("guard_min_adults", 15))
        min_soldiers = int(PLANNER_CONFIG.get("guard_min_soldiers", 3))
    except Exception:  # noqa: BLE001
        min_adults, min_soldiers = 15, 3
    adults = _int(_d(s.get("dwarves")).get("adults"))
    have = _int(_d(s.get("military")).get("soldiers"))
    if adults is None or have is None or adults < min_adults:
        return None
    if have - n < min_soldiers:
        return (f"{have} soldier(s) less {n} leaves fewer than {min_soldiers} in a fort of {adults} adults: "
                "a guard in every fort")
    return None


def strategist_no_cheats(action: dict, s: dict, memory) -> str | None:
    if action.get("by") != "strategist":
        return None
    t = str(action.get("type") or "")
    if t in CHEAT_ACTIONS or any(w in t.lower() for w in CHEAT_WORDS):
        return f"{t} can change the game's numbers directly: never from the strategist"
    return None


def _bridge_rows(s: dict, action: dict) -> list:
    """The bridges this action moves, as the state lists them."""
    t = action.get("type")
    rows = []
    if t == "pull_gate":
        lever = action.get("lever_id")
        for e in _entrances(s):
            rows += [p for p in _pieces(e) if p.get("kind") == "bridge" and lever in _lever_ids(p)]
    # (moon_cell: the were_cells report gives the cells, not their bridges'
    # tiles; ai-werecells own_near holds those bridges in the game)
    return rows


def _own_positions(s: dict) -> list:
    out = []
    for u in _l(s.get("units")) + _l(_d(s.get("insane")).get("list")):
        p = _pos(u) if isinstance(u, dict) else None
        if p:
            out.append(p)
    return out


def bridge_no_citizen(action: dict, s: dict, memory) -> str | None:
    rows = _bridge_rows(s, action)
    if not rows:
        return None
    own = _own_positions(s)
    for b in rows:
        if b.get("own_on") or b.get("own_near") or b.get("own_crossing"):
            return f"bridge {b.get('id')}: one of the fort's own is on, beside or crossing it"
        x1, y1 = _int(b.get("x1", b.get("x"))), _int(b.get("y1", b.get("y")))
        x2, y2 = _int(b.get("x2", b.get("x"))), _int(b.get("y2", b.get("y")))
        z = _int(b.get("z"))
        if None in (x1, y1, x2, y2, z):
            continue
        for (x, y, uz) in own:
            d = max(x1 - x, x - x2, y1 - y, y - y2, 0)
            if (uz == z and d <= 1) or (abs(uz - z) == 1 and d == 1):
                return (f"bridge {b.get('id')}: a citizen is " + ("on" if d == 0 else "beside")
                        + f" it (x{x} y{y} z{uz})")
    return None


NEVER = [
    ("never_kill_citizen", never_kill_citizen),
    ("never_sealed_in", never_sealed_in),
    ("gates_close_late", gates_close_late),
    ("guard_in_every_fort", guard_in_every_fort),
    ("strategist_no_cheats", strategist_no_cheats),
    ("bridge_no_citizen", bridge_no_citizen),
]


def gate(actions, state: dict, memory, errors: list | None = None) -> tuple[list, list]:
    """(passed, blocked): blocked = [(item, predicate name, reason)], the first
    predicate that holds an item naming it."""
    passed, blocked = [], []
    s = state if isinstance(state, dict) else {}
    for item in actions or []:
        action = getattr(item, "action", item)
        if not isinstance(action, dict):
            passed.append(item)
            continue
        view = dict(action, by="strategist") if _from_strategist(item, action) else action
        hit = None
        for name, pred in NEVER:
            try:
                why = pred(view, s, memory)
            except Exception as e:  # noqa: BLE001  (the rule and the bridge still hold)
                if errors is not None:
                    errors.append(f"{name}: {type(e).__name__}: {e}")
                continue
            if why:
                hit = (item, name, str(why))
                break
        if hit:
            blocked.append(hit)
        else:
            passed.append(item)
    return passed, blocked


def blocked_line(item, name: str, why: str) -> str:
    action = getattr(item, "action", item)
    rule = getattr(item, "rule", None)
    return f"never ({name}): {(rule + ': ') if rule else ''}{_d(action).get('type')} held: {why}"


def never_step(allowed: list, held: list, state: dict, memory, key, say=print, journal=None) -> tuple[list, list]:
    """overseer_cycle's one call, between select() and the dispatch loop (the
    planner's and the strategist's proposals alike): the blocked ones said once
    this cycle with the predicate's name and why, journaled (kind
    never_blocked), and added to the held lines. Failing whole, everything
    goes as select() let it (the rules and the bridge's own checks hold)."""
    try:
        errors: list = []
        passed, blocked = gate(allowed, state, memory, errors)
    except Exception as e:  # noqa: BLE001  (the gate never stops the cycle)
        say(f"  never gate failed ({type(e).__name__}: {e}); the actions go as selected")
        return allowed, held
    held = list(held)
    for item, name, why in blocked:
        line = blocked_line(item, name, why)
        say(f"  {line}")
        held.append(line)
        if journal is not None:
            try:
                journal({"kind": "never_blocked", "fort": key, "date": _d(state).get("date"), "never": name,
                         "why": why, "rule": getattr(item, "rule", None), "reason": getattr(item, "reason", None),
                         "action": getattr(item, "action", item)})
            except Exception:  # noqa: BLE001
                pass
    for err in errors:
        say(f"  never gate: {err} (passed)")
    return passed, held

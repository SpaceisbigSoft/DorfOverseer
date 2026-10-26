"""(0.104.0) The AI's ledger: the few things it must remember that the game
can't tell it, kept in the save the moment they change.

The AI's memory goes into the save only once a game week (each write froze
the game about a second), so a save could hold memory older than its game:
reloaded, the AI forgot it had raised the civilian alert (never lowered it),
closed the gate (pulled the lever again: open, during a threat), the
memorials it built (built again), the petitions it agreed to (agreed twice),
a dwarf sent away (the next one a week later), the stop-gap temple (0.103.13).
These fields are written through the bridge (`ledger_set`) in the same cycle
they change, and read back over the memory whenever the memory is read from
the save (a restart, a reload): the save's ledger always matches its game.

    snap = ledger.snapshot(memory)
    ledger.apply(memory, state["ledger"])     # on load; True if anything was set
"""

from __future__ import annotations

import json

# memory field -> its default (the shape the planner expects)
FIELDS: dict = {
    "ai_alert_raised": False, "gate_closed_by_ai": False, "kitchen_ban": False, "farm_steer": "",
    "tree_year": {}, "libraries_imported": [], "squads_trained": [], "squads_rested": [],
    "tools_seen_on": [], "tools_player_disabled": [], "stuck_cancelled": {}, "wishes_agreed": {},
    "last_expel_tick": None, "last_memorial_tick": None, "last_garden_tick": None, "gardens_built": [],
    "quick_locations": {},
}
DICT_MAX = 40           # newest entries kept of the dicts keyed by time
LIST_MAX = 60


def _newest(d: dict, n: int) -> dict:
    """The n entries with the latest tick (a number, or a dict's "tick")."""
    def t(v):
        if isinstance(v, (int, float)):
            return v
        if isinstance(v, dict) and isinstance(v.get("tick"), (int, float)):
            return v["tick"]
        return 0
    items = sorted(d.items(), key=lambda kv: t(kv[1]))[-n:]
    return {str(k): v for k, v in items}


def snapshot(memory) -> dict:
    """The ledger fields of the memory, JSON-safe and bounded."""
    out: dict = {}
    for name, default in FIELDS.items():
        v = getattr(memory, name, default)
        if isinstance(default, dict):
            v = _newest(v, DICT_MAX) if isinstance(v, dict) else {}
        elif isinstance(default, list):
            v = list(v)[-LIST_MAX:] if isinstance(v, list) else []
        elif isinstance(default, bool):
            v = bool(v)
        elif isinstance(default, str):
            v = str(v or "")[:80]
        else:
            v = v if isinstance(v, int) else None
        out[name] = v
    culture = getattr(memory, "culture", None)
    built = culture.get("memorials_built") if isinstance(culture, dict) else None
    out["memorials_built"] = list(built)[-LIST_MAX:] if isinstance(built, list) else []
    return out


def _as(default, v):
    """A value read back from the save in the shape the planner expects (an
    empty table may come back as [] or {})."""
    if isinstance(default, bool):
        return bool(v)
    if isinstance(default, dict):
        return dict(v) if isinstance(v, dict) else {}
    if isinstance(default, list):
        if isinstance(v, dict):                 # a Lua array that came back keyed
            v = [v[k] for k in sorted(v, key=lambda k: int(k) if str(k).isdigit() else 0)]
        return list(v) if isinstance(v, list) else []
    if isinstance(default, str):
        return str(v) if isinstance(v, str) else ""
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def apply(memory, ledger) -> bool:
    """The save's ledger over the memory. Nothing happens without one (a save
    from before 0.104.0 keeps its memory as it was)."""
    if not isinstance(ledger, dict) or not ledger or "error" in ledger:
        return False
    for name, default in FIELDS.items():
        if name in ledger:
            setattr(memory, name, _as(default, ledger[name]))
    if "memorials_built" in ledger:
        if not isinstance(getattr(memory, "culture", None), dict):
            memory.culture = {}
        memory.culture["memorials_built"] = _as([], ledger["memorials_built"])
    return True


def same(a: dict, b) -> bool:
    """Equal as the save would hold them (key order and [] vs {} aside)."""
    def norm(x):
        if isinstance(x, dict):
            return {str(k): norm(v) for k, v in x.items()} if x else None
        if isinstance(x, list):
            return [norm(v) for v in x] if x else None
        return None if (x is False or x is None or x == "") else x      # (unset: as good as absent)
    if not isinstance(b, dict):
        return False
    return json.dumps(norm(a), sort_keys=True) == json.dumps(norm({k: b.get(k) for k in a}), sort_keys=True)

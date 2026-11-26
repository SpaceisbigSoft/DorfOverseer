"""(r36) The player's "AI gate" lever (one named so and linked to something):
pulled when a threat can reach the dwarves, pulled back for a sortie, a few
enemies left inside, or the quiet. Moved whole out of planner_military's
_military_rules (the 60 KB line); the names tests patch there (all_clear,
quick_clear, watched_gate_levers) are read through that module."""

from __future__ import annotations

from digest import _l
from planner_core import Proposal

__all__ = ["ai_gate_lever"]


def ai_gate_lever(s: dict, memory, cfg: dict, rules_: dict, mil: dict, any_reach: bool, open_up: bool,
                  sortie: bool, proposals: list) -> None:
    import planner_military as pm
    watched_gate_levers, all_clear, quick_clear = pm.watched_gate_levers, pm.all_clear, pm.quick_clear
    # A lever the player named "AI gate" and linked to something: pulled too.
    gates = [g for g in _l(mil.get("gates")) if isinstance(g, dict) and not g.get("pending") and g.get("linked")]
    # (one linked to an entrance's drawbridge is the gate watcher's to pull)
    watched = watched_gate_levers(s)
    gates = [g for g in gates if g.get("id") not in watched]
    if rules_["gate_lever"] and gates:
        # (0.105.36) never pulled while the report says the gate is already
        # shut (the player's, or the AI's own not yet read back)
        if any_reach and not memory.gate_closed_by_ai and not open_up and gates[0].get("shut") is not True:
            proposals.append(Proposal("gate", {"type": "pull_gate", "lever_id": gates[0]["id"]},
                                      "a threat can reach the dwarves: pull the AI gate lever", 0))
        elif memory.gate_closed_by_ai and sortie:
            proposals.append(Proposal("gate", {"type": "pull_gate", "lever_id": gates[0]["id"]},
                                      "the squads sortie against the enemies outside, the civilians in the "
                                      "shelter: pull the AI gate lever back (open) to let them out", 0))
        elif memory.gate_closed_by_ai and any_reach and open_up:
            proposals.append(Proposal("gate", {"type": "pull_gate", "lever_id": gates[0]["id"]},
                                      "only a few enemies left, inside the fort, or no new one for days: pull "
                                      "the AI gate lever back (open)", 0))
        elif (not any_reach and memory.gate_closed_by_ai and gates
              and (all_clear(s, memory, cfg)[0] or quick_clear(s, memory, cfg))):     # (0.105.3)
            proposals.append(Proposal("gate", {"type": "pull_gate", "lever_id": gates[0]["id"]},
                                      f"no threat for {memory.quiet_cycles} cycles: pull the AI gate "
                                      "lever back", 1))


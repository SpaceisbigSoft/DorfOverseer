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
        # (F2a) one Switch (planner_switch): the lever is a toggle, so it is
        # pulled only when the gate differs from the state wanted, and the
        # wanted state flips at most once a hold (real seconds and cycles);
        # an enemy within switch_emergency_tiles shuts it at once. plan() only
        # reads the switch: record() books the flip of the pull that went
        from planner_switch import Switch, enemy_within
        lever = gates[0]
        closed_ai = bool(memory.gate_closed_by_ai)
        closed = closed_ai or lever.get("shut") is True
        shut_now = any_reach and not open_up
        open_why = ("sortie" if closed_ai and sortie else
                    "few" if closed_ai and any_reach and open_up else
                    "quiet" if (closed_ai and not any_reach
                                and (all_clear(s, memory, cfg)[0] or quick_clear(s, memory, cfg))) else "")
        signal = (True if not closed and shut_now else False if open_why else None)
        sw = Switch(memory, "gate_lever", lever.get("id"), cfg=cfg)
        sw.decide(signal, s, observed=closed,
                  emergency=True if shut_now and enemy_within(s, cfg.get("switch_emergency_tiles")) else None)
        if not sw.act(closed):
            return
        sw.expect("gate", {"type": "pull_gate", "lever_id": lever["id"]})     # record() books the flip
        # (0.105.36) never pulled while the report says the gate is already
        # shut (the player's, or the AI's own not yet read back)
        if sw.state and shut_now and not closed_ai and lever.get("shut") is not True:
            proposals.append(Proposal("gate", {"type": "pull_gate", "lever_id": lever["id"]},
                                      "a threat can reach the dwarves: pull the AI gate lever", 0))
        elif not sw.state and open_why == "sortie":
            proposals.append(Proposal("gate", {"type": "pull_gate", "lever_id": lever["id"]},
                                      "the squads sortie against the enemies outside, the civilians in the "
                                      "shelter: pull the AI gate lever back (open) to let them out", 0))
        elif not sw.state and open_why == "few":
            proposals.append(Proposal("gate", {"type": "pull_gate", "lever_id": lever["id"]},
                                      "only a few enemies left, inside the fort, or no new one for days: pull "
                                      "the AI gate lever back (open)", 0))
        elif not sw.state and open_why == "quiet":     # (0.105.3)
            proposals.append(Proposal("gate", {"type": "pull_gate", "lever_id": lever["id"]},
                                      f"no threat for {memory.quiet_cycles} cycles: pull the AI gate "
                                      "lever back", 1))

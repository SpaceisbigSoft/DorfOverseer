"""Round 9, builder f5: the audit A8 findings fixed on the brain's side
(the Lua sides are tested beside their modules' own tests).

    python tests/test_r9_f5.py

- A8 #7: DF's "not OKAY" for a goal at a site (NO_CIV, ALREADY_IN_CONTACT,
  OWN_CIV...: reason 'unavailable') drops that site for that goal and the
  next one is tried, instead of the nearest site blocking the goal a year
- A8 #23: without raid_sites no site is "clearly beaten"
- A8 #24: no broker call once the caravan at the depot was traded with
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402

import planner_missions as pm  # noqa: E402
import planner_world as pw  # noqa: E402
import planner_trade as pt  # noqa: E402
from planner_core import PLANNER_CONFIG  # noqa: E402

YEAR = 403200


def _state(**kw):
    s = {"date": {"year": 120, "tick": 5000}, "missions": {}, "others_on_map": {"threats_that_can_reach_dwarves": 0},
         "settings": {"traits": {}}}
    s.update(kw)
    return s


class _Mem:
    def __init__(self):
        self.missions_seen = {}
        self.world_seen = {}


@test("A8 #7: Make contact at a site DF says NO_CIV ('unavailable') goes to the next site at once, no Needs you, "
      "and the site stays dropped (remembered) the next year")
def _():
    nearest = [{"id": 61, "relation": "NoContact", "dist": 2}, {"id": 59, "relation": "NoContact", "dist": 6}]
    last = {"goal": "make_contact", "result": "stopped", "reason": "unavailable", "step": "site", "site_id": 61,
            "why": "Diplomacy is NO_CIV there, not OKAY", "tick": 120 * YEAR + 4000}
    s = _state(missions={"sites": {"nearest": nearest},
                         "send": {"buttons": ["World", "Diplomacy"], "last_by_goal": {"make_contact": last}}},
               offices={"offices": {"MESSENGER": {"held": ["Led"]}}})
    orig = pw.player_rules
    try:
        pw.player_rules = lambda st: {**orig(st), "send_messenger": True, "make_contact": True}
        site = pw._contact_site(s, None)
        assert site["id"] == 59, site          # before: 61 again (the nearest), or None for a year
        assert pw._contact_sends(s)            # a soft stop: the send isn't held back
        props, notes = [], []
        pw._contact_rule(s, PLANNER_CONFIG, props, notes, None)
        assert not any(n.startswith("Needs you") for n in notes), notes
        # remembered: a year on, with the run's outcome gone, 61 still dropped for Make contact
        m = _Mem()
        pm.note_unreachable(s, m)
        assert m.missions_seen["unavailable"] == {"make_contact:61": 120 * YEAR + 4000}, m.missions_seen
        s2 = _state(date={"year": 121, "tick": 0}, missions={"sites": {"nearest": nearest}},
                    offices={"offices": {"MESSENGER": {"held": ["Led"]}}})
        assert pw._contact_site(s2, m)["id"] == 59
        assert pm.unavailable_sites(s2, "raid", m) == set()        # only that goal
        # forgotten after mission_unreachable_ticks
        s3 = _state(date={"year": 124, "tick": 0}, missions={})
        pm.note_unreachable(s3, m)
        assert m.missions_seen["unavailable"] == {}
    finally:
        pw.player_rules = orig


@test("A8 #7 (and #19's stop): a mission DF said 'not OKAY' to at a site passes over that site for the next; the goal isn't "
      "blocked a year and nothing waits for the player")
def _():
    send = {"last_by_goal": {"rescue": {"goal": "rescue", "result": "stopped", "reason": "unavailable",
                                        "step": "site", "site_id": 1600, "tick": 120 * YEAR + 4000}}}
    targets = [{"goal": "rescue", "site_id": 1600, "dist": 3, "hf_id": 5},
               {"goal": "rescue", "site_id": 73, "dist": 9, "hf_id": 6}]
    s = _state(missions={"send": send, "targets": targets})
    orig = pm.player_rules
    try:
        pm.player_rules = lambda st: {**orig(st), "missions": "all"}
        t, stopped = pm.mission_target(s, PLANNER_CONFIG, None)
        assert t["site_id"] == 73 and stopped == [], (t, stopped)
        notes = []
        pm._stopped_needs_you(s, "rescue", PLANNER_CONFIG, notes)
        assert notes == []
    finally:
        pm.player_rules = orig


@test("A8 #23: without raid_sites (lua/ai-raids failed to load) the matchup isn't skipped: no raid, and why")
def _():
    import planner_raids as pr
    tgt = [{"goal": "raid", "site_id": 5, "site": "Pits", "dist": 5, "civ_id": 7, "hostile": True, "at_war": True,
            "type": "Town"}]
    s = _state(missions={"targets": tgt}, settings={"traits": {}, "raid_policy": "aggressive"})
    squads = [{"id": 4, "power": {"power": 22.9}}]
    cands, words, _ = pr.raid_candidates(s, PLANNER_CONFIG, None, squads, tgt)
    assert cands == [] and any("couldn't be read" in w for w in words), (cands, words)
    s["missions"]["raid_sites"] = {"rows": [{"site_id": 5, "pop": 1, "type": "Town", "civ_id": 7}]}
    cands, words, _ = pr.raid_candidates(s, PLANNER_CONFIG, None, squads, tgt)
    assert [c["site_id"] for c in cands] == [5], (cands, words)


def _trade_state(fresh):
    return {"trade": {"depot": True, "caravans": [{"civ": "Humans", "state": "AtDepot"}], "goods": 0,
                      "trader": {"at_depot": False, "requested": True, "fresh": fresh}},
            "buildings": {}, "date": {"year": 120, "tick": 5000}}


@test("A8 #24: the broker isn't called again once the caravan at the depot was traded with (fresh false); "
      "called while it is fresh")
def _():
    for fresh, want in ((True, True), (False, False)):
        props, notes = [], []
        pt._trade_rules(_trade_state(fresh), PLANNER_CONFIG, 20, props, notes, {"trade": 0}, None)
        got = any(p.action.get("type") == "call_trader" for p in props)
        assert got is want, (fresh, [p.action for p in props])


if __name__ == "__main__":
    finish()

"""Tests for memory, part one: the outcome log, self-calibration and learning
from the player. No game, no tokens.

    python tests/test_learning.py
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

import calibrate  # noqa: E402
import learning  # noqa: E402
import outcomes  # noqa: E402
from planner import PLANNER_CONFIG, Memory, Proposal, effective_config, plan  # noqa: E402
from weights import choose  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
TMP = Path(tempfile.mkdtemp())
learning.PLAYER_FILE = TMP / "player-memory.json"
RESULTS = []
DAY = 1200


def test(name):
    def wrap(fn):
        learning.PLAYER_FILE.unlink(missing_ok=True)
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception:  # noqa: BLE001
            import traceback
            RESULTS.append((name, False, traceback.format_exc()))
        return fn
    return wrap


def fort(**traits) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["tick"] = 0
    s["settings"]["traits"] = traits
    return s


def at(s: dict, days: int) -> dict:
    s = copy.deepcopy(s)
    s["date"]["tick"] += days * DAY
    return s


def ok(action, rule="test", reason="because"):
    return (Proposal(rule, action, reason, 5), {"ok": True})


def settled(**traits):
    """Beds, dining, workshops, stockpiles, hospital, tavern, library: only culture is left."""
    s = fort(**traits)
    s["locations"] = {"count": {"HOSPITAL": 1, "INN_TAVERN": 1, "LIBRARY": 1}, "total": 3}
    return s


def builds(state, memory):
    return [p.action for p in plan(state, memory)[0] if p.rule == "build"]


# --- the outcome log ----------------------------------------------------------------------

@test("outcome log: a brewing order is judged after 14 days by drink per dwarf (one entry per kind)")
def _():
    m = Memory()
    s = fort()
    s["stocks"]["drink"] = 194 * 3
    order = {"type": "work_order", "recipe": "brew_drink", "amount": 40}
    opened = outcomes.record_actions([ok(order), ok(order)], s, m)
    assert len(opened) == 1 and opened[0]["metric"] == "drink_pd" and opened[0]["expect"] == "up"
    assert outcomes.judge(at(s, 13), m) == []                     # not yet
    later = at(s, 14)
    later["stocks"]["drink"] = 194 * 8
    done = outcomes.judge(later, m)
    assert [e["verdict"] for e in done] == ["helped"], done
    assert m.outcomes["tally"]["drink_order"]["helped"] == 1 and not m.outcomes["open"]


@test("outcome log: no change is 'no effect', the wrong way is 'hurt'")
def _():
    for drink_after, want in ((194 * 3, "none"), (194 * 1, "hurt")):
        m = Memory()
        s = fort()
        s["stocks"]["drink"] = 194 * 3
        outcomes.record_actions([ok({"type": "work_order", "recipe": "brew_drink", "amount": 40})], s, m)
        later = at(s, 20)
        later["stocks"]["drink"] = drink_after
        assert outcomes.judge(later, m)[0]["verdict"] == want


@test("outcome log: a siege or a migrant wave in between makes it unclear")
def _():
    m = Memory(culture={"sieges": 0})
    s = fort()
    outcomes.record_actions([ok({"type": "work_order", "recipe": "brew_drink", "amount": 40})], s, m)
    m.culture["sieges"] = 1
    e = outcomes.judge(at(s, 14), m)[0]
    assert e["verdict"] == "unclear" and "siege" in e["why"]
    m = Memory()
    outcomes.record_actions([ok({"type": "work_order", "recipe": "brew_drink", "amount": 40})], s, m)
    later = at(s, 14)
    later["dwarves"]["total"] = 260
    assert outcomes.judge(later, m)[0]["verdict"] == "unclear"


@test("outcome log: free beds are judged with the newcomers taken out (0.42: 'a bedroom level hurt')")
def _():
    m = Memory()
    s = fort()
    s["dwarves"]["total"] = 20
    s["buildings"]["other"]["Bed"] = 14                      # -6 free
    outcomes.record_actions([ok({"type": "start_project", "kind": "bedrooms", "rooms": 8})], s, m)
    later = at(s, 28)
    later["dwarves"]["total"] = 24                           # 4 migrants
    later["buildings"]["other"]["Bed"] = 22                  # 8 beds built: -2 free, +4 without the migrants
    e = outcomes.judge(later, m)[0]
    assert e["verdict"] == "helped" and "+4 dwarves" in e["why"], e


@test("outcome log: a level still being built is judged after it's done (at most 12 weeks late)")
def _():
    m = Memory()
    s = fort()
    s["dwarves"]["total"] = 20
    s["buildings"]["other"]["Bed"] = 14
    outcomes.record_actions([ok({"type": "start_project", "kind": "bedrooms", "rooms": 8})], s, m)
    later = at(s, 28)
    later["projects"] = {"open": [{"kind": "bedrooms", "phase": "furnish"}]}
    first = m.outcomes["open"][0]["judge_at"]
    assert outcomes.judge(later, m) == [] and m.outcomes["open"][0]["judge_at"] == first + 7 * DAY, m.outcomes
    done = at(s, 36)
    done["projects"] = {"open": []}
    done["buildings"]["other"]["Bed"] = 22
    assert outcomes.judge(done, m)[0]["verdict"] == "helped"
    m = Memory()
    outcomes.record_actions([ok({"type": "start_project", "kind": "bedrooms", "rooms": 8})], s, m)
    stuck = at(s, 28)
    stuck["projects"] = {"open": [{"kind": "bedrooms", "phase": "dig"}]}
    for d in range(28, 28 + 84 + 8, 7):
        r = outcomes.judge(at(stuck, d - 28), m)
    assert not m.outcomes["open"], m.outcomes["open"]                  # judged in the end anyway


@test("outcome log: a big stock must move by 5% to count (drink 22.8 to 23.6 is no effect)")
def _():
    m = Memory()
    s = fort()
    s["stocks"]["drink"] = round(194 * 22.8)
    outcomes.record_actions([ok({"type": "work_order", "recipe": "brew_drink", "amount": 10})], s, m)
    later = at(s, 14)
    later["stocks"]["drink"] = round(194 * 23.9)
    assert outcomes.judge(later, m)[0]["verdict"] == "none"


@test("outcome log: agreeing verdicts become a lesson in words; refused actions open nothing")
def _():
    m = Memory()
    s = fort()
    for i in range(4):
        s["stocks"]["drink"] = 194 * 2
        outcomes.record_actions([ok({"type": "work_order", "recipe": "brew_drink", "amount": 40})], s, m)
        s = at(s, 15)
        s["stocks"]["drink"] = 194 * 6
        outcomes.judge(s, m)
    assert outcomes.lessons(m) == ["brewing orders: helped (4 of 4)"], outcomes.lessons(m)
    assert outcomes.record_actions([(Proposal("x", {"type": "work_order", "recipe": "brew_drink"}, "", 1),
                                     {"ok": False})], s, m) == []


@test("outcome log: entries from 'the future' (an older save) are dropped")
def _():
    m = Memory()
    s = at(fort(), 30)
    outcomes.record_actions([ok({"type": "start_project", "kind": "tavern"})], s, m)
    assert m.outcomes["open"]
    outcomes.judge(fort(), m)
    assert not m.outcomes["open"] and not m.outcomes["recent"]


# --- self-calibration -----------------------------------------------------------------------

def run_days(s, m, days, change=None):
    out = []
    for d in range(days):
        cur = at(s, d)
        if change:
            change(cur, d)
        cfg = effective_config(m.adjust, calibration=calibrate.values(m))
        out += calibrate.update(cur, m, cfg, m.adjust)
    return out


@test("self-tuning: drink below the urgent line raises the drink target by 2, then it waits")
def _():
    m = Memory()
    s = fort()
    def thin(cur, d):
        cur["stocks"]["drink"] = 194 * (1 if d == 5 else 9)
    ch = run_days(s, m, 15, thin)
    assert [(c["key"], c["old"], c["new"]) for c in ch if c["key"] == "drink_per_dwarf"] == \
        [("drink_per_dwarf", 10, 12)], ch
    assert effective_config(m.adjust, calibration=calibrate.values(m))["drink_per_dwarf"] == 12
    later = run_days(at(s, 15), m, 20, thin)
    assert not [c for c in later if c["key"] == "drink_per_dwarf"], later   # waits 28 days after a change


@test("self-tuning: drawn down but never short lowers the target by 1; bounds hold")
def _():
    m = Memory()
    s = fort()
    def drawn(cur, d):
        cur["stocks"]["drink"] = 194 * (5 if d == 3 else 12)
        cur["stocks"]["prepared_meals"] = 194 * 20
    ch = run_days(s, m, 15, drawn)
    assert [(c["key"], c["new"]) for c in ch if c["key"] == "drink_per_dwarf"] == [("drink_per_dwarf", 9)], ch
    m.calibration["values"]["drink_per_dwarf"] = 6
    m.calibration["changed"] = {}
    assert calibrate._step("drink_per_dwarf", 6, False) == 6 and calibrate._step("drink_per_dwarf", 20, True) == 20


@test("self-tuning: no cooked meals but plenty of raw food doesn't raise the meal target (0.39 raised it to 16)")
def _():
    m = Memory()
    s = fort()
    def raw(cur, d):
        cur["stocks"].update(prepared_meals=0, meat=194 * 10, plants=194 * 10, drink=194 * 12)
    ch = run_days(s, m, 15, raw)
    assert not [c for c in ch if c["key"] == "meals_per_dwarf" and c["up"]], ch


@test("self-tuning: a value learned from evidence since corrected is dropped and learned again; bounds hold")
def _():
    m = Memory()
    m.calibration = {"values": {"meals_per_dwarf": 16, "drink_per_dwarf": 30}, "windows": {}, "changed": {},
                     "log": []}
    v = calibrate.values(m)
    assert "meals_per_dwarf" not in v and v["drink_per_dwarf"] == 20, v      # (drink's bound is 20)
    assert m.calibration["revisions"]["meals_per_dwarf"] == calibrate.REVISIONS["meals_per_dwarf"]
    assert any("corrected" in x.get("why", "") for x in m.calibration["log"])
    m.calibration["values"]["meals_per_dwarf"] = 12                      # learned under today's evidence: kept
    assert calibrate.values(m)["meals_per_dwarf"] == 12


@test("self-tuning: a target the strategist set is left alone; the strategist's value wins")
def _():
    m = Memory(adjust={"drink_per_dwarf": 25})
    s = fort()
    ch = run_days(s, m, 15, lambda cur, d: cur["stocks"].__setitem__("drink", 10))
    assert not [c for c in ch if c["key"] == "drink_per_dwarf"]
    assert effective_config({"drink_per_dwarf": 25}, calibration={"drink_per_dwarf": 12})["drink_per_dwarf"] == 25


@test("self-tuning: farms shrink only at full size with plenty of food and idle hands")
def _():
    m = Memory()
    s = fort()
    s["farms"] = {"plots": 30, "tiles": 400}
    def plenty(cur, d):
        cur["stocks"]["plants"] = 194 * 12
        cur["dwarves"]["idle_adults"] = cur["dwarves"]["adults"] // 2
    ch = run_days(s, m, 29, plenty)
    assert [(c["key"], c["new"]) for c in ch if c["key"] == "farm_tiles_per_dwarf"] == [("farm_tiles_per_dwarf", 0.9)], ch
    m = Memory()
    s["farms"] = {"plots": 2, "tiles": 8}                         # far below target: can't judge the size
    assert not [c for c in run_days(s, m, 29, plenty) if c["key"] == "farm_tiles_per_dwarf"]


@test("self-tuning: a new pasture needed again soon after the last one raises the margin")
def _():
    s = fort()
    m = Memory(last_fired={"new_pasture": s["date"]["year"] * 403200})     # the AI made one today
    def waiting(cur, d):
        cur["society"].update({"grazers_unpastured": 3, "pastures": 2, "pasture_spare": 0,
                               "grazer_tiles_smallest": 6})
    ch = run_days(s, m, 85, waiting)
    assert [(c["key"], c["new"]) for c in ch if c["key"] == "pasture_margin"] == [("pasture_margin", 1.4)], ch


# --- learning from you ---------------------------------------------------------------------

TEMPLE = {"type": "start_project", "kind": "temple", "size": "shrine"}


@test("learning: one No holds temples back 4 weeks; the next kind of level gets its turn")
def _():
    m = Memory()
    s = settled(piety=60)
    s["locations"]["count"].pop("LIBRARY")
    s["dwarves"]["total"] = 194
    assert builds(s, m)[0]["kind"] == "library"                   # library comes before the temple
    s["locations"]["count"]["LIBRARY"] = 1
    assert builds(s, m)[0]["kind"] == "temple"
    learning.note_decline(m, TEMPLE, s)
    assert builds(s, m) == []
    notes = plan(s, m)[1]
    assert any("holding back on temples for 28 more days" in n for n in notes), notes
    assert builds(at(s, 29), m)[0]["kind"] == "temple"            # waited, then tries again


@test("learning: two of a kind make a lesson: left to you, and the Worship choice leans away")
def _():
    m = Memory(culture={})
    s = settled(piety=60)
    learning.note_decline(m, TEMPLE, s)
    text = learning.note_decline(m, TEMPLE, at(s, 40))
    assert text.startswith("lesson:"), text
    later = at(s, 400)
    assert builds(later, m) == []
    assert any("left to you: temples" in n for n in plan(later, m)[1])
    before = choose("worship", {"piety": 30}, {})["id"]
    m.culture["learned"] = learning.engine_bonuses(m)
    after = choose("worship", {"piety": 30}, m.culture)
    assert before == "shrine" and after["id"] == "none" and "turned it down" in \
        __import__("weights").why_text(after), (before, after)


@test("learning: what keeps the fort alive is never held back (drink, the alarm, bedrooms)")
def _():
    m = Memory()
    s = fort()
    for a in ({"type": "work_order", "recipe": "brew_drink", "amount": 10},
              {"type": "start_project", "kind": "bedrooms", "rooms": 10}):
        learning.note_decline(m, a, s)
        learning.note_decline(m, a, s)
    props = [Proposal("drink", {"type": "work_order", "recipe": "brew_drink", "amount": 10}, "", 1, True),
             Proposal("build", {"type": "start_project", "kind": "bedrooms", "rooms": 10}, "", 6),
             Proposal("threat_alert", {"type": "civ_alert", "on": True}, "", 0)]
    kept, notes = learning.apply(props, m, 0)
    assert len(kept) == 3 and not notes
    kinds = {d["text"]: d["effect"] for d in learning.describe(m, 0)}
    assert kinds["bedroom levels"] == "still done when the fort needs it", kinds


@test("learning: a slider moved against an AI action right after it is a correction; a big move back forgets")
def _():
    m = Memory()
    s = fort(piety=60)
    learning.observe(s, m)
    learning.note_actions([ok(TEMPLE)], s, m)
    nxt = at(fort(piety=30), 1)
    out = learning.observe(nxt, m)
    assert out and "lowered Piety" in out[0] and learning.weight(m, "level:temple") == 1, out
    assert learning.observe(at(fort(piety=0), 2), m) == []        # one correction per action
    out = learning.observe(at(fort(piety=60), 3), m)
    assert "forgot" in out[0] and learning.weight(m, "level:temple") == 0, out
    # long after the action: a slider move is just a setting
    learning.note_actions([ok(TEMPLE)], at(s, 3), m)
    assert learning.observe(at(fort(piety=0), 10), m) == []


@test("learning: removing an AI pasture, cancelling a big AI order, switching off an AI tool")
def _():
    m = Memory(tools_enabled_by_ai=["autobutcher"], tools_confirmed_on=["autobutcher"])
    s = fort()
    s["society"]["ai_pastures"] = 0
    learning.observe(s, m)
    learning.note_actions([ok({"type": "make_pasture", "tiles": 50})], s, m)
    s1 = at(s, 1)
    s1["society"]["ai_pastures"] = 1
    assert learning.observe(s1, m) == []                          # the one it just made
    s2 = at(s, 2)
    s2["society"]["ai_pastures"] = 0
    s2["orders"] = [{"id": 77, "by_ai": True, "recipe": "stone_blocks", "amount_left": 40, "amount_total": 50}]
    out = learning.observe(s2, m)
    assert any("removed an AI pasture" in x for x in out), out
    s3 = at(s, 3)
    s3["society"]["ai_pastures"] = 0
    s3["orders"] = []
    s3["tools"]["autobutcher"] = False
    out = learning.observe(s3, m)
    assert any("cancelled the AI's order for 40 stone blocks" in x for x in out), out
    assert any("switched off autobutcher" in x for x in out), out
    # a small order that finished is not a cancellation
    s4 = at(s, 4)
    s4["orders"] = [{"id": 78, "by_ai": True, "recipe": "brew_drink", "amount_left": 5, "amount_total": 30}]
    learning.observe(s4, m)
    s5 = at(s, 5)
    s5["orders"] = []
    assert learning.observe(s5, m) == []


@test("learning: switching a Rules option off right after the AI did it")
def _():
    m = Memory()
    s = fort()
    learning.observe(s, m)
    learning.note_actions([ok({"type": "fortify_entrance", "style": "gatehouse", "entrance_id": 1})], s, m)
    s1 = at(s, 1)
    s1["settings"]["fortify_entrances"] = False
    out = learning.observe(s1, m)
    assert out and learning.weight(m, "gate:gatehouse") == 1, out
    m.culture = {}
    m.culture["learned"] = learning.engine_bonuses(m)
    assert m.culture["learned"] == {"defence": {"gatehouse": -0.15}}


@test("learning: a Yes takes one signal back")
def _():
    m = Memory()
    s = fort()
    learning.note_decline(m, TEMPLE, s)
    learning.note_decline(m, TEMPLE, s)
    learning.note_approve(m, TEMPLE, s)
    assert learning.weight(m, "level:temple") == 1


@test("your memory: a lesson goes to the shared file; a new fort starts with it at half weight")
def _():
    a = Memory()
    s = fort()
    learning.note_decline(a, TEMPLE, s)
    learning.note_decline(a, TEMPLE, s)
    learning.observe(s, a, "fortA#1")
    shared = json.loads(learning.PLAYER_FILE.read_text(encoding="utf-8"))
    entry = shared["lessons"]["level:temple"]["forts"]["fortA#1"]
    assert list(shared["lessons"]["level:temple"]["forts"]) == ["fortA#1"] and entry["w"] == 2.0 and entry["seen"]
    b = Memory()
    learning.observe(s, b, "fortB#2")
    assert learning.weight(b, "level:temple") == 1.0
    verdict, why = learning.hold(b, "level:temple", 0, "build", 6)
    assert verdict == "wait", (verdict, why)                       # half weight: waits, isn't left to you
    assert learning.describe(b, 0)[0]["inherited"] is True
    learning.note_approve(b, TEMPLE, s)                            # this fort wants temples after all
    learning.observe(at(s, 1), b, "fortB#2")
    assert learning.weight(b, "level:temple") == 0
    # fort A changes its mind: the lesson leaves the shared file
    a.learning["prefs"]["level:temple"]["weight"] = 0
    learning.observe(at(s, 1), a, "fortA#1")
    assert json.loads(learning.PLAYER_FILE.read_text(encoding="utf-8"))["lessons"] == {}


@test("wipe: the panel's counters; first sight never wipes; this fort / all forts")
def _():
    m = Memory()
    s = fort()
    s["settings"]["wipe_learned"], s["settings"]["wipe_learned_all"] = 3, 0
    learning.note_decline(m, TEMPLE, s)
    learning.note_decline(m, TEMPLE, s)
    m.calibration = {"values": {"drink_per_dwarf": 12}}
    learning.observe(s, m, "fortA#1")
    assert learning.weight(m, "level:temple") == 2                 # first look: nothing pressed
    s1 = at(s, 1)
    s1["settings"]["wipe_learned"] = 4
    out = learning.observe(s1, m, "fortA#1")
    assert "wiped" in out[0] and learning.weight(m, "level:temple") == 0 and calibrate.values(m) == {}
    # wiping all clears the shared lessons too
    other = Memory()
    learning.note_decline(other, TEMPLE, s)
    learning.note_decline(other, TEMPLE, s)
    learning.observe(s, other, "fortC#3")
    s2 = at(s, 2)
    s2["settings"]["wipe_learned"], s2["settings"]["wipe_learned_all"] = 4, 1
    learning.observe(s2, m, "fortA#1")
    assert json.loads(learning.PLAYER_FILE.read_text(encoding="utf-8"))["lessons"] == {}


@test("plan() never changes memory, also with preferences learned")
def _():
    m = Memory()
    s = settled(piety=60)
    learning.note_decline(m, TEMPLE, s)
    before = json.dumps(m.to_dict(), sort_keys=True)
    plan(s, m)
    assert json.dumps(m.to_dict(), sort_keys=True) == before


@test("the strategist is told what the player turned down and what tuned itself")
def _():
    import review  # noqa: F401  (review builds the culture lines the strategist reads)
    from strategist import review_message
    m = Memory()
    s = fort()
    learning.note_decline(m, TEMPLE, s)
    m.calibration = {"values": {"drink_per_dwarf": 12}, "log": [{"key": "drink_per_dwarf", "why": "ran short"}]}
    msg = review_message(s, "routine", [], [], {}, [], {
        "learned": learning.brief(m),
        "tuned": [f"{c['key']}={c['value']}" for c in calibrate.describe(m, PLANNER_CONFIG)]})
    assert "THE PLAYER TURNED DOWN (don't propose these) no temples" in msg, msg
    assert "SELF-TUNED TARGETS (yours to undo with adjust) drink_per_dwarf=12" in msg, msg


@test("the panel's settings (Lua) keep the wipe counters, and an odd value becomes 0")
def _():
    try:
        from lupa import LuaRuntime
    except ImportError:
        return
    lua = LuaRuntime(unpack_returned_tuples=True)
    src = (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    S = lua.eval("""function(src)
      local env = setmetatable({dfhack_flags = {module = true}, dfhack = {getDFPath = function() return '.' end,
                                          isMapLoaded = function() return false end}},
                               {__index = _G})
      env.require = function(n) if n == 'json' then return {} end return require(n) end
      assert(load(src, 'settings', 't', env))()
      return env end""")(src)
    d = S.defaults()
    assert d.wipe_learned == 0 and d.wipe_learned_all == 0
    s = S.sanitize(lua.table_from({"wipe_learned": 5, "wipe_learned_all": "x"}))
    assert s.wipe_learned == 5 and s.wipe_learned_all == 0
    ai = S.for_ai(s)
    assert ai.wipe_learned == 5 and ai.wipe_learned_all == 0


@test("the hospital burrow's Rules switch (0.104.168): on by default, saved, sent to the AI; the panel shows it")
def _():
    try:
        from lupa import LuaRuntime
    except ImportError:
        return
    lua = LuaRuntime(unpack_returned_tuples=True)
    src = (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    S = lua.eval("""function(src)
      local env = setmetatable({dfhack_flags = {module = true}, dfhack = {getDFPath = function() return '.' end,
                                          isMapLoaded = function() return false end}},
                               {__index = _G})
      env.require = function(n) if n == 'json' then return {} end return require(n) end
      assert(load(src, 'settings', 't', env))()
      return env end""")(src)
    assert S.defaults().hospital_burrow is True and S.for_ai(S.defaults()).hospital_burrow is True
    off = S.sanitize(lua.table_from({"hospital_burrow": False}))
    assert off.hospital_burrow is False and S.for_ai(off).hospital_burrow is False
    assert S.sanitize(lua.table_from({})).hospital_burrow is True             # an older save: on
    # the brain reads it the same way: off only when the settings say so
    from planner_core import player_rules
    assert player_rules({"settings": {"hospital_burrow": False}})["hospital_burrow"] is False
    assert player_rules({"settings": {}})["hospital_burrow"] is True
    # the panel: a switch on the Rules page, set again on refresh (and the file still loads)
    gui = (ROOT / "lua" / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
    assert "view_id = 'hospital_burrow'" in gui and "p:set_field('hospital_burrow', v)" in gui
    assert "self.subviews.hospital_burrow:setOption(" in gui
    # (0.104.169) the calm-down burrows' switch, the same way
    assert S.defaults().calm_burrow is True and S.for_ai(S.defaults()).calm_burrow is True
    off = S.sanitize(lua.table_from({"calm_burrow": False}))
    assert off.calm_burrow is False and S.for_ai(off).calm_burrow is False
    assert S.sanitize(lua.table_from({})).calm_burrow is True
    assert player_rules({"settings": {"calm_burrow": False}})["calm_burrow"] is False
    assert player_rules({"settings": {}})["calm_burrow"] is True
    assert "view_id = 'calm_burrow'" in gui and "p:set_field('calm_burrow', v)" in gui
    assert "self.subviews.calm_burrow:setOption(" in gui
    ok = lua.eval("function(src) local f, e = load(src, 'gui', 't', {}); return f ~= nil, e end")(gui)
    assert ok[0], ok



@test("your memory (0.97.1): a fort's copies and autosaves are one fort; it never inherits itself (B1)")
def _():
    assert learning.line_key("autosave 2#239", "Enxah") == "line:Enxah#239" == learning.line_key("region2#239", "Enxah")
    assert learning.line_key("region2#239", None) == "region2#239"
    s = fort()
    learning.save_player({"version": 1, "lessons": {"level:temple": {"text": "temples", "forts": {
        "autosave 1#239": 2.0, "AI Test Run 2#239": 3.0}}}})
    m = Memory()
    learning.observe(s, m, "line:Enxah#239")
    assert learning.weight(m, "level:temple") == 0                 # its own old copies: not inherited
    assert learning.load_player()["lessons"] == {}                 # and folded away


@test("your memory (0.97.1): inheritance is a lean, never a lesson; it ages with real time (B2, B8)")
def _():
    from datetime import datetime, timedelta
    s = fort()
    today = datetime.now().date().isoformat()
    learning.save_player({"version": 1, "lessons": {"level:temple": {"text": "temples", "forts": {
        "line:W#1": {"w": 6.0, "seen": today}}}}})
    m = Memory()
    learning.observe(s, m, "line:W#2")
    assert learning.weight(m, "level:temple") == learning.INHERIT_MAX
    assert learning.hold(m, "level:temple", 0, "build", 6)[0] == "wait"        # not "left to you"
    old = (datetime.now() - timedelta(days=65)).date().isoformat()
    learning.save_player({"version": 1, "lessons": {"level:temple": {"text": "temples", "forts": {
        "line:W#1": {"w": 2.0, "seen": old}}}}})
    learning.observe(at(s, 1), m, "line:W#2")
    assert learning.weight(m, "level:temple") == 0.25, learning.weight(m, "level:temple")   # 2 x 1/4 / 2
    older = (datetime.now() - timedelta(days=100)).date().isoformat()
    learning.save_player({"version": 1, "lessons": {"level:temple": {"text": "temples", "forts": {
        "line:W#1": {"w": 2.0, "seen": older}}}}})
    learning.observe(at(s, 2), m, "line:W#2")
    assert learning.weight(m, "level:temple") == 0                 # past three months: ignored


@test("your memory (0.97.1): 'wipe all forts' is honoured by the other forts, once (B3)")
def _():
    s = fort()
    a, b = Memory(), Memory()
    for m, key in ((a, "line:W#1"), (b, "line:W#2")):
        learning.note_decline(m, TEMPLE, s)
        learning.note_decline(m, TEMPLE, s)
        learning.observe(s, m, key)
    learning.wipe(a, everything=True)
    out = learning.observe(at(s, 1), b, "line:W#2")
    assert any("forgotten here too" in x for x in out), out
    assert learning.weight(b, "level:temple") == 0 and learning.load_player()["lessons"] == {}
    learning.note_decline(b, TEMPLE, s)
    learning.note_decline(b, TEMPLE, s)                           # learned again afterwards: kept
    learning.observe(at(s, 2), b, "line:W#2")
    assert learning.weight(b, "level:temple") >= 2


@test("your memory (0.97.1): forgiving by slider sticks; a dry run doesn't write the PC file (B4, B11)")
def _():
    s = fort()
    learning.save_player({"version": 1, "lessons": {"level:temple": {"text": "temples", "forts": {
        "line:W#1": {"w": 2.0, "seen": __import__("datetime").datetime.now().date().isoformat()}}}}})
    m = Memory()
    s["settings"]["traits"] = {"piety": 0}
    learning.observe(s, m, "line:W#2")
    assert learning.weight(m, "level:temple") == 1.0
    s2 = at(s, 1)
    s2["settings"]["traits"] = {"piety": 60}                      # you want temples after all
    out = learning.observe(s2, m, "line:W#2")
    assert any("forgot" in x for x in out) and learning.weight(m, "level:temple") == 0, out
    learning.observe(at(s2, 2), m, "line:W#2")
    assert learning.weight(m, "level:temple") == 0                 # not inherited straight back
    before = learning.PLAYER_FILE.read_text(encoding="utf-8")
    d = Memory()
    learning.note_decline(d, TEMPLE, s)
    learning.note_decline(d, TEMPLE, s)
    learning.observe(s, d, "line:W#3", write_pc=False)
    assert learning.PLAYER_FILE.read_text(encoding="utf-8") == before



@test("B6 (0.102.7): a self-tuned raise judged no effect or hurt is taken back; one that helped stays")
def _():
    m = Memory()
    state = {"date": {"year": 60, "tick": 5000, "day": 3, "month": "Granite"}}
    c = calibrate._state(m)
    c["values"]["drink_per_dwarf"] = 12
    e = {"kind": "drink_target", "by": "self-tuning", "verdict": "none",
         "tune_key": "drink_per_dwarf", "tune_old": 10, "tune_new": 12}
    ch = calibrate.heed(e, m, state)
    assert ch and ch["new"] == 10 and calibrate.values(m).get("drink_per_dwarf") == 10, (ch, calibrate.values(m))
    c["values"]["drink_per_dwarf"] = 12
    assert calibrate.heed(dict(e, verdict="helped"), m, state) is None
    assert calibrate.heed(dict(e, by="strategist"), m, state) is None
    c["values"]["drink_per_dwarf"] = 14                     # moved again since: left alone
    assert calibrate.heed(e, m, state) is None

if __name__ == "__main__":
    for name, passed, msg in RESULTS:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, passed, _ in RESULTS if not passed)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

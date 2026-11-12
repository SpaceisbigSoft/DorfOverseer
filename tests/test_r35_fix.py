"""(v35 fixes) The independent verifier's findings on 0.105.35, fixed:

Bugs
1. The player's gates: the AI never opens a gate it didn't shut (no lever of
   the player's pulled, no door the player locked unlocked); citizens behind
   one get a way dug in (dig_way_in), said in a plain note.
2. open_entrance's refusal key carries the entrance id, and the stranded
   rule's proposals for different entrances keep their own cooldowns.
3. The cistern after a leak: the first leak asks for the plain step (the
   bridge lets water in again once dry and closed all round); a leak is
   counted once per event, not per step; the second retires it.
4. The alarm held for citizens in the caverns: `cavern_alarm_max_days` (3)
   at most, then let down and the ways locked, said.
5. Berserk: no re-send at the same target within `berserk_resend_ticks`
   (the loop guard counts the sends); never at a changed werebeast by a
   squad only partly armed.

Risks
- leak-watch holds of the water works ("water is still getting in", "the
  floodgate is gone") are never retired;
- the unfound-cavern decision counts armed soldiers; the Rules switch is
  three-state (AI decides / Always / Never);
- free_gate_jobs resumes only what the AI planned;
- unstick step 3 never on a cavern's way;
- the labour rules' caps (LABOR_CAPS);
- the workshops level re-started SHOPS_RETRY_MAX times at most.
Nits: the retire cap's floodgate shut as said; a timed-out wide founding
search isn't booked as a wide failure.

    python tests/test_r35_fix.py
"""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))

from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

import planner  # noqa: E402
import planner_core  # noqa: E402
import planner_gates as pg  # noqa: E402
import planner_military as pm  # noqa: E402
import planner_threats as pt  # noqa: E402
import planner_water as pwt  # noqa: E402
import planner_wells as pw  # noqa: E402
import strategist  # noqa: E402
import overseer  # noqa: E402
from planner import Memory, PLANNER_CONFIG, plan, record, select  # noqa: E402
from planner_core import Proposal, abs_tick, note_refusal, refusal_key  # noqa: E402

CFG = PLANNER_CONFIG
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
DAY = planner_core.TICKS_PER_DAY

_src = (ROOT / "tests" / "test_r32_gatesplit.py").read_text(encoding="utf-8")
_ns: dict = {"module_src": module_src, "sys": sys}
exec(compile(_src[_src.index("try:\n    from lupa"):_src.index("\ndef lst")], "r32rig", "exec"), _ns)
LUA = _ns["LUA"]
rig = _ns["rig"]
t = LUA.table_from


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    return s


def you(notes):
    return [n for n in notes if isinstance(n, str) and n.startswith(("[you]", "Needs you"))]


def player_gate_state(siege=False):
    s = fort()
    s["others_on_map"] = dict(s.get("others_on_map") or {}, threats_that_can_reach_dwarves=2 if siege else 0)
    s["entrances"] = dict(s.get("entrances") or {}, scanned=True, armed=siege, stranded=[
        {"name": "Kib", "x": 10, "y": 10, "z": 5, "cause": "gate_shut", "by_ai": False, "out_ticks": 5000,
         "out_days": 4, "gate_danger": 35, "danger_near": 35,
         "entrance": {"id": 3, "kind": "surface", "x": 9, "y": 9, "z": 5}}])
    return s


# --- 1. the player's gates ------------------------------------------------------------

@test("bug 1: a gate the AI didn't shut, siege or not, gate_lever on or off: never open_entrance; a way dug in, said")
def _():
    for siege in (True, False):
        for lever in (True, False):
            s = player_gate_state(siege)
            s["settings"]["gate_lever"] = lever
            props, notes = [], []
            pg._stranded_rule(s, CFG, props, notes, Memory())
            assert not [p for p in props if p.action.get("type") in ("open_entrance", "open_gates")], props
            line = [n for n in notes if "the gate is the player's" in n]
            assert line and "leaves it as it is" in line[0] and not you(notes), notes
            way = [p for p in props if p.rule == "way_in"]
            if siege:
                assert not way and "once the siege is over" in line[0], (props, line)
            else:
                assert [p.action["type"] for p in way] == ["dig_way_in"], props
                assert "behind a gate the AI didn't shut" in way[0].reason, way[0].reason
                assert "digs them a way in" in line[0], line


@test("bug 1: down in the caverns behind the player's gate: no gate opened, no way dug from a cavern, a plain note")
def _():
    s = player_gate_state()
    s["deep"] = {"caverns": [], "dangers": []}
    r = s["entrances"]["stranded"][0]
    r.update(in_cavern=True, entrance={"id": 4, "kind": "cavern", "x": 9, "y": 9, "z": 5})
    props, notes = [], []
    pg._stranded_rule(s, CFG, props, notes, Memory())
    assert not [p for p in props if p.rule in ("stranded", "way_in")], props
    assert [n for n in notes if "down in the caverns" in n and "the gate is the player's" in n], notes
    assert not you(notes), notes
    # the AI's own gate there, the caverns read safe: still opened by the AI
    r["by_ai"] = True
    props, notes = [], []
    pg._stranded_rule(s, CFG, props, notes, Memory())
    assert [p.action for p in props if p.rule == "stranded"] == [{"type": "open_entrance", "id": 4,
                                                                  "cavern_ok": True}], props


@test("bug 1 lua: open_entrance never pulls the player's lever nor unlocks the player's door (dry run too); the AI's opens")
def _():
    E, G = rig(player=True, closed=True)
    for dry in (True, False):
        r = E.open_entrance(1, dry)
        assert not r.ok and r.rejected and r.not_ai, dict(r)
    assert len(list(G.pulled.values())) == 0 and G.blds[7].door_flags.closed
    E, G = rig(player=True, closed=False, forbidden=True)
    eq = E.GATES.entrances[1].equipment[1]
    eq.lever_driven, eq.drive_lever, eq.lever_id = False, None, None
    r = E.open_entrance(1, False)
    assert not r.ok and r.not_ai and G.blds[7].door_flags.forbidden, dict(r)
    # shut by the AI (its record): opened
    E, G = rig(player=True, closed=True)
    E.GATES.closed[1] = True
    r = E.open_entrance(1, False)
    assert r.ok and not G.blds[7].door_flags.closed, dict(r)


# --- 2. per-entrance refusal and cooldown ---------------------------------------------

@test("bug 2: a refusal at entrance 5 doesn't hold entrance 3; both entrances may open in one cycle, each its own cooldown")
def _():
    s = fort()
    m = Memory()
    now = abs_tick(s)
    pa = Proposal("stranded", {"type": "open_entrance", "id": 5, "cavern_ok": True}, "cavern", 0)
    pb = Proposal("stranded", {"type": "open_entrance", "id": 3}, "surface", 0)
    assert refusal_key(pa) != refusal_key(pb) and '"id": 5' in refusal_key(pa)
    note_refusal(m, pa, {"ok": False, "rejected": True, "error": "the cavern seal holds this entrance"}, now,
                 s.get("bridge_version"))
    allowed, held = select([pa, pb], s, m)
    assert [p.action["id"] for p in allowed] == [3], (allowed, held)
    assert held and "refused it 1 time(s)" in held[0], held
    # both free: both in one cycle
    m = Memory()
    allowed, held = select([copy.deepcopy(pa), copy.deepcopy(pb)], s, m)
    assert sorted(p.action["id"] for p in allowed) == [3, 5], (allowed, held)
    record([(p, {"ok": True}) for p in allowed], s, m)
    assert "stranded:3" in m.last_fired and "stranded:5" in m.last_fired, m.last_fired
    # entrance 3 just opened: its own cooldown holds it, entrance 7 goes on
    pc = Proposal("stranded", {"type": "open_entrance", "id": 7}, "another", 0)
    allowed, held = select([copy.deepcopy(pb), pc], s, m)
    assert [p.action["id"] for p in allowed] == [7] and any("cooldown" in h for h in held), (allowed, held)


# --- 3. the cistern after a leak ------------------------------------------------------

@test("bug 3: the first leak asks for the plain step; the second retires it")
def _():
    for leaks, retire in ((1, None), (2, True)):
        s = fort()
        s.setdefault("water", {})["cistern_status"] = {"v": 2, "stage": "filling", "gate": "closed",
                                                       "leak": "x5 y5 elevation 3", "leaks": leaks, "depth": 2}
        props, notes = [], []
        pw._cistern_rule(s, Memory(), CFG, props, notes, pw.player_rules(s))
        c = [p for p in props if p.rule == "cistern"]
        assert len(c) == 1 and c[0].action["type"] == "cistern_step" and c[0].action.get("retire") is retire, c
        assert not you(notes), notes


def _const(path: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / path).read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name)


from lupa.lua53 import LuaRuntime  # noqa: E402

_BL = LuaRuntime(unpack_returned_tuples=True)
_BL.globals().LUA_DIR = str(ROOT / "lua")
_B, _W = _BL.execute(_const("test_builder.py", "HARNESS"), (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8"),
                     (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8"))
_BL.execute("df = {global = {cur_year = 148, cur_year_tick = 100}}")
_STORE = _BL.execute("""
    local B = ...
    local S = {}
    B.site_get = function(k, d) return S[k] or d or {} end
    B.site_put = function(k, v) S[k] = v end
    B.cistern_data = function() local d = S['ai-overseer/cistern']; return d and d.stage and d or nil end
    return S
""", _B)
GAME_FAKE, GAME_CLEAN = _const("test_builder.py", "GAME_FAKE"), _const("test_builder.py", "GAME_CLEAN")
LUA_T = _BL.table_from


@test("bug 3 lua: one leak counted once over many steps; cleared once dry and closed all round; the next leak is the second")
def _():
    _BL.execute(GAME_FAKE)
    try:
        _BL.execute("""
          local B = ...
          df.building_type[9] = 'Floodgate'; df.building_type.Floodgate = 9
          local g = MKS(80, 50, 60, 9, true)
          g.gate_flags = {closed = true}
          WET = {}
          B.tile_info = function(x, y, z)
            return {shape = 'FLOOR', liquid = WET[x .. ',' .. y .. ',' .. z] == true, magma = false}
          end
          B.cistern_status = function() return {depth = 2} end
          B.cistern_sealed = function() return true end
          B.pull = function() return true end
        """, _B)
        _STORE["ai-overseer/cistern"] = LUA_T({
            "stage": "filling", "plan": LUA_T({
                "v": 2, "floodgate": LUA_T({"x": 80, "y": 50}), "intake_z": 60,
                "cistern": LUA_T({"z": 60, "x1": 10, "y1": 10, "x2": 14, "y2": 14}),
                "well": LUA_T({"x": 12, "y": 12, "z": 62}), "plug": LUA_T({"x": 79, "y": 50}),
                "tunnel_path": LUA_T([]), "source": "pool"})})
        wet = _BL.eval("WET")
        wet["11,11,62"] = True
        for _ in range(3):
            r = _B.cistern_step(False)
            assert not r.ok and r.leak and r.waiting, dict(r)
        d = _STORE["ai-overseer/cistern"]
        assert d.leaks == 1 and d.leak, (d.leaks, d.leak)
        wet["11,11,62"] = None
        try:
            _B.cistern_step(False)          # cleared; the filling step after it may want more of the game
        except Exception:  # noqa: BLE001
            pass
        d = _STORE["ai-overseer/cistern"]
        assert d.leak is None and d.leaks == 1, (d.leak, d.leaks)
        wet["12,12,62"] = True
        for _ in range(2):
            _B.cistern_step(False)
        assert _STORE["ai-overseer/cistern"].leaks == 2
    finally:
        _BL.execute(GAME_CLEAN)


@test("nit: the retire cap's refusal shuts an open floodgate, as it says")
def _():
    _BL.execute(GAME_FAKE)
    try:
        _BL.execute("df.building_type[9] = 'Floodgate'; df.building_type.Floodgate = 9")
        g = _BL.eval("function() local b = MKS(80, 50, 60, 9, true); b.gate_flags = {closed = false}; return b end")()
        pulls = _BL.execute("local B = ...; local P = {}; B.pull = function(id, i) P[#P + 1] = id; return true end; "
                            "return P", _B)
        _STORE["ai-overseer/cistern"] = LUA_T({"stage": "done", "lever_id": 5, "plan": LUA_T({
            "floodgate": LUA_T({"x": 80, "y": 50}), "intake_z": 60, "cistern": LUA_T({"z": 60})})})
        _STORE["ai-overseer/cistern/retired"] = LUA_T([LUA_T({"by_ai": True}) for _ in range(3)])
        r = _B.cistern_retire(True, "x")
        assert not r.ok and len(pulls) == 0, dict(r)          # a dry run changes nothing
        r = _B.cistern_retire(False, "x")
        assert not r.ok and r.rejected and "its floodgate shut" in r.error and list(pulls.values()) == [5], dict(r)
        assert g is not None
    finally:
        _BL.execute(GAME_CLEAN)


# --- 4. the alarm held for citizens in the caverns -----------------------------------

def cavern_state():
    s = fort()
    s["threats"] = {"sealed": {}}
    s["deep"] = {"caverns": [{"name": "Cavern1", "discovered": True, "open": True, "z_top": 120, "z_bottom": 110}],
                 "dangers": [{"id": 50, "name": "Ozkak", "kind": "forgotten beast", "layer": "Cavern1"}],
                 "cursed": []}
    s["threats"]["cavern_citizens"] = {"n": 1, "list": [{"name": "Kib", "x": 1, "y": 2, "z": 3}]}
    s["civ_alert"], s["civ_alert_ready"] = True, True
    return s


@test("bug 4: the alarm is held for citizens in the caverns 3 days at most, then let down, said; forgotten when none are down")
def _():
    s = cavern_state()
    m = Memory()
    m.ai_alert_raised = True
    off = {"type": "civ_alert", "on": False}
    for days, kept in ((0, False), (2, False), (3, True), (40, True)):
        if days:
            m.cavern_alarm = {"since": abs_tick(s) - days * DAY}
        props = [Proposal("threat_alert", dict(off), "all clear", 0)]
        notes = []
        pt._cavern_beasts(s, CFG, m, s["threats"], pt.threat_rules_of(s), props, notes)
        assert any(p.action == off for p in props) is kept, (days, props)
        if kept:
            assert any("lets the alarm down" in n for n in notes) and not you(notes), notes
    # no all-clear proposed by anyone: the AI lets its own alarm down itself
    props, notes = [], []
    pt._cavern_beasts(s, CFG, m, s["threats"], pt.threat_rules_of(s), props, notes)
    assert [p.action for p in props if p.rule == "threat_alert"] == [off], props
    # nobody down any more: the hold forgotten
    s["threats"]["cavern_citizens"] = {"n": 0, "list": []}
    pt._cavern_beasts(s, CFG, m, s["threats"], pt.threat_rules_of(s), [], [])
    assert m.cavern_alarm == {}, m.cavern_alarm
    assert CFG["cavern_alarm_max_days"] == 3


# --- 5. berserk -----------------------------------------------------------------------

def berserk_state(changed=False, armed=1, members=8):
    s = fort()
    s["civ_alert"] = True
    s["hazards"] = {"berserk": [{"id": 900, "name": "Urist", "changed": changed}]}
    q1, q2 = s["military"]["squads"][:2]
    q1.update(members=members, power={"armed": armed}, ai_orders=0)
    q2.update(members=8, power={"armed": 0}, ai_orders=0)
    return s


def berserk_sends(s, m):
    props, notes = [], []
    pm._hazard_rules(s, m, CFG, props, notes, pm.player_rules(s))
    return [p for p in props if p.rule == "squad_attack"], notes


@test("bug 5: a weak squad already on the berserk dwarf isn't re-sent; one sent isn't re-sent within the cooldown")
def _():
    s = berserk_state()
    s["military"]["squads"][0].update(ai_orders=1, kill_ids=[900])
    sent, notes = berserk_sends(s, Memory())
    assert not sent and any("is after them" in n for n in notes), (sent, notes)
    s = berserk_state()
    m = Memory()
    sent, _n = berserk_sends(s, m)
    assert [p.action for p in sent] == [{"type": "squad_orders", "squad_id": 11, "kill": [900]}] and sent[0].guard
    record([(sent[0], {"ok": True})], s, m)
    sent, notes = berserk_sends(s, m)              # the order not in the report yet
    assert not sent and any("is after them" in n for n in notes), (sent, notes)
    later = copy.deepcopy(s)
    later["date"]["tick"] += CFG["berserk_resend_ticks"] + 1
    sent, _n = berserk_sends(later, m)
    assert len(sent) == 1, sent


@test("bug 5: a changed werebeast: never by a squad only partly armed; a fully armed one goes")
def _():
    sent, notes = berserk_sends(berserk_state(changed=True, armed=1, members=8), Memory())
    assert not sent and any("too few against a changed beast" in n for n in notes), (sent, notes)
    sent, _n = berserk_sends(berserk_state(changed=True, armed=2, members=2), Memory())
    assert [p.action["squad_id"] for p in sent] == [11], sent


@test("bug 5: the loop guard counts the berserk sends (guard), and still not other squad_attack")
def _():
    s = berserk_state()
    m = Memory()
    sent, _n = berserk_sends(s, m)
    now = abs_tick(s)
    m.action_log[refusal_key(sent[0])] = [now - i * 10 for i in range(1, planner_core.LOOP_LIMIT_DEFAULT + 1)]
    assert planner_core._loop_count(m, sent[0], now) is not None
    other = Proposal("squad_attack", dict(sent[0].action), "an invader", 0)
    assert planner_core._loop_count(m, other, now) is None


# --- risks ------------------------------------------------------------------------------

@test("risk: a leak-watch hold (water still getting in, floodgate gone) is never retired; an open floodgate shut")
def _():
    for why in ("the farm room is still wet after 20 days (4 tile(s)): water is still getting in",
                "the floodgate is gone"):
        for gate in ("closed", "open"):
            s = fort()
            s["waterworks"] = {"works": {"irrigation": {"kind": "irrigation", "stage": "held", "why": why,
                                                        "gate": gate}}, "refused": {}}
            props, notes = [], []
            pwt._waterworks_rule(s, Memory(), CFG, props, notes)
            assert not [p for p in props if p.action.get("retire")], props
            assert [n for n in notes if "keeps it watched" in n], notes
            shut = [p for p in props if p.action.get("shut")]
            assert bool(shut) is (gate == "open"), props
    # another hold: retired as before
    s = fort()
    s["waterworks"] = {"works": {"irrigation": {"kind": "irrigation", "stage": "held",
                                                "why": "the floor dried without mud"}}, "refused": {}}
    props = []
    pwt._waterworks_rule(s, Memory(), CFG, props, [])
    assert [p.action.get("retire") for p in props] == [True], props


@test("risk lua: water_work retire refuses a leak-watch hold")
def _():
    L = LuaRuntime(unpack_returned_tuples=True)
    env = L.execute(_const("test_waterworks.py", "FAKE"), (ROOT / "lua" / "ai-waterworks.lua").read_text(encoding="utf-8"))
    st = env.load_state()
    st.works["irrigation"] = L.table_from({"kind": "irrigation", "stage": "held",
                                           "why": "the farm room is still wet after 20 days (3 tile(s)): water is "
                                                  "still getting in (the floodgate leaks)",
                                           "plan": L.table_from({"gate": L.table_from({"x": 1, "y": 1, "z": 90})})})
    env.save_state(st)
    for dry in (True, False):
        r = env.step("irrigation", L.table_from({"retire": True, "why": "x", "dry_run": dry}))
        assert not r.ok and r.leak_watch, dict(r)
    assert env.load_state().works["irrigation"].stage == "held"


@test("risk: the unfound-cavern decision counts armed soldiers only")
def _():
    s = fort()
    s["stocks"]["drink"] = 0
    for q in s["military"]["squads"]:
        q.update(members=2, power={"armed": 0})
    ok, why = pw.ai_opens_cavern(s, CFG)
    assert not ok and "only 0 armed soldier(s)" in why, why
    s["military"]["squads"][0]["power"] = {"armed": 2}
    s["military"]["squads"][1]["power"] = {"armed": 1}
    assert pw.ai_opens_cavern(s, CFG)[0]


@test("risk: the Rules switch is three-state: AI decides (default) / Always / Never; old saves' true = Always, false = AI")
def _():
    pr = planner_core.player_rules
    assert pr({"settings": {}})["open_caverns"] == "ai"
    assert pr({"settings": {"open_caverns": True}})["open_caverns"] == "always"
    assert pr({"settings": {"open_caverns": False}})["open_caverns"] == "ai"
    assert pr({"settings": {"open_caverns": "never"}})["open_caverns"] == "never"
    assert pr({"settings": {"open_caverns": "junk"}})["open_caverns"] == "ai"
    s = fort()
    for l in s["map"]["layers"]:
        if l["name"] == "Cavern1":
            l["discovered"] = False
    s["water"] = {"bodies": [{"kind": "cavern", "nearest": {"x": 1, "y": 1, "z": 125}}]}
    s["dwarves"]["needs_medical_care"] = 4
    s["settings"]["open_caverns"] = "never"
    act = pw.cavern_action(s, CFG, True)
    assert "open_caverns" not in act, act
    s["settings"]["open_caverns"] = "always"
    assert pw.cavern_action(s, CFG, True).get("open_caverns") is True
    line = strategist.rules_line(pr({"settings": {"open_caverns": "never"}}))
    assert "open_caverns=never" in line, line
    assert "AI decides: open_caverns" in strategist.rules_line(pr({"settings": {}}))
    assert overseer.short({"type": "set_rules", "rules": {"open_caverns": "never"}}) == \
        "set Rules switches: open_caverns never"


@test("risk lua: settings sanitize the three states; set_rules takes a choice or an old on/off")
def _():
    L = LuaRuntime(unpack_returned_tuples=True)
    src = (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    S = L.eval("""function(src)
      local env = setmetatable({dfhack_flags = {module = true}, dfhack = {getDFPath = function() return '.' end,
                                          isMapLoaded = function() return false end}},
                               {__index = _G})
      env.require = function(n) if n == 'json' then return {} end return require(n) end
      assert(load(src, 'settings', 't', env))()
      return env end""")(src)
    assert S.defaults().open_caverns == "ai"
    for v, want in ((True, "always"), (False, "ai"), ("never", "never"), ("always", "always"), ("x", "ai")):
        assert S.sanitize(L.table_from({"open_caverns": v})).open_caverns == want, (v, want)
    assert list(S.RULE_CHOICES.open_caverns.values()) == ["ai", "always", "never"]
    acts = (ROOT / "lua" / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    assert "k == 'open_caverns' and type(v) == 'boolean'" in acts


@test("risk lua: free_gate_jobs resumes only the pieces the AI planned (recorded when placed)")
def _():
    E, G = rig()
    job = t({"flags": t({"suspend": True})})
    G.blds[50] = t({"id": 50, "name": "", "x1": 30, "y1": 31, "x2": 31, "y2": 31, "z": 170, "jobs": t([job])})
    E.GATES.entrances[1].pending_ids = t([50])
    r = E.free_gate_jobs(1, False)
    assert not r.ok and r.players and job.flags.suspend, dict(r)          # the player's plan
    E.note_gate_planned(t({"x": 31, "y": 31, "z": 170}))
    r = E.free_gate_jobs(1, True)
    assert r.ok and r.dry_run and job.flags.suspend, dict(r)
    r = E.free_gate_jobs(1, False)
    assert r.ok and r.unsuspended == 1 and not job.flags.suspend, dict(r)
    from lua_modules_util import split_src   # (13e) the hub and its parts
    src = split_src("ai-gates.lua")
    assert "if ok then pcall(note_gate_planned, pos) end" in src


@test("risk: unstick step 3 never on a cavern's way (brain), and the bridge refuses it there")
def _():
    from test_r32_brain import fort as gfort, cycle, later, acts, answer, HOUR  # noqa: E402
    m = Memory()
    s = gfort()
    s["deep"] = {"caverns": [], "dangers": []}
    s["entrances"]["entrances"][0]["kind"] = "cavern"
    p1 = acts(cycle(s, m)[0], "gate_stuck")[0]
    answer(s, m, p1, split_after=True)
    s2 = later(s, 6 * HOUR + 10, rescan=True)
    s2["deep"] = {"caverns": [], "dangers": []}
    p2 = acts(cycle(s2, m)[0], "gate_stuck")[0]
    assert p2.action["step"] == 2, p2.action
    answer(s2, m, p2, split_after=True)
    for h in (12, 30):
        s3 = later(s, h * HOUR + 20, rescan=True)
        s3["deep"] = {"caverns": [], "dangers": []}
        assert not acts(cycle(s3, m)[0], "gate_stuck"), h
    E, G = rig()
    E.GATES.entrances[1].kind = "cavern"
    r = E.unstick_gate(7, 3, False, True)
    assert not r.ok and r.cavern and "does not take it down" in r.error, dict(r)
    assert len(list(G.removed.values())) == 0


@test("risk: each labour rule gives at most its cap of dwarves in a year (count clamped, then held)")
def _():
    s = fort()
    m = Memory()
    assert CFG["care_feed_labor_cap"] == 4
    for rule in planner_core.LABOR_CAPS:
        assert isinstance(CFG.get(planner_core.LABOR_CAPS[rule]), int), rule
    given = 0
    for day in range(0, 60):
        s2 = copy.deepcopy(s)
        s2["date"]["tick"] += day * DAY
        p = Proposal("care_feed", {"type": "assign_labor", "job": "FEED_WATER_CIVILIANS", "count": 3}, "parched", 2)
        allowed, held = select([p], s2, m)
        for a in allowed:
            record([(a, {"ok": True, "assigned": ["x"] * a.action["count"]})], s2, m)
            given += a.action["count"]
    assert given == 4, given
    assert planner_core.labor_given(m, "care_feed", abs_tick(s) + 59 * DAY) == 4
    p = Proposal("care_feed", {"type": "assign_labor", "job": "FEED_WATER_CIVILIANS", "count": 2}, "parched", 2)
    s3 = copy.deepcopy(s)
    s3["date"]["tick"] += 60 * DAY
    allowed, held = select([p], s3, m)
    assert not allowed and "at most 4" in held[0], held


@test("risk: a workshops level not seen built is re-started 3 times at most")
def _():
    s = fort()
    m = Memory()
    m.shops_started = {"Masons": 2}
    m.shops_seen = {"Masons": planner_core.shop_count(s.get("buildings") or {}, "Masons")}
    starts = 0
    for k in range(10):
        s2 = copy.deepcopy(s)
        s2["date"]["tick"] += k * (planner.SHOPS_RETRY_DAYS + 1) * DAY
        p = Proposal("workshops", {"type": "start_project", "kind": "workshops", "shops": ["Masons"]}, "x", 4)
        allowed, held = select([p], s2, m)
        if allowed:
            starts += 1
            m.shops_started["Masons"] = 2          # started again, and again not seen built
    assert starts == planner.SHOPS_RETRY_MAX == 3, starts
    assert "starts it no more" in held[0], held


@test("nit: a wide founding search that ran out of time isn't booked as a wide failure")
def _():
    s = fort()
    m = Memory()
    planner_core._record_any_outcome({"type": "found_fort", "wide": True},
                                     {"ok": False, "timed_out": True, "error": "cut short"}, s, m, abs_tick(s))
    assert m.found_wide_failure == ""
    planner_core._record_any_outcome({"type": "found_fort", "wide": True},
                                     {"ok": False, "error": "no spot"}, s, m, abs_tick(s))
    assert m.found_wide_failure == "no spot"


@test("everything compiles under Lua 5.3")
def _():
    L = LuaRuntime()
    for p in sorted((ROOT / "lua").glob("*.lua")) + sorted((ROOT / "lua" / "gui").glob("*.lua")):
        ok, err = L.eval("function(src, n) local f, e = load(src, n, 't', {}); return f ~= nil, e end")(
            p.read_text(encoding="utf-8"), p.name)
        assert ok, (p.name, err)


if __name__ == "__main__":
    finish()

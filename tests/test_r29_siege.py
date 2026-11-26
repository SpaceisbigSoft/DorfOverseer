"""(R29 W2, Phase 11) The invited siege and the siege's record: the Rules'
"Invite a siege (test)" switch (settings, the Army tab, the bridge action,
lua/ai-siege.lua invite_siege with DFHack's force and DF 53's army event,
once a fort), the planner's whole answer to an army at the map edge
(brain/scenario_siege.py, each check a test), the squads holding the gate an
army they can't beat comes at, the siege watch and its summary
(brain/planner_siege_watch.py), and the gatehouse judged per gate
(brain/defence.py).

    python tests/test_r29_siege.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import code_has, finish, need_lua, test  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, Proposal  # noqa: E402
import planner_siege as PS  # noqa: E402
import planner_siege_watch as W  # noqa: E402
import scenario_siege as SC  # noqa: E402

LUA = ROOT / "lua"
CFG = PLANNER_CONFIG


def _src(name: str) -> str:
    return (LUA / name).read_text(encoding="utf-8")


# --- the scenario: every check a test ------------------------------------------------------

_RESULTS = SC.run()
for _i, (_name, _ok, _why) in enumerate(_RESULTS):
    def _make(ok=_ok, why=_why):
        def _t():
            assert ok, why
        return _t
    test(f"scenario {_name}")(_make())


# --- the switch ------------------------------------------------------------------------------

@test("settings: invite_siege off by default, kept by sanitize and for_ai, in a block of its own")
def _():
    s = _src("ai-overseer-settings.lua")
    assert code_has(s, "function defaults() local d = base_defaults(); d.invite_siege = false; return d end")
    assert code_has(s, "out.invite_siege = type(s) == 'table' and s.invite_siege == true")
    assert code_has(s, "out.invite_siege = sanitize(s).invite_siege")
    assert s.index("base_defaults, base_sanitize, base_for_ai = defaults, sanitize, for_ai") > s.index("function for_ai(")
    assert "'invite_siege'" not in s.split("PRESET_RULE_KEYS = {", 1)[1].split("}", 1)[0]   # no preset carries it


@test("the Army tab: the switch, its help line and its refresh")
def _():
    g = _src("gui/ai-overseer-rules.lua")
    assert code_has(g, "view_id = 'invite_siege',") and code_has(g, "p:set_field('invite_siege', v)")
    assert code_has(g, "self.subviews.invite_siege:setOption(s.invite_siege == true, false)")
    mil = g.split("function MilitaryPage:init()", 1)[1].split("\nend\n", 1)[0]
    assert "invite_siege" in mil, "on the Army tab"


@test("the bridge: the action, its label, its hold class")
def _():
    assert code_has(_src("ai-bridge-catalog.lua"),
                    "invite_siege = function(a) return reqscript('ai-siege').invite_siege(a.dry_run == true) end,")
    import overseer_words
    assert "invite_siege" in overseer_words.SHORT_WORDS
    import hold_classes as HC
    assert HC.step_class(Proposal("invite_siege", {"type": "invite_siege"}, "", 6)) == HC.EXPANSION


@test("ai-siege.lua stays under 55 KB (place_mood_shop kept)")
def _():
    s = _src("ai-siege.lua")
    assert len(s.encode("utf-8")) < 55 * 1024, len(s.encode("utf-8"))
    assert "function place_mood_shop(kind, dry_run)" in s and "function invite_siege(dry)" in s
    assert "out.invited = invited()" in s


# --- the Lua action, in a fake game ------------------------------------------------------------

FAKE = r"""
local src, force_ok, hostile = ...
local W = {site = {}, saved = nil, ran = {}}
local env = setmetatable({}, {__index = _G})
local events = setmetatable({}, {__index = {insert = function(self, _, v) table.insert(self, v) end}})
W.events = events
local ents = {
    [278] = {id = 278, type = 'Civilization', race = 1, site_links = {1, 2, 3, 4}, name = 'elves'},
    [304] = {id = 304, type = 'Civilization', race = 2, site_links = {1, 2, 3, 4}, name = 'skirmishers'},
    [314] = {id = 314, type = 'Civilization', race = 2, site_links = {1, 2, 3, 4, 5, 6}, name = 'war'},
    [323] = {id = 323, type = 'SiteGovernment', race = 3, site_links = {1}, name = 'site'},
}
local rels = {{group_id = 278, relation = 'Peace'}, {group_id = 304, relation = 'Skirmishing'},
              {group_id = 323, relation = 'TotalWar'}}
if hostile then table.insert(rels, {group_id = 314, relation = 'TotalWar'}) end
local fort_civ = {relations = {diplomacy = {state = rels}}}
env.df = {
    global = {plotinfo = {civ_id = 1}, timed_events = events, cur_season = 2, cur_season_tick = 77,
              cur_year = 260, cur_year_tick = 1000},
    timed_event_type = {EvaluateAttackAndSendImmediateArmy = 10, [10] = 'EvaluateAttackAndSendImmediateArmy'},
    historical_entity = {find = function(id) if id == 1 then return fort_civ end return ents[id] end},
    historical_entity_type = setmetatable({}, {__index = function(_, k) return k end}),
    diplomacy_state_type = setmetatable({}, {__index = function(_, k) return k end}),
    creature_raw = {find = function(r) return {creature_id = ({'ELF', 'GOBLIN', 'DWARF'})[r]} end},
}
env.dfhack = {
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
    findScript = function(n) if force_ok and n == 'force' then return 'hack/scripts/force.lua' end return nil end,
    run_command_silent = function(cmd, arg)
        table.insert(W.ran, cmd .. ' ' .. arg)
        events:insert('#', {type = env.df.timed_event_type[arg], season = 2, season_ticks = 77, entity = nil})
        return '', 0
    end,
    translation = {translateName = function(n) return 'The ' .. tostring(n) end},
}
local settings = {invite_siege = true}
local S = {load_settings = function() return settings end, save_settings = function(s) W.saved = s end}
env.reqscript = function(n)
    if n == 'ai-overseer-settings' then return S end
    error('reqscript ' .. tostring(n))
end
assert(load(src, 'ai-siege', 't', env))()
return env, W
"""


def _lua(force_ok=True, hostile=True):
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-siege.lua"), force_ok, hostile)
    _lua.runtime = lua
    return env, w


@test("invite_siege (Lua): force queues DF 53's army event, its entity the civ at total war; once only")
def _():
    need_lua()
    env, w = _lua()
    r = env.invite_siege(False)
    assert r.ok and r.how == "force" and r.civ_id == 314 and r.event == "EvaluateAttackAndSendImmediateArmy", dict(r)
    assert list(w.ran.values()) == ["force EvaluateAttackAndSendImmediateArmy"]
    assert w.events[1].entity.id == 314
    rec = w.site["ai-overseer/siege-invite"]
    assert rec.civ_id == 314 and rec.how == "force"
    assert w.saved.invite_siege is False, "the switch turned off"
    again = env.invite_siege(False)
    assert not again.ok and again.rejected and "once already" in again.error
    assert len(list(w.ran.values())) == 1 and len(w.events) == 1, "never a second army"


@test("invite_siege (Lua): no force script: the same event queued directly; dry run: nothing")
def _():
    need_lua()
    env, w = _lua(force_ok=False)
    d = env.invite_siege(True)
    assert d.ok and d.dry_run and d.civ_id == 314 and len(w.events) == 0 and w.site["ai-overseer/siege-invite"] is None
    r = env.invite_siege(False)
    assert r.ok and r.how == "timed_event" and w.events[1].entity.id == 314 and w.events[1].type == 10


@test("invite_siege (Lua): none at total war: the skirmishing civ")
def _():
    need_lua()
    env, w = _lua(hostile=False)
    r = env.invite_siege(False)
    # Skirmishing still counts as hostile: 304 is picked over nothing
    assert r.ok and r.civ_id == 304, dict(r)


@test("pick_civ (Lua): TotalWar before Skirmishing, most sites first, civilisations only")
def _():
    need_lua()
    env, _ = _lua()
    lua_rows = env.pick_civ
    lua = _lua.runtime
    t = lua.eval("""function(f) return f({
        {id = 5, kind = 'Civilization', relation = 'Skirmishing', sites = 9},
        {id = 6, kind = 'Civilization', relation = 'TotalWar', sites = 1},
        {id = 7, kind = 'SiteGovernment', relation = 'TotalWar', sites = 9},
        {id = 8, kind = 'Civilization', relation = 'Peace', sites = 30}}) end""")(lua_rows)
    assert t.id == 6
    none = lua.eval("function(f) return f({{id = 1, kind = 'Civilization', relation = 'Peace', sites = 3}}) end")(lua_rows)
    assert none is None


# --- the planner's rule ------------------------------------------------------------------------

@test("invite rule: waits while enemies are on the map; off: nothing")
def _():
    s = SC.at(SC.base_state(invite=True), 1, SC.army(5, 60))
    props, notes = [], []
    PS._invite_rule(s, Memory(), CFG, props, notes)
    assert not props and any("waits while enemies" in n for n in notes), notes
    s = SC.base_state(invite=False)
    PS._invite_rule(s, Memory(), CFG, props, notes)
    assert not props


# --- the watch ---------------------------------------------------------------------------------

@test("watch: an invitation no army followed in 30 days is said once")
def _():
    m = Memory()
    s = SC.base_state()
    s["field_watch"]["invited"] = {"tick": 148 * 403200 + 100 * 1200, "civ_name": SC.CIV, "how": "force"}
    s = SC.at(s, 31, [])
    W.note_siege_watch(s, m, CFG)
    j = W.siege_journal(m)
    assert len(j) == 1 and j[0]["what"] == "siege_no_show", j
    W.note_siege_watch(SC.at(s, 33, []), m, CFG)
    assert not W.siege_journal(m)


@test("watch: thieves and animals are no siege; a pulse without the threat list leaves the watch alone")
def _():
    m = Memory()
    t = SC.army(2, 30)
    t[0]["thief"] = True
    t[1]["animal"] = True
    W.note_siege_watch(SC.at(SC.base_state(), 1, t), m, CFG)
    assert "siege_watch" not in m.holdfast
    W.note_siege_watch(SC.at(SC.base_state(), 1, SC.army(3, 30)), m, CFG)
    assert m.holdfast["siege_watch"]["peak"] == 3
    s = SC.at(SC.base_state(), 3, [])
    s["others_on_map"] = {}
    W.note_siege_watch(s, m, CFG)
    assert "siege_watch" in m.holdfast


@test("watch: the summary says a fort that fell")
def _():
    m = Memory()
    W.note_siege_watch(SC.at(SC.base_state(), 1, SC.army(4, 30)), m, CFG)
    s = SC.at(SC.base_state(), 2, [])
    s["dwarves"]["total"] = 0
    W.note_siege_watch(s, m, CFG)
    e = W.siege_journal(m)[0]
    assert e["what"] == "siege_summary" and e["survived"] is False and "fell" in e["text"]


@test("note_invite: a refusal and a failure are journal lines too; a dry run nothing")
def _():
    m = Memory()
    p = Proposal("invite_siege", {"type": "invite_siege"}, "", 6)
    W.note_invite(p, {"ok": False, "rejected": True, "done": {"year": 1}, "error": "once already"}, {}, m, 5)
    W.note_invite(p, {"ok": False, "error": "no army event"}, {}, m, 5)
    W.note_invite(Proposal("invite_siege", {"type": "invite_siege", "dry_run": True}, "", 6), {"ok": True}, {}, m, 5)
    assert [e["what"] for e in W.siege_journal(m)] == ["siege_invite_refused", "siege_invite_failed"]


# --- the squads at the gate --------------------------------------------------------------------

@test("siege hold: never for the player's squads, nor with train_squads off")
def _():
    import planner_holdfast as HF
    s = SC.at(SC.base_state(power=5.0), 3, SC.army(15, 60))
    rows = SC.army(15, 60)
    pool = [dict(q, id=q["id"]) for q in s["military"]["squads"]]
    add, notes = [], []
    HF._siege_hold(s, CFG, rows, [dict(pool[0], orders=1, ai_orders=0)], "x", add, set(), notes)
    assert not add
    s2 = copy.deepcopy(s)
    s2["settings"]["train_squads"] = False
    HF._siege_hold(s2, CFG, rows, pool, "x", add, set(), notes)
    assert not add
    HF._siege_hold(s, CFG, rows, pool, "x", add, set(), notes)
    assert add and add[0].action["type"] == "guard_gate" and add[0].action["squads"] == [11, 12]


# --- the gatehouse judged per gate -------------------------------------------------------------

@test("defence: the War-hold's gatehouse is judged after a siege like any AI gate")
def _():
    import defence
    m = Memory()
    m.atlas = {"registry": {"gatehouse:31,140,173": {"tick": 10, "variant": "cage", "kind": "gatehouse"}},
               "entrances": {"31,140,173": {"elevation": 0}}, "events": [
                   {"k": "threat_at_gate", "t": 100, "near": "entrance:31,140,173"},
                   {"k": "kill", "t": 110, "near": "entrance:31,140,173"}]}
    gates = defence._gates(m.atlas, 50)
    assert gates == [("31,140,173", ["defence:gatehouse"])], gates
    assert defence._label("defence:gatehouse") == "its gatehouse"


if __name__ == "__main__":
    finish()

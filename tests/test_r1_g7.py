"""(r1 g7) Visitors who come for the fort's artifacts.

B (16 Nov, 0.105.55) fell to zero twice: lone heroes came in as guests for
artifacts in the fort (Itvid in y258 for Pillartoned, Len Karaura in y262
for Nettlewalk; Len killed 19 citizens in 65 seconds). B was Outsiders +60
and held ~19 artifacts other civs claim; its heist lockout shut the
locations 168 days after each killing, then opened them again for the next
hero. F lost its last 4 to two visiting humans. A (R-AD item 9):
`artifact_display` hit a Lua error 45 times (df.job_item_ref.T_role).

Tested here:
  * lua/ai-artifacts.lua: display_artifact uses df.job_role_type.Hauled (no
    T_role) and makes no job when the role is missing; the report marks an
    artifact a figure from afar claims (remote_claims: `sought`) and counts
    the artifacts at risk.
  * brain/planner_visitors.py: while a claimed or sought artifact is in the
    fort its locations stay shut to visitors, whatever Outsiders says (B's
    real artifacts and locations); the lockout's end doesn't reopen them; a
    spotted hero's artifact (Nettlewalk, no civ's claim) counts; the last
    report holds a week between full reports; none left: open again; the
    Rules switch and the config switch turn it off.
  * lua/ai-threats.lua + ai-military.lua + ai-bridge-report.lua: a visitor who
    kills a citizen, or a hero spotted sneaking after an artifact, is marked
    (kept in the save), listed as a threat in others_on_map and taken as a
    kill target; and the brain sends a squad at the row.

    python tests/test_r1_g7.py
"""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish, need_lua, code_has  # noqa: E402
from lua_modules_util import module_src, bridge_part_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan, TICKS_PER_DAY, abs_tick  # noqa: E402
from planner_visitors import (_location_access_rule, note_heists, note_locations,  # noqa: E402
                              artifacts_at_risk, claimed_shut, sought_artifact)

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

CFG = dict(PLANNER_CONFIG)
LUA_DIR = ROOT / "lua"
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
BOTH = ["VISITORS_ALLOWED", "NON_CITIZENS_ALLOWED"]
SHUT = ["NON_CITIZENS_ALLOWED"]

# B's state-last.json (Hammerstirred, y263): its five locations and the first
# artifact rows (claimed by other civs; most not the AI's), as the bridge gave them
B_LOCATIONS = [(0, "TEMPLE"), (1, "INN_TAVERN"), (2, "INN_TAVERN"), (3, "TEMPLE"), (4, "LIBRARY"), (5, "HOSPITAL")]
B_ARTIFACTS = [
    {"claimed_by": ["The Nation of Dignity", "The League of Coincidence"], "id": 58, "item_id": 58,
     "kind": "SLAB", "mine": False, "name": "Nightsearch", "state": "loose", "x": 115, "y": 158, "z": 158},
    {"claimed_by": ["The Tongs of Confederacy"], "id": 188, "item_id": 188, "kind": "WEAPON", "mine": False,
     "name": "Deeptrailed", "state": "carried", "x": 107, "y": 161, "z": 165},
    {"claimed_by": ["The Tongs of Confederacy"], "id": 1186, "item_id": 1186, "kind": "TOY", "mine": False,
     "name": "The Name of Crystal", "state": "loose", "x": 113, "y": 159, "z": 167},
    {"id": 1350, "item_id": 1350, "kind": "FIGURINE", "mine": False, "name": "Ramwound", "state": "loose",
     "x": 115, "y": 160, "z": 167},
]
B_COUNTS = {"claimed": 19, "displayed": 0, "displayed_open": 0, "loose": 16, "mine": 0, "mine_loose": 0, "total": 140}
# F's state-last.json: Nettlewalk, which no civ claims; Len Karaura came for it (B, 09:32:02 y262)
NETTLEWALK = {"id": 2767, "item_id": 2767, "kind": "BRACELET", "mine": False, "name": "Nettlewalk",
              "state": "loose", "x": 109, "y": 160, "z": 168}
LEN = {"kind": "report", "report_id": 10618, "topic": "thief", "type": "AMBUSH_HERO", "x": 113, "y": 116,
       "z": 162, "text": "The Human Axeman Len Karaura was spotted sneaking around!  "
                         "\"You will not stand between me and Nettlewalk!\""}


def fort(outsiders=60, flags=BOTH, artifacts=None, counts=None) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "autumn"
    s["locations"] = {"count": {}, "total": 6, "built": abs_tick(s),
                      "list": [{"id": i, "type": t, "flags": list(BOTH if t == "HOSPITAL" else flags)}
                               for i, t in B_LOCATIONS]}
    s["settings"]["traits"] = {"outsiders": outsiders}
    if artifacts is not None:
        s["artifacts"] = {"artifacts": copy.deepcopy(artifacts), "counts": dict(counts or {}),
                          "displays": [], "rooms": [], "free": {"case": 0, "pedestal": 0}, "api": {"display_job": True}}
    return s


def rule(s, m, notes=None):
    props = []
    _location_access_rule(s, m, CFG, props, notes if notes is not None else [])
    return props


def closing(props):
    return [p for p in props if p.action.get("type") == "location_access" and p.action.get("visitors") is False]


def opening(props):
    return [p for p in props if p.action.get("type") == "location_access" and p.action.get("visitors") is True]


# --- the brain: locations shut while claimed artifacts are in the fort --------------------------

@test("B's Monastery (Outsiders +60, ~19 artifacts other civs claim, no theft yet): its 2 taverns, 2 temples "
      "and library shut to visitors (the hospital stays open); welcoming Outsiders +100 too")
def _():
    for outsiders in (60, 100):
        s = fort(outsiders, artifacts=B_ARTIFACTS, counts=B_COUNTS)
        props = rule(s, Memory())
        c = closing(props)
        assert c and sorted(c[0].action["ids"]) == [0, 1, 2, 3, 4], (outsiders, [(p.rule, p.action) for p in props])
        assert "claimed" in c[0].reason and "Nightsearch" in c[0].reason, c[0].reason
        assert c[0].priority == 3
    risk = artifacts_at_risk(fort(artifacts=B_ARTIFACTS, counts=B_COUNTS), Memory(), CFG)
    assert len(risk) == 19, len(risk)                       # 3 listed + 16 counted but not listed


@test("B y258: the 168-day lockout after Gulo is over, the claimed artifacts still lie there: no reopen (the "
      "AI opened them on 7 Hematite y258 and Itvid came on 24 Limestone); with none left, opened again")
def _():
    s = fort(flags=SHUT, artifacts=B_ARTIFACTS, counts=B_COUNTS)
    m = Memory()
    m.locations_closed = [0, 1, 2, 3, 4]
    m.heists = [[abs_tick(s) - 170 * TICKS_PER_DAY, "Human Spearman Gulo Medonsana"]]
    note_locations(s, m, CFG)
    notes = []
    props = rule(s, m, notes)
    assert not opening(props), [(p.rule, p.action, p.reason) for p in props]
    assert any("while" in n and "artifact(s) someone may come for" in n for n in notes), notes
    # the claimed ones gone (taken home, or the player's choice): the fort opens up
    s2 = fort(flags=SHUT, artifacts=[B_ARTIFACTS[3]], counts={"claimed": 0, "total": 1})
    note_locations(s2, m, CFG)
    props = rule(s2, m)
    o = opening(props)
    assert o and sorted(o[0].action["ids"]) == [0, 1, 2, 3, 4], props
    assert "no claimed or sought artifact left" in o[0].reason, o[0].reason


@test("Nettlewalk (no civ claims it): Len Karaura's 'stand between me and Nettlewalk' makes it sought; the "
      "locations shut while it is in the fort, after the theft lockout too")
def _():
    assert sought_artifact(LEN["text"]) == "Nettlewalk"
    assert sought_artifact("The Goblin Thief Snodub was spotted sneaking around!  \"You will not stand "
                           "between me and Bluegold the Shining!\"") == "Bluegold the Shining"
    assert sought_artifact("Urist cancels Drink: Interrupted by a human bard.") == ""
    s = fort(artifacts=[NETTLEWALK], counts={"claimed": 0, "total": 1})
    m = Memory()
    assert not closing(rule(s, m))                          # nobody has come for it yet: open
    note_heists(s, m, [LEN])
    assert m.artifacts_sought.get("Nettlewalk") == abs_tick(s), m.artifacts_sought
    assert closing(rule(s, m))                              # the lockout and the claim both
    # a year on (the lockout long over), Nettlewalk still here: still shut
    later = copy.deepcopy(s)
    later["date"]["year"] += 1
    later["locations"]["built"] = abs_tick(later)
    c = closing(rule(later, m))
    assert c and "Nettlewalk (a hero came for it)" in c[0].reason, [(p.action, p.reason) for p in rule(later, m)]


@test("an artifact a figure from afar claims (the bridge's `sought`): at risk; g7_hf_claims_risk off: not")
def _():
    art = dict(NETTLEWALK, sought=2)
    s = fort(artifacts=[art], counts={"claimed": 0, "at_risk": 1, "total": 1})
    assert closing(rule(s, Memory()))
    cfg = dict(CFG, g7_hf_claims_risk=False)
    props = []
    _location_access_rule(s, Memory(), cfg, props, [])
    assert not closing(props)


@test("a pulse or a cached report without the artifacts section: the last report's risk holds a week, then "
      "the AI's shut locations open again")
def _():
    s = fort(flags=SHUT, artifacts=B_ARTIFACTS, counts=B_COUNTS)
    m = Memory()
    m.locations_closed = [0, 1, 2, 3, 4]
    note_locations(s, m, CFG)
    assert m.artifact_risk.get("seen") == abs_tick(s) and m.artifact_risk.get("n") == 19, m.artifact_risk
    bare = fort(flags=SHUT)                                 # no artifacts section
    bare["date"]["tick"] += 3 * TICKS_PER_DAY
    bare["locations"]["built"] = abs_tick(bare)
    assert claimed_shut(bare, m, CFG) and not opening(rule(bare, m))
    bare["date"]["tick"] += 6 * TICKS_PER_DAY
    bare["locations"]["built"] = abs_tick(bare)
    assert claimed_shut(bare, m, CFG) is None and opening(rule(bare, m))


@test("the Rules switch heist_lockout off, or g7_claimed_shut off: nothing shut for the claims; the player's "
      "own opened location stays open; a closed fort shuts as before")
def _():
    s = fort(artifacts=B_ARTIFACTS, counts=B_COUNTS)
    s["settings"]["heist_lockout"] = False
    assert not closing(rule(s, Memory()))
    s = fort(artifacts=B_ARTIFACTS, counts=B_COUNTS)
    props = []
    _location_access_rule(s, Memory(), dict(CFG, g7_claimed_shut=False), props, [])
    assert not closing(props)
    m = Memory()
    m.locations_yours = [1]
    c = closing(rule(s, m))
    assert c and 1 not in c[0].action["ids"] and 0 in c[0].action["ids"], c
    c = closing(rule(fort(-60, artifacts=B_ARTIFACTS, counts=B_COUNTS), Memory()))
    assert c and "keeps to itself" in c[0].reason, c


@test("plan(): the claimed shut comes out of the whole planner for B's state (and no reopen of a shut fort)")
def _():
    s = fort(artifacts=B_ARTIFACTS, counts=B_COUNTS)
    props, _ = plan(s, Memory())
    c = [p for p in props if p.rule == "location_access" and p.action.get("visitors") is False]
    assert c and sorted(c[0].action["ids"]) == [0, 1, 2, 3, 4], [(p.rule, p.action) for p in props
                                                                if p.rule == "location_access"]


# --- the brain: a visitor turned killer is a target -------------------------------------------

def threat_fort(rows, squads):
    s = copy.deepcopy(BASE)
    s["others_on_map"]["threats"] = rows
    s["others_on_map"]["threats_that_can_reach_dwarves"] = sum(1 for t in rows if t.get("can_reach_dwarves") is True)
    s["military"]["squads"] = squads
    s["civ_alert"] = False
    s["civ_alert_ready"] = True
    s["settings"]["attack_policy"] = "ordinary"
    return s


@test("plan(): the bridge's turned-visitor row (Len Karaura, not invader, not thief) gets the alarm and a squad")
def _():
    row = {"id": 15366, "name": "Len Karaura \"Heatdied\", Human Axeman", "invader": False, "great_danger": False,
           "turned": True, "visitor": True, "flier": False, "size": 70000, "can_reach_dwarves": True,
           "layer": "upper_levels", "distance_to_nearest_dwarf": 3, "levels_from_nearest_dwarf": 0,
           "pos": {"x": 113, "y": 116, "z": 162}}
    sq = [{"id": 3, "name": "Axes", "members": 5, "size": 10, "orders": 0, "ai_orders": 0,
           "power": {"power": 30.0, "armed": 5, "melee_power": 30.0, "ranged_power": 0}}]
    props, notes = plan(threat_fort([row], sq), Memory())
    kills = [p for p in props if p.action.get("type") == "squad_orders" and 15366 in (p.action.get("kill") or [])]
    alarm = [p for p in props if p.action == {"type": "civ_alert", "on": True}]
    assert kills and alarm, ([(p.rule, p.action) for p in props], notes)


# --- the Lua: the artifacts module -----------------------------------------------------------

def artifacts_fake() -> str:
    tree = ast.parse((ROOT / "tests" / "test_artifacts.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "FAKE" for t in node.targets):
            return node.value.value
    raise AssertionError("test_artifacts.FAKE not found")


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


def art_world(job_role=True, t_role=False):
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(artifacts_fake(), module_src("ai-artifacts.lua"))
    lua.execute("local env, role, trole = ...; env.df.job_item_ref = trole and {T_role = {Hauled = 'Hauled'}} or nil; "
                "env.df.job_role_type = role and {Hauled = 'Hauled', Other = 'Other'} or nil", env, job_role, t_role)
    return lua, env, w


def display_setup(lua, env, w):
    z = w.zone(T(lua, {"x1": 10, "y1": 10, "x2": 14, "y2": 14, "loc": {"type": "TEMPLE", "visitors": False}}))
    w.door(12, 9)
    w.boxes[1] = T(lua, {"x1": 9, "y1": 9, "x2": 15, "y2": 15, "z": 100})
    env.first_id()
    d = w.display(T(lua, {"x": 11, "y": 11}))
    w.with_jobs(d)
    reg = env.registry()
    reg.displays[1] = d.id
    w.site["ai-overseer/artifacts"] = reg
    it = w.art(T(lua, {"id": 3}))
    return z, d, it


@test("lua: display_artifact in DFHack 53.17 (df.job_role_type.Hauled, no df.job_item_ref.T_role): the job is "
      "made with the hauled role (A: 45 Lua errors at ai-artifacts.lua:562)")
def _():
    need_lua()
    lua, env, w = art_world(job_role=True, t_role=False)
    _, d, it = display_setup(lua, env, w)
    r = env.display_artifact(T(lua, {"item_id": it.id, "building_id": d.id}), False)
    assert r.ok is True, dict(r)
    job = w.jobs[1]
    assert job["items"][1][2] == "Hauled" and job.job_type == "PutItemOnDisplay"


@test("lua: no hauled role in this DF at all: refused before any job is made (none left allocated)")
def _():
    need_lua()
    lua, env, w = art_world(job_role=False, t_role=False)
    _, d, it = display_setup(lua, env, w)
    made = []
    lua.execute("local env, made = ...; local new = env.df.job.new; "
                "env.df.job.new = function(...) made[#made + 1] = 1; return new(...) end", env, made)
    r = env.display_artifact(T(lua, {"item_id": it.id, "building_id": d.id}), False)
    assert r.rejected and "hauled job role" in r.error, dict(r)
    assert len(list(w.jobs.keys())) == 0


@test("lua: the report marks an artifact a figure from afar claims (`sought`, remote_claims) and counts the "
      "artifacts at risk (claimed by a civ or a figure); they sort before the rest")
def _():
    need_lua()
    lua, env, w = art_world()
    env.first_id()
    a = w.art(T(lua, {"id": 7, "name": "Nettlewalk"}))
    b = w.art(T(lua, {"id": 8, "name": "Plain", "pos": {"x": 2, "y": 2, "z": 100}}))
    c = w.art(T(lua, {"id": 9, "name": "Claimed", "claims": [44], "pos": {"x": 3, "y": 3, "z": 100}}))
    lua.execute("local W = ...; for _, r in ipairs(W.records) do if r.id == 7 then r.remote_claims = {101, 102} end end", w)
    r = env.report()
    rows = {r.artifacts[i].name: r.artifacts[i] for i in range(1, len(r.artifacts) + 1)}
    assert rows["Nettlewalk"].sought == 2 and rows["Plain"].sought is None, dict(rows["Nettlewalk"])
    assert rows["Claimed"].claimed_by is not None
    assert r.counts.at_risk == 2 and r.counts.claimed == 1, dict(r.counts)
    order = [r.artifacts[i].name for i in range(1, len(r.artifacts) + 1)]
    assert order.index("Plain") > order.index("Nettlewalk"), order
    _ = (a, b, c)


# --- the Lua: visitors turned killers ----------------------------------------------------------

THREATS_GAME = r"""
local src = ...
local G = {units = {}, active = {}, site = {}}
local e = setmetatable({G = G}, {__index = _G})
e.df = {global = {cur_year = 262, cur_year_tick = 283204, plotinfo = {site_id = 1430},
                  world = {units = {active = G.active}}},
        unit = {find = function(id) return G.units[id] end}}
local function has(k) return function(u) return u[k] == true end end
e.dfhack = {persistent = {getSiteData = function(k, d) local v = G.site[k]; if v == nil then return d end return v end,
                          saveSiteData = function(k, v) G.site[k] = v end},
            units = {isActive = function() return true end, isDead = has('dead'),
                     isCitizen = has('citizen'), isAnimal = has('animal'), isVisitor = has('visitor'),
                     getReadableName = function(u) return u.name end}}
e.reqscript = function(name) error('no ' .. name) end
assert(load(src, 'ai-threats', 't', e))()
function e.add_unit(u) G.units[u.id] = u; G.active[#G.active + 1] = u end
return e
"""


def threats_env():
    lua = LuaRuntime(unpack_returned_tuples=True)
    return lua, lua.execute(THREATS_GAME, module_src("ai-threats.lua"))


def unit(lua, i, name, x, y, z, **kw):
    return lua.table_from(dict({"id": i, "name": name, "pos": lua.table_from({"x": x, "y": y, "z": z})}, **kw))


@test("lua: a visitor who kills a citizen is marked (kept in the save, for 28 days); a berserk victim, an animal "
      "victim, a citizen killer, a dead killer, a told-again death: not")
def _():
    need_lua()
    lua, E = threats_env()
    len_ = unit(lua, 15366, 'Len Karaura "Heatdied", Human Axeman', 113, 116, 162, visitor=True)
    E.add_unit(len_)
    ev = dict(kind="death", own_civ=True, animal=False, killer_kind="outsider", killer_id=15366,
              killer_visitor=True, cause="STRUCK_DOWN")
    assert E.is_turned(len_) is False
    for bad in (dict(ev, mood="Berserk"), dict(ev, animal=True), dict(ev, killer_kind="citizen"),
                dict(ev, killer_dead=True), dict(ev, again=True), dict(ev, own_civ=False)):
        assert E.note_death(lua.table_from(bad)) is False, bad
    assert E.is_turned(len_) is False
    assert E.note_death(lua.table_from(ev)) is True and E.is_turned(len_) is True
    saved = E.G.site["ai-overseer/threats"]
    assert saved.turned["15366"] == 262 * 403200 + 283204
    # read back from the save in a fresh session (the module's table lost)
    lua.execute("local E = ...; E.TURNED = nil", E)
    assert E.is_turned(len_) is True
    # 28 days on: no longer
    lua.execute("local E = ...; E.df.global.cur_year_tick = E.df.global.cur_year_tick + 29 * 1200", E)
    assert E.is_turned(len_) is False


@test("lua: the AMBUSH_HERO report marks the hero it names (Len Karaura), or the one stranger by its place; "
      "never a citizen or an animal; other reports mark nobody")
def _():
    need_lua()
    lua, E = threats_env()
    hero = unit(lua, 15366, 'Len Karaura "Heatdied", Human Axeman', 140, 140, 150, visitor=True)
    bard = unit(lua, 900, 'Udib Shorast, Human Bard', 113, 116, 162, visitor=True)
    dwarf = unit(lua, 10, 'Kubuk Fikod, Miner', 113, 117, 162, citizen=True)
    for u in (hero, bard, dwarf):
        E.add_unit(u)
    assert E.first_name_of('Len Karaura "Heatdied", Human Axeman') == "Len Karaura"
    assert E.note_report(lua.table_from(LEN)) == 15366          # by name, though it stands elsewhere now
    assert E.is_turned(hero) and not E.is_turned(bard) and not E.is_turned(dwarf)
    # unnamed (the text names no unit here): the one non-citizen within 3 tiles of the report
    lua2, E2 = threats_env()
    bard2 = unit(lua2, 900, 'Udib Shorast, Human Bard', 113, 116, 162, visitor=True)
    cat = unit(lua2, 901, 'cat', 112, 116, 162, animal=True)
    E2.add_unit(bard2)
    E2.add_unit(cat)
    E2.add_unit(unit(lua2, 10, 'Kubuk Fikod, Miner', 113, 117, 162, citizen=True))
    ev = dict(LEN, text="The Human Swordsman Itvid Gicthosmnisam was spotted sneaking around!  "
                        "\"You will not stand between me and Pillartoned!\"")
    assert E2.note_report(lua2.table_from(ev)) == 900 and E2.is_turned(bard2) and not E2.is_turned(cat)
    assert E2.note_report(lua2.table_from({"kind": "report", "type": "MASTERPIECE_CRAFTED",
                                           "text": "Urist has created a masterpiece!"})) is None


@test("lua: ai-military's kill_target_ok takes a marked visitor (ai-threats is_turned), never a citizen")
def _():
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    M = lua.execute(r"""
    local src = ...
    local env = setmetatable({}, {__index = _G})
    env.TURN = {}
    env.reqscript = function(name)
        if name == 'ai-threats' then
            return {interrupting = function() return false end, is_turned = function(u) return env.TURN[u.id] == true end}
        end
        error('no ' .. name)
    end
    assert(load(src, 'ai-military', 't', env))()
    env.df = {mood_type = {Berserk = 7}}
    local function has(k) return function(u) return u[k] == true end end
    env.dfhack = {units = {isMerchant = has('merchant'), isDiplomat = has('diplomat'), isTame = has('tame'),
        isCitizen = has('citizen'), isDanger = has('danger'), isInvader = has('invader')}}
    return env
    """, module_src("ai-military.lua"))
    t = lambda **kw: lua.table_from(kw)
    assert not M.kill_target_ok(t(id=15366, visitor=True))
    lua.execute("local M = ...; M.TURN[15366] = true; M.TURN[10] = true", M)
    assert M.kill_target_ok(t(id=15366, visitor=True))
    assert not M.kill_target_ok(t(id=10, citizen=True))


@test("bridge: deaths and reports feed the marks; others_on_map lists a marked visitor as a threat (turned)")
def _():
    rep = bridge_part_src("ai-bridge-report")
    br = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    assert code_has(rep, "pcall(function() reqscript('ai-threats').note_death(ev) end)")
    assert code_has(br, "pcall(function() reqscript('ai-threats').note_report(ev, txt) end)")
    assert code_has(rep, "elseif dfhack.units.isDanger(u) or turned then")
    assert code_has(rep, "turned = turned or nil,")
    art = (LUA_DIR / "ai-artifacts.lua").read_text(encoding="utf-8")
    assert code_has(art, "dfhack.job.attachJobItem(job, it, role, -1, -1)")
    assert not code_has(art, "df.job_item_ref.T_role.Hauled")


if __name__ == "__main__":
    finish()

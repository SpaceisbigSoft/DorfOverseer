"""(0.105.45) The sweep for things stuck "in progress" (Phase 11 (d)):
lua/ai-stuck.lua in a fake fort (the pure helpers: since/moved kept and
moved on, the list ranked and capped, the AI's lever names, the targets'
states; the collectors: levers' pull jobs, kill orders on targets gone, the
AI's one-time orders, the cistern, the waterworks, projects, gates; the
`stuck_reset` action: only the AI's levers, reissue and drop, the dry run),
the bridge's wiring, and the brain (brain/planner_stuck.py: timeouts,
escalation nudge -> retire, the backoff and the family's doubling, never
twice with another rule's action, the soak count and health_check's line).

    python tests/test_stuck.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, Proposal, plan, record  # noqa: E402
import planner_stuck as PS  # noqa: E402
from digest import normalize, SECTION_DEFAULTS  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
DAY = 1200
YEAR = 403200

FAKE = r"""
local src = ...
local W = {site = {}, traps = {}, buildings = {}, units = {}, squads = {}, orders = {}, removed = {}, cmds = {},
           projects = {list = {}}, works = {}, gates = {entrances = {}, closing_since = {}}, planned = {},
           fort = {squads = {}}}
local env = setmetatable({}, {__index = _G})
env.CR_OK = 0
env.df = {
    global = {cur_year = 300, cur_year_tick = 0, plotinfo = {group_id = 7},
              world = {buildings = {other = {TRAP = W.traps}}, manager_orders = {all = W.orders}}},
    trap_type = {Lever = 1},
    job_type = {PullLever = 77, [77] = 'PullLever', [12] = 'MakeCrafts'},
    building = {find = function(id) return W.buildings[id] end},
    unit = {find = function(id) return W.units[id] end},
    squad = {find = function(id) return W.squads[id] end},
    historical_entity = {find = function() return W.fort end},
    squad_order_kill_listst = {is_instance = function(_, o) return o.kill == true end},
    workquota_frequency_type = {[0] = 'OneTime', [1] = 'Daily'},
}
env.dfhack = {
    df2utf = function(s) return s end,
    units = {isDead = function(u) return u.dead == true end,
             isActive = function(u) return u.inactive ~= true end},
    job = {getWorker = function(j) return j.worker end,
           removeJob = function(j)
               table.insert(W.removed, j.id)
               for _, b in pairs(W.buildings) do
                   for i, x in ipairs(b.jobs or {}) do if x == j then table.remove(b.jobs, i) break end end
               end
               return true
           end},
    military = {getSquadName = function(id) return 'Squad ' .. id end},
    run_command_silent = function(...) table.insert(W.cmds, table.concat({...}, ' ')); return 'ok', 0 end,
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
}
env.reqscript = function(name)
    if name == 'ai-builder' then
        return {load_projects = function() return W.projects end,
                tile_info = function() return {liquid = true, depth = W.depth or 0} end}
    elseif name == 'ai-waterworks' then
        return {load_state = function() return {works = W.works, refused = {}} end}
    elseif name == 'ai-military' then
        return {AI_ORDER_TITLE = 'AI overseer'}
    elseif name == 'ai-gates' then
        return {GATES = W.gates, ai_planned_building = function(b) return W.planned[b.id] == true end}
    end
    error('no module ' .. tostring(name))
end
assert(load(src, 'ai-stuck', 't', env))()
function W.lever(id, name, jobs)
    local b = {id = id, name = name, trap_type = 1, jobs = jobs or {}, centerx = 5, centery = 6, z = 100}
    table.insert(W.traps, b)
    W.buildings[id] = b
    return b
end
return env, W
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-stuck.lua"))
    return lua, env, w


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


def py(v):
    if hasattr(v, "items"):
        d = {k: py(x) for k, x in v.items()}
        if d and all(isinstance(k, int) for k in d) and sorted(d) == list(range(1, len(d) + 1)):
            return [d[i] for i in range(1, len(d) + 1)]
        return d
    return v


def set_tick(env, ticks):
    env.df["global"].cur_year = 300 + ticks // YEAR
    env.df["global"].cur_year_tick = ticks % YEAR


# --- 1. the pure helpers -------------------------------------------------------------------

@test("lua track: a new thing gets its own start or now; progress moves `moved`; a new state starts again; gone dropped")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    rows = T(lua, [{"kind": "order", "id": 5, "state": "open", "progress": 10},
                   {"kind": "project", "id": 3, "state": "dig", "since": 1000}])
    seen, changed = env.track(T(lua, {}), rows, 5000)
    r = py(rows)
    assert changed is True
    assert (r[0]["since"], r[0]["moved"], r[0]["key"]) == (5000, 5000, "order:5"), r[0]
    assert (r[1]["since"], r[1]["moved"], r[1]["age_days"], r[1]["still_days"]) == (1000, 5000, 3, 0), r[1]
    # nothing moved: the same; the order moved: `moved` now; the project's state changed: since now
    rows = T(lua, [{"kind": "order", "id": 5, "state": "open", "progress": 10},
                   {"kind": "project", "id": 3, "state": "dig", "since": 1000}])
    seen2, changed = env.track(seen, rows, 9800)
    r = py(rows)
    assert changed is False and r[0]["still_days"] == 4 and r[1]["still_days"] == 4, (changed, r)
    rows = T(lua, [{"kind": "order", "id": 5, "state": "open", "progress": 9},
                   {"kind": "project", "id": 3, "state": "furnish", "since": 9000}])
    seen3, changed = env.track(seen2, rows, 12000)
    r = py(rows)
    assert changed is True and r[0]["moved"] == 12000 and r[0]["since"] == 5000
    assert r[1]["since"] == 9000 and r[1]["moved"] == 12000, r[1]
    seen4, changed = env.track(seen3, T(lua, [{"kind": "order", "id": 5, "state": "open", "progress": 9}]), 13000)
    assert changed is True and sorted(py(seen4)) == ["order:5"], py(seen4)


@test("lua rank: oldest first, capped, with the total; lever names: the AI's yes, the player's 'AI gate' no")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    rows = T(lua, [{"key": "a", "since": 30}, {"key": "b", "since": 10}, {"key": "c", "since": 20}])
    out, total = env.rank(rows, 2)
    assert [x["key"] for x in py(out)] == ["b", "c"] and total == 3
    assert env.ai_lever_name("AI gate lever") and env.ai_lever_name("AI moat") and env.ai_lever_name("ai pump")
    assert not env.ai_lever_name("AI gate") and not env.ai_lever_name("Gate lever") and not env.ai_lever_name(None)
    c = py(env.targets_state(T(lua, [1, 2, 3, 4]), lambda i: {1: "dead", 2: "gone", 3: "caged", 4: "live"}[i]))
    assert c == {"live": 1, "dead": 1, "gone": 1, "caged": 1}, c


# --- 2. the collectors and the report ------------------------------------------------------

@test("lua report: an AI lever's pull job (worker or not), the player's 'AI gate' left out; since kept in the save")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    w.lever(10, "AI gate lever", T(lua, [{"id": 900, "job_type": 77, "flags": {}}]))
    w.lever(11, "AI gate", T(lua, [{"id": 901, "job_type": 77, "flags": {}}]))
    w.lever(12, "AI moat", T(lua, []))
    r = py(env.report())
    lev = [x for x in r["list"] if x["kind"] == "lever"]
    assert [(x["id"], x["state"], x["worker"], x["pulls"]) for x in lev] == [(10, "pull:900", False, 1)], lev
    assert "ai-overseer/stuck" in py(w.site)
    set_tick(env, 3 * DAY)
    r = py(env.report())
    lev = [x for x in r["list"] if x["kind"] == "lever"][0]
    assert lev["since"] == 300 * YEAR and lev["still_days"] == 3, lev


@test("lua report: kill orders on targets all dead/gone/caged are kill_done; a live one is kill; not the AI's: none")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    w.units[1] = T(lua, {"dead": True, "flags1": {}})
    w.units[3] = T(lua, {"flags1": {"caged": True}})
    w.units[4] = T(lua, {"flags1": {}})
    w.squads[40] = T(lua, {"orders": [{"title": "AI overseer", "kill": True, "units": [1, 2, 3]}]})
    w.squads[41] = T(lua, {"orders": [{"title": "AI overseer", "kill": True, "units": [1, 4]}]})
    w.squads[42] = T(lua, {"orders": [{"title": "", "kill": True, "units": [1]}]})
    w.fort.squads = T(lua, [40, 41, 42])
    r = py(env.report())
    sq = {x["id"]: x for x in r["list"] if x["kind"] == "squad"}
    assert sorted(sq) == [40, 41], sq
    assert (sq[40]["state"], sq[40]["dead"], sq[40]["gone"], sq[40]["caged"]) == ("kill_done", 1, 1, 1), sq[40]
    assert sq[41]["state"] == "kill" and sq[41]["live"] == 1


@test("lua report: the AI's one-time orders (amount left as progress), the cistern, a waterwork, projects, a gate")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    w.site["ai-overseer/orders"] = T(lua, {"ids": {"5": True, "6": True}})
    w.orders[1] = T(lua, {"id": 5, "frequency": 0, "amount_left": 3, "amount_total": 5, "job_type": 12,
                          "status": {"validated": True}})
    w.orders[2] = T(lua, {"id": 6, "frequency": 1, "amount_left": 1, "amount_total": 1, "job_type": 12})
    w.orders[3] = T(lua, {"id": 7, "frequency": 0, "amount_left": 1, "amount_total": 1, "job_type": 12})
    w.site["ai-overseer/cistern"] = T(lua, {"stage": "linking", "relinks": 2})
    w.works["moat"] = T(lua, {"kind": "moat", "stage": "digging", "since": 299 * YEAR})
    w.works["pump"] = T(lua, {"kind": "pump", "stage": "done"})
    w.projects.list = T(lua, [{"id": 3, "kind": "bedrooms", "phase": "dig", "started": {"year": 299, "tick": 100}},
                              {"id": 4, "kind": "dining", "phase": "done"}])
    w.buildings[70] = T(lua, {"id": 70, "jobs": [{"id": 1, "flags": {"suspend": True}}]})
    w.buildings[71] = T(lua, {"id": 71, "jobs": [{"id": 2, "flags": {}}]})
    w.planned[70] = True
    w.gates.entrances = T(lua, [{"id": 2, "x": 10, "y": 11, "z": 100, "kind": "stair", "closing": True,
                                 "pending_ids": [70, 71]}])
    w.gates.closing_since[(100 * 4096 + 11) * 4096 + 10] = 299 * YEAR + 50
    r = py(env.report())
    by = {x["key"]: x for x in r["list"]}
    assert by["order:5"]["progress"] == 3 and "order:6" not in by and "order:7" not in by, sorted(by)
    assert by["cistern:cistern"]["state"] == "linking" and by["cistern:cistern"]["progress"].startswith("2/")
    assert by["waterwork:moat"]["since"] == 299 * YEAR and "waterwork:pump" not in by
    assert by["project:3"]["since"] == 299 * YEAR + 100 and "project:4" not in by
    g = by["gate:10,11,100"]
    assert (g["id"], g["pieces"], g["job"], g["suspended"], g["since"]) == (2, 1, True, True, 299 * YEAR + 50), g
    assert r["total"] == len(r["list"]) and r.get("errors") is None
    # oldest first
    assert [x["key"] for x in r["list"]][:3] == ["waterwork:moat", "gate:10,11,100", "project:3"], r["list"]


@test("lua report: a collector that fails is said in errors, the others still listed, its old rows kept")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    w.site["ai-overseer/cistern"] = T(lua, {"stage": "digging"})
    w.site["ai-overseer/stuck"] = T(lua, {"items": {"project:9": {"s": "dig", "p": "", "since": 5, "moved": 5}}})
    w.projects = None          # load_projects returns nil: projects() throws
    r = py(env.report())
    assert "project" in r["errors"] and [x["key"] for x in r["list"]] == ["cistern:cistern"], r
    assert "project:9" in py(w.site["ai-overseer/stuck"])["items"]


# --- 3. the action --------------------------------------------------------------------------

@test("lua stuck_reset: the AI's lever only; dry run counts; reissue takes the job off and pulls afresh; drop only takes it off")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    w.lever(10, "AI gate lever", T(lua, [{"id": 900, "job_type": 77, "flags": {}}]))
    w.lever(11, "AI gate", T(lua, [{"id": 901, "job_type": 77, "flags": {}}]))
    w.lever(13, "My lever", T(lua, [{"id": 903, "job_type": 77, "flags": {}}]))
    w.lever(14, "AI pump", T(lua, [{"id": 904, "job_type": 77, "flags": {}}, {"id": 905, "job_type": 77, "flags": {}}]))
    assert py(env.reset(T(lua, {"kind": "lever", "id": 11}), False))["rejected"] is True
    assert py(env.reset(T(lua, {"kind": "lever", "id": 13}), False))["rejected"] is True
    assert py(env.reset(T(lua, {"kind": "squad", "id": 10}), False))["rejected"] is True
    assert py(env.reset(T(lua, {"kind": "lever", "id": 10, "mode": "x"}), False))["rejected"] is True
    d = py(env.reset(T(lua, {"kind": "lever", "id": 10}), True))
    assert d == {"ok": True, "dry_run": True, "jobs": 1, "queued": 1} and py(w.removed) in ({}, []), (d, py(w.removed))
    r = py(env.reset(T(lua, {"kind": "lever", "id": 10, "mode": "reissue"}), False))
    assert r == {"ok": True, "removed": 1, "queued": 1}, r
    assert py(w.cmds) == ["lever pull --id 10"], py(w.cmds)
    # two pulls waiting undo each other: taken off, none asked again
    r = py(env.reset(T(lua, {"kind": "lever", "id": 14, "mode": "reissue"}), False))
    assert r == {"ok": True, "removed": 2, "queued": 0} and len(py(w.cmds)) == 1, r
    w.lever(15, "AI moat", T(lua, [{"id": 906, "job_type": 77, "flags": {}}]))
    r = py(env.reset(T(lua, {"kind": "lever", "id": 15, "mode": "drop"}), False))
    assert r == {"ok": True, "removed": 1, "queued": 0} and len(py(w.cmds)) == 1, r
    assert py(env.reset(T(lua, {"kind": "lever", "id": 15}), False))["rejected"] is True    # no job now


@test("bridge: the stuck section (safe), stuck_reset (kind and mode checked, dry run), DRY_OK, the module listed; digest, label")
def _():
    src = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "stuck = function() return safe(function() return reqscript('ai-stuck').report() end) end," in src
    actions = src[src.index("ACTIONS = {"):src.index("DRY_OK = {}")]
    assert "stuck_reset = function(a)" in actions and "reqscript('ai-stuck').reset(" in actions
    dry = src[src.index("DRY_OK = {}"):src.index("}) do DRY_OK[name] = true end")]
    assert "'stuck_reset'" in dry
    mods = src[src.index("BRIDGE_MODULES = {"):src.index("}", src.index("BRIDGE_MODULES = {"))]
    assert "'ai-stuck'" in mods
    assert SECTION_DEFAULTS["stuck"] == {}
    import overseer
    assert "stuck_reset" in overseer.SHORT_WORDS
    if LuaRuntime is None:
        return
    i = src.index("    stuck_reset = function(a)")
    j = src.index("    end,\n", i) + len("    end,\n")
    fn = src[i:j].strip().rstrip(",").replace("stuck_reset = function(a)", "return function(a)", 1)
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
        GOT = nil
        function reject(r) return {ok = false, rejected = true, error = r} end
        function reqscript() return {reset = function(o, dry) GOT = {o = o, dry = dry}; return {ok = true} end} end
    """)
    f = lua.execute(fn)
    assert f(lua.table_from({"kind": "squad", "id": 1}))["rejected"] is True
    assert f(lua.table_from({"kind": "lever", "id": 1, "mode": "x"}))["rejected"] is True
    assert f(lua.table_from({"kind": "lever", "id": 3, "mode": "drop", "dry_run": True}))["ok"] is True
    got = lua.globals().GOT
    assert (got.o.kind, got.o.id, got.o.mode, got.dry) == ("lever", 3, "drop", True)


# --- 4. the brain ---------------------------------------------------------------------------

NOW = 300 * YEAR + 100 * DAY


def state(rows, projects=None, orders=None, **extra):
    base = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    base["date"] = {"year": NOW // YEAR, "tick": NOW % YEAR, "day": 1, "month": "Granite", "season": "spring"}
    base["stuck"] = {"list": rows, "total": len(rows), "tick": NOW}
    if projects is not None:
        base["projects"] = {"open": projects, "decorating": [], "finished": 0, "max_open": 2}
    if orders is not None:
        base["orders"] = orders
    base.update(extra)
    return normalize(base)


def at(s, days):
    t = NOW + days * DAY
    s = dict(s)
    s["date"] = dict(s["date"], year=t // YEAR, tick=t % YEAR)
    return s


def run(s, memory, proposals=None):
    props, notes = list(proposals or []), []
    PS._stuck_rule(s, memory, dict(PLANNER_CONFIG), props, notes)
    return props, notes


def mine(props):
    return [p for p in props if p.rule == PS.STUCK_RULE]


def done(props, s, memory, ok=True):
    record([(p, {"ok": ok}) for p in props], s, memory)


LEVER = {"kind": "lever", "id": 10, "key": "lever:10", "state": "pull:900", "since": NOW - 5 * DAY,
         "moved": NOW - 5 * DAY, "worker": False, "what": "AI gate lever"}


@test("brain: under the timeout nothing; past it the nudge, then (still nothing) the retire, then the backoff")
def _():
    p, n = run(state([dict(LEVER, since=NOW - DAY, moved=NOW - DAY)]), Memory())
    assert mine(p) == [] and n == [], (p, n)
    m = Memory()
    s = state([LEVER])
    p, n = run(s, m)
    assert [x.action for x in mine(p)] == [{"type": "stuck_reset", "kind": "lever", "id": 10, "mode": "reissue"}], p
    assert len(n) == 1 and "nudged" in n[0] and "no dwarf has taken it" in n[0], n
    done(mine(p), s, m)
    assert m.stuck_seen["items"]["lever:10"]["step"] == 1
    # the next cycle: waiting out the nudge (a note, nothing proposed)
    p, n = run(at(s, 0), m)
    assert mine(p) == [] and "nudged 0 day(s) ago" in n[0], n
    # a day on (the lever's wait is half its 2-day timeout), the same job: dropped
    p, n = run(at(s, 1), m)
    assert [x.action for x in mine(p)] == [{"type": "stuck_reset", "kind": "lever", "id": 10, "mode": "drop"}], p
    done(mine(p), at(s, 1), m)
    assert m.stuck_seen["items"]["lever:10"]["step"] == 2 and m.stuck_seen["families"]["lever:10"]
    p, n = run(at(s, 2), m)
    assert mine(p) == [] and "retired" in n[0] and "left" in n[0], n


@test("brain: progress starts the steps again; a refused action leaves the step; a thing gone is forgotten")
def _():
    m = Memory()
    s = state([dict(LEVER)])
    p, _ = run(s, m)
    done(mine(p), s, m, ok=False)
    assert m.stuck_seen["items"]["lever:10"]["step"] == 0
    p, _ = run(s, m)
    done(mine(p), s, m)
    assert m.stuck_seen["items"]["lever:10"]["step"] == 1
    # a new pull job (a new state): the steps begin again, and it's fresh (not past)
    s2 = state([dict(LEVER, state="pull:950", since=NOW, moved=NOW)])
    p, n = run(s2, m)
    assert mine(p) == [] and m.stuck_seen["items"]["lever:10"]["step"] == 0
    run(state([]), m)
    assert m.stuck_seen["items"] == {} and m.stuck_seen["past"] == {}


@test("brain: a project's dig nudged (free_dig_jobs / prioritize_dig / renew_well_dig), then given up; its dig moving resets")
def _():
    row = {"kind": "project", "id": 3, "state": "dig", "since": NOW - 200 * DAY, "moved": NOW - 100 * DAY,
           "what": "bedrooms"}
    proj = {"id": 3, "kind": "bedrooms", "phase": "dig", "dig": {"dug": 40, "total": 89, "digging": 2}}
    m = Memory()
    s = state([row], projects=[proj])
    p, n = run(s, m)
    assert [x.action for x in mine(p)] == [{"type": "free_dig_jobs", "project_id": 3}], p
    done(mine(p), s, m)
    p, n = run(at(s, 15), m)
    assert [x.action for x in mine(p)] == [{"type": "cancel_project", "project_id": 3}], p
    # nothing dug and nobody digging: dug first; a well: its channel renewed; the give-up keeps the spot off-limits
    m = Memory()
    s = state([row], projects=[dict(proj, dig={"dug": 0, "total": 89, "digging": 0})])
    p, _ = run(s, m)
    assert [x.action for x in mine(p)] == [{"type": "prioritize_dig", "project_id": 3, "priority": 2}]
    done(mine(p), s, m)
    p, _ = run(at(s, 15), m)
    assert [x.action for x in mine(p)] == [{"type": "cancel_project", "project_id": 3, "unreached": True}]
    m = Memory()
    s = state([dict(row, what="well", cavern=True)], projects=[dict(proj, kind="well", dig={"dug": 0, "total": 1})])
    p, _ = run(s, m)
    assert [x.action for x in mine(p)] == [{"type": "renew_well_dig", "project_id": 3, "priority": 2}]
    done(mine(p), s, m)
    p, _ = run(at(s, 15), m)
    assert mine(p)[0].action == {"type": "cancel_project", "project_id": 3, "unreached": True, "cavern_well": True}
    # its dig moves (the projects section's count changes): the steps begin again
    m = Memory()
    s = state([row], projects=[proj])
    p, _ = run(s, m)
    done(mine(p), s, m)
    s2 = state([row], projects=[dict(proj, dig={"dug": 41, "total": 89, "digging": 2})])
    p, n = run(at(s2, 15), m)
    assert mine(p) == [] and m.stuck_seen["items"]["project:3"]["step"] == 0, (p, n)


@test("brain: a level furnishing for ever is finished as it stands; a way in, a landmark, decorating: never the sweep's")
def _():
    row = {"kind": "project", "id": 5, "state": "furnish", "since": NOW - 200 * DAY, "moved": NOW - 100 * DAY,
           "what": "dining"}
    proj = {"id": 5, "kind": "dining", "phase": "furnish", "furnish": {"done": 3, "placed": 9}}
    p, _ = run(state([row], projects=[proj]), Memory())
    assert [x.action for x in mine(p)] == [{"type": "finish_project", "project_id": 5, "stalled": True}], p
    for what, phase in (("way_in", "dig"), ("landmark", "dig"), ("dining", "decorate")):
        p, n = run(state([dict(row, what=what, state=phase)], projects=[dict(proj, kind=what, phase=phase)]), Memory())
        assert mine(p) == [] and n == [], (what, p, n)
    # not in the projects section this cycle: left
    p, n = run(state([row], projects=[]), Memory())
    assert mine(p) == [] and n == []


@test("brain: never twice: another rule's proposal on the same thing leaves it (projects, squads, orders, gates, the cistern)")
def _():
    row = {"kind": "project", "id": 3, "state": "dig", "since": NOW - 200 * DAY, "moved": NOW - 100 * DAY,
           "what": "bedrooms"}
    proj = {"id": 3, "kind": "bedrooms", "phase": "dig", "dig": {"dug": 40, "total": 89, "digging": 2}}
    other = Proposal("dig_jobs", {"type": "free_dig_jobs", "project_id": 3}, "the level rule", 3)
    p, n = run(state([row], projects=[proj]), Memory(), [other])
    assert mine(p) == [] and "the dig_jobs rule acts on it" in n[0], n
    gate = {"kind": "gate", "id": 2, "key": "gate:10,11,100", "state": "closing", "since": NOW - 60 * DAY,
            "moved": NOW - 60 * DAY, "pieces": 1, "what": "stair", "x": 10, "y": 11}
    for rule, act in (("gate_stuck", {"type": "unstick_gate", "id": 77}), ("way_in", {"type": "dig_way_in"}),
                      ("gate_jobs", {"type": "free_gate_jobs", "entrance_id": 2})):
        p, n = run(state([gate]), Memory(), [Proposal(rule, act, "theirs", 0)])
        assert mine(p) == [] and f"the {rule} rule acts on it" in n[0], (rule, p, n)
    p, _ = run(state([gate]), Memory())
    assert [x.action for x in mine(p)] == [{"type": "free_gate_jobs", "entrance_id": 2}]
    # a gate rule that acted lately (its cooldown's record) keeps the gates its own a while
    m = Memory()
    m.last_fired = {"gate_jobs": NOW - 3 * DAY}
    p, n = run(state([gate]), m)
    assert mine(p) == [] and "the gate_jobs rule acts on it" in n[0], n
    m.last_fired = {"gate_stuck:5": NOW - 20 * DAY}
    p, n = run(state([gate]), m)
    assert len(mine(p)) == 1
    sq = {"kind": "squad", "id": 40, "state": "kill_done", "since": NOW - 3 * DAY, "moved": NOW - 3 * DAY,
          "targets": 2, "dead": 2, "what": "The Axes"}
    p, n = run(state([sq]), Memory(), [Proposal("squad_recall", {"type": "squad_orders", "squad_id": 40,
                                                                  "clear": True}, "theirs", 1)])
    assert mine(p) == [], p
    p, n = run(state([sq]), Memory())
    assert [x.action for x in mine(p)] == [{"type": "squad_orders", "squad_id": 40, "clear": True}], p
    assert "2 dead" in p[0].reason
    p, _ = run(state([dict(sq, state="kill", live=1)]), Memory())
    assert mine(p) == []
    cis = {"kind": "cistern", "id": "cistern", "state": "linking", "since": NOW - 100 * DAY,
           "moved": NOW - 100 * DAY}
    p, _ = run(state([cis]), Memory(), [Proposal("cistern", {"type": "cistern_step", "retire": True}, "x", 4)])
    assert mine(p) == []


@test("brain: the cistern: its own rule's step is the nudge; then retired (its plain step left out that cycle); on hold: left")
def _():
    cis = {"kind": "cistern", "id": "cistern", "state": "linking", "since": NOW - 100 * DAY,
           "moved": NOW - 100 * DAY}
    m = Memory()
    plain = Proposal("cistern", {"type": "cistern_step"}, "the next step", 4)
    s = state([cis])
    p, n = run(s, m, [plain])
    assert mine(p) == [] and m.stuck_seen["items"]["cistern:cistern"]["step"] == 1 and "asked again" in n[0], n
    p, n = run(at(s, 15), m, [plain])
    assert [x.action.get("retire") for x in mine(p)] == [True] and plain not in p, p
    assert mine(p)[0].action["type"] == "cistern_step"
    cfg = dict(PLANNER_CONFIG, cistern_hold=True)
    props, notes = [], []
    PS._stuck_rule(s, Memory(), cfg, props, notes)
    assert props == [] and notes == []
    # a waterwork without its own step this cycle: the sweep asks it
    ww = {"kind": "waterwork", "id": "magma:MagmaForge", "state": "building", "since": NOW - 100 * DAY,
          "moved": NOW - 100 * DAY, "what": "magma", "shop": "MagmaForge"}
    p, _ = run(state([ww]), Memory())
    assert [x.action for x in mine(p)] == [{"type": "water_work", "kind": "magma", "shop": "MagmaForge"}], p


@test("brain: an AI order unmoved past 56 days is cancelled and booked stuck; the player's, repeating or unapproved: left")
def _():
    row = {"kind": "order", "id": 5, "state": "open", "progress": 3, "since": NOW - 60 * DAY,
           "moved": NOW - 60 * DAY, "left": 3, "total": 5, "what": "MakeCrafts"}
    o = {"id": 5, "recipe": "rock_crafts", "by_ai": True, "amount_left": 3, "validated": True}
    p, _ = run(state([row], orders=[o]), Memory())
    assert [x.action for x in mine(p)] == [{"type": "cancel_work_order", "order_id": 5, "stuck": "rock_crafts"}], p
    for bad in (dict(o, by_ai=False), dict(o, repeats=True), dict(o, validated=False)):
        p, n = run(state([row], orders=[bad]), Memory())
        assert mine(p) == [] and n == [], (bad, p)
    p, _ = run(state([dict(row, since=NOW - 30 * DAY, moved=NOW - 30 * DAY)], orders=[o]), Memory())
    assert mine(p) == []
    # a dwarf at work on it; the last slab while ghosts walk (the orders rule's own keep)
    p, n = run(state([row], orders=[dict(o, jobs={"working": 1})]), Memory())
    assert mine(p) == [] and n == []
    slab = dict(o, recipe="stone_slab")
    p, _ = run(state([row], orders=[slab], dead={"ghosts": 2}), Memory())
    assert mine(p) == []
    p, _ = run(state([row], orders=[slab], dead={"ghosts": 0, "unburied": 0}), Memory())
    assert len(mine(p)) == 1


@test("brain: the family's backoff: a retire doubles its timeout; past stuck_family_max a year: only said")
def _():
    m = Memory()
    sq = {"kind": "squad", "id": 40, "state": "kill_done", "since": NOW - 3 * DAY, "moved": NOW - 3 * DAY,
          "targets": 1, "gone": 1}
    s = state([sq])
    p, _ = run(s, m)
    done(mine(p), s, m)
    assert len(m.stuck_seen["families"]["squad:40"]) == 1
    # the same squad on a new dead order: 2 days now needed (x2), 1 is not enough
    s2 = state([dict(sq, state="kill_done", since=NOW + 5 * DAY, moved=NOW + 5 * DAY)])
    m.stuck_seen["items"]["squad:40"]["state"] = "kill"         # (it lived in between)
    p, _ = run(at(s2, 6), m)
    assert mine(p) == [], p
    p, _ = run(at(s2, 7), m)
    assert len(mine(p)) == 1
    m.stuck_seen["families"]["squad:40"] = [NOW, NOW, NOW]
    m.stuck_seen["items"].clear()
    p, n = run(at(s2, 40), m)
    assert mine(p) == [] and "3 like it retired this year already" in n[0], n


@test("brain: the sweep's limit a cycle, one note a thing, the notes capped; the soak count and past_count")
def _():
    rows = [dict(LEVER, id=i, key=f"lever:{i}") for i in range(1, 10)]
    m = Memory()
    p, n = run(state(rows), m)
    assert len(mine(p)) == PLANNER_CONFIG["stuck_sweep_actions_max"]
    assert len(n) == PLANNER_CONFIG["stuck_sweep_notes_max"] + 1 and "3 more thing(s)" in n[-1], n
    assert PS.soak_summary(m) == {"past": 9, "kinds": {"lever": 9}} and PS.past_count(m) == 9
    assert PS.soak_summary(Memory()) is None


@test("brain: plan() runs the sweep last; without the stuck section (the fixtures) nothing is said or proposed")
def _():
    s = state([LEVER])
    props, notes = plan(s, Memory())
    assert [x.action["type"] for x in props if x.rule == PS.STUCK_RULE] == ["stuck_reset"], [x.rule for x in props]
    base = normalize(json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8")))
    props, notes = plan(base, Memory())
    assert not [x for x in props if x.rule == PS.STUCK_RULE] and not [x for x in notes if x.startswith("stuck:")]
    for path in [ROOT / "tests" / "fixtures" / "test_fort.json"] + sorted((ROOT / "tests" / "fixtures" / "real").glob("*.json")):
        assert "stuck" not in json.loads(path.read_text(encoding="utf-8")), path.name


@test("brain: select lets two sweep actions through a cycle (several things), the memory field round-trips")
def _():
    from planner import select
    s = state([dict(LEVER, id=i, key=f"lever:{i}") for i in (1, 2)])
    m = Memory()
    p, _ = run(s, m)
    allowed, held = select(mine(p), s, m)
    assert len(allowed) == 2, held
    m2 = Memory.from_dict(json.loads(json.dumps(m.to_dict())))
    assert m2.stuck_seen == m.stuck_seen


@test("health_check: the stuck line from the latest soak row; flagged only when past in each of the last rows")
def _():
    import health_check as H
    f, lines = H.stuck_flags([])
    assert f == [] and "no count yet" in lines[0]
    rows = [{"fort": "a", "stuck": {"past": 2, "kinds": {"lever": 1, "project": 1}}}] * H.STUCK_ROWS
    f, lines = H.stuck_flags(rows)
    assert lines == ["stuck: 2 thing(s) past their timeout (lever 1, project 1)"] and len(f) == 1, (f, lines)
    rows2 = rows[:-1] + [{"fort": "a", "stuck": {"past": 0, "kinds": {}}}]
    f, lines = H.stuck_flags(rows2)
    assert f == [] and lines == ["stuck: 0 thing(s) past their timeout"]
    f, _ = H.stuck_flags(rows[:3])
    assert f == []
    # the fort played now only
    f, lines = H.stuck_flags(rows + [{"fort": "b", "stuck": {"past": 0, "kinds": {}}}])
    assert f == [] and "0 thing" in lines[0]


if LuaRuntime is None:
    finish("these tests need the lupa package (pip install lupa)")
finish()

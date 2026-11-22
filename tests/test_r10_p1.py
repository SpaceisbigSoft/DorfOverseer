"""(r10 p1, Phase 12b) Residency and citizenship petitions answered in game.

The cause (docs/dfhack-notes.md, "Petitions (r10)"): DFHack 53.17-r1 binds
DF's petition standing orders by the names standing_orders_petition_*, and
the win64 symbol tables list them under DF's own names
standingorder_petition_*, so on Windows the report read none (`orders: []`).
The bridge now binds DFHack's names to DF's addresses (guarded), so DF's own
standing orders answer the petitions; the AI's weighing sets them. Here:

  * the bridge: bound on a fake Windows (and left alone on Linux names, a
    far address, an odd byte); the orders set, a dry run changing nothing;
    nothing changed with DF's petitions screen open; residency agreed and
    declined, citizenship declined (agreeing it by the flag refused);
  * the planner: the orders set from the weighing, a refusal backed off, your
    change of an order left alone, nothing with the screen open or in danger,
    whether DF took the petitions that waited before recorded, citizenship
    declined (gone, vampire, closed);
  * the probe compiles and writes nothing.

    python tests/test_r10_p1.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import finish, make_test  # noqa: E402

from planner import PLANNER_CONFIG, Memory, NEEDS_YOU, Proposal, plan, record  # noqa: E402
import planner_visitors as V  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

CFG = PLANNER_CONFIG
DAY = 1200

# ---- the bridge, on a stub DFHack (as tests/test_bridge_memory.py) ---------------------------------

HARNESS = r"""
local src, lua_dir = ...
local H = {persist = {}, printed = nil}
local json = {decode = function() return H.action end, encode = function(t) H.printed = t; return 'json' end,
              decode_file = function() error('no file') end, encode_file = function() end}
local utils = {invert = function(t) local o = {}; for i, v in ipairs(t) do o[v] = i end; return o end}
local persistent = {getSiteData = function(k, d) local v = H.persist[k]; if v == nil then return d end; return v end,
                    saveSiteData = function(k, v) H.persist[k] = v end, deleteSiteData = function(k) H.persist[k] = nil end}
local dfhack = {getDFPath = function() return '/df' end, isMapLoaded = function() return true end,
                isWorldLoaded = function() return true end, world = {isFortressMode = function() return true end},
                persistent = persistent, filesystem = {mkdir_recursive = function() end},
                maps = {getTileSize = function() return 120, 120, 100 end}}
local df = {global = {cur_year = 150, cur_year_tick = 1000, pause_state = true,
  world = {cur_savegame = {save_dir = 'region1'}, map = {region_z = 140}},
  plotinfo = {site_id = 7, tasks = {wealth = {total = 1234}}, alerts = {civ_alert_idx = 0, list = {}}},
  game = {main_interface = {petitions = {open = false}}}}}
H.df, H.dfhack = df, dfhack
function H.module()
  local env = setmetatable({}, {__index = _G})
  env.dfhack, env.df = dfhack, df
  env.require = function(name) if name == 'json' then return json end if name == 'utils' then return utils end
    error('unexpected require ' .. name) end
  env.reqscript = function(name)
    if name == 'ai-status' then return {is_halted = function() return false end} end
    error('no ' .. name .. ' here')
  end
  env.dfhack_flags = {module = true}
  env.print = function() end
  assert(load(src, '@' .. lua_dir .. '/ai-bridge.lua', 't', env))()
  return env
end
return H
"""

# DF's memory for the six orders and the addresses DFHack's symbol table has;
# df.global's petition names read and write it only once bound (as DFHack:
# "global address not known" before).
WORLD = r"""
local M, df, dfhack, windows = ...
local W = {mem = {}, addr = {}, bound = {}, sets = 0}
local NAMES = {'performer', 'scholar', 'monster_hunter', 'mercenary', 'sanctuary', 'citizenship'}
local function dname(k) return k == 'citizenship' and 'standing_orders_petition_citizenship' or ('standing_orders_petition_resident_' .. k) end
local function sname(k) return k == 'citizenship' and 'standingorder_petition_citizenship' or ('standingorder_petition_resident_' .. k) end
W.addr['standing_orders_auto_collect_webs'] = 1000
for i, k in ipairs(NAMES) do
  local a = 1001 + i
  W.mem[a] = 0
  if windows then W.addr[sname(k)] = a else W.addr[dname(k)] = a; W.bound[dname(k)] = a end
end
W.dname, W.sname, W.NAMES = dname, sname, NAMES
dfhack.internal = {
  getAddress = function(n) local a = W.addr[n]; if a == 0 then return nil end; return a end,
  setAddress = function(n, a) W.sets = W.sets + 1; local old = W.addr[n]; W.addr[n] = a; W.bound[n] = (a ~= 0) and a or nil; return old end,
}
local known = {}
for _, k in ipairs(NAMES) do known[dname(k)] = true end
setmetatable(df.global, {
  __index = function(t, k)
    if known[k] then
      local a = W.bound[k]
      if not a then error('global address not known: ' .. k) end
      return W.mem[a]
    end
  end,
  __newindex = function(t, k, v)
    if known[k] then
      local a = W.bound[k]
      if not a then error('global address not known: ' .. k) end
      W.mem[a] = v
      return
    end
    rawset(t, k, v)
  end,
})
local function vec(items)
  local v = {n = #items}
  for i, x in ipairs(items) do v[i - 1] = x end
  v.erase = function(self, i)
    for k = i, self.n - 2 do self[k] = self[k + 1] end
    self[self.n - 1] = nil; self.n = self.n - 1
  end
  return setmetatable(v, {__len = function(self) return self.n end})
end
local _ipairs = ipairs
M.ipairs = function(t)
  if type(t) == 'table' and t.n ~= nil then
    return function(_, i) i = i + 1; if i < t.n then return i, t[i] end end, t, -1
  end
  return _ipairs(t)
end
local function enum(names) local e = {} for i, n in pairs(names) do e[i] = n; e[n] = i end return e end
df.agreement_details_type = enum({[0] = 'JoinParty', [1] = 'Location', [2] = 'Residency', [3] = 'Citizenship'})
df.abstract_building_type = enum({[0] = 'MEAD_HALL', [1] = 'TEMPLE', [2] = 'GUILDHALL'})
df.religious_practice_type = enum({[-1] = 'NONE', [0] = 'WORSHIP_HFID'})
df.history_event_reason = enum({[0] = 'none', [1] = 'entertain_people'})
local function agr(id, kind, data)
  return {id = id, flags = {petition_not_accepted = true}, parties = vec({}),
          details = vec({{type = kind, year = 150, year_tick = 0, data = data}})}
end
W.A = {[200] = agr(200, 2, {Residency = {applicant = 0, reason = 1}}),
       [201] = agr(201, 2, {Residency = {applicant = 0, reason = 1}}),
       [300] = agr(300, 3, {Citizenship = {applicant = 0}}),
       [301] = agr(301, 3, {Citizenship = {applicant = 0}}),
       [400] = agr(400, 1, {Location = {type = 1, tier = 1, deity_type = -1, deity_data = {}, profession = -1, site = 7}})}
df.agreement = {find = function(id) return W.A[id] end,
                get_vector = function() return vec({W.A[200], W.A[201], W.A[300], W.A[301], W.A[400]}) end}
df.historical_figure = {find = function() return nil end}
df.historical_entity = {find = function() return nil end}
dfhack.translation = {translateName = function(n) return n end}
df.global.plotinfo.petitions = vec({200, 201, 300, 301, 400})
function W.screen(open) df.global.game.main_interface.petitions.open = open end
function W.order(k) return W.mem[W.bound[dname(k)] or W.addr[sname(k)]] end
return W
"""

LUA = LuaRuntime(unpack_returned_tuples=True)
H = LUA.execute(HARNESS, (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8"), str(ROOT / "lua"))


def t(d):
    if isinstance(d, dict):
        return LUA.table_from({k: t(v) for k, v in d.items()})
    if isinstance(d, list):
        return LUA.table_from([t(v) for v in d])
    return d


def world(windows=True):
    M = H.module()
    W = LUA.execute(WORLD, M, H.df, H.dfhack, windows)
    return M, W


def waiting():
    pl = H.df["global"]["plotinfo"]["petitions"]
    return [pl[i] for i in range(pl.n)]


test = make_test()


@test("bridge: on Windows DF's own names are bound to DFHack's, and the report reads the six orders")
def _():
    M, W = world(windows=True)
    p = M.get_petitions()
    assert p.orders_via == "symbols" and p.orders_why is None, (p.orders_via, p.orders_why)
    assert dict(p.orders) == {k: 0 for k in V.PETITION_KINDS}, dict(p.orders)
    assert W.sets == 6
    M.get_petitions()                                   # once a session
    assert W.sets == 6
    M2 = H.module()                                     # the bridge loaded again: still DF's names, no new bind
    M2.PETITION_BIND = None
    via, why = M2.petition_orders_bind()
    assert via == "symbols" and why is None and W.sets == 6, (via, why)
    kinds = sorted(e.type for e in p.pending.values())
    assert kinds == ["Citizenship", "Citizenship", "Location", "Residency", "Residency"], kinds


@test("bridge: Linux (DFHack's names bound) is left alone; a far address or an odd byte binds nothing")
def _():
    M, W = world(windows=False)
    p = M.get_petitions()
    assert p.orders_via == "names" and W.sets == 0 and dict(p.orders)["citizenship"] == 0
    M, W = world(windows=True)
    W.addr[W.sname("citizenship")] = 5000               # not by the other standing orders
    p = M.get_petitions()
    assert p.orders_via is None and "not by the other standing orders" in p.orders_why and W.sets == 0
    assert len(list(p.orders.keys())) == 0               # nothing read, nothing to set
    r = M.ACTIONS.petition_orders(t({"orders": {"citizenship": 1}}))
    assert r.ok is False and r.rejected, dict(r)
    M, W = world(windows=True)
    W.mem[W.addr[W.sname("scholar")]] = 7               # a byte that is no 0/1 order
    p = M.get_petitions()
    assert p.orders_via is None and "unbound" in p.orders_why, p.orders_why
    assert len(list(p.orders.keys())) == 0 and not W.bound[W.dname("scholar")], dict(p.orders)


@test("bridge: approve and deny by DF's standing orders; a dry run changes nothing; never with the screen open")
def _():
    M, W = world(windows=True)
    act = M.ACTIONS.petition_orders
    d = act(t({"orders": {"citizenship": 1, "performer": 1}, "dry_run": True}))
    assert d.ok and d.dry_run and d.would_set.citizenship == 1 and d.via == "symbols", dict(d)
    assert W.order("citizenship") == 0 and W.order("performer") == 0
    W.screen(True)
    r = act(t({"orders": {"citizenship": 1, "performer": 1}}))
    assert r.ok is False and r.waiting and "petitions screen" in r.error, dict(r)
    assert W.order("citizenship") == 0 and W.order("performer") == 0
    W.screen(False)
    r = act(t({"orders": {"citizenship": 1, "performer": 1}}))
    assert r.ok and r.set.citizenship == 1 and W.order("citizenship") == 1 and W.order("performer") == 1, dict(r)
    r = act(t({"orders": {"citizenship": 0}}))           # denied from now on: back to ask
    assert r.ok and W.order("citizenship") == 0 and W.order("performer") == 1
    # the standing orders' Petitions tab open (DFHack's focus string): nothing set either
    H.dfhack["gui"] = LUA.eval("""{getDFViewscreen = function() return {} end,
        getFocusStrings = function() return {'dwarfmode/Info/LABOR/STANDING_ORDERS/PETITIONS'} end}""")
    r = act(t({"orders": {"scholar": 1}}))
    assert r.ok is False and r.waiting and "Petitions tab" in r.error and W.order("scholar") == 0, dict(r)
    H.dfhack["gui"] = None


@test("bridge: each kind answered on the waiting list: residency agreed and declined, citizenship declined only")
def _():
    M, W = world(windows=True)
    act = M.ACTIONS.answer_petition
    d = act(t({"id": 200, "accept": True, "dry_run": True}))
    assert d.ok and d.dry_run and d.kind == "Residency" and waiting() == [200, 201, 300, 301, 400]
    assert W.A[200].flags.petition_not_accepted is True
    W.screen(True)                                      # the player reading the petitions: hands off
    r = act(t({"id": 200, "accept": True}))
    assert r.ok is False and r.waiting and waiting() == [200, 201, 300, 301, 400], dict(r)
    W.screen(False)
    r = act(t({"id": 200, "accept": True}))
    assert r.ok and r.accepted and W.A[200].flags.petition_not_accepted is False and 200 not in waiting()
    r = act(t({"id": 201, "accept": False}))
    assert r.ok and r.declined and W.A[201].flags.petition_not_accepted is True and 201 not in waiting()
    r = act(t({"id": 300, "accept": True}))             # citizenship isn't agreed by the flag
    assert r.ok is False and r.rejected and "standing order" in r.error and 300 in waiting(), dict(r)
    d = act(t({"ids": t([300, 301]), "accept": False, "dry_run": True}))
    assert d.ok and d.answered == 2 and waiting() == [300, 301, 400], dict(d)
    r = act(t({"ids": t([300, 301]), "accept": False}))
    assert r.ok and r.answered == 2 and waiting() == [400], dict(r)
    assert W.A[300].flags.petition_not_accepted is True


@test("probe-petitions compiles under Lua 5.3, prints JSON and writes nothing (no setAddress, no assignment to df)")
def _():
    import re
    src = (ROOT / "lua" / "probes" / "probe-petitions.lua").read_text(encoding="utf-8")
    ok = LUA.eval("function(s) local f, e = load(s, 'probe', 't', {}); return f ~= nil, e end")(src)
    assert ok[0], ok[1]
    code = "\n".join(line.split("--")[0] for line in src.splitlines())
    assert "setAddress" not in code and "json.encode" in code
    assert not re.search(r"\bdf\.[\w.\[\]]+\s*=[^=]", code), "the probe assigns to df"
    assert not re.search(r"[:.](erase|insert|resize|assign|delete)\(", code.replace("table.insert(", ""))


@test("every changed Lua file compiles under Lua 5.3 and stays under 60 KB")
def _():
    chk = LUA.eval("function(src) local f, e = load(src, 'b', 't', {}); return f ~= nil, e end")
    for f in ("ai-bridge-report.lua", "ai-bridge-report-fort.lua", "ai-bridge-actions-civic.lua",
              "probes/probe-petitions.lua"):
        p = ROOT / "lua" / f
        ok = chk(p.read_text(encoding="utf-8"))
        assert ok[0], (f, ok[1])
        assert p.stat().st_size < 60000, (f, p.stat().st_size)


# ---- the planner ----------------------------------------------------------------------------------

def fort(outsiders=40, pending=None, orders=None, pop=30, **kw):
    s = {"settings": {"traits": {"outsiders": outsiders, "militarism": 10}, "accept_visitors": True},
         "dwarves": {"total": pop, "stress": {"content": pop}},
         "stocks": {"drink": 20 * pop, "prepared_meals": 30 * pop},
         "buildings": {"other": {"Bed": 40}},
         "locations": {"count": {"INN_TAVERN": 1, "LIBRARY": 1}},
         "others_on_map": {"threats": [], "threats_that_can_reach_dwarves": 0},
         "petitions": {"pending": pending or [], "residents": [],
                       "orders": {k: 0 for k in V.PETITION_KINDS} if orders is None else orders,
                       "orders_via": "symbols"},
         "date": {"year": 256, "tick": 1000}}
    s.update(kw)
    return s


def pet(i, kind="Residency", days=10, **kw):
    e = {"id": i, "type": kind, "name": f"Bard {i}", "days": days,
         "applicant": {"unit": 100 + i, "on_map": True, "hf": i}, **kw}
    if kind == "Residency":
        e.setdefault("reason", "entertain_people")
    return e


def run(rule, s, m, *extra):
    props, notes = [], []
    if rule is V._petition_rules:
        rule(s, CFG, props, notes, m)
    else:
        rule(s, m, CFG, props, notes)
    return props, notes


def tick(s, days):
    s = copy.deepcopy(s)
    s["date"]["tick"] += days * DAY
    return s


@test("planner: the weighing sets DF's orders (accept performers, scholars, citizenship under the target)")
def _():
    m = Memory()
    props, _ = run(V._petition_rules, fort(), m)
    assert len(props) == 1 and props[0].action["type"] == "petition_orders", props
    o = props[0].action["orders"]
    assert o["performer"] == 1 and o["scholar"] == 1 and o["citizenship"] == 1 and "mercenary" not in o, o
    # a closed fort asks about all (nothing to change from 0)
    props, _ = run(V._petition_rules, fort(outsiders=-60), m)
    assert not props, props
    # past the population target: citizenship back to ask
    s = fort(pop=400, orders=dict({k: 0 for k in V.PETITION_KINDS}, citizenship=1, performer=1, scholar=1,
                                  sanctuary=1, monster_hunter=1))
    props, _ = run(V._petition_rules, s, m)
    assert props and props[0].action["orders"] == {"citizenship": 0}, props


@test("planner: nothing with DF's petitions screen open or with threats that can reach the dwarves")
def _():
    m = Memory()
    for s in (fort(pending=[pet(1, days=40), pet(2, "Citizenship", days=40, vampire=True)]),):
        busy = copy.deepcopy(s)
        busy["petitions"]["screen_busy"] = "DF's petitions screen is open"
        danger = copy.deepcopy(s)
        danger["others_on_map"] = {"threats": [{"id": 9, "can_reach_dwarves": True}], "threats_that_can_reach_dwarves": 1}
        for st, word in ((busy, "petitions screen is open"), (danger, "threats")):
            notes = []
            for rule in (V._petition_rules, V._residency_rule, V._citizenship_rule):
                props, n = run(rule, st, m)
                assert not props, (word, rule.__name__, props)
                notes += n
            assert any(word in x for x in notes), (word, notes)
        # and the same fort answered once it is clear
        assert run(V._petition_rules, s, m)[0] and run(V._citizenship_rule, s, m)[0]


@test("planner: a refused order change is backed off (the general back-off), then tried again")
def _():
    from planner import select

    def chosen(st, mem):
        props, _ = plan(st, mem)
        allowed, held = select(props, st, mem)
        return [x for x in allowed if x.rule == "petitions"], held
    m = Memory()
    s = fort()
    p, _ = chosen(s, m)
    assert p, "nothing proposed"
    record([(p[0], {"ok": False, "rejected": True, "error": "standing order citizenship reads nil, not 0 or 1"})], s, m)
    p2, held = chosen(tick(s, 0), m)
    assert not p2 and any(h.startswith("petitions: the game refused it") for h in held), held
    assert chosen(tick(s, 3), m)[0], "never tried again"
    # the screen open (waiting): looked at again in two days, no back-off
    m2 = Memory()
    record([(p[0], {"ok": False, "waiting": True, "error": "DF's petitions screen is open: the orders are set later"})],
           s, m2)
    assert not chosen(tick(s, 1), m2)[0] and chosen(tick(s, 3), m2)[0]


@test("planner: an order you change after the AI set it is left alone a year; the switch off resets only the AI's")
def _():
    m = Memory()
    s = fort()
    props, _ = run(V._petition_rules, s, m)
    p = props[0]
    record([(p, {"ok": True, "set": p.action["orders"]})], s, m)
    assert m.petition_orders["set"]["citizenship"] == 1 and isinstance(m.petition_orders["at"]["citizenship"], int)
    after = fort(orders=dict({k: 0 for k in V.PETITION_KINDS}, **p.action["orders"]))
    after["petitions"]["orders"]["citizenship"] = 0           # you put it back to ask
    later = tick(after, 1)
    V.note_residency(later, m)
    assert "citizenship" in m.petition_orders["yours"] and "citizenship" not in m.petition_orders["set"]
    props, notes = run(V._petition_rules, later, m)
    assert not props and any("you changed DF's petition standing order for citizenship" in n for n in notes), notes
    props, _ = run(V._petition_rules, tick(later, CFG["r10p1_orders_yours_days"] + 1), m)
    assert props and props[0].action["orders"] == {"citizenship": 1}, props
    # the Rules switch "accept visitors" off: the AI's accepts back to ask, nothing else touched
    off = copy.deepcopy(later)
    off["settings"]["accept_visitors"] = False
    props, _ = run(V._petition_rules, off, m)
    assert props and props[0].action["orders"] == {"performer": 0, "scholar": 0, "sanctuary": 0,
                                                   "monster_hunter": 0}, props
    assert not run(V._petition_rules, off, Memory())[0]       # never set by the AI: never touched


@test("planner: whether DF's order took the petitions that waited before is recorded, and said")
def _():
    for taken in (True, False):
        m = Memory()
        old = [pet(1, "Citizenship", days=20), pet(2, "Citizenship", days=20)]
        s = fort(pending=old)
        props, _ = run(V._petition_rules, s, m)
        record([(props[0], {"ok": True, "set": props[0].action["orders"]})], s, m)
        assert m.petition_orders["before"]["citizenship"] == [1, 2]
        on = fort(pending=old, orders=dict({k: 0 for k in V.PETITION_KINDS}, **props[0].action["orders"]))
        notes = []
        V._citizenship_notes(on, CFG, old, notes, m)
        assert any("watches whether DF takes them" in n for n in notes) and not any(
            n.startswith(NEEDS_YOU) for n in notes), notes
        later = tick(on, CFG["r10p1_orders_sweep_days"])
        if taken:
            later["petitions"]["pending"] = []
        V.note_residency(later, m)
        assert m.petition_orders["swept"]["citizenship"] is taken and "citizenship" not in m.petition_orders["before"]
        if not taken:
            notes = []
            V._citizenship_notes(later, CFG, old, notes, m)
            assert any(n.startswith(NEEDS_YOU) and "petitions screen" in n and "left these" in n for n in notes), notes


@test("planner: citizenship declined when the visitor left, is a vampire, or the fort is closed; else left")
def _():
    m = Memory()
    gone = pet(1, "Citizenship", applicant={"unit": None, "on_map": False})
    vamp = pet(2, "Citizenship", vampire=True)
    fine = pet(3, "Citizenship")
    props, _ = run(V._citizenship_rule, fort(pending=[gone, vamp, fine]), m)
    assert len(props) == 1 and props[0].rule == "citizenship", props
    assert props[0].action == {"type": "answer_petition", "ids": [1, 2], "accept": False, "citizenship": True}
    props, _ = run(V._citizenship_rule, fort(outsiders=-60, pending=[fine]), m)
    assert props and props[0].action["ids"] == [3], props
    assert not run(V._citizenship_rule, fort(pending=[fine]), m)[0]          # wanted: DF's order or you
    old = pet(4, "Citizenship", days=CFG["h9_residency_player_days"])
    assert run(V._citizenship_rule, fort(pop=400, pending=[old]), m)[0]      # past the target, waited long
    assert not run(V._citizenship_rule, fort(pop=400, pending=[fine]), m)[0]
    # through plan(): the rule runs with the residency rule's
    rules = [p.rule for p in plan(fort(pending=[vamp]), Memory())[0]]
    assert "citizenship" in rules, rules
    from overseer_words import short
    assert short(props[0].action) == "decline 1 citizenship petition(s)", short(props[0].action)


@test("planner: residency agreed by DF's order; the words no longer blame DFHack when the orders are reached")
def _():
    m = Memory()
    s = fort(outsiders=60, pending=[pet(1, days=5)])
    props, notes = run(V._residency_rule, s, m)
    assert not props and any(n.startswith(NEEDS_YOU) and "take new ones as they come" in n for n in notes), notes
    s["petitions"]["orders"] = {}
    props, notes = run(V._residency_rule, s, m)
    assert any("DFHack can't reach" in n for n in notes), notes
    # a declined one (a vampire) still goes, by the bridge's answer_petition
    props, _ = run(V._residency_rule, fort(outsiders=60, pending=[pet(2, vampire=True)]), m)
    assert props and props[0].action["accept"] is False and props[0].action["ids"] == [2], props


@test("v12: a vampire's waiting petition holds its kind at ask (DF's order takes a whole kind)")
def _():
    m = Memory()
    props, notes = run(V._petition_rules, fort(pending=[pet(2, "Citizenship", days=5, vampire=True)]), m)
    for p in props:
        if p.action.get("type") == "petition_orders":
            assert p.action["orders"].get("citizenship") != 1, p.action
    assert any("whole kind" in n for n in notes), notes
    # an order already at accept is put back to ask while the vampire waits
    s = fort(pending=[pet(3, days=5, vampire=True)],
             orders=dict({k: 0 for k in V.PETITION_KINDS}, performer=1, scholar=1, sanctuary=1, citizenship=1))
    props, _ = run(V._petition_rules, s, m)
    kinds = {V.petition_kind(e) for e in s["petitions"]["pending"]}
    assert props and all(props[0].action["orders"].get(k) == 0 for k in kinds), props


if __name__ == "__main__":
    finish()

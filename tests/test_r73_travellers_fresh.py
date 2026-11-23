"""(0.105.73) The travellers' way out never judged blocked from a stale cache.

Live 22 Nov 21:42 on A (War-hold): the planner's notes said "N traveller(s)
can't walk off the map and none of the AI's gates holds the way" for the Make
contact messenger and every raid squad. The same state.json read
`way_out: {open: true, fresh: true, inside_group: 5287, in_group: 68 of 68}`
but `missions.way_out: {messenger_blocked: true, shut: [], squads: {184: 10,
201: 9, 204: 9, 206: 9, 211: 5}}`: every soldier and the messenger "blocked"
while they stood in the citizens' own group, which reaches the map edge. The
`missions` section is rebuilt once a game day from ai-way-out's cached edge
groups, and DF renumbers its walk groups as the map changes (0.105.51's case,
which fixed only the fort-wide check).

Tested here:
  * ai-way-out edge_groups_fresh: re-reads unless already read this tick;
  * ai-mission-way: a traveller who'd read blocked from the cache makes one
    fresh read; renumbered groups read open; one truly cut off still reads
    blocked; no re-read when everyone reads open from the cache;
  * ai-recovery: a caravan's merchants likewise.

    python tests/test_r73_travellers_fresh.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None


def need_lua():
    if LuaRuntime is None:
        skip("needs the lupa package")


# ai-way-out with a fake map: the border tiles in group EDGE_G, the rest INSIDE
WAYOUT_FAKE = r"""
local src = ...
EDGE_G, INSIDE, READS = 5100, 5100, 0
G = {IMMINENT = 12, WIDE = 60}
G.GATES = {scanned = true, closed = {}, entrances = {{id = 1, kind = 'surface', x = 5, y = 1, z = 2,
                                                       equipment = {}, outer = {}}}}
U = {REPATH = {n = 0}, repath_summary = function() return {n = 0} end, citizens = function() return {} end}
reqscript = function(n)
  if n == 'ai-gates' then return G end
  if n == 'ai-util' then return U end
  error('reqscript ' .. tostring(n))
end
df = {global = {world = {map = {x_count = 10, y_count = 10, z_count = 5}}, plotinfo = {site_id = 1},
                cur_year = 253, cur_year_tick = 100}}
dfhack = {maps = {}}
xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-way-out', 't', env))()
env.group_at = function(x, y, z)
  if x == 0 and y == 0 and z == 0 then READS = READS + 1 end
  if x == 0 or y == 0 or x == 9 or y == 9 then return EDGE_G end
  return INSIDE
end
return env
"""


def wayout():
    need_lua()
    L = LuaRuntime(unpack_returned_tuples=True)
    return L, L.execute(WAYOUT_FAKE, module_src("ai-way-out.lua"))


@test("ai-way-out: edge_groups_fresh re-reads the edges unless they were read this game tick")
def _():
    L, env = wayout()
    g = env.edge_groups()
    assert g[5100] is True and L.eval("READS") == 1
    assert env.edge_groups()[5100] is True and L.eval("READS") == 1      # the cache
    g = env.edge_groups_fresh()                                          # same tick: the same read
    assert L.eval("READS") == 1
    L.execute("df.global.cur_year_tick = 101; EDGE_G = 5287")
    g = env.edge_groups_fresh()
    assert L.eval("READS") == 2 and g[5287] is True and g[5100] is None


# ai-mission-way over a fake ai-way-out whose cache can be stale
MW_FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local W = {cached = {[5100] = true}, live = {[5287] = true}, fresh_reads = 0}
env.reqscript = function(name)
  if name == 'ai-way-out' then
    return {edge_groups = function() return W.cached end,
            edge_groups_fresh = function() W.fresh_reads = W.fresh_reads + 1; W.cached = W.live; return W.live end}
  end
  if name == 'ai-gates' then return {GATES = {scanned = true, closed = {}, entrances = {}}} end
  if name == 'ai-util' then return {abs_tick = function() return 1000 end} end
  error(name)
end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
-- unit 99 stands cut off (group 6000); every other unit in the citizens' group 5287
env.dfhack = {maps = {getWalkableGroup = function(p) return p.x == 99 and 6000 or 5287 end}}
env.df = {unit = {find = function(id)
  return {pos = {x = id == 99 and 99 or 100, y = 159, z = 166}, flags1 = {inactive = false}, flags2 = {killed = false}}
end}}
assert(load(src, 'ai-mission-way', 't', env))()
return env, W
"""


def mission_way():
    need_lua()
    L = LuaRuntime(unpack_returned_tuples=True)
    env, W = L.execute(MW_FAKE, module_src("ai-mission-way.lua"))
    return L, env, W


@test("ai-mission-way report: A's 22 Nov state (renumbered groups, the cache stale): the messenger and "
      "five squads read free after one fresh read, not blocked")
def _():
    L, env, W = mission_way()
    squads = L.eval("""{ {id = 184, units = {1,2,3,4,5,6,7,8,9,10}}, {id = 201, units = {11,12,13}},
                         {id = 211, units = {21,22,23,24,25}} }""")
    r = env.report(squads, 18237)
    assert r.known is True and r.messenger_blocked is False, r.messenger_blocked
    assert r.squads["184"] == 0 and r.squads["201"] == 0 and r.squads["211"] == 0
    assert W.fresh_reads == 1
    # everyone free from the cache now: no further read
    env.report(squads, 18237)
    assert W.fresh_reads == 1


@test("ai-mission-way: one truly cut off still reads blocked after the fresh read; the rest free")
def _():
    L, env, W = mission_way()
    r = env.way(L.table_from([18237, 99]))
    assert r.known is True and r.n == 2 and list(r.blocked.values()) == [99], list(r.blocked.values())
    assert W.fresh_reads == 1
    r = env.report(L.eval("{ {id = 7, units = {99, 1}} }"), 99)
    assert r.messenger_blocked is True and r.squads["7"] == 1


@test("ai-mission-way: groups_for (pure) re-reads only for a would-be-blocked traveller; no cache: the fresh read")
def _():
    L, env, W = mission_way()
    calls = []
    L.globals().CALLS = 0
    fresh = L.eval("function() CALLS = CALLS + 1; return {[2] = true} end")
    at = L.eval("function(x, y, z) return x end")
    units = L.eval("{ {id = 1, x = 1, y = 0, z = 0} }")
    g = env.groups_for(units, L.eval("{[1] = true}"), fresh, at)
    assert g[1] is True and L.globals().CALLS == 0
    units = L.eval("{ {id = 1, x = 1, y = 0, z = 0}, {id = 2, x = 2, y = 0, z = 0} }")
    g = env.groups_for(units, L.eval("{[1] = true}"), fresh, at)
    assert g[2] is True and L.globals().CALLS == 1
    g = env.groups_for(units, None, fresh, at)
    assert g[2] is True and L.globals().CALLS == 2


CARAVAN_FAKE = r"""
local src = ...
local W = {fresh_reads = 0}
local env = setmetatable({}, {__index = _G})
local function unit(id, civ, x, grp)
  return {id = id, civ_id = civ, pos = {x = x, y = 0, z = 0, grp = grp},
          flags1 = {merchant = true, left = false, inactive = false, forest = false}, animal = {leave_countdown = 0}}
end
W.u1, W.u2 = unit(1, 308, 1, 5287), unit(2, 308, 2, 5287)
env.df = {global = {timed_events = {}, plotinfo = {civ_id = 308,
            caravans = {{entity = 308, trade_state = 3, time_remaining = 0, flags = {tribute = false}}}},
                    world = {units = {active = {W.u1, W.u2}}}},
          caravan_state = {T_trade_state = {[1] = 'Approaching', [2] = 'AtDepot', [3] = 'Leaving'}},
          timed_event_type = {Migrants = 2},
          historical_entity = {find = function(id) return {id = id} end}}
env.dfhack = {findScript = function(n) return n == 'force' and 'x' or nil end,
              units = {isDead = function() return false end},
              maps = {getWalkableGroup = function(p) return p.grp end}}
env.reqscript = function(name)
    if name == 'ai-way-out' then
      return {edge_groups = function() return {[5100] = true} end,
              edge_groups_fresh = function() W.fresh_reads = W.fresh_reads + 1; return {[5287] = true} end}
    end
    error('no module ' .. tostring(name))
end
assert(load(src, 'ai-recovery', 't', env))()
return env, W
"""


@test("ai-recovery: a leaving caravan's merchants read 'can leave' after a fresh read of renumbered groups; "
      "free_caravan tells them both")
def _():
    need_lua()
    L = LuaRuntime(unpack_returned_tuples=True)
    env, w = L.execute(CARAVAN_FAKE, module_src("ai-recovery.lua"))
    c = list(env.report().caravans.values())[0]
    assert c.can_leave == 2 and w.fresh_reads == 1, (c.can_leave, w.fresh_reads)
    d = env.free_caravan(308, True)
    assert d.ok and d.told == 2 and not d.shut, dict(d)


if __name__ == "__main__":
    finish()

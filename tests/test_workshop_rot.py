"""(0.105.85) Rotting leftovers in a workshop go to the dump: ai-syndromes'
keep_rotting no longer keeps a thing a workshop holds outside any job as
'held' (F, 23 Nov: 280 corpse pieces and rotten meat in the butcher's, the
one refuse pile full, miasma for 82 citizens); a body for the butcher, one
in a job, one loose elsewhere keep their old answers.

    python tests/test_workshop_rot.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402

FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local U = {
    fort_remains = function() return false end,
    on_ground = function(it) return it.flags.on_ground == true end,
    near_danger = function() return false end,
    forbidden_reason = function() return nil end,
    item_kind = function(it) return it.kind end,
}
env.reqscript = function(n) if n == 'ai-util' then return U end return setmetatable({}, {__index = function() return function() end end}) end
env.require = function() return {} end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {building_type = {Workshop = 'Workshop', Stockpile = 'Stockpile', Civzone = 'Civzone'},
          global = {world = {buildings = {all = {}}}}}
env.dfhack = {
    items = {getHolderBuilding = function(it) return it.holder end},
    maps = {getTileFlags = function() return {} end, getWalkableGroup = function() return 1 end},
    buildings = {findAtTile = function() return nil end},
}
assert(load(src, 'ai-syndromes', 't', env))()
local shop = {getType = function() return 'Workshop' end}
local bin = {getType = function() return 'Coffin' end}
local function e(kind, flags, holder)
    return {it = {kind = kind, flags = flags or {}, holder = holder, corpse_flags = {unbutchered = false}},
            kind = kind, x = 126, y = 154, z = 169}
end
local ctx = {danger = {}, groups = nil, butcher = true}
return {
    piece = env.keep_rotting(e('CORPSEPIECE', {}, shop), ctx, {}),
    meat = env.keep_rotting(e('MEAT', {rotten = true}, shop), ctx, {}),
    job = env.keep_rotting(e('CORPSEPIECE', {in_job = true}, shop), ctx, {}),
    other = env.keep_rotting(e('CORPSEPIECE', {}, bin), ctx, {}),
    carried = env.keep_rotting(e('CORPSEPIECE', {}, nil), ctx, {}),
    loose = env.keep_rotting(e('CORPSEPIECE', {on_ground = true}, nil), ctx, {}),
}
"""


@test("keep_rotting: a workshop's leftovers (not in a job) may go to the dump; in a job, another building's, carried: kept")
def _():
    if not need_lua():
        return
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    src = (ROOT / "lua" / "ai-syndromes.lua").read_text(encoding="utf-8")
    r = lua.execute(FAKE, src)
    got = {k: r[k] for k in ("piece", "meat", "job", "other", "carried", "loose")}
    assert got["piece"] is None and got["meat"] is None, got
    assert got["job"] == "in_job" and got["other"] == "held" and got["carried"] == "held", got
    assert got["loose"] is None, got


if __name__ == "__main__":
    finish()

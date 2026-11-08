"""(0.105.24) Tests for lua/ai-moods.lua: a strange mood's requests, what the
fort holds for each (free within reach, forbidden, held by a job), cloth by
its dimension, and freeing forbidden materials; in a real Lua engine with a
stub DFHack (pip install lupa).

    python tests/test_moods.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from lua_modules_util import module_src  # (13c lua-modules) the modules' sources, with lua/ai-util.lua
from harness import test, finish, code_has  # noqa: E402

try:
    from lupa import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)


SRC = module_src("ai-moods.lua")

# A fake world: item types by name, a job with requests (0-based vectors),
# items with flags, positions (x < 100 within the dwarf's walk), material
# kinds ('silk', 'yarn', 'plant', 'gem', 'bone', 'iron').
FAKE = r"""
local src = ...
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    return t
end
local W = {items = {}, units = {}}
local env = setmetatable({}, {__index = _G})
env.ipairs = function(t)
    if type(t) == 'table' and (rawget(t, 0) ~= nil or next(t) == nil) then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return ipairs(t)
end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
local TYPES = {[-1] = 'NONE', [1] = 'CLOTH', [2] = 'ROUGH', [3] = 'CORPSEPIECE', [4] = 'BAR', [5] = 'SKIN_TANNED'}
local item_type = {}
for k, v in pairs(TYPES) do item_type[k] = v; item_type[v] = k end
local other = {}
local other_id = {IN_PLAY = 'IN_PLAY', CLOTH = 'CLOTH', ROUGH = 'ROUGH', CORPSEPIECE = 'CORPSEPIECE',
                  BAR = 'BAR', SKIN_TANNED = 'SKIN_TANNED'}
env.df = {item_type = item_type, items_other_id = other_id,
          global = {cur_year = 100, cur_year_tick = 1000, world = {items = {other = other}}},
          unit = {find = function(id) return W.units[id] end}}
env.dfhack = {
    matinfo = {decode = function(t, i) return {toString = function() return t == 0 and i < 0 and 'rock' or 'iron' end} end},
    job = {
        isSuitableItem = function(ji, t, st) return ji.item_type == -1 or ji.item_type == t end,
        isSuitableMaterial = function(ji, mt, mi, t) return ji.kind == nil or ji.kind == mi end,
    },
    items = {getPosition = function(it) return it.x, 1, 1 end,
             getReadableDescription = function(it) return it.name or 'item' end},
    maps = {canWalkBetween = function(a, b) return b.x < 100 end},
}
function W.reset()
    for k in pairs(other) do other[k] = nil end
    for k in pairs(other_id) do other[k] = vec({}) end
    W.items, W.units = {}, {}
    env.AVAIL_CACHE = {}
end
-- item(type, kind, x, flags, stack, dim)
function W.item(t, kind, x, flags, stack, dim)
    local it = {id = #W.items + 1, flags = flags or {}, x = x or 1, name = kind .. ' ' .. TYPES[t]:lower()}
    it.getType = function() return t end
    it.getSubtype = function() return -1 end
    it.getMaterial = function() return 0 end
    it.getMaterialIndex = function() return kind end
    it.getStackSize = function() return stack or 1 end
    it.getTotalDimension = function() return dim or 10000 end
    local l = other[TYPES[t]]
    l[W.items_of(TYPES[t])] = it
    local all = other.IN_PLAY
    all[W.items_of("IN_PLAY")] = it
    table.insert(W.items, it)
    return it
end
function W.items_of(name)
    local n = 0
    while other[name][n] ~= nil do n = n + 1 end
    return n
end
-- a mood job: reqs {{item_type, kind, quantity, flags...}}, fetched {{idx, item}}
function W.job(reqs, fetched)
    local jis = {}
    for _, r in ipairs(reqs) do
        local f2 = {}
        for _, f in ipairs(r.flags or {}) do f2[f] = true end
        table.insert(jis, {item_type = r.t, kind = r.kind, quantity = r.q, mat_type = r.mt or -1, mat_index = -1,
                           flags1 = {}, flags2 = f2, flags3 = {}})
    end
    local refs = {}
    for _, f in ipairs(fetched or {}) do table.insert(refs, {job_item_idx = f[1], item = f[2]}) end
    return {job_items = vec(jis), items = vec(refs)}
end
function W.unit(id, job)
    local u = {id = id, mood = 2, pos = {x = 1, y = 1, z = 1}, job = {current_job = job}}
    W.units[id] = u
    return u
end
W.reset()
assert(load(src, 'ai-moods', 't', env))()
W.env = env
return W
"""

LUA = LuaRuntime(unpack_returned_tuples=True)
W = LUA.execute(FAKE, SRC)
M = W.env
CLOTH, ROUGH, CORPSE, BAR, LEATHER, NONE = 1, 2, 3, 4, 5, -1


def t(x):
    if isinstance(x, dict):
        return LUA.table_from({k: t(v) for k, v in x.items()})
    if isinstance(x, list):
        return LUA.table_from([t(v) for v in x])
    return x


def job(reqs, fetched=None):
    return W.job(t(reqs), t(fetched or []))


@test("cloth by its dimension: one whole cloth fetched meets a 10000 request; 30000 asks 3 cloths")
def _():
    W.reset()
    have = W.item(CLOTH, "silk", 1, t({"in_job": True}), 1, 10000)
    j = job([{"t": CLOTH, "kind": "silk", "q": 10000, "flags": ["silk"]},
             {"t": CLOTH, "kind": "yarn", "q": 30000, "flags": ["yarn"]}], [[0, have]])
    miss = M.requests_missing(j)
    assert len(miss) == 1, [dict(m) for m in miss.values()]          # the silk is met (was "9999 cloths")
    assert miss[1].index == 1 and miss[1].quantity == 3 and miss[1].item == "CLOTH"
    assert list(miss[1].flags.values()) == ["yarn"]


@test("rough gem, any stone: no 'of rock' material; bars of a metal keep theirs; the order is the mood's")
def _():
    W.reset()
    j = job([{"t": ROUGH, "q": 1, "mt": 0}, {"t": BAR, "q": 2, "mt": 0, "kind": "iron"}])
    j.job_items[1].mat_index = 7
    miss = M.requests_missing(j)
    assert miss[1].material is None and miss[1].index == 0
    assert miss[2].material == "iron" and miss[2].quantity == 2


@test("avail: free within reach, beyond reach, forbidden, held by a job, a trader's; the walk stops once enough")
def _():
    W.reset()
    W.item(ROUGH, "gem", 1, t({"in_job": True}))
    W.item(ROUGH, "gem", 150)                                      # free, beyond the dwarf's walk
    W.item(ROUGH, "gem", 2, t({"forbid": True}))
    W.item(ROUGH, "gem", 3, t({"trader": True}))
    W.item(CLOTH, "silk", 4)                                       # another type: never counted
    j = job([{"t": ROUGH, "kind": "gem", "q": 1}])
    u = W.unit(5, j)
    miss = M.mood_report(j, u)
    a = miss[1].avail
    assert (a.free, a.reach, a.forbidden, a.forbidden_reach, a.job, a.other) == (1, 0, 1, 1, 1, 1), dict(a)
    assert not a.enough
    W.item(ROUGH, "gem", 4)                                        # one free within reach
    M.AVAIL_CACHE = LUA.table_from({})
    a = M.mood_report(j, u)[1].avail
    assert a.reach == 1 and a.enough, dict(a)


@test("avail: what the mood has fetched itself is not 'held by another job'")
def _():
    W.reset()
    own = W.item(ROUGH, "gem", 1, t({"in_job": True}))
    j = job([{"t": ROUGH, "kind": "gem", "q": 2}], [[0, own]])
    u = W.unit(9, j)
    a = M.mood_report(j, u)[1].avail
    assert a.job == 0, dict(a)
    W.item(ROUGH, "gem", 1, t({"in_job": True}))
    M.AVAIL_CACHE = LUA.table_from({})
    assert M.mood_report(j, u)[1].avail.job == 1


@test("avail is kept half a day (the moods are in every pulse); a bone request looks among the corpse pieces")
def _():
    W.reset()
    j = job([{"t": NONE, "kind": "bone", "q": 1, "flags": ["bone"]}])
    u = W.unit(6, j)
    assert list(M.search_lists("NONE", t(["bone"])).values()) == ["CORPSEPIECE"]
    assert list(M.search_lists("NONE", t([])).values()) == ["IN_PLAY"]
    a = M.mood_report(j, u)[1].avail
    assert a.reach == 0
    W.item(CORPSE, "bone", 1)
    assert M.mood_report(j, u)[1].avail.reach == 0                # cached
    M.df["global"].cur_year_tick = M.df["global"].cur_year_tick + 700
    assert M.mood_report(j, u)[1].avail.reach == 1                # half a day on: counted again


@test("free_items: forbidden and dumped items within reach unforbidden, as many as the mood lacks; nothing else touched")
def _():
    W.reset()
    f1 = W.item(LEATHER, "hide", 1, t({"forbid": True}))
    f2 = W.item(LEATHER, "hide", 2, t({"dump": True}))
    f3 = W.item(LEATHER, "hide", 3, t({"forbid": True}))
    far = W.item(LEATHER, "hide", 150, t({"forbid": True}))
    held = W.item(LEATHER, "hide", 4, t({"forbid": True, "in_job": True}))
    j = job([{"t": LEATHER, "kind": "hide", "q": 2}])
    W.unit(7, j)
    r = M.free_items(7, True, 10)
    assert r.ok and r.freed == 2 and r.dry_run and f1.flags.forbid, dict(r)     # a dry run changes nothing
    r = M.free_items(7, False, 10)
    assert r.ok and r.freed == 2, dict(r)
    assert not f1.flags.forbid and not f2.flags.dump and f3.flags.forbid       # only what it lacks
    assert far.flags.forbid and held.flags.forbid
    r = M.free_items(7, False, 10)                                 # enough free within reach now
    assert not r.ok and r.rejected, dict(r)
    assert M.free_items(99, False, 10).rejected                    # no such unit
    W.unit(8, None)
    assert M.free_items(8, False, 10).rejected                     # no mood job


@test("bridge: mood_free_items is in the action table, bounded, passed to ai-moods; get_moods asks ai-moods first")
def _():
    src = "".join(f.read_text(encoding="utf-8") for f in sorted((ROOT / "lua").glob("ai-bridge*.lua")))   # (13c) with its parts
    assert code_has(src, "    mood_free_items = act_mood_free_items,")
    assert code_has(src, "CACHE_INVALIDATES.mood_free_items = {'moods'}")
    assert code_has(src, "pcall(M.mood_report, job, u, txt)")
    assert code_has(src, "tan_hide = {job = 'CustomReaction', reaction = 'TAN_A_HIDE'}") and code_has(src, "raw_green_glass = {job = 'MakeRawGlass'")
    body = src[src.index("function act_mood_free_items"):]
    body = body[:body.index("\nend\n") + 5]
    L = LuaRuntime(unpack_returned_tuples=True)
    f = L.execute(r"""
      local body = ...
      local CALLS = {}
      local env = setmetatable({CALLS = CALLS}, {__index = _G})
      env.reject = function(r) return {ok = false, rejected = true, error = r} end
      env.int_in = function(v, lo, hi) v = tonumber(v); if v and v >= lo and v <= hi and v == math.floor(v) then return v end end
      env.txt = tostring
      env.reqscript = function(n) assert(n == 'ai-moods'); return {free_items = function(id, dry, max)
          table.insert(CALLS, {id, dry, max}); return {ok = true} end} end
      assert(load(body, 'b', 't', env))()
      return env
    """, body)
    assert f.act_mood_free_items(L.table_from({"unit_id": 12})).ok
    assert (f.CALLS[1][1], f.CALLS[1][2], f.CALLS[1][3]) == (12, False, 10)
    assert f.act_mood_free_items(L.table_from({"unit_id": 12, "max": 3, "dry_run": True})).ok
    assert (f.CALLS[2][2], f.CALLS[2][3]) == (True, 3)
    assert f.act_mood_free_items(L.table_from({})).rejected
    assert f.act_mood_free_items(L.table_from({"unit_id": 12, "max": 11})).rejected


if __name__ == "__main__":
    finish()

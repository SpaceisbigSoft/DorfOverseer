"""(0.105.41, item 2) Wheelbarrows and feeder links: lua/ai-pile-links.lua in
a fake fort (the report's wheelbarrows, the AI's stone piles and feeders;
set_barrows on the AI's piles only; link_feeder linking an AI feeder to an
AI workshop, links only from the AI's bigger pile, unlinking for good; the
player's piles and workshops left alone), the bridge's wiring, the Rules
switch, and the brain (brain/planner_piles.py: barrows set, wheelbarrows
ordered, feeders linked and unlinked, the digest line).

    python tests/test_r41_pile_links.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish, code_has  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
from planner_core import player_rules, Proposal  # noqa: E402
import planner_piles as PP  # noqa: E402
import digest  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
CFG = PLANNER_CONFIG

# A fort level at z 100. Stockpiles: W.pile{...} (a stone pile unless flags
# given; links and storage as df vectors, 0-based); workshops: W.shop{...}
# (3x3, a profile with links); wheelbarrows: W.barrow{...}. The AI's levels:
# W.areas; the food store's own corners and ids: W.food_corners, W.food_ids.
FAKE = r"""
local src = ...
local W = {piles = {}, shops = {}, site = {}, used = {}, tools = {}, areas = {}, food_corners = {}, food_ids = {},
           next_id = 500, now = 1200 * 100}
local env = setmetatable({}, {__index = _G})
local function key(x, y, z) return x .. ',' .. y .. ',' .. z end
-- a df vector: 0-based, # its length, insert(at, v), erase(at)
function W.vec(list)
    local data = {}
    for i, v in ipairs(list or {}) do data[i] = v end
    local v = {data = data}
    function v:insert(at, x) table.insert(self.data, at + 1, x) end
    function v:erase(at) table.remove(self.data, at + 1) end
    return setmetatable(v, {__len = function(self) return #self.data end,
                             __index = function(self, i) if type(i) == 'number' then return rawget(self, 'data')[i + 1] end end})
end
function W.list(vec) local out = {} for i, x in ipairs(vec.data) do out[i] = x.id or x end return out end
function W.pile(t)
    t.id = t.id or W.next_id; W.next_id = W.next_id + 1
    t.z = t.z or 100
    t.settings = t.settings or {flags = {stone = t.stone ~= false, wood = t.wood == true}}
    t.storage = {max_wheelbarrows = t.barrows or 0, container_item_id = W.vec(t.held or {})}
    t.links = {give_to_pile = W.vec(), take_from_pile = W.vec(), give_to_workshop = W.vec(), take_from_workshop = W.vec()}
    t.stockpile_flag = {use_links_only = false}
    table.insert(W.piles, t)
    return t
end
function W.shop(t)
    t.id = t.id or W.next_id; W.next_id = W.next_id + 1
    t.z = t.z or 100
    t.x2, t.y2 = t.x1 + 2, t.y1 + 2
    t.centerx, t.centery = t.x1 + 1, t.y1 + 1
    t.btype = t.btype or 'Workshop'
    t.getType = function(self) return self.btype end
    t.profile = {links = {take_from_pile = W.vec(), give_to_pile = W.vec()}}
    t.jobs = t.jobs or {}
    table.insert(W.shops, t)
    return t
end
function W.barrow(t)
    t.id = t.id or W.next_id; W.next_id = W.next_id + 1
    t.subtype = {id = t.sub or 'ITEM_TOOL_WHEELBARROW'}
    t.flags = t.flags or {}
    table.insert(W.tools, t)
    return t
end
local function in_pile(x, y, z)
    for _, p in ipairs(W.piles) do
        if p.z == z and x >= p.x1 and x <= p.x2 and y >= p.y1 and y <= p.y2 then return p end
    end
end
local function find(id)
    for _, p in ipairs(W.piles) do if p.id == id then return p end end
    for _, b in ipairs(W.shops) do if b.id == id then return b end end
end
function W.remove(id)
    for i, p in ipairs(W.piles) do if p.id == id then table.remove(W.piles, i) return end end
end
env.df = {
    global = {world = {buildings = {other = {STOCKPILE = W.piles}}, items = {other = {TOOL = W.tools}},
                       map = {region_z = 100}}},
    building = {find = find},
    building_type = {Workshop = 'Workshop', Furnace = 'Furnace'},
    workshop_type = setmetatable({}, {__index = function(_, k) return k end}),
    furnace_type = setmetatable({}, {__index = function(_, k) return k end}),
}
env.dfhack = {
    maps = {getTileFlags = function(x, y, z)
        return {pile = in_pile(x, y, z) ~= nil}, {item = W.used[key(x, y, z)] == true}
    end},
    job = {getWorker = function(j) return j.worker end},
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
}
assert(load(src, 'ai-pile-links', 't', env))()
env.ai_areas = function() return W.areas end
env.now_tick = function() return W.now end
env.food_store = function()
    return {own_corners = function() return W.food_corners end, own_ids = function() return W.food_ids end}
end
return env, W
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-pile-links.lua"))
    return lua, env, w


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


def py(v):
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    try:
        keys = list(v.keys())
    except AttributeError:
        return v
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in sorted(keys)]
    return {k: py(v[k]) for k in keys}


def ids(w, vec):
    return py(w.list(vec)) or []


def ai_masons(lua, env, w, used=True, kind="Masons"):
    """An AI workshop level with a Masons and its feeder (booked as place_feeder does)."""
    w.areas = T(lua, [{"x1": 0, "y1": 0, "x2": 59, "y2": 59, "z": 100}])
    shop = w.shop(T(lua, {"type": kind, "x1": 20, "y1": 20}))
    pile = w.pile(T(lua, {"x1": 25, "y1": 20, "x2": 27, "y2": 22}))
    env.remember_feeder(25, 20, 100, shop.id, kind, "stone")
    if used:
        w.used["25,20,100"] = True
    return shop, pile


# --- 1. the report -----------------------------------------------------------------------

if LuaRuntime is not None:
    @test("report: wheelbarrows owned, held by a pile, in a job, free, wanted by every pile and the AI's own; "
          "forbidden and other tools not counted")
    def _():
        lua, env, w = world()
        b1, b2, b3 = w.barrow(T(lua, {})), w.barrow(T(lua, {})), w.barrow(T(lua, {"flags": {"in_job": True}}))
        w.barrow(T(lua, {"flags": {"forbid": True}}))
        w.barrow(T(lua, {"sub": "ITEM_TOOL_LARGE_POT"}))
        w.barrow(T(lua, {}))
        mine = w.pile(T(lua, {"x1": 10, "y1": 10, "x2": 14, "y2": 14, "barrows": 2, "held": [b1.id]}))
        w.pile(T(lua, {"x1": 30, "y1": 30, "x2": 31, "y2": 31, "barrows": 1, "held": [b2.id]}))   # the player's
        w.food_corners = T(lua, {"10,10,100": True})
        r = py(env.report())
        assert r["barrows"] == {"owned": 4, "assigned": 2, "free": 1, "in_job": 1, "wanted": 3, "ai_wanted": 2}, r
        assert [p["id"] for p in r["stone_piles"]] == [mine.id], r["stone_piles"]
        p = r["stone_piles"][0]
        assert (p["tiles"], p["barrows"], p["held"]) == (25, 2, 1), p
        assert r["feeders"] == [] or r["feeders"] == {} and r["unlinked"] == 0

    @test("report: an AI feeder beside an AI Masons: unlinked, may link, its bigger AI pile named as main; "
          "the player's workshop, a many-material one, a player-linked one each say why")
    def _():
        lua, env, w = world()
        shop, pile = ai_masons(lua, env, w)
        main = w.pile(T(lua, {"x1": 40, "y1": 20, "x2": 44, "y2": 24}))
        w.food_ids = T(lua, {main.id: True})                   # a level's stone pile, the AI's
        w.used["40,20,100"] = True
        r = py(env.report())
        f = r["feeders"][0]
        assert (f["pile_id"], f["shop_id"], f["kind"], f["linked"], f.get("why"), f["main"]) == \
            (pile.id, shop.id, "Masons", False, None, main.id), f
        assert r["unlinked"] == 1 and r["feeders_ai"] == 1
        assert any(p["id"] == pile.id and p.get("feeder") for p in r["stone_piles"])
        # the workshop outside every AI level: the player's
        w.areas = T(lua, [])
        assert py(env.report())["feeders"][0]["why"] == "players_workshop"
        w.areas = T(lua, [{"x1": 0, "y1": 0, "x2": 59, "y2": 59, "z": 100}])
        # the player linked another pile to it
        other = w.pile(T(lua, {"x1": 5, "y1": 5, "x2": 6, "y2": 6}))
        shop.profile.links.take_from_pile.insert(shop.profile.links.take_from_pile, 0, other)
        assert py(env.report())["feeders"][0]["why"] == "player_links"
        lua2, env2, w2 = world()
        ai_masons(lua2, env2, w2, kind="Craftsdwarfs")
        assert py(env2.report())["feeders"][0]["why"] == "kind"

    @test("report: a linked feeder empty while its workshop has work, and a workshop nobody works: days counted, "
          "cleared when it fills or someone works")
    def _():
        lua, env, w = world()
        shop, pile = ai_masons(lua, env, w, used=False)
        env.link_feeder(T(lua, {"pile_id": pile.id}), False)
        shop.jobs = T(lua, [{}])
        r = py(env.report())["feeders"][0]
        assert r["linked"] and r["empty_days"] == 0 and r["idle_days"] == 0 and r["jobs"] == 1, r
        w.now = w.now + 3 * 1200
        r = py(env.report())["feeders"][0]
        assert r["empty_days"] == 3 and r["idle_days"] == 3, r
        w.used["25,20,100"] = True
        shop.jobs = T(lua, [{"worker": {}}])
        r = py(env.report())["feeders"][0]
        assert r.get("empty_days") is None and r.get("idle_days") is None and r["working"] == 1, r

    @test("report: a remembered feeder whose pile is gone is forgotten")
    def _():
        lua, env, w = world()
        shop, pile = ai_masons(lua, env, w)
        w.remove(pile.id)
        r = py(env.report())
        assert r["feeders"] == [] or r["feeders"] == {}
        assert not py(env.registry())["feeders"]

    # --- 2. the actions ----------------------------------------------------------------------

    @test("set_barrows: an AI stone pile's max wheelbarrows set (at most its tiles - 1); the player's refused; "
          "a dry run changes nothing; the same count refused")
    def _():
        lua, env, w = world()
        mine = w.pile(T(lua, {"x1": 10, "y1": 10, "x2": 11, "y2": 11}))
        theirs = w.pile(T(lua, {"x1": 30, "y1": 30, "x2": 34, "y2": 34}))
        w.food_corners = T(lua, {"10,10,100": True})
        r = py(env.set_barrows(T(lua, {"pile_id": mine.id, "barrows": 2}), True))
        assert r["ok"] and r["dry_run"] and mine.storage.max_wheelbarrows == 0, r
        r = py(env.set_barrows(T(lua, {"pile_id": mine.id, "barrows": 9}), False))
        assert r["ok"] and r["barrows"] == 3 and mine.storage.max_wheelbarrows == 3, r     # 4 tiles: 3 at most
        r = py(env.set_barrows(T(lua, {"pile_id": mine.id, "barrows": 3}), False))
        assert r["rejected"] and "already" in r["error"]
        r = py(env.set_barrows(T(lua, {"pile_id": theirs.id, "barrows": 2}), False))
        assert r["rejected"] and "player" in r["error"] and theirs.storage.max_wheelbarrows == 0
        assert py(env.set_barrows(T(lua, {"pile_id": 99999, "barrows": 1}), False))["rejected"]

    @test("link_feeder: the AI feeder and its workshop linked on both sides; a dry run links nothing; "
          "linked twice refused; a pile the AI didn't book refused")
    def _():
        lua, env, w = world()
        shop, pile = ai_masons(lua, env, w)
        r = py(env.link_feeder(T(lua, {"pile_id": pile.id}), True))
        assert r["ok"] and r["dry_run"] and ids(w, shop.profile.links.take_from_pile) == [], r
        r = py(env.link_feeder(T(lua, {"pile_id": pile.id}), False))
        assert r["ok"] and r["shop_id"] == shop.id and r["kind"] == "Masons", r
        assert ids(w, shop.profile.links.take_from_pile) == [pile.id]
        assert ids(w, pile.links.give_to_workshop) == [shop.id]
        assert pile.stockpile_flag.use_links_only is False
        assert py(env.link_feeder(T(lua, {"pile_id": pile.id}), False))["rejected"]
        stray = w.pile(T(lua, {"x1": 5, "y1": 5, "x2": 6, "y2": 6}))
        r = py(env.link_feeder(T(lua, {"pile_id": stray.id}), False))
        assert r["rejected"] and "AI" in r["error"]
        assert py(env.report())["feeders"][0]["linked"] is True

    @test("link_feeder: never the player's workshop, a many-material one, one the player linked")
    def _():
        lua, env, w = world()
        shop, pile = ai_masons(lua, env, w)
        w.areas = T(lua, [])
        r = py(env.link_feeder(T(lua, {"pile_id": pile.id}), False))
        assert r["rejected"] and r["why"] == "players_workshop" and ids(w, shop.profile.links.take_from_pile) == []
        lua, env, w = world()
        shop, pile = ai_masons(lua, env, w, kind="Craftsdwarfs")
        assert py(env.link_feeder(T(lua, {"pile_id": pile.id}), False))["why"] == "kind"
        lua, env, w = world()
        shop, pile = ai_masons(lua, env, w)
        other = w.pile(T(lua, {"x1": 5, "y1": 5, "x2": 6, "y2": 6}))
        shop.profile.links.give_to_pile.insert(shop.profile.links.give_to_pile, 0, other)
        assert py(env.link_feeder(T(lua, {"pile_id": pile.id}), False))["why"] == "player_links"

    @test("link_feeder links_only: fed from the AI's bigger pile of its kind on its level, taking from links only; "
          "with none near it is linked to its workshop alone")
    def _():
        lua, env, w = world()
        shop, pile = ai_masons(lua, env, w)
        main = w.pile(T(lua, {"x1": 40, "y1": 20, "x2": 44, "y2": 24}))
        w.food_corners = T(lua, {"40,20,100": True})
        w.used["41,21,100"] = True
        r = py(env.link_feeder(T(lua, {"pile_id": pile.id, "links_only": True}), False))
        assert r["ok"] and r["main"] == main.id and r["links_only"], r
        assert ids(w, main.links.give_to_pile) == [pile.id] and ids(w, pile.links.take_from_pile) == [main.id]
        assert pile.stockpile_flag.use_links_only is True
        lua, env, w = world()
        shop, pile = ai_masons(lua, env, w)
        theirs = w.pile(T(lua, {"x1": 40, "y1": 20, "x2": 44, "y2": 24}))   # the player's: never the main
        w.used["41,21,100"] = True
        r = py(env.link_feeder(T(lua, {"pile_id": pile.id, "links_only": True}), False))
        assert r["ok"] and r.get("main") is None and "note" in r and pile.stockpile_flag.use_links_only is False, r
        assert ids(w, theirs.links.give_to_pile) == []

    @test("link_feeder unlink: every link the AI made undone, links only off, and never linked again")
    def _():
        lua, env, w = world()
        shop, pile = ai_masons(lua, env, w)
        main = w.pile(T(lua, {"x1": 40, "y1": 20, "x2": 44, "y2": 24}))
        w.food_corners = T(lua, {"40,20,100": True})
        w.used["41,21,100"] = True
        env.link_feeder(T(lua, {"pile_id": pile.id, "links_only": True}), False)
        r = py(env.link_feeder(T(lua, {"pile_id": pile.id, "unlink": True}), True))
        assert r["ok"] and r["dry_run"] and ids(w, shop.profile.links.take_from_pile) == [pile.id]
        r = py(env.link_feeder(T(lua, {"pile_id": pile.id, "unlink": True}), False))
        assert r["ok"] and r["unlinked"], r
        for vec in (shop.profile.links.take_from_pile, pile.links.give_to_workshop, main.links.give_to_pile,
                    pile.links.take_from_pile):
            assert ids(w, vec) == []
        assert pile.stockpile_flag.use_links_only is False
        r = py(env.link_feeder(T(lua, {"pile_id": pile.id}), False))
        assert r["rejected"] and r["why"] == "unlinked", r
        row = py(env.report())["feeders"][0]
        assert row["why"] == "unlinked" and row["unlinked"] is True
        assert py(env.link_feeder(T(lua, {"pile_id": pile.id, "unlink": True}), False))["rejected"]

    @test("remember_feeder: booked once, by the pile at the corner; nothing there, nothing booked")
    def _():
        lua, env, w = world()
        shop, pile = ai_masons(lua, env, w)
        env.remember_feeder(25, 20, 100, shop.id, "Masons", "stone")
        assert len(py(env.registry())["feeders"]) == 1
        assert env.remember_feeder(1, 1, 100, shop.id, "Masons", "stone") is False


# --- 3. the bridge, the switch ------------------------------------------------------------

@test("bridge: the section (safe, cached a day), the actions (dry runs, labels), the module listed, place_feeder's hook")
def _():
    hub = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    acts = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    assert "pile_links = function() return safe(function() return reqscript('ai-pile-links').report() end) end" in hub
    assert "SECTION_CACHE_DAYS.pile_links = 1" in hub
    assert "pile_barrows = act_pile_barrows," in hub and "feeder_link = act_feeder_link," in hub
    assert "'pile_barrows', 'feeder_link'," in hub
    assert "'ai-pile-links'" in hub.split("BRIDGE_MODULES = {")[1].split("}")[0]
    assert "CACHE_INVALIDATES.feeder_pile = {'logistics', 'food_store', 'pile_links'}" in hub
    assert "function act_pile_barrows(a)" in acts and "function act_feeder_link(a)" in acts
    rooms = (LUA_DIR / "ai-builder-rooms.lua").read_text(encoding="utf-8")
    assert "reqscript('ai-pile-links').remember_feeder(r.x, r.y, r.z, b.id, kind, f.flag)" in rooms
    import overseer
    for a in ("pile_barrows", "feeder_link"):
        assert a in overseer.SHORT_WORDS
    assert digest.SECTION_DEFAULTS["pile_links"] == {}


@test("Rules: link_feeders on by default, off only when the settings say so")
def _():
    s = (LUA_DIR / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    assert code_has(s, "link_feeders = true,") and code_has(s, "link_feeders = s.link_feeders,")
    assert "'link_feeders'," in s
    assert player_rules({"settings": {}})["link_feeders"] is True
    assert player_rules({"settings": {"link_feeders": False}})["link_feeders"] is False


# --- 4. the brain -----------------------------------------------------------------------------

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def section(stone=(), feeders=(), owned=0, assigned=0, free=0, in_job=0, wanted=0, ai_wanted=None):
    return {"barrows": {"owned": owned, "assigned": assigned, "free": free, "in_job": in_job, "wanted": wanted,
                        "ai_wanted": sum(p.get("barrows", 0) for p in stone) if ai_wanted is None else ai_wanted},
            "stone_piles": list(stone), "feeders": list(feeders),
            "unlinked": sum(1 for f in feeders if not f.get("linked")), "feeders_ai": len(feeders)}


def spile(i, tiles, barrows=0):
    return {"id": i, "x1": 10, "y1": 10, "x2": 14, "y2": 14, "z": 100, "tiles": tiles, "used": 0, "barrows": barrows,
            "held": 0}


def feeder(i, kind="Masons", linked=False, used=3, jobs=0, **kw):
    r = {"pile_id": i, "shop_id": 100 + i, "kind": kind, "flag": "stone", "x": 25, "y": 20, "z": 100, "linked": linked,
         "links_only": False, "tiles": 9, "used": used, "jobs": jobs, "working": 0}
    r.update(kw)
    return r


def fort(pl=None, citizens=40) -> dict:
    s = copy.deepcopy(BASE)
    if pl is not None:
        s["pile_links"] = pl
    s["dwarves"]["total"] = citizens
    return digest.normalize(s)


RULES = {"order_supplies": True, "link_feeders": True}


def mine(s, rules=None, props=None):
    props = props if props is not None else []
    PP._pile_links_rule(s, CFG, s["dwarves"]["total"], props, rules or RULES)
    return props


def by(props, rule):
    return [p for p in props if p.rule == rule]


@test("brain barrows: the biggest AI stone pile under its want set (one per 12 tiles, 1..2, tiles - 1); "
      "the AI's total capped by the citizens; small piles none")
def _():
    p = by(mine(fort(section([spile(1, 9), spile(2, 25)]))), "barrows")
    assert len(p) == 1 and p[0].action == {"type": "pile_barrows", "pile_id": 2, "barrows": 2}, p
    p = by(mine(fort(section([spile(1, 9), spile(2, 25, barrows=2)]))), "barrows")
    assert p[0].action == {"type": "pile_barrows", "pile_id": 1, "barrows": 1}, p
    assert not by(mine(fort(section([spile(1, 3)]))), "barrows")                       # too small
    # 15 citizens: 2 at most for the AI's piles, 2 taken already
    assert not by(mine(fort(section([spile(1, 9), spile(2, 25, barrows=2)]), citizens=15)), "barrows")
    assert PP.barrows_want(2, CFG) == 0 and PP.barrows_want(4, CFG) == 1 and PP.barrows_want(100, CFG) == 2
    assert not mine(fort(None))                                                       # no section: nothing


@test("brain barrow_order: the piles' unmet want past the free, in-job and ordered ones made at a carpenter's; "
      "not when the hauling rule orders them, without wood, or with supplies off")
def _():
    s = fort(section([spile(1, 25, barrows=2)], owned=1, assigned=0, free=1, wanted=5))
    o = by(mine(s), "barrow_order")
    assert len(o) == 1 and o[0].action == {"type": "work_order", "recipe": "wheelbarrow", "amount": 3} and o[0].is_order
    s2 = fort(section([spile(1, 25, barrows=2)], owned=3, assigned=1, free=1, in_job=1, wanted=4))
    o = by(mine(s2), "barrow_order")
    assert o and o[0].action["amount"] == 1, o
    s3 = fort(section([spile(1, 25, barrows=2)], owned=4, assigned=2, free=2, wanted=4))
    assert not by(mine(s3), "barrow_order")                                           # enough free
    pre = [Proposal("hauling", {"type": "work_order", "recipe": "wheelbarrow", "amount": 2}, "x", 6, True)]
    assert not by(mine(s, props=pre), "barrow_order")
    assert not by(mine(s, rules={"order_supplies": False, "link_feeders": True}), "barrow_order")
    dry = copy.deepcopy(s)
    dry["stocks"]["wood"] = 0
    assert not by(mine(dry), "barrow_order")


@test("brain feeder_link: an unlinked AI Masons feeder with stone in it linked (links only when the AI's main pile "
      "is named); a many-material, refused, unlinked or empty one not; the switch off: nothing")
def _():
    p = by(mine(fort(section(feeders=[feeder(1)]))), "feeder_link")
    assert len(p) == 1 and p[0].action == {"type": "feeder_link", "pile_id": 1}, p
    p = by(mine(fort(section(feeders=[feeder(1, main=77)]))), "feeder_link")
    assert p[0].action == {"type": "feeder_link", "pile_id": 1, "links_only": True}
    for f in (feeder(1, kind="Craftsdwarfs"), feeder(1, why="players_workshop"), feeder(1, unlinked=True),
              feeder(1, used=0), feeder(1, linked=True), feeder(1, kind="Leatherworks")):
        assert not by(mine(fort(section(feeders=[f]))), "feeder_link"), f
    assert not by(mine(fort(section(feeders=[feeder(1)])), rules={"order_supplies": True, "link_feeders": False}),
                  "feeder_link")


@test("brain feeder_link unlink: a linked feeder empty 2 days, or its workshop idle 4, with work waiting: unlinked "
      "first; no work waiting: left")
def _():
    starved = feeder(1, linked=True, used=0, jobs=2, empty_days=2)
    p = by(mine(fort(section(feeders=[feeder(2), starved]))), "feeder_link")
    assert len(p) == 1 and p[0].action == {"type": "feeder_link", "pile_id": 1, "unlink": True}, p
    idle = feeder(1, linked=True, jobs=1, idle_days=4)
    assert by(mine(fort(section(feeders=[idle]))), "feeder_link")[0].action["unlink"] is True
    for f in (feeder(1, linked=True, used=0, jobs=2, empty_days=1), feeder(1, linked=True, used=0, jobs=0, empty_days=9)):
        assert not by(mine(fort(section(feeders=[f]))), "feeder_link"), f


@test("brain: plan() carries the rules, the config keys, the agenda, the digest line; no section: no line")
def _():
    props, _ = plan(fort(section([spile(1, 25)], feeders=[feeder(1)], owned=0, wanted=0)), Memory())
    rules = {p.rule for p in props}
    assert "barrows" in rules and "feeder_link" in rules, rules
    for r in ("barrows", "barrow_order", "feeder_link"):
        assert f"{r}_cooldown_ticks" in CFG
        assert r in PP.AGENDA_THEMES
    line = digest.pile_links_line(fort(section([spile(1, 25, barrows=2)], feeders=[feeder(1), feeder(2, linked=True)],
                                               owned=3, assigned=2, free=1, wanted=4)))
    assert line.startswith("PILES wheelbarrows 3 owned, 2 in piles, 1 free, piles want 4 (AI's 2)"), line
    assert "AI feeders 2: 1 linked, 1 unlinked" in line
    assert digest.pile_links_line(fort()) == ""
    assert "PILES wheelbarrows" in digest.digest(fort(section()))
    assert "PILES" not in digest.digest(fort()).split("\n")[0]


if __name__ == "__main__":
    finish()

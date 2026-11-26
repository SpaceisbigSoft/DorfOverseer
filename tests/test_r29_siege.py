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
                    "invite_siege = function(a) return reqscript('ai-siege').invite_siege(a.dry_run == true, a) end,")
    import overseer_words
    assert "invite_siege" in overseer_words.SHORT_WORDS
    import hold_classes as HC
    assert HC.step_class(Proposal("invite_siege", {"type": "invite_siege"}, "", 6)) == HC.EXPANSION


@test("ai-siege.lua split: the invitation in ai-siege-invite.lua (both under 60 KB, place_mood_shop kept)")
def _():
    from lua_modules_util import SPLIT, split_parts
    s, part = _src("ai-siege.lua"), _src("ai-siege-invite.lua")
    assert len(s.encode("utf-8")) < 55 * 1024, len(s.encode("utf-8"))
    assert len(part.encode("utf-8")) < 60 * 1024, len(part.encode("utf-8"))
    assert "function place_mood_shop(kind, dry_run)" in s and "function invite_siege(dry, opts)" in part
    assert "function invite_siege(" not in s.split("if PART_MISSING then", 1)[0], "the hub keeps only a stub"
    assert "out.invited = invited()" in s
    assert "ai-siege.lua" in SPLIT and split_parts("ai-siege.lua") == ["ai-siege-invite"]
    assert "PART_VERSIONS['ai-siege-invite']" in part and "PART_LOCALS = {U = U, is = is, entrances_of = entrances_of}" in s


# --- the Lua action, in a fake game ------------------------------------------------------------

DAY = 1200

FAKE = r"""
local src, force_ok, hostile, spawn_src = ...
local W = {site = {}, saved = nil, ran = {}, drop_entity = false}
local env = setmetatable({}, {__index = _G})
local events = setmetatable({}, {__index = {insert = function(self, _, v) table.insert(self, v) end}})
W.events = events
local function hfs(n) local t = {} for i = 1, n do t[i] = 9000 + i end return t end
local ents = {
    [278] = {id = 278, type = 'Civilization', race = 1, site_links = {1, 2, 3, 4}, name = 'elves', histfig_ids = hfs(2), entity_links = {}},
    [304] = {id = 304, type = 'Civilization', race = 2, site_links = {1, 2, 3, 4}, name = 'skirmishers', histfig_ids = hfs(2), entity_links = {}},
    [314] = {id = 314, type = 'Civilization', race = 2, site_links = {1}, name = 'near', histfig_ids = hfs(2), entity_links = {}},
    [320] = {id = 320, type = 'Civilization', race = 2, site_links = {1, 2, 3, 4, 5, 6}, name = 'big', histfig_ids = hfs(2), entity_links = {}},
    [321] = {id = 321, type = 'Civilization', race = 2, site_links = {1, 2}, name = 'dead', histfig_ids = {}, entity_links = {}},
    [323] = {id = 323, type = 'SiteGovernment', race = 3, site_links = {1}, name = 'site', histfig_ids = hfs(1),
             entity_links = {{type = 'PARENT', target = 320}}},
}
W.ents = ents
local rels = {{group_id = 278, relation = 'Peace'}, {group_id = 304, relation = 'Skirmishing'},
              {group_id = 323, relation = 'TotalWar'}, {group_id = 321, relation = 'TotalWar'}}
if hostile then
    table.insert(rels, {group_id = 314, relation = 'TotalWar'})
    table.insert(rels, {group_id = 320, relation = 'TotalWar'})
end
local fort_civ = {relations = {diplomacy = {state = rels}}}
-- the fort's site at world 47,60; 314: one site 20 tiles off; 320 (most sites): 60 off, a
-- site of its government 55 off; 304: 10 off; an army of 320 (pos in 48ths) 40 off
local sites = {{id = 1430, civ_id = 1, cur_owner_id = -1, pos = {x = 47, y = 60}},
               {id = 1, civ_id = 314, cur_owner_id = -1, pos = {x = 67, y = 60}},
               {id = 2, civ_id = 320, cur_owner_id = -1, pos = {x = 47, y = 120}},
               {id = 3, civ_id = -1, cur_owner_id = 323, pos = {x = 102, y = 60}},
               {id = 4, civ_id = 304, cur_owner_id = -1, pos = {x = 57, y = 60}},
               {id = 5, civ_id = 278, cur_owner_id = -1, pos = {x = 48, y = 60}}}
W.armies = {{controller = {entity_id = 323, site_id = 3}, pos = {x = 87 * 48, y = 60 * 48}, members = {}},
            {controller = {entity_id = 278, site_id = 1430}, pos = {x = 47 * 48, y = 61 * 48}, members = {}}}
W.controllers = {}
W.units = {}
env.df = {
    global = {plotinfo = {civ_id = 1}, timed_events = events, cur_season = 2, cur_season_tick = 77,
              cur_year = 260, cur_year_tick = 1000,
              world = {world_data = {sites = sites}, armies = {all = W.armies}, army_controllers = {all = W.controllers},
                       units = {active = W.units}}},
    timed_event_type = {EvaluateAttackAndSendImmediateArmy = 10, [10] = 'EvaluateAttackAndSendImmediateArmy'},
    historical_entity = {find = function(id) if id == 1 then return fort_civ end return ents[id] end},
    historical_figure = {find = function(id) return {id = id, died_year = -1} end},
    historical_entity_type = setmetatable({}, {__index = function(_, k) return k end}),
    entity_entity_link_type = {PARENT = 'PARENT'},
    diplomacy_state_type = setmetatable({}, {__index = function(_, k) return k end}),
    creature_raw = {find = function(r) return {creature_id = ({'ELF', 'GOBLIN', 'DWARF'})[r]} end},
}
W.df = env.df
env.dfhack = {
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
    findScript = function(n) if force_ok and n == 'force' then return 'hack/scripts/force.lua' end return nil end,
    run_command_silent = function(cmd, arg)
        table.insert(W.ran, cmd .. ' ' .. arg)
        local ev = {type = env.df.timed_event_type[arg], season = 2, season_ticks = 77}
        if W.drop_entity then setmetatable(ev, {__newindex = function() end}) end
        events:insert('#', ev)
        return '', 0
    end,
    translation = {translateName = function(n) return 'The ' .. tostring(n) end},
    world = {getCurrentSite = function() return sites[1] end},
    units = {isInvader = function(u) return u.invader == true end, isDead = function(u) return false end},
    printerr = function() end,
}
-- (0.105.123) a 20x20x10 map, its surface at z 5; the right edge (x 19) a walkable group of its own
-- (unreachable), the rest group 7 with the entrance at 3,3,5
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df.tiletype = {attrs = {[1] = {shape = 'OPEN'}, [2] = {shape = 'FLOOR'}}}
env.df.tiletype_shape = {attrs = {OPEN = {basic_shape = 'Open', walkable = false}, FLOOR = {basic_shape = 'Floor', walkable = true}}}
env.df.tiletype_shape_basic = {Open = 'Open'}
env.dfhack.maps = {
    getTileSize = function() return 20, 20, 10 end,
    getTileType = function(x, y, z) if z > 5 then return 1 end return 2 end,
    getTileFlags = function(p) return {outside = true, flow_size = 0} end,
    getWalkableGroup = function(p) if p.x == 19 then return 9 end return 7 end,
}
local G = {GATES = {entrances = {{id = 1, kind = 'surface', x = 3, y = 3, z = 5}}}}
W.made = {}
W.cu_fail_equip = false
local CU = {createUnit = function(race, caste, pos, range, ltype, age, dom, civ_id, group_id, ern, nick, van, qty, equip, skills, prof, cprof, fset, fclear)
    if equip and W.cu_fail_equip then error('Invalid equipment material: IRON') end
    table.insert(W.made, {race = race, x = pos.x, y = pos.y, z = pos.z, spread = range.offset_x, ltype = ltype, civ = civ_id,
                          group = group_id, qty = qty, equip = equip and #equip or 0, flags = fset and table.concat(fset, ',')})
    local us = {}
    for i = 1, qty do us[i] = {id = 5000 + i, civ_id = -1, flags1 = {}} end
    W.units = us
    return us
end}
W.CU = CU
W.cu = false
-- (item8) the native route (dfhack.units.create) over this map, when W.native
W.native = false
local function vec0(list)
    local t = {_n = #list}
    for i, v in ipairs(list) do t[i - 1] = v end
    return setmetatable(t, {__len = function(self) return rawget(self, '_n') end})
end
local active = setmetatable({}, {__index = {insert = function(self, _, v) table.insert(self, v) end}})
env.df.global.world.units.active = active
W.active = active
env.df.global.unit_next_id = 6000
env.df.global.world.raws = {creatures = {all = {{creature_id = 'ELF', caste = {{caste_id = 'F'}}},
                                                {creature_id = 'GOBLIN', caste = {{caste_id = 'F'}, {caste_id = 'M'}}}}},
                            itemdefs = {weapons = {{id = 'ITEM_WEAPON_SPEAR', subtype = 3}}, armor = {{id = 'ITEM_ARMOR_MAIL_SHIRT', subtype = 1}},
                                        helms = {{id = 'ITEM_HELM_HELM', subtype = 0}}, shields = {{id = 'ITEM_SHIELD_BUCKLER', subtype = 1}}}}
env.df.item_type = {WEAPON = 24, ARMOR = 25, HELM = 28, SHIELD = 27}
env.df.inv_item_role_type = {Weapon = 1, Worn = 2, Strapped = 10}
env.dfhack.isMapLoaded = function() return true end
env.dfhack.maps.isValidTilePos = function(x, y, z) return x >= 0 and y >= 0 and x < 20 and y < 20 and z >= 0 and z < 10 end
env.dfhack.maps.getTileBlock = function() return nil end
env.dfhack.buildings = {findAtTile = function() return nil end}
env.dfhack.matinfo = {find = function(s) if s == 'INORGANIC:IRON' then return {type = 0, index = 8} end return nil end}
env.dfhack.units.create = function(race, caste)
    if not W.native then error('no unit made in this fake') end
    local id = env.df.global.unit_next_id
    env.df.global.unit_next_id = id + 1
    local parts = {}
    for _, f in ipairs({'UPPERBODY', 'LOWERBODY', 'HEAD', 'GRASP', 'GRASP'}) do table.insert(parts, {flags = {[f] = true}}) end
    return {id = id, race = race, caste = caste, pos = {x = -30000, y = -30000, z = -30000}, civ_id = -1, flags1 = {},
            flags2 = {}, flags3 = {}, inventory = {}, military = {uniform_drop = {resize = function() end}},
            body = {body_plan = {body_parts = vec0(parts)}}}
end
env.dfhack.units.teleport = function(u, p) return true end
env.dfhack.items = {createItem = function(u, t, st) return {{type = t, subtype = st}} end,
                    moveToInventory = function(it, u, role, bp)
                        table.insert(u.inventory, {item = it, mode = role, body_part_id = bp}); return true end,
                    remove = function() end}
local settings = {invite_siege = true}
W.settings = settings
local S = {load_settings = function() return settings end, save_settings = function(s) W.saved = s; settings.invite_siege = s.invite_siege end}
env.reqscript = function(n)
    if n == 'ai-overseer-settings' then return S end
    if n == 'ai-gates' then return G end
    if n == 'modtools/create-unit' and W.cu then return CU end
    if n == 'ai-spawn' then           -- (item1) the real module, over this fake game
        if not W.spawn_env then
            local e = setmetatable({}, {__index = env})
            assert(load(spawn_src, 'ai-spawn', 't', e))()
            W.spawn_env = e
        end
        return W.spawn_env
    end
    error('reqscript ' .. tostring(n))
end
assert(load(src, 'ai-siege', 't', env))()
return env, W
"""


def _lua(force_ok=True, hostile=True):
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-siege.lua"), force_ok, hostile, _src("ai-spawn.lua"))
    _lua.runtime = lua
    return env, w


def lua_tbl(d):
    return _lua.runtime.table_from(d)


def _days(w, n):
    w.df["global"]["cur_year_tick"] += int(n * DAY)


def _ids(t):
    return [r.id for r in t.values()]


@test("invite_siege (Lua): the civ by reach (TotalWar first, the nearest, not the most sites); the event's civ read back")
def _():
    need_lua()
    env, w = _lua()
    r = env.invite_siege(False)
    assert r.ok and r.invited and r.how == "force" and r.civ_id == 314 and r.state == "waiting", dict(r)
    assert r.entity_set is True and r.entity_read == 314
    assert list(w.ran.values()) == ["force EvaluateAttackAndSendImmediateArmy"]
    assert w.events[1].entity.id == 314
    # 314 at 20 tiles, 320 (its government's site 55, its army 40) next, then the skirmishers;
    # elves at peace and the civ with no one alive left out
    assert _ids(r.ranking) == [314, 320, 304], _ids(r.ranking)
    rk = list(r.ranking.values())
    assert rk[0].reach == 20 and rk[1].reach == 40 and rk[1].site_d == 55 and rk[2].reach == 10
    rec = w.site["ai-overseer/siege-invite"]
    assert rec.civ_id == 314 and rec.how == "force" and rec.state == "waiting" and rec.invitation == 1
    assert len(rec.tries) == 1 and rec.tries[1].entity_set is True
    assert w.saved.invite_siege is False, "the switch turned off"


@test("invite_siege (Lua): no army in 7 days: the next civ, 3 at most, then no_army with the civs tried")
def _():
    need_lua()
    env, w = _lua()
    env.invite_siege(False)
    _days(w, 2)
    r = env.invite_siege(False)
    assert r.ok and r.waiting and r.quiet and len(w.events) == 1, dict(r)
    _days(w, 6)
    r = env.invite_siege(False)
    assert r.ok and r.retried and r.no_army == "The near" and r.civ_id == 320 and len(w.events) == 2, dict(r)
    assert w.events[2].entity.id == 320
    _days(w, 8)
    r = env.invite_siege(False)
    assert r.retried and r.civ_id == 304, dict(r)
    _days(w, 8)
    r = env.invite_siege(False)
    assert r.ok and r.gave_up and r.state == "no_army" and len(w.events) == 3, dict(r)
    assert list(r.tried.values()) == ["The near", "The big", "The skirmishers"]
    rec = w.site["ai-overseer/siege-invite"]
    assert rec.state == "no_army" and [t.outcome for t in rec.tries.values()] == ["no_army"] * 3


@test("invite_siege (Lua): no army from 3 civs: the top civ's war party at the reachable map edge, once a fort")
def _():
    need_lua()
    env, w = _lua()
    w.cu = True
    env.invite_siege(False)
    for _ in range(2):
        _days(w, 8)
        env.invite_siege(False)
    _days(w, 8)
    r = env.invite_siege(False)
    assert r.ok and r.gave_up and r.state == "came" and r.spawned and r.spawned.count == 16, dict(r)
    made = list(w.made.values())
    assert len(made) == 1, made
    mk = made[0]
    # the farthest reachable edge tile from the entrance (3,3): 17,19 (x 19 is another walkable group)
    assert (mk.x, mk.y, mk.z) == (17, 19, 5) and mk.ltype == "Walkable" and mk.spread in (3, 6, 9, 12), dict(mk)   # (0.105.127) grown to fit the party
    assert mk.race == "GOBLIN" and mk.civ == 314 and mk.qty == 16 and mk.equip == 4, dict(mk)
    assert mk.flags == "active_invader,invader_origin"
    u = w.units[1]
    assert u.civ_id == 314 and u.flags1.active_invader and u.flags1.invader_origin
    assert r.civ_name == "The near" and w.site["ai-overseer/siege-spawned"].count == 16
    # (0.105.127) the party still alive: no second one; the switch on again is refused while it lives
    res = env.spawn_party(lua_tbl({"id": 314, "race": "GOBLIN"}))
    assert isinstance(res, tuple) and res[0] is None and "still on the map" in res[1], res
    w.settings.invite_siege = True
    again = env.invite_siege(False)
    assert again.rejected and "not over" in again.error and len(list(w.made.values())) == 1, dict(again)


@test("invite_siege (Lua): the war party's equipment refused: placed unarmed; no create-unit: no_army, said why")
def _():
    need_lua()
    env, w = _lua()
    w.cu, w.cu_fail_equip = True, True
    sp = env.spawn_party(lua_tbl({"id": 314, "name": "The near", "race": "GOBLIN"}))
    assert sp and sp.count == 16 and sp.equipped is False and "IRON" in sp.equip_error, dict(sp)
    assert sp.route == "create-unit", dict(sp)
    env, w = _lua()
    env.invite_siege(False)
    for _ in range(3):
        _days(w, 8)
        r = env.invite_siege(False)
    assert r.gave_up and r.state == "no_army" and "create-unit" in r.spawn_error, dict(r)
    # (item8) both routes' reasons kept (600 chars) and the spawner's info in the record
    assert "native: " in r.spawn_error and "no unit made in this fake" in r.spawn_error, r.spawn_error
    assert r.spawn_info.route == "none" and "no unit made in this fake" in r.spawn_info.native_error, dict(r.spawn_info)
    rec = w.site["ai-overseer/siege-invite"]
    assert rec.spawn_error == r.spawn_error and rec.spawn_info.route == "none"


@test("invite_siege (Lua): create-unit stale: the war party made by dfhack.units.create, armed, invaders of the civ")
def _():
    need_lua()
    env, w = _lua()
    w.native = True
    env.invite_siege(False)
    for _ in range(3):
        _days(w, 8)
        r = env.invite_siege(False)
    assert r.ok and r.gave_up and r.state == "came" and r.spawned.count == 16, dict(r)
    assert r.spawned.route == "native" and r.spawned.equipped is True, dict(r.spawned)
    sp = r.spawned.spawn_info
    assert sp.route == "native" and sp.made == 16 and sp.armed == 16 and "create-unit" not in str(sp.native_error), dict(sp)
    assert "Cannot" in sp.cu_error or "create-unit" in sp.cu_error, dict(sp)
    us = [w.active[i] for i in range(1, len(w.active) + 1)]
    assert len(us) == 16
    for u in us:
        assert u.civ_id == 314 and u.flags1.active_invader and u.flags1.invader_origin and u.flags1.marauder
        assert abs(u.pos.x - 17) <= 3 and abs(u.pos.y - 19) <= 3 and u.pos.z == 5 and u.pos.x != 19, dict(u.pos)
        kinds = sorted(i.item.type for i in u.inventory.values())
        assert kinds == [24, 25, 27, 28], kinds
    assert len({(u.pos.x, u.pos.y) for u in us}) == 16, "one a tile"
    assert w.site["ai-overseer/siege-spawned"].spawn_info.route == "native"


@test("invite_siege (Lua): after no army, one new invitation by the switch; the civs tried before go last")
def _():
    need_lua()
    env, w = _lua()
    env.invite_siege(False)
    for _ in range(3):
        _days(w, 8)
        env.invite_siege(False)
    assert w.site["ai-overseer/siege-invite"].state == "no_army"
    w.settings.invite_siege = False
    r = env.invite_siege(False)
    assert not r.ok and r.rejected and "starts a new one" in r.error, dict(r)
    w.settings.invite_siege = True
    r = env.invite_siege(False)
    assert r.ok and r.invited and r.reinvite and r.invitation == 2 and len(w.events) == 4, dict(r)
    assert r.previous.state == "no_army" and len(r.previous.tried) == 3
    assert w.saved.invite_siege is False


@test("invite_siege (Lua): an army set out for the fort: came; then again once it is over")
def _():
    need_lua()
    env, w = _lua()
    env.invite_siege(False)
    _days(w, 3)
    # an army of 320's government (a hostile civ's group) ordered at the fort's site; the elves' one never counts
    w.armies[1].controller.site_id = 1430
    r = env.invite_siege(False)
    assert r.ok and r.came and r.armies == 1 and r.state == "came", dict(r)
    # (0.105.127) again once it is over: the army's civ sent one, so it is invited again (no direct war party)
    w.settings.invite_siege = True
    again = env.invite_siege(False)
    assert again.ok and again.invited and not again.direct, dict(again)
    assert len(w.events) == 2, "a second invitation once the first is over"


@test("invite_siege (Lua): the brain saw invaders (came): no next civ after 7 days; the elves' caravan army is no army")
def _():
    need_lua()
    env, w = _lua()
    env.invite_siege(False)
    _days(w, 9)
    lua = _lua.runtime
    r = env.invite_siege(False, lua.table_from({"came": True}))
    assert r.ok and r.came and len(w.events) == 1, dict(r)


@test("invite_siege (Lua): the event's civ not held: said (entity_set false); no force: queued directly; dry: nothing")
def _():
    need_lua()
    env, w = _lua()
    w.drop_entity = True
    r = env.invite_siege(False)
    assert r.ok and r.entity_set is False and r.entity_read is None, dict(r)
    env, w = _lua(force_ok=False)
    d = env.invite_siege(True)
    assert d.ok and d.dry_run and d.civ_id == 314 and len(w.events) == 0 and w.site["ai-overseer/siege-invite"] is None
    r = env.invite_siege(False)
    assert r.ok and r.how == "timed_event" and w.events[1].entity.id == 314 and w.events[1].type == 10
    assert r.entity_set is True


@test("invite_siege (Lua): none at total war: the skirmishing civ")
def _():
    need_lua()
    env, w = _lua(hostile=False)
    r = env.invite_siege(False)
    # 323 is a site government (no civ), 321 has no one alive: 304, Skirmishing
    assert r.ok and r.civ_id == 304, dict(r)


@test("invite_siege (Lua): a 0.105.122 record (no state) is an invitation waiting on its one civ")
def _():
    need_lua()
    env, w = _lua()
    lua = _lua.runtime
    w.site["ai-overseer/siege-invite"] = lua.table_from({"tick": 260 * 403200 + 1000, "year": 260, "civ_id": 314,
                                                          "civ_name": "The near", "how": "force"})
    rec = env.invited()
    assert rec.state == "waiting" and len(rec.tries) == 1 and rec.tries[1].civ_id == 314
    _days(w, 8)
    r = env.invite_siege(False)
    # no ranking kept by 0.105.122: no next civ; it ends, and the switch may start a new one
    assert r.gave_up and r.state == "no_army", dict(r)


@test("rank_civs (Lua): tier, then reach; civilisations only; the dead out; the tried before last")
def _():
    need_lua()
    env, _ = _lua()
    lua = _lua.runtime
    f = lua.eval("""function(f, before) return f({
        {id = 5, kind = 'Civilization', relation = 'Skirmishing', sites = 9, site_d = 3},
        {id = 6, kind = 'Civilization', relation = 'TotalWar', sites = 1, site_d = 50},
        {id = 9, kind = 'Civilization', relation = 'TotalWar', sites = 30, site_d = 80, army_d = 30},
        {id = 7, kind = 'SiteGovernment', relation = 'TotalWar', sites = 9, site_d = 1},
        {id = 10, kind = 'Civilization', relation = 'TotalWar', sites = 3, site_d = 2, alive = false},
        {id = 8, kind = 'Civilization', relation = 'Peace', sites = 30, site_d = 1}}, before) end""")
    t = f(env.rank_civs, None)
    assert _ids(t) == [9, 6, 5], _ids(t)
    t = f(env.rank_civs, lua.table_from({9: True}))
    assert _ids(t) == [6, 5, 9], _ids(t)
    assert env.pick_civ(lua.table_from([lua.table_from({"id": 1, "kind": "Civilization", "relation": "Peace"})])) is None


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

@test("watch: an invitation no army followed in 30 days is said once, with the civs tried")
def _():
    m = Memory()
    s = SC.base_state()
    s["field_watch"]["invited"] = {"tick": 148 * 403200 + 100 * 1200, "civ_name": SC.CIV, "how": "force",
                                   "state": "waiting", "tries": [{"civ_name": "X"}, {"civ_name": SC.CIV}]}
    s = SC.at(s, 31, [])
    W.note_siege_watch(s, m, CFG)
    j = W.siege_journal(m)
    assert len(j) == 1 and j[0]["what"] == "siege_no_show" and f"tried X, {SC.CIV}" in j[0]["text"], j
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
    # (0.105.123) a daily look while it waits says nothing; a new invitation names the ranking
    W.note_invite(p, {"ok": True, "waiting": True, "quiet": True, "tick": 5, "state": "waiting"}, {}, m, 5)
    assert not W.siege_journal(m)
    W.note_invite(p, {"ok": True, "invited": True, "tick": 9, "civ_id": 314, "civ_name": "A", "how": "force",
                      "event": "E", "entity_set": False, "entity_read": None,
                      "ranking": [{"id": 314, "name": "A", "relation": "TotalWar", "reach": 52},
                                  {"id": 304, "name": "B", "relation": "Skirmishing", "reach": 51}]}, {}, m, 9)
    e = W.siege_journal(m)[0]
    assert e["what"] == "siege_invited" and "A (TotalWar, 52 world tiles); B (Skirmishing, 51" in e["text"]
    assert "read back: NOT set" in e["text"] and m.holdfast["invited"]["tick"] == 9


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

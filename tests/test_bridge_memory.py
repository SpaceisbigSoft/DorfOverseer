"""Tests for the pure parts of lua/ai-bridge.lua (memory saved per kind, the
report tiers), with a stub DFHack, in a real Lua engine (pip install lupa).

    python tests/test_bridge_memory.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = []

try:
    from lupa import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

HARNESS = r"""
local src = ...
local H = {persist = {}, files = {}, to_save = nil, action = nil, printed = nil, has_delete = true}
local json = {
  decode = function(text) return H.action end,
  decode_file = function(path) if H.to_save == nil then error('no file') end return H.to_save end,
  encode_file = function(data, path) H.files[path] = data end,
  encode = function(t) H.printed = t; return 'json' end,
}
local utils = {invert = function(t) local o = {}; for i, v in ipairs(t) do o[v] = i end; return o end}
local persistent = {
  getSiteData = function(k, default) local v = H.persist[k]; if v == nil then return default end; return v end,
  saveSiteData = function(k, v) H.persist[k] = v end,
}
function H.set_delete(on)
  persistent.deleteSiteData = on and function(k) H.persist[k] = nil end or nil
end
H.set_delete(true)
local dfhack = {
  getDFPath = function() return '/df' end,
  isMapLoaded = function() return true end, isWorldLoaded = function() return true end,
  world = {isFortressMode = function() return true end},
  persistent = persistent,
  filesystem = {mkdir_recursive = function() end},
  maps = {getTileSize = function() return 120, 120, 100 end},
}
local df = {global = {cur_year = 150, cur_year_tick = 1000, pause_state = true,
  world = {cur_savegame = {save_dir = 'region1'}, map = {region_z = 140}},
  plotinfo = {site_id = 7, tasks = {wealth = {total = 1234}},
              alerts = {civ_alert_idx = 0, list = {}}}}}
H.df, H.dfhack = df, dfhack
local function new_env(module)
  local env = setmetatable({}, {__index = _G})
  env.dfhack, env.df = dfhack, df
  env.require = function(name) if name == 'json' then return json end if name == 'utils' then return utils end
    if H.modules and H.modules[name] then return H.modules[name] end
    error('unexpected require ' .. name) end
  env.reqscript = function(name)
    if H.scripts and H.scripts[name] then return H.scripts[name] end
    if name == 'ai-status' then return {is_halted = function() return false end} end
    error('no ' .. name .. ' here')
  end
  env.dfhack_flags = {module = module}
  env.print = function() end
  return env
end
local chunk_src = src
function H.run(...)
  local env = new_env(false)
  assert(load(chunk_src, 'ai-bridge', 't', env))(...)
  return H.printed
end
function H.module()
  local env = new_env(true)
  assert(load(chunk_src, 'ai-bridge', 't', env))()
  return env
end
return H
"""

LUA = LuaRuntime(unpack_returned_tuples=True)
H = LUA.execute(HARNESS, (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8"))
FROM = "/df/dfhack-config/ai-overseer/memory-from-save.json"


def t(d):
    if isinstance(d, dict):
        return LUA.table_from({k: t(v) for k, v in d.items()})
    if isinstance(d, list):
        return LUA.table_from([t(v) for v in d])
    return d


def reset():
    H.persist = LUA.table()
    H.files = LUA.table()
    H.to_save = None
    H.scripts = None
    H.set_delete(True)


def save(data):
    H.to_save = t(data)
    H.action = t({"type": "save_memory"})
    return H.run("act", "{}")


def test(name):
    def wrap(fn):
        reset()
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return wrap


@test("save_memory stores each kind's text under its own key; memory hands them back")
def _():
    r = save({"fort": "region1/7", "kinds": {"working": '{"a": []}', "atlas": "[]"}})
    assert r.ok and list(r.saved.values()) == ["atlas", "working"], dict(r)
    assert H.persist["ai-overseer/mem/working"].text == '{"a": []}'
    assert H.persist["ai-overseer/mem/atlas"].fort == "region1/7"
    m = H.run("memory")
    assert m.ok and m.present and m.file == FROM, dict(m)
    out = H.files[FROM]
    assert out.kinds.working.text == '{"a": []}' and out.kinds.atlas.fort == "region1/7"
    assert out.kinds.timeline is None and out.legacy is None


@test("save_memory refuses unknown kinds and non-text values, storing nothing")
def _():
    r = save({"fort": "f", "kinds": {"working": "{}", "secrets": "{}"}})
    assert not r.ok and r.rejected and "secrets" in r.error, dict(r)
    r = save({"fort": "f", "kinds": {"working": t({"x": 1})}})
    assert not r.ok and r.rejected and "working" in r.error, dict(r)
    assert len(H.persist) == 0
    assert not save({"kinds": {"working": "{}"}}).ok                # no fort
    assert H.run("memory").present is False


@test("old format still goes to the old key; memory hands it back as legacy")
def _():
    r = save({"fort": "f", "memory": {"cooldowns": {"x": 1}}})
    assert r.ok, dict(r)
    m = H.run("memory")
    assert m.present and H.files[FROM].legacy.memory.cooldowns.x == 1
    assert H.files[FROM].kinds is None                             # nothing per kind yet


@test("drop_legacy deletes the old key (or leaves a marker read as absent)")
def _():
    save({"fort": "f", "memory": {"a": 1}})
    r = save({"fort": "f", "kinds": {"knowledge": "{}"}, "drop_legacy": True})
    assert r.ok and H.persist["ai-overseer/memory"] is None
    assert H.files[FROM] is None and H.run("memory").present and H.files[FROM].legacy is None
    reset()
    H.set_delete(False)
    save({"fort": "f", "memory": {"a": 1}})
    save({"fort": "f", "kinds": {"chronicle": "[]"}, "drop_legacy": True})
    assert H.persist["ai-overseer/memory"].dropped is True
    H.run("memory")
    assert H.files[FROM].legacy is None and H.files[FROM].kinds.chronicle.text == "[]"
    reset()
    H.set_delete(False)
    save({"fort": "f", "memory": {"a": 1}})
    save({"fort": "f", "kinds": {}, "drop_legacy": True})
    assert H.run("memory").present is False


@test("report tiers: pulse is a small subset without units; daily has everything plus the registry")
def _():
    M = H.module()
    M.get_dwarves = LUA.eval("function(inc) return {total = 7}, inc and {{id = 1}} or nil end")
    pulse = M.build_state(True, "pulse")
    keys = set(pulse.keys())
    want = set(M.PULSE_SECTIONS.values()) | {"tier", "_timing"}
    assert keys == want, keys ^ want
    assert pulse.tier == "pulse" and pulse.units is None and pulse.dwarves.total == 7
    assert pulse.wealth == 1234 and pulse.fort.site_id == 7
    for absent in ("supplies", "map", "jobs", "recent_announcements", "registry"):
        assert absent not in keys, absent
    daily = M.build_state(True)
    assert daily.tier == "daily" and daily.units[1].id == 1 and daily.bridge_version == "0.104.128"
    assert set(pulse.keys()) - {"tier"} <= set(daily.keys())
    assert daily.registry.error is not None                         # no builder here, but the section is there
    assert M.build_state(False, "survey").tier == "survey"


@test("report rotation (0.100): expired cached sections rebuilt two a report, the stalest first")
def _():
    M = H.module()
    M.get_dwarves = LUA.eval("function(inc) return {total = 7}, nil end")
    calls = LUA.eval("{}")
    LUA.eval("""function(M, calls)
        M.SECTIONS = {}
        for _, n in ipairs({'a', 'b', 'c', 'live'}) do
            M.SECTIONS[n] = function() calls[n] = (calls[n] or 0) + 1; return {n = n} end
        end
        M.SECTION_CACHE_DAYS = {a = 1, b = 2, c = 3}
        M.SECTION_CACHE = {}
        M.SECTION_REBUILDS = 2
    end""")(M, calls)
    count = lambda: {k: calls[k] for k in ("a", "b", "c", "live")}
    M.build_state(False)
    assert count() == {"a": 1, "b": 1, "c": 1, "live": 1}, count()      # first report: everything
    M.build_state(False)
    assert count() == {"a": 1, "b": 1, "c": 1, "live": 2}, count()      # cached ones not due
    H.df["global"]["cur_year_tick"] += 4 * 1200                       # all three expired
    M.build_state(False)
    got = count()
    assert got["live"] == 3 and got["a"] + got["b"] + got["c"] == 5, got  # only two rebuilt
    M.build_state(False)
    assert sum(calls[k] for k in ("a", "b", "c")) == 6, count()        # the third the next time
    H.df["global"]["cur_year_tick"] -= 4 * 1200


# --- the master plan ------------------------------------------------------------------

STUBS = r"""
local H = ...
H.started = nil
H.scripts = {
  ['ai-layouts'] = {STOCKPILES = {food = true}, WORKSHOPS = {}, KINDS = {'bedrooms'}},
  ['ai-builder'] = {
    start_project = function(p, now, dry) H.started = p; return {ok = true, dry_run = dry} end,
    survey = function() return {ok = true, elevation_offset = -40, citizen_elevation = 30,
                                stairs = {{x = 1, y = 2, z_top = 80, z_bottom = 60, elev_top = 40,
                                           elev_bottom = 20, count = 5}}, soil = {22, 25}} end,
  },
}
"""


def stub_scripts():
    LUA.execute(STUBS, H)


def start(plan):
    stub_scripts()
    a = {"type": "start_project", "kind": "bedrooms", "rooms": 4, "dry_run": True}
    if plan is not None:
        a["plan"] = plan
    H.action = t(a)
    return H.run("act", "{}")


@test("start_project: a valid plan reaches the builder, cleaned; none means none")
def _():
    r = start({"spine": {"x": 60, "y": 61}, "elev_lo": -20, "elev_hi": -10, "dirs": ["north", "east"],
               "district": "Deep Halls 2", "extra": "ignored"})
    assert r.ok and r.action == "start_project", dict(r)
    p = H.started.plan
    assert (p.spine.x, p.spine.y, p.elev_lo, p.elev_hi, p.elev_target) == (60, 61, -20, -10, -15)
    assert list(p.dirs.values()) == ["north", "east"] and p.district == "Deep Halls 2" and p.extra is None
    r = start({"elev_lo": 5, "elev_hi": 5, "elev_target": 3})
    assert r.ok and H.started.plan.elev_target == 3 and H.started.plan.spine is None
    r = start(None)
    assert r.ok and H.started.plan is None


@test("start_project: bad plan values are refused before the builder is asked")
def _():
    bad = [
        "north",
        {"elev_hi": 5},
        {"elev_lo": 6, "elev_hi": 5},
        {"elev_lo": -401, "elev_hi": 0},
        {"elev_lo": 0, "elev_hi": 401},
        {"elev_lo": 0.5, "elev_hi": 3},
        {"elev_lo": 0, "elev_hi": 3, "elev_target": 999},
        {"elev_lo": 0, "elev_hi": 3, "spine": {"x": 1000, "y": 5}},
        {"elev_lo": 0, "elev_hi": 3, "spine": {"x": 5}},
        {"elev_lo": 0, "elev_hi": 3, "spine": [5, 5]},
        {"elev_lo": 0, "elev_hi": 3, "dirs": []},
        {"elev_lo": 0, "elev_hi": 3, "dirs": ["north", "north"]},
        {"elev_lo": 0, "elev_hi": 3, "dirs": ["up"]},
        {"elev_lo": 0, "elev_hi": 3, "dirs": "north"},
        {"elev_lo": 0, "elev_hi": 3, "dirs": ["north", "south", "east", "west", "north"]},
        {"elev_lo": 0, "elev_hi": 3, "district": "x" * 41},
        {"elev_lo": 0, "elev_hi": 3, "district": "Halls; drop"},
        {"elev_lo": 0, "elev_hi": 3, "district": ""},
        {"elev_lo": 0, "elev_hi": 3, "district": 7},
    ]
    for pl in bad:
        r = start(pl)
        assert not r.ok and r.rejected and "plan" in r.error and H.started is None, (pl, dict(r))
    M = H.module()
    assert M.parse_plan(None) is None
    assert M.parse_plan(t({"elev_lo": 1, "elev_hi": 4, "district": "O'Brien-Hall"})).elev_target == 2


def start_styled(style, plan=None):
    stub_scripts()
    a = {"type": "start_project", "kind": "bedrooms", "rooms": 4, "dry_run": True, "style": style}
    if plan is not None:
        a["plan"] = plan
    H.action = t(a)
    return H.run("act", "{}")


@test("start_project: orientation, pillar rhythm and corridor grammar pass through; bad values refused")
def _():
    r = start_styled({"orient": 2, "rhythm": 5},
                     {"elev_lo": 0, "elev_hi": 3, "avenue": 3, "corridors": "dog-leg", "doors": "fortified"})
    assert r.ok, dict(r)
    st, pl = H.started.style, H.started.plan
    assert (st.orient, st.rhythm) == (2, 5)
    assert (pl.avenue, pl.corridors, pl.doors) == (3, "dog-leg", "fortified")
    r = start_styled({}, {"elev_lo": 0, "elev_hi": 3})
    assert r.ok and H.started.style.orient is None and H.started.style.rhythm is None
    assert H.started.plan.avenue is None and H.started.plan.corridors is None and H.started.plan.doors is None
    for style in ({"orient": 4}, {"orient": -1}, {"orient": 1.5}, {"orient": "east"},
                  {"rhythm": 2}, {"rhythm": 7}, {"rhythm": 4.5}):
        r = start_styled(style)
        assert not r.ok and r.rejected and "style." in r.error and H.started is None, (style, dict(r))
    for extra in ({"avenue": 0}, {"avenue": 4}, {"avenue": 2.5}, {"corridors": "curved"},
                  {"corridors": 1}, {"doors": "locked"}, {"doors": True}):
        r = start_styled({}, dict({"elev_lo": 0, "elev_hi": 3}, **extra))
        assert not r.ok and r.rejected and "plan." in r.error and H.started is None, (extra, dict(r))

@test("survey: hands back the builder's survey, and needs a fort")
def _():
    stub_scripts()
    r = H.run("survey")
    assert r.ok and r.citizen_elevation == 30 and r.stairs[1].elev_top == 40 and list(r.soil.values()) == [22, 25]
    LUA.execute("local H = ...; H.scripts['ai-builder'].survey = function() error('boom') end", H)
    r = H.run("survey")
    assert not r.ok and "boom" in r.error


@test("set_culture keeps the master plan's lines and the phase, cleaned and capped")
def _():
    H.action = t({"type": "set_culture", "culture": {
        "plan": ["Spine at x60 y61", "Halls: <b>-20 to -10</b>"] + [f"line {i}" for i in range(10)] + [7],
        "phase": "Founding; dig the spine"}})
    r = H.run("act", "{}")
    assert r.ok, dict(r)
    c = H.persist["ai-overseer/culture"]
    lines = list(c.plan.values())
    assert len(lines) == 8 and lines[0] == "Spine at x60 y61" and "<" not in lines[1], lines
    assert c.phase == "Founding; dig the spine"
    H.action = t({"type": "set_culture", "culture": {}})
    assert H.run("act", "{}").ok and H.persist["ai-overseer/culture"].phase is None


@test("set_culture (0.95) keeps each slider's leanings for the panel, cleaned and capped")
def _():
    H.action = t({"type": "set_culture", "culture": {
        "leanings": {"caution": "leans +21: own +11, the caverns +10", "Bad Key": "x",
                     "piety": "leans +5: <b>own</b> +5" + "x" * 200, "greed": 7}}})
    assert H.run("act", "{}").ok
    lean = H.persist["ai-overseer/culture"].leanings
    assert lean.caution == "leans +21: own +11, the caverns +10"
    assert "<" not in lean.piety and len(lean.piety) == 110 and lean.greed is None and lean["Bad Key"] is None


PROBE_STUB = r"""
local H = ...
local df, dfhack = H.df, H.dfhack
local function ref(kind, id) return {building_id = id, getType = function() return kind end} end
df.general_ref_type = {[1] = 'BUILDING_TRIGGER', [2] = 'BUILDING_TRIGGERTARGET', [3] = 'BUILDING_HOLDER',
                       BUILDING_TRIGGER = 1, BUILDING_TRIGGERTARGET = 2, BUILDING_HOLDER = 3}
df.trap_type = {[0] = 'CageTrap', [1] = 'Lever', CageTrap = 0, Lever = 1}
df.building_type = {[5] = 'Bridge', [6] = 'Trap', Bridge = 5, Trap = 6}
df.tiletype_shape = {[1] = 'FLOOR', [2] = 'STAIR_UPDOWN'}
df.tiletype = {attrs = {[10] = {shape = 1}, [11] = {shape = 2}}}
local bridge = {id = 500, x1 = 34, y1 = 120, x2 = 36, y2 = 120, direction = -1,
                getType = function() return 5 end,
                contained_items = {{item = {general_refs = {ref(1, 4045)}}}}}
local trap = {id = 501, x1 = 6, y1 = 126, x2 = 6, y2 = 126, trap_type = 0,
              getType = function() return 6 end, contained_items = {}}
df.building = {find = function(id) if id == 500 then return bridge end end}
local levers = {}
for i = 1, 50 do
  -- DF 53.16: a lever's linked mechanism sits in its target, holder = the target
  local mechs = i == 45 and {{general_refs = {ref(3, 500), ref(1, 4045)}}} or {}
  table.insert(levers, {id = 4000 + i, name = '', trap_type = 1, centerx = i, centery = 1, z = 175,
                        linked_mechanisms = mechs, jobs = {}})
end
table.insert(levers, {id = 67938, name = 'AI Gate', trap_type = 1, centerx = 36, centery = 124, z = 179,
                      linked_mechanisms = {}, jobs = {}})
df.global.world.buildings = {other = {TRAP = levers}}
dfhack.buildings = {findAtTile = function(x, y, z)
  if y == 120 and x >= 34 and x <= 36 then return bridge end
  if x == 6 and y == 126 then return trap end end}
dfhack.job = {}
dfhack.df2utf = function(s) return s end
dfhack.maps.getTileType = function(x, y, z) if x == 5 then return 11 end return 10 end
dfhack.maps.getTileFlags = function(x, y, z)
  if x == 14 then return {flow_size = 3, liquid_type = false} end
  return {flow_size = 0, liquid_type = false} end
"""


@test("probe_defence reads lever links from the mechanisms, lists the AI gate lever and the probed tiles' levers first")
def _():
    LUA.execute(PROBE_STUB, H)
    r = H.run("probe_defence", "35", "120", "112", "6", "126", "112", "14", "108", "193", "5", "66", "127")
    p = r.probe
    assert r.ok and p.levers_total == 51 and p.levers_error is None, dict(p)
    gate, works = p.levers[1], p.levers[2]
    assert gate.id == 67938 and gate.name == "AI Gate" and len(gate.targets) == 0 and gate.mechanisms == 0, dict(gate)
    assert works.id == 4045 and works.targets[1].id == 500 and works.targets[1].type == "Bridge", dict(works)
    assert len(p.levers) == 40 and len(p.levers[3].targets) == 0
    br, tr, wet, st = p.tiles[1], p.tiles[2], p.tiles[3], p.tiles[4]
    assert br.building == "Bridge" and br.linked and br.levers[1] == 4045 and br.size[1] == 3, dict(br)
    assert tr.building == "Trap" and tr.trap == "CageTrap" and not tr.linked, dict(tr)
    assert wet.building is None and wet.liquid == "water" and wet.depth == 3 and wet.shape == "FLOOR", dict(wet)
    assert st.shape == "STAIR_UPDOWN" and st.error is None, dict(st)


QUIET_STUB = r"""
local H = ...
local df, dfhack = H.df, H.dfhack
local flags = {}
for i = 0, 4 do flags[i] = {PAUSE = (i % 2 == 0), DO_MEGA = (i == 1)} end
df.announcement_type = {_first_item = 0, _last_item = 4}
df.global.d_init = {announcements = {flags = flags}}
H.flags = flags
dfhack.getDFPath = function() return '/df' end
dfhack.findScript = function() return '/df/hack/scripts/quicksave.lua' end
dfhack.filesystem.listdir = function() return {'autosave 1', 'region1'} end
dfhack.filesystem.mtime = function(p) return H.mtime end
dfhack.run_command_silent = function() H.saved = true; return '', 0 end
CR_OK = 0
df.global.plotinfo.main = {autosave_request = false}
"""


@test("unattended: quiet_announcements walks every kind (enum first..last) and clears pause and box")
def _():
    LUA.execute(QUIET_STUB, H)
    H.action = t({"type": "quiet_announcements", "dry_run": True})
    r = H.run("act", "{}")
    assert r.ok and r.pausing == 3 and r.boxes == 1 and r.kinds == 5, dict(r)
    assert H.flags[0].PAUSE                                     # dry run: unchanged
    H.action = t({"type": "quiet_announcements"})
    r = H.run("act", "{}")
    assert r.ok and r.pausing == 3 and not any(H.flags[i].PAUSE or H.flags[i].DO_MEGA for i in range(5))


@test("unattended: no extra save when the game saved itself in the last 15 minutes")
def _():
    import time as _t
    LUA.execute(QUIET_STUB, H)
    H.saved = None
    H.mtime = int(_t.time()) - 120
    H.action = t({"type": "save_game"})
    r = H.run("act", "{}")
    assert r.ok and r.already and "2 minute" in r.by and not H.saved, dict(r)
    H.mtime = int(_t.time()) - 3600
    r = H.run("act", "{}")
    assert r.ok and not r.already and H.saved, dict(r)
    # Windows: the file time in 100 ns steps since 1601 (what DF 53.16 gave in the game)
    H.saved = None
    H.mtime = (int(_t.time()) - 300 + 11644473600) * 10_000_000
    r = H.run("act", "{}")
    assert r.ok and r.already and "5 minute" in r.by and not H.saved, dict(r)


PRUNE_STUB = r"""
local H = ...
local dfhack = H.dfhack
H.cmds = {}
dfhack.findScript = function(name) if H.no_script then return nil end return '/df/hack/scripts/' .. name .. '.lua' end
dfhack.run_command_silent = function(...) table.insert(H.cmds, table.concat({...}, ' ')); return 'ok', 0 end
CR_OK = 0
"""


@test("prune_remains (0.104): deteriorate for corpses and useless parts only, then enabled; dry run and no script")
def _():
    LUA.execute(PRUNE_STUB, H)
    H.no_script = False
    H.action = t({"type": "prune_remains", "dry_run": True})
    r = H.run("act", "{}")
    assert r.ok and r.dry_run and len(H.cmds) == 0, dict(r)
    H.action = t({"type": "prune_remains"})
    r = H.run("act", "{}")
    cmds = [H.cmds[i] for i in range(1, len(H.cmds) + 1)]
    assert r.ok and cmds == ["deteriorate enable corpses,unusable-parts", "enable deteriorate"], (dict(r), cmds)
    H.no_script = True
    r = H.run("act", "{}")
    assert not r.ok and "deteriorate" in r.error, dict(r)
    H.no_script = False


@test("ledger_set (0.104.0): only ledger fields, kept with accents, bounded; read back by ledger_data; allowed while halted")
def _():
    H.action = t({"type": "ledger_set", "values": {"ai_alert_raised": True, "memorials_built": ["Hall of Ôlon"],
                                                   "stuck_cancelled": {"cloth_bag": {"tick": 5}}, "tree_year": {}}})
    r = H.run("act", "{}")
    assert r.ok, dict(r)
    led = H.persist["ai-overseer/ledger"]
    assert led.ai_alert_raised is True and led.memorials_built[1] == "Hall of Ôlon", dict(led)
    assert led.stuck_cancelled.cloth_bag.tick == 5
    M = H.module()
    assert M.ledger_data().ai_alert_raised is True
    H.action = t({"type": "ledger_set", "values": {"anything_else": 1}})
    r = H.run("act", "{}")
    assert not r.ok and "not a ledger field" in r.error, dict(r)
    H.action = t({"type": "ledger_set", "values": {"gardens_built": [f"g{i}" for i in range(700)]}})
    r = H.run("act", "{}")
    assert not r.ok and "too much" in r.error, dict(r)
    assert H.persist["ai-overseer/ledger"].ai_alert_raised is True          # unchanged by the refusals
    H.scripts = t({})
    H.scripts["ai-status"] = LUA.eval("{is_halted = function() return true end}")
    H.action = t({"type": "ledger_set", "values": {"kitchen_ban": True}})
    r = H.run("act", "{}")
    assert r.ok and H.persist["ai-overseer/ledger"].kitchen_ban is True, dict(r)


@test("close_meeting (0.104.0): leaves only DF's meeting screen; refused when none is open")
def _():
    LUA.execute(r"""local H = ...
      H.focus = 'dwarfmode/Default'
      H.dfhack.gui = {getCurFocus = function() return {H.focus} end, getDFViewscreen = function() return {} end}
    """, H)
    H.action = t({"type": "close_meeting"})
    r = H.run("act", "{}")
    assert not r.ok and r.rejected and "no meeting" in r.error, dict(r)
    LUA.execute(r"""local H = ...
      H.focus = 'dwarfmode/Diplomacy/Meeting'
      H.modules = {gui = {simulateInput = function(_, key) if key == 'LEAVESCREEN' then H.focus = 'dwarfmode/Default' end end}}
    """, H)
    r = H.run("act", "{}")
    assert r.ok and r.screen == "dwarfmode/Diplomacy/Meeting", dict(r)


@test("slaughter_pick (0.104.7): the most numerous kind (3+), a male while it has two or more; none from small herds")
def _():
    M = H.module()
    a = lambda i, r, m: t({"id": i, "race": r, "male": m})
    pick, race, n = M.slaughter_pick(t([a(1, "COW", False), a(2, "COW", True), a(3, "COW", True), a(4, "COW", False),
                                        a(5, "GOAT", True), a(6, "GOAT", False), a(7, "GOAT", False)]))
    assert race == "COW" and n == 4 and pick.id == 2, (race, n, pick.id)
    pick, race, n = M.slaughter_pick(t([a(1, "PIG", True), a(2, "PIG", False), a(3, "PIG", False)]))
    assert pick.id == 2, pick.id                                   # one male only: a female goes
    assert M.slaughter_pick(t([a(1, "CAT", True), a(2, "CAT", False)])) is None


@test("instrument_pick (0.104.8): a hand-held instrument the tool lists, the fewest parts first")
def _():
    M = H.module()
    defs = t([{"name": "munsog", "pieces": 1, "flags": ["PLACED_AS_BUILDING"]},
              {"name": "katad", "pieces": 4, "flags": []}, {"name": "gelut", "pieces": 2, "flags": []},
              {"name": "osp", "pieces": 0, "flags": []}])
    p = M.instrument_pick(t({"munsog": True, "katad": True, "gelut": True}), defs)
    assert p.name == "gelut", p.name                         # osp isn't listed; munsog stands as a building
    assert M.instrument_pick(t({"munsog": True}), defs) is None


@test("hazards: fire near a dwarf, a cloud, a dwarf in deep water, one in magma, a berserk one, caged invaders")
def _():
    M = H.module()
    LUA.execute("""local M, H = ...
      local function u(id, x, y, z, extra)
        local t = {id = id, pos = {x = x, y = y, z = z}, mood = -1, flags1 = {}}
        for k, v in pairs(extra or {}) do t[k] = v end
        return t
      end
      H.df.flow_type = {[1] = 'Fire', [2] = 'MaterialGas', [3] = 'Miasma'}
      H.df.mood_type = {Berserk = 7}
      H.df.global.flows = {{density = 50, type = 1, pos = {x = 12, y = 10, z = 5}},
                           {density = 20, type = 2, pos = {x = 40, y = 10, z = 5}},
                           {density = 10, type = 3, pos = {x = 0, y = 0, z = 0}}}
      local cits = {u(1, 10, 10, 5), u(2, 50, 50, 5, {mood = 7}), u(3, 60, 60, 5)}
      local tiles = {['50,50,5'] = {flow_size = 6, liquid_type = false}, ['60,60,5'] = {flow_size = 5, liquid_type = true}}
      H.dfhack.units = {getCitizens = function() return cits end, getReadableName = function(x) return 'D' .. x.id end,
                        isCitizen = function(x) return false end, isActive = function() return true end,
                        isInvader = function() return true end, isDanger = function() return true end}
      H.dfhack.maps.getWalkableGroup = function() return 1 end
      H.dfhack.maps.getTileFlags = function(x, y, z) return tiles[x .. ',' .. y .. ',' .. z] or {flow_size = 0} end
      H.df.global.world.units = {active = {{flags1 = {caged = true}}, {flags1 = {caged = false}}}}
      M.txt = function(x) return x end
    """, M, H)
    r = M.get_hazards()
    assert r.fires == 1 and r.fire_near == 2 and r.clouds == 1 and r.miasma == 1, (r.fires, r.fire_near, r.clouds)
    assert len(r.wet) == 1 and r.wet[1].id == 2 and len(r.burning) == 1 and r.burning[1].id == 3
    assert len(r.berserk) == 1 and r.berserk[1].id == 2 and r.caged == 1

@test("locations (0.83): each one's wanted and held supplies, its books, its posts filled and empty")
def _():
    M = H.module()
    LUA.execute("""local M, df, dfhack = ...
        local function vec(l) local t = {}; for i, v in ipairs(l) do t[i - 1] = v end
            return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end}) end
        local real = ipairs
        M.ipairs = function(t)
            if type(t) == 'table' and rawget(t, 0) ~= nil then
                local i = -1
                return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
            end
            return real(t)
        end
        df.abstract_building_type = {[1] = 'HOSPITAL', [2] = 'LIBRARY'}
        df.occupation_type = {[5] = 'SCRIBE'}
        local hosp = {id = 3, flags = {}, occupations = vec({}),
            getType = function() return 1 end,
            getContents = function() return {location_tier = 1, location_value = 50, desired_thread = 5, count_thread = 0,
                                              desired_cloth = 5, count_cloth = 2} end}
        local lib = {id = 4, flags = {}, copied_artifacts = vec({11, 12}),
            occupations = vec({{type = 5, histfig_id = -1}, {type = 5, histfig_id = 9}}),
            getType = function() return 2 end,
            getContents = function() return {desired_paper = 0, count_paper = 0, desired_copies = 2} end}
        dfhack.world.getCurrentSite = function() return {buildings = vec({hosp, lib})} end
    """, M, H.df, H.dfhack)
    r = M.get_locations()
    assert r.total == 2 and r.count.HOSPITAL == 1, dict(r.count)
    h, lib = r.list[1], r.list[2]
    assert h.type == "HOSPITAL" and h.want.thread == 5 and h.have.thread == 0 and h.have.cloth == 2, dict(h.want)
    assert lib.books == 2 and lib.want.copies == 2 and lib.jobs.SCRIBE.posts == 2 and lib.jobs.SCRIBE.filled == 1


@test("petition orders (0.87): set only from 0/1 to 0/1; refused when any reads otherwise; dry run says what")
def _():
    M = H.module()
    g = H.df["global"]
    for k in ("citizenship",):
        g["standing_orders_petition_" + k] = 0
    for k in ("performer", "scholar", "monster_hunter", "mercenary", "sanctuary"):
        g["standing_orders_petition_resident_" + k] = 0
    act = M.ACTIONS.petition_orders
    d = act(t({"orders": {"performer": 1}, "dry_run": True}))
    assert d.ok and d.dry_run and d.would_set.performer == 1 and g["standing_orders_petition_resident_performer"] == 0
    r = act(t({"orders": {"performer": 1, "citizenship": 1}}))
    assert r.ok and g["standing_orders_petition_resident_performer"] == 1 and g["standing_orders_petition_citizenship"] == 1
    assert not act(t({"orders": {"performer": 3}})).ok
    g["standing_orders_petition_resident_scholar"] = 2
    r = act(t({"orders": {"performer": 0}}))
    assert r.ok is False and "not 0 or 1" in r.error and g["standing_orders_petition_resident_performer"] == 1



PETITION_FAKES = r"""
local M, df, dfhack = ...
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
df.agreement_details_type = enum({[0] = 'JoinParty', [1] = 'Location', [2] = 'Residency'})
df.abstract_building_type = enum({[0] = 'MEAD_HALL', [1] = 'TEMPLE', [2] = 'GUILDHALL'})
df.religious_practice_type = enum({[-1] = 'NONE', [0] = 'WORSHIP_HFID', [1] = 'RELIGION_ENID'})
df.profession = enum({[0] = 'MINER', [1] = 'MASON'})
local function agr(id, loc, extra)
  local L = {type = loc, tier = 1, deity_type = -1, deity_data = {}, profession = -1, site = 7}
  for k, v in pairs(extra or {}) do L[k] = v end
  return {id = id, flags = {petition_not_accepted = true},
          details = vec({{type = 1, year = 150, year_tick = 0, data = {Location = L}}})}
end
local A = {[174] = agr(174, 1, {deity_type = 0, deity_data = {Deity = 55}}),
           [175] = agr(175, 2, {profession = 1}),
           [176] = {id = 176, flags = {}, details = vec({{type = 2, year = 150, year_tick = 0, data = {}}})}}
df.agreement = {find = function(id) return A[id] end,
                get_vector = function() return vec({A[174], A[175], A[176]}) end}
df.historical_figure = {find = function(id) if id == 55 then return {name = 'Rimtar'} end end}
df.historical_entity = {find = function() return nil end}
dfhack.translation = {translateName = function(n) return n end}
df.global.plotinfo.petitions = vec({174, 175, 176})
df.global.plotinfo.trees_removed = 640
df.global.plotinfo.main = {custom_difficulty = {tree_fell_count = 100, tree_fell_count_savage = 1000}}
df.global.plotinfo.caravans = vec({})
return A
"""


@test("location petitions (0.89): what each asks for; agreed ones listed; answering as the screen does")
def _():
    M = H.module()
    A = LUA.execute(PETITION_FAKES, M, H.df, H.dfhack)
    p = M.get_petitions()
    by = {e.id: e for e in p.pending.values()}
    assert by[174].loc == "TEMPLE" and by[174].deity_hf == 55 and by[174].deity == "Rimtar" and by[174].days == 0, dict(by[174])
    assert by[175].loc == "GUILDHALL" and by[175].profession == "MASON", dict(by[175])
    assert p.agreed is None                                            # all three still wait
    act = M.ACTIONS.answer_petition
    assert not act(t({"id": 176, "accept": True})).ok                   # residency: DF's standing orders
    d = act(t({"id": 174, "accept": True, "dry_run": True}))
    assert d.ok and d.dry_run and A[174].flags.petition_not_accepted is True
    r = act(t({"id": 174, "accept": True}))
    assert r.ok and r.accepted and A[174].flags.petition_not_accepted is False, dict(r)
    pl = H.df["global"]["plotinfo"]["petitions"]
    assert pl.n == 2 and pl[0] == 175
    r = act(t({"id": 175, "accept": False}))
    assert r.ok and r.declined and A[175].flags.petition_not_accepted is True and pl.n == 1
    assert not act(t({"id": 174, "accept": True})).ok                   # no longer waiting
    p = M.get_petitions()
    agreed = list(p.agreed.values())
    assert len(agreed) == 1 and agreed[0].id == 174 and agreed[0].deity_hf == 55, agreed
    dp = M.get_diplomacy()
    assert dp.trees_removed == 640 and dp.tree_cap == 100 and dp.elves is None, dict(dp)


KITCHEN_FAKES = r"""
local M, df, dfhack = ...
local function vec(items)
  local v = {n = #items}
  for i, x in ipairs(items) do v[i - 1] = x end
  return setmetatable(v, {__len = function(self) return self.n end})
end
local _ipairs = ipairs
M.ipairs = function(t)
  if type(t) == 'table' and t.n ~= nil then
    return function(_, i) i = i + 1; if i < t.n then return i, t[i] end end, t, -1
  end
  return _ipairs(t)
end
df.item_type = {PLANT = 53, PLANT_GROWTH = 54}
local function mat(id, brews, cooks)
  return {id = id, flags = {EDIBLE_COOKED = cooks},
          reaction_product = {id = vec(brews and {{value = 'SEED_MAT'}, {value = 'DRINK_MAT'}} or {{value = 'SEED_MAT'}})}}
end
local mats = {['419:0'] = mat('STRUCTURAL', true, true), ['420:0'] = mat('FRUIT', true, true),
              ['421:0'] = mat('LEAF', false, true), ['422:0'] = mat('STRUCTURAL', true, true)}
df.global.world.raws = {plants = {all = vec({
  {id = 'HELMET', material_defs = {type = {drink = 5}, idx = {drink = 1}},
   material = vec({mats['419:0']}), growths = vec({})},
  {id = 'BERRY', material_defs = {type = {drink = 5}, idx = {drink = 2}},
   material = vec({}), growths = vec({{mt = 421, mi = 0}, {mt = 420, mi = 0}})},
  {id = 'GRASS', material_defs = {type = {drink = -1}, idx = {drink = -1}},
   material = vec({mats['422:0']}), growths = vec({})}})}}
dfhack.matinfo = {
  find = function(pid, mid) if pid == 'HELMET' then return {type = 419, index = 0} end end,
  decode = function(g) return {type = g.mt, index = g.mi, material = mats[g.mt .. ':' .. g.mi]} end}
local ex = {}
local function key(t, s, mt, mi) return t .. ':' .. s .. ':' .. mt .. ':' .. mi end
dfhack.kitchen = {
  addExclusion = function(c, t, s, mt, mi) local k = key(t, s, mt, mi); if ex[k] then return false end; ex[k] = true; return true end,
  removeExclusion = function(c, t, s, mt, mi) local k = key(t, s, mt, mi); if not ex[k] then return false end; ex[k] = nil; return true end}
return ex
"""


@test("kitchen_brewables (0.100): bans cooking brewable plants and growths; lifts only the AI's own bans")
def _():
    M = H.module()
    ex = LUA.execute(KITCHEN_FAKES, M, H.df, H.dfhack)
    ex["54:0:421:0"] = True                                  # the player's own ban (a leaf)
    ex["53:-1:419:0"] = True                                 # ... and one that matches a brewable
    act = M.ACTIONS.kitchen_brewables
    assert not act(t({})).ok                                 # ban must be true or false
    d = act(t({"ban": True, "dry_run": True}))
    assert d.ok and d.dry_run and d.kinds == 2 and "54:1:420:0" not in list(ex.keys()), dict(d)
    r = act(t({"ban": True}))
    assert r.ok and r.kinds == 2 and r.banned == 1 and ex["54:1:420:0"], dict(r)   # the fruit; the plant was banned
    assert len(H.persist["ai-overseer/kitchen"].bans) == 1
    r = act(t({"ban": False}))
    assert r.ok and r.lifted == 1, dict(r)
    assert sorted(ex.keys()) == ["53:-1:419:0", "54:0:421:0"], list(ex.keys())         # the player's stay
    assert len(H.persist["ai-overseer/kitchen"].bans) == 0


@test("expel (0.100 security): at most one dwarf a game week, whoever asks; kept in the save")
def _():
    M = H.module()
    calls = LUA.eval("{n = 0}")
    H.scripts = LUA.eval("""function(calls) return {['ai-society'] = {expel_one = function(txt, id)
        calls.n = calls.n + 1; return {ok = true, unit_id = id or 5} end}} end""")(calls)
    act = M.ACTIONS.expel_dwarf
    assert act(t({})).ok and calls.n == 1
    r = act(t({"unit_id": 9}))
    assert not r.ok and calls.n == 1, dict(r)                       # a day later: refused
    H.df["global"]["cur_year_tick"] += 7 * 1200
    assert act(t({"unit_id": 9})).ok and calls.n == 2                # a week on
    H.df["global"]["cur_year_tick"] -= 7 * 1200

@test("bench_jobs (0.104.32): blank slabs on a full mason's bench, room made by lifting autoslab's unworked engrave jobs")
def _():
    env = H.module()
    r = LUA.execute(r"""
    local env, df, dfhack = ...
    local JT = {ConstructCoffin = 1, ConstructSlab = 2, EngraveSlab = 3}
    df.job_type = {}
    for k, v in pairs(JT) do df.job_type[k] = v; df.job_type[v] = k end
    df.workshop_type = {Masons = 5, [5] = 'Masons'}
    df.item_type = {BOULDER = 1, WOOD = 2}
    df.job_item_vector_id = {BOULDER = 1, WOOD = 2}
    df.job_item = {new = function() return {flags3 = {}} end}
    local bench = {type = 5, id = 13, jobs = {}}
    function bench:getBuildStage() return 1 end
    function bench:getMaxBuildStage() return 1 end
    local function job(t, order, worker) return {job_type = JT[t], order_id = order or -1, worker = worker} end
    table.insert(bench.jobs, job('ConstructCoffin', -1, 7))
    table.insert(bench.jobs, job('ConstructCoffin'))
    table.insert(bench.jobs, job('ConstructCoffin'))
    for i = 1, 6 do table.insert(bench.jobs, job('EngraveSlab', 1500 + i)) end
    table.insert(bench.jobs, job('EngraveSlab', 1600, 9))           -- one being worked: never lifted
    df.global.world.buildings = {other = {WORKSHOP_ANY = {bench}}}
    df.global.world.manager_orders = {all = {}}
    dfhack.job = {
      getWorker = function(j) return j.worker and {id = j.worker} or nil end,
      removeJob = function(j)
        for i, x in ipairs(bench.jobs) do if x == j then table.remove(bench.jobs, i) return true end end
        return false end,
      createLinked = function() return {job_items = {elements = {insert = function() end}}, material_category = {}} end,
      assignToWorkshop = function(j, b) table.insert(b.jobs, j) end,
    }
    local full = env.act_bench_jobs({kind = 'slab', count = 3})
    local r = env.act_bench_jobs({kind = 'slab', count = 3, make_room = true})
    local slabs, engrave = 0, 0
    for _, j in ipairs(bench.jobs) do
      if j.job_type == 2 then slabs = slabs + 1 elseif j.job_type == 3 then engrave = engrave + 1 end
    end
    return {full_ok = full.ok == true, ok = r.ok, count = r.count, lifted = r.lifted, slabs = slabs, engrave = engrave, n = #bench.jobs}
    """, env, H.df, H.dfhack)
    assert not r["full_ok"], "a full bench without make_room is refused"
    assert r["ok"] and r["count"] == 3 and r["lifted"] == 3, dict(r)
    assert r["slabs"] == 3 and r["engrave"] == 4 and r["n"] == 10, dict(r)


@test("clear_orphan_jobs (0.104.34): unworked jobs of orders that are gone come off; worked ones, the player's and live orders' stay")
def _():
    env = H.module()
    r = LUA.execute(r"""
    local env, df, dfhack = ...
    df.job_type = {MakeRing = 1, [1] = 'MakeRing'}
    df.global.world.manager_orders = {all = {{id = 7}}}
    local jobs = {
      {job_type = 1, order_id = 5},              -- gone order, unworked: off
      {job_type = 1, order_id = 5, worker = 3},  -- worked: stays
      {job_type = 1, order_id = 7},              -- live order: stays
      {job_type = 1, order_id = -1},             -- the player's: stays
      {job_type = 1, order_id = 6},              -- gone order: off
    }
    local function relink()
      local head = {next = nil}
      local prev = head
      for _, j in ipairs(jobs) do local l = {item = j}; prev.next = l; prev = l end
      df.global.world.jobs = {list = head}
    end
    relink()
    dfhack.job = {
      getWorker = function(j) return j.worker and {id = j.worker} or nil end,
      getHolder = function(j) return {id = 1} end,
      removeJob = function(j) for i, x in ipairs(jobs) do if x == j then table.remove(jobs, i) relink() return true end end end,
    }
    local before = env.orphan_jobs(true)
    local r = env.act_clear_orphan_jobs({})
    local again = env.act_clear_orphan_jobs({})
    return {before = before, removed = r.removed, left = #jobs, again_ok = again.ok == true}
    """, env, H.df, H.dfhack)
    assert r["before"] == 2 and r["removed"] == 2 and r["left"] == 3 and not r["again_ok"], dict(r)


@test("death_details (0.104.100): DF's cause and the killer (a great beast); a second death of one unit is `again`")
def _():
    env = H.module()
    r = LUA.execute(r"""
    local env, df, dfhack = ...
    df.death_type = {[2] = 'STRUCK_DOWN'}
    local victim = {id = 5, counters = {death_id = 70}}
    local titan = {id = 9}
    df.unit = {find = function(id) return ({[5] = victim, [9] = titan})[id] end}
    df.incident = {find = function(id) return id == 70 and {death_cause = 2, criminal = 9} or nil end}
    dfhack.units.getReadableName = function(u) return u == titan and 'Ume, Swamp Titan' or 'a dwarf' end
    dfhack.units.isGhost = function() return false end
    dfhack.units.isGreatDanger = function(u) return u == titan end
    dfhack.units.isCitizen = function() return false end
    dfhack.units.isOwnCiv = function() return false end
    dfhack.units.isAnimal = function() return false end
    env.DEATHS_TOLD = {}
    local a, b = {}, {}
    env.death_details(a, 5)
    env.death_details(b, 5)
    return {cause = a.cause, killer = a.killer, kind = a.killer_kind, again1 = a.again or false, again2 = b.again or false}
    """, env, H.df, H.dfhack)
    assert (r["cause"], r["killer"], r["kind"], r["again1"], r["again2"]) == \
        ("STRUCK_DOWN", "Ume, Swamp Titan", "great beast", False, True), dict(r)


@test("free_slabs (0.104.42): forbidden memorial slabs unforbidden, their suspended slab buildings resumed")
def _():
    env = H.module()
    r = LUA.execute(r"""
    local env, df, dfhack = ...
    df.slab_engraving_type = {Memorial = 1}
    df.specific_ref_type = {JOB = 3}
    df.building_type = {Slab = 9}
    local bld = {getType = function() return 9 end}
    local job = {flags = {suspend = true}}
    local a = {engraving_type = 1, flags = {forbid = true}, specific_refs = {}}
    local b = {engraving_type = 1, flags = {}, specific_refs = {{type = 3, data = {job = job}}}}
    local c = {engraving_type = 0, flags = {forbid = true}, specific_refs = {}}      -- not a memorial
    df.global.world.items = {other = {SLAB = {a, b, c}}}
    dfhack.units.getCitizens = function() return {} end
    dfhack.items = {getPosition = function() return 1, 1, 1 end}
    dfhack.job = {getHolder = function(j) return bld end}
    local r = env.act_free_slabs({})
    return {ok = r.ok, unf = r.unforbidden, res = r.resumed, a = a.flags.forbid, c = c.flags.forbid, j = job.flags.suspend}
    """, env, H.df, H.dfhack)
    assert r["ok"] and r["unf"] == 1 and r["res"] == 1 and not r["a"] and r["c"] and not r["j"], dict(r)


@test("restrict_water (0.104.45): the tile over water or ice gets restricted traffic; a hand-set one is left")
def _():
    env = H.module()
    r = LUA.execute(r"""
    local env, df, dfhack = ...
    df.tile_traffic = {Normal = 0, Low = 1, High = 2, Restricted = 3}
    df.tiletype_material = {FROZEN_LIQUID = 7, STONE = 1}
    df.tiletype = {attrs = {[1] = {material = 1}, [2] = {material = 7}}}
    local tiles = {}
    local function key(x, y, z) return x .. ',' .. y .. ',' .. z end
    tiles[key(10, 10, 5)] = {flow_size = 7, liquid_type = false, tt = 1}   -- water
    tiles[key(11, 10, 5)] = {flow_size = 0, liquid_type = false, tt = 2}   -- ice
    tiles[key(12, 10, 5)] = {flow_size = 3, liquid_type = true, tt = 1}    -- magma: not this
    tiles[key(13, 10, 5)] = {flow_size = 7, liquid_type = false, tt = 1}   -- water, its top set by hand
    for x = 10, 13 do tiles[key(x, 10, 6)] = {flow_size = 0, traffic = 0, tt = 1} end
    tiles[key(13, 10, 6)].traffic = 2
    _G.xyz2pos = _G.xyz2pos or function(x, y, z) return {x = x, y = y, z = z} end
    env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
    dfhack.maps.getTileSize = function() return 20, 20, 10 end
    dfhack.maps.getTileFlags = function(p) return tiles[key(p.x, p.y, p.z)] end
    dfhack.maps.getTileType = function(p) local t = tiles[key(p.x, p.y, p.z)] return t and t.tt end
    local r = env.act_restrict_water({levels = {5}, x = 10, y = 10, radius = 5})
    return {ok = r.ok, marked = r.marked, seen = r.water_tiles, a = tiles[key(10, 10, 6)].traffic,
            b = tiles[key(11, 10, 6)].traffic, c = tiles[key(12, 10, 6)].traffic, d = tiles[key(13, 10, 6)].traffic}
    """, env, H.df, H.dfhack)
    assert r["ok"] and r["marked"] == 2 and r["seen"] == 3, dict(r)
    assert r["a"] == 3 and r["b"] == 3 and r["c"] == 0 and r["d"] == 2, dict(r)



@test("memory (0.104.62): a long kind comes as the save keeps it (raw JSON, decoded in Python, not in Lua)")
def _():
    reset()
    big = "x" * 30000
    raw = '{"fort":"Enxah","text":"' + big + '"}'
    r = LUA.execute("""
    local H, raw, small = ...
    local written = {}
    H.dfhack.persistent.getSiteDataString = function(k)
        if k == 'ai-overseer/mem/working' then return raw end
        if k == 'ai-overseer/mem/atlas' then return small end
        return nil
    end
    H.persist['ai-overseer/mem/atlas'] = {fort = 'Enxah', text = 'short'}
    local real_open = io.open
    io.open = function(path, mode)
        return {write = function(_, d) written[path] = d end, close = function() end}
    end
    local okold, old = pcall(H.run, 'memory')          -- an older brain: no raw files
    local oldk = H.files['/df/dfhack-config/ai-overseer/memory-from-save.json'].kinds
    local old_raw = oldk.working and oldk.working.raw
    local ok, out = pcall(H.run, 'memory', 'raw')
    io.open = real_open
    H.dfhack.persistent.getSiteDataString = nil
    local k = H.files['/df/dfhack-config/ai-overseer/memory-from-save.json'].kinds
    return {ok = ok and out.present, raw = k.working.raw,
            body = written['/df/dfhack-config/ai-overseer/memory-from-save.working.json'],
            atlas = k.atlas.text, old_raw = old_raw or false}
    """, H, raw, '{"fort":"Enxah","text":"short"}')
    assert r["ok"] and r["raw"].endswith("memory-from-save.working.json"), dict(r)
    assert r["body"] == raw and r["atlas"] == "short", (len(r["body"] or ""), r["atlas"])
    assert r["old_raw"] is False, "raw files only when asked"
    # the brain's side reads it back as {fort, text}
    import json as _json, tempfile
    sys.path.insert(0, str(ROOT / "brain"))
    from bridge import Bridge
    d = Path(tempfile.mkdtemp())
    (d / "w.json").write_text(raw, encoding="utf-8")
    (d / "bad.json").write_text("{not json", encoding="utf-8")
    (d / "from.json").write_text(_json.dumps({"kinds": {"working": {"raw": str(d / "w.json")},
                                                         "chronicle": {"raw": str(d / "bad.json")},
                                                         "atlas": {"fort": "Enxah", "text": "short"}}}),
                                 encoding="utf-8")
    b = Bridge.__new__(Bridge)
    b._call = lambda *a, timeout=None: {"present": True, "file": str(d / "from.json")}
    m = b.load_memory()
    assert m["kinds"]["working"] == {"fort": "Enxah", "text": big} and m["kinds"]["atlas"]["text"] == "short"
    assert "chronicle" not in m["kinds"], "a raw file that can't be read is dropped, not half-read"


@test("0.104.119: a recipe that names a material (green glass) matches only orders in it")
def _():
    reset()
    env = H.module()
    LUA.execute("local H = ...; H.dfhack.matinfo = {find = function(tok) if tok == 'GLASS_GREEN' then "
                "return {type = 3, index = -1} end end}", H)
    glass = t({"material": "GLASS_GREEN"})
    assert env.material_matches(glass, t({"mat_type": 3, "mat_index": -1}))
    assert not env.material_matches(glass, t({"mat_type": 0, "mat_index": 12})), "rock crafts aren't glass_crafts"
    assert env.material_matches(t({"kind": "stone"}), t({"mat_type": 0, "mat_index": 12}))

@test("0.104.121: health counts every patient and every dwarf on the Rest job, the list capped at 30")
def _():
    reset()
    M = H.module()
    LUA.execute("""local M, H = ...
      H.df.job_type = {Rest = 99}
      local cits = {}
      for i = 1, 40 do
        local rq = {needs_healthcare = true, rq_dressing = (i % 2 == 0), rq_suture = (i == 3)}
        cits[i] = {id = i, pos = {x = i, y = 0, z = 1}, health = {flags = rq},
                   body = {wounds = {{flags = {infection = (i <= 5)}}}}, syndromes = {active = {}},
                   job = {current_job = (i <= 12) and {job_type = 99} or nil}}
      end
      table.insert(cits, {id = 41, pos = {x = 0, y = 0, z = 1}, health = {flags = {}}, body = {wounds = {}},
                          syndromes = {active = {}}, job = {current_job = {job_type = 99}}})   -- resting, not a patient
      H.dfhack.units = {getCitizens = function() return cits end, getReadableName = function(x) return 'D' .. x.id end}
      H.dfhack.job = {getName = function() return 'Rest' end}
      H.dfhack.buildings = {findCivzonesAt = function(p) if p.x <= 3 then return {{id = 287}} end return {} end,
                            findAtTile = function() return nil end}
      M.hospital_survey = function() M.HOSPITAL_ZONES = {[287] = true}; return {} end
      M.txt = function(x) return x end
    """, M, H)
    r = M.get_health()
    assert r.total == 40 and len(r.patients) == 30, (r.total, len(r.patients))
    assert r.resting == 13 and r.resting_in_hospital == 4, (r.resting, r.resting_in_hospital)
    assert r.infected == 5 and r.needs_counts.dressing == 20 and r.needs_counts.suture == 1


@test("0.104.124: allow_stone frees an ore only when asked with ore = true")
def _():
    reset()
    M = H.module()
    LUA.execute("""local M, H = ...
      local econ = {[0] = true, [1] = true}
      setmetatable(econ, {__len = function() return 2 end})
      H.df.global.plotinfo.economic_stone = econ
      H.df.global.world.raws = {inorganics = {all = {[0] = {id = 'MAGNETITE', metal_ore = {mat_index = {1}}},
                                                     [1] = {id = 'GYPSUM', metal_ore = {mat_index = {}}}}}}
      H.econ = econ
    """, M, H)
    LUA.execute("""local M = ...
      local ip = ipairs
      M.ipairs = function(t) if type(t) == 'table' and rawget(t, 0) ~= nil then
          local i = -1; return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end end
        return ip(t) end
    """, M)
    r = M.act_allow_stone(t({"stone": "MAGNETITE"}))
    assert not r.ok and "ore" in r.error, dict(r)
    r = M.act_allow_stone(t({"stone": "MAGNETITE", "ore": True}))
    assert r.ok and H.econ[0] is False, dict(r)


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

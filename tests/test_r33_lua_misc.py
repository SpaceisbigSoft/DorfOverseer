"""Round 0.105.33, group lua-misc: the military orders, the gear report's
cost, the quarry's scan, tribute by the Rules, the settings window (stale
saves, the Army tab), the title screen's revive, and Lows.

    python tests/test_r33_lua_misc.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from lua_modules_util import with_util  # noqa: E402
from harness import test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import test_military as TM  # noqa: E402  (its fakes; its tests don't run on import)
import test_industry as TI  # noqa: E402
import test_world as TW  # noqa: E402

LUA_DIR = ROOT / "lua"
GUI = (LUA_DIR / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")


def code_has(src: str, s: str) -> bool:
    return s in src


# --- L7 military 1398-1429: a refused kill list keeps the shelter order --------------------------

KILL_FAKE = """local env = ...
    env.fort_squad = function(id) return env.df.squad.find(id) end
    local mt = getmetatable(env.df.squad.find(7).orders)
    env.df.squad_order_kill_listst = {new = function()
        return setmetatable({units = setmetatable({}, mt), _kill = true}, {__index = {delete = function() end}}) end,
        is_instance = function(_, o) return type(o) == 'table' and o._kill == true end}
    env.LIVE = {}
    env.df.unit.find = function(id) return env.LIVE[id] end
    env.dfhack.units = env.dfhack.units or {}
    env.dfhack.units.isDead = function() return false end
"""


@test("L7 military orders: no live target -> rejected and the shelter order stays (it was dropped first)")
def _():
    lua, n, env, eq, sq7, sq8 = TM.army()
    lua.execute(KILL_FAKE, env)
    assert env.shelter(7, False).ok and n(sq7.orders) == 1
    k = env.orders(7, lua.table(123456), False)
    assert not k.ok and k.rejected and "on the map" in k.error, dict(k)
    assert n(sq7.orders) == 1 and sq7.orders[0]._defend, "the shelter order was taken off"


@test("L7 military orders: a live threat -> the AI's old order replaced by the kill order")
def _():
    lua, n, env, eq, sq7, sq8 = TM.army()
    lua.execute(KILL_FAKE, env)
    lua.execute("local env = ...; env.LIVE[555] = {id = 555, mood = -1}; env.kill_target_ok = function() return true end", env)
    env.shelter(7, False)
    k = env.orders(7, lua.table(555), False)
    assert k.ok and k.targets == 1 and k.replaced == 1, dict(k)
    assert n(sq7.orders) == 1 and sq7.orders[0]._kill


@test("L7 military Low: a sheltering squad asked to hold the gate is not told it holds the gate already")
def _():
    lua, n, env, eq, sq7, sq8 = TM.army()
    lua.execute(KILL_FAKE, env)
    env.shelter(7, False)
    r = env.defend(7, 99)
    assert "already holds the gate" not in str(r.error), dict(r)


@test("L7 military Low: pick_template and set_uniform share one crossbow-name test")
def _():
    lua, n, env, eq, sq7, sq8 = TM.army()
    assert env.ranged_template_name("Ranged, leather") and env.ranged_template_name("Archers")
    assert env.ranged_template_name("Crossbow") and not env.ranged_template_name("Melee, metal")
    src = (LUA_DIR / "ai-military.lua").read_text(encoding="utf-8")
    assert code_has(src, "if ranged and not ranged_template_name(uf.name) then")


# --- L7 gear 53-68/712-732/864-872/1071 and 789-849 --------------------------------------------

def gear_env(lua, env):
    return lua.execute("local env = ...; return env.reqscript('ai-military-gear')", env)


@test("L7 gear: the claim walks read the fort's squads, never world.squads.all (a world's thousands)")
def _():
    lua, n, env, eq, sq7, sq8 = TM.army()
    before = dict(env.gaps_why("weapon", "WEAPON").why)
    lua.execute("""local env = ...
        env.df.global.world.squads.all = setmetatable({}, {__index = function() error('world.squads.all walked') end,
                                                           __len = function() error('world.squads.all walked') end})""", env)
    after = dict(env.gaps_why("weapon", "WEAPON").why)
    assert after == before, (before, after)
    src = (LUA_DIR / "ai-military-gear.lua").read_text(encoding="utf-8")
    assert len(re.findall(r"ipairs\(df\.global\.world\.squads\.all\)", src)) == 1      # fort_squads' fallback only


@test("L7 gear: gear_report builds the claim sets once and leaves none behind (actions build their own)")
def _():
    lua, n, env, eq, sq7, sq8 = TM.army()
    g = gear_env(lua, env)
    lua.execute("""local g, env = ...
        g.CALLS = 0
        local U = env.reqscript('ai-util')
        local real = U.fort_entity
        U.fort_entity = function(...) g.CALLS = g.CALLS + 1; return real(...) end""", g, env)
    a = lua.execute("local g = ...; g.CALLS = 0; g.CLAIM_MEMO = {}; g.gaps_why('weapon', 'WEAPON'); "
                    "g.gaps_why('shield', 'SHIELD'); local c = g.CALLS; g.CLAIM_MEMO = nil; return c", g)
    b = lua.execute("local g = ...; g.CALLS = 0; g.gaps_why('weapon', 'WEAPON'); g.gaps_why('shield', 'SHIELD'); "
                    "return g.CALLS", g)
    assert (a, b) == (3, 4), (a, b)          # gaps_why reads the fort twice itself; the claims once, not twice
    lua.execute("local g = ...; pcall(g.gear_report)", g)
    assert g.CLAIM_MEMO is None


@test("L7 gear gaps_why: each (entry kind, walk group) judged once against the items, same answers")
def _():
    lua, n, env, eq, sq7, sq8 = TM.army()
    g = gear_env(lua, env)
    base = dict(env.gaps_why("weapon", "WEAPON").why)
    # every soldier asks for the same thing: 6 empty entries, one judging walk
    lua.execute("""local g, env = ...
        env.dfhack.maps.getWalkableGroup = function() return 1 end
        local real = g.weapon_fits
        g.FITS = 0
        g.weapon_fits = function(...) g.FITS = g.FITS + 1; return real(...) end""", g, env)
    lua.execute("""local env = ...
        for _, sid in ipairs({7, 8}) do
            local sq = env.df.squad.find(sid)
            for _, pos in env.ipairs(sq.positions) do
                local s = pos.equipment.uniform[2][0]
                s.item_subtype, s.material_class, s.indiv_choice = 1, -1, {}
            end
        end""", env)
    w = env.gaps_why("weapon", "WEAPON")
    assert w.entries == 6 and sum(dict(w.why).values()) == 6, dict(w.why)
    assert g.FITS <= 5, g.FITS               # 5 weapons once (was up to 6 x 5)
    assert len(base) >= 1


# --- L7 industry 577-622: the quarry's scan ---------------------------------------------------

OLD_INDUSTRY = None


def old_industry_src():
    global OLD_INDUSTRY
    if OLD_INDUSTRY is None:
        try:
            OLD_INDUSTRY = subprocess.run(["git", "show", "merge33:lua/ai-industry.lua"], cwd=ROOT,
                                          capture_output=True, text=True, check=True).stdout
        except Exception:  # noqa: BLE001
            OLD_INDUSTRY = ""
    return OLD_INDUSTRY


def quarry_run(src, rows, cz=10, margin=None):
    L = LuaRuntime(unpack_returned_tuples=True)
    env, dig = L.execute(TI.FAKE, src, L.table_from(rows))
    L.execute(TI.QUARRY_SETUP, env, 3, False)
    L.execute("""local env = ...
        env.READS = 0
        local real = env.dfhack.maps.getTileType
        env.dfhack.maps.getTileType = function(...) env.READS = env.READS + 1; return real(...) end""", env)
    if margin is not None:
        env.SURVEY_MARGIN = margin
    r = env.quarry(4, True)
    return r, env.READS


@test("L7 industry quarry: nearest wall found as before, reading far fewer tiles")
def _():
    rows = list(TI.MAP)
    new, n_new = quarry_run(with_util((LUA_DIR / "ai-industry.lua").read_text(encoding="utf-8"), "ai-industry.lua"),
                            rows)
    assert new.ok, dict(new)
    d_new = abs(new.x - 2) + abs(new.y - 2)
    old = old_industry_src()
    if old:
        prev, n_old = quarry_run(with_util(old, "ai-industry.lua"), rows)
        assert prev.ok and abs(prev.x - 2) + abs(prev.y - 2) == d_new, (dict(prev), dict(new))
        assert n_new * 10 < n_old, (n_new, n_old)


@test("L7 industry quarry: no wall to be had -> refused, and the scan stops at QUARRY_SCAN_MAX")
def _():
    rows = ["." * 16] * 16                    # all floor: no wall anywhere
    L = LuaRuntime(unpack_returned_tuples=True)
    env, dig = L.execute(TI.FAKE, with_util((LUA_DIR / "ai-industry.lua").read_text(encoding="utf-8"),
                                            "ai-industry.lua"), L.table_from(rows))
    L.execute(TI.QUARRY_SETUP, env, 3, False)
    L.execute("""local env = ...
        env.READS = 0
        local real = env.dfhack.maps.getWalkableGroup
        env.dfhack.maps.getWalkableGroup = function(...) env.READS = env.READS + 1; return real(...) end
        env.QUARRY_SCAN_MAX = 500""", env)
    r = env.quarry(4, True)
    assert not r.ok and r.rejected, dict(r)
    assert env.READS < 1500, env.READS


@test("L7 industry Low: METAL_ORDER (dead) gone")
def _():
    src = (LUA_DIR / "ai-industry.lua").read_text(encoding="utf-8")
    assert "METAL_ORDER" not in src


# --- L7 diplomacy 131-135: tribute answered by the Rules ----------------------------------------

@test("L7 diplomacy press_guard: tribute passes for pay and refuse, for small only with the amount known")
def _():
    env, _ = TW.world()
    T = lambda *a: TW.LUA.table_from(list(a))   # noqa: E731
    assert env.press_guard(T("TributeAgreement"), "pay") is None
    assert env.press_guard(T("TributeAgreement"), "refuse") is None
    assert "not known" in env.press_guard(T("TributeAgreement"), "small")
    assert env.press_guard(T("TributeAgreement"), "small", True) is None
    assert "DeclareWar" in env.press_guard(T("DeclareWar"), "refuse")


@test("L7 diplomacy answer_meeting: 'refuse' presses No; 'small' a small one Yes (dry run)")
def _():
    tribute = TW.MEETING + "df.global.game.main_interface.diplomacy.dipev.topic_list = G.vec({9}); " \
                           "df.global.game.main_interface.diplomacy.dipev.agreement_topic = G.vec({}); " \
                           "df.global.game.main_interface.diplomacy.dipev.topic_parms = G.vec({%d})"
    env, G = TW.world(tribute % 3000)
    G.tribute = "refuse"
    r = env.answer_meeting(TW.LUA.table_from({"dry_run": True}))
    assert r.ok and r.answer == "no", dict(r)
    env, G = TW.world(tribute % 100)
    G.tribute = "small"
    r = env.answer_meeting(TW.LUA.table_from({"dry_run": True}))
    assert r.ok and r.answer == "yes", dict(r)


# --- L8 gui 1081/1185-1187/1218-1221: no stale save over the keeper's ---------------------------

GUI_FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local stored = {traits = {caution = {value = 0, extreme = false}}, ai_sliders = {}, open_caverns = false,
                disposal = 'destroy', levels = {}}
local function copy(v) if type(v) ~= 'table' then return v end local o = {} for k, x in pairs(v) do o[k] = copy(x) end return o end
local S = {load_settings = function() return copy(stored) end,
           save_settings = function(s) stored = copy(s) end,
           TRAIT_GROUPS = {}, TRAIT_MIN = -100, TRAIT_MAX = 100, TRAIT_STEP = 10}
local function cls() local c = {}; c.__index = c; return setmetatable(c, {__call = function(k, t) return setmetatable(t or {}, k) end}) end
env.reqscript = function(n) return S end
env.require = function() return setmetatable({}, {__index = function() return {} end}) end
env.defclass = function() local c = cls(); c.ATTRS = function() end; return c end
env.mkdir_recursive = function() end
env.dfhack = setmetatable({}, {__index = function() return {} end})
env.DEFAULT_NIL = nil
local f = assert(load(src, 'gui', 't', env))
pcall(f)
return env, function() return stored end, function(s) stored = s end
"""


@test("L8 gui persist: a field the keeper saved while the window was open is not turned back")
def _():
    L = LuaRuntime(unpack_returned_tuples=True)
    env, get, put = L.execute(GUI_FAKE, GUI)
    assert env.merge_changes is not None and env.OverseerWindow is not None
    w = L.eval("function(env) local w = setmetatable({}, {__index = env.OverseerWindow}); w:reload(); return w end")(env)
    # the keeper's act_set_rules saves open_caverns while the window is open
    L.execute("local get, put = ...; local s = get(); s.open_caverns = true; s.disposal = 'dump'; put(s)", get, put)
    assert env.merge_changes(L.table_from({"a": False}), L.table_from({"a": False}), L.table_from({"a": True})).a is True
    L.execute("local w = ...; w:set_field('fort_goal', 'grow')", w)
    s = get()
    assert s.open_caverns is True and s.disposal == "dump" and s.fort_goal == "grow", (s.open_caverns, s.disposal)
    # a trait moved: only that trait written
    L.execute("local get, put = ...; local s = get(); s.levels.jail = false; put(s)", get, put)
    L.execute("local w = ...; w:trait('caution').value = 40; w:persist()", w)
    s = get()
    assert s.traits.caution.value == 40 and s.levels.jail is False and s.open_caverns is True


@test("L8 gui: the tab bar reloads the settings before a page is shown")
def _():
    assert code_has(GUI, "self:reload()            -- (0.105.33 review) what the keeper saved meanwhile")
    assert code_has(GUI, "function OverseerWindow:persist()\n    local fresh = S.load_settings()")


# --- L8 gui 1075-1077/1113/568-694: every page row inside the window -------------------------------

def page_rows(src: str, start: str, end: str, t0: int, jrow=8, hrow=2) -> list[int]:
    part = src[src.index(start):src.index(end)]
    rows = []
    for m in re.finditer(r"frame = \{t = ([^,}]+)[,}]", part):
        expr = m.group(1).strip()
        for i in ((1, 2, 3, 7) if "i" in re.sub(r"\bt\b", "", expr).replace("jrow", "").replace("hrow", "") else (0,)):
            try:
                rows.append(eval(expr, {"t": t0, "i": i, "jrow": jrow, "hrow": hrow}))
            except NameError:
                pass
    return rows


@test("L8 gui: the Rules page ends at row 27 and the Army tab holds the military, junk and prisoner rows")
def _():
    m = re.search(r"frame = \{w = EFFECTIVE_L \+ 10, h = (\d+)\}", GUI)
    h = int(m.group(1))
    top, bottom = 3, 9
    visible = h - 2 - top - bottom                      # 28 rows: 0..27
    # the Rules page, from its lower block (t = 5 + 9 levels = 14): the camera pace last
    rules = page_rows(GUI, "local t = 5 + #S.OPTIONAL_LEVELS", "function MilitaryPage:init()", 14)
    assert max(rules) <= visible - 1, (max(rules), visible)
    assert code_has(GUI, "local t = 5 + #S.OPTIONAL_LEVELS")
    army = page_rows(GUI, "function MilitaryPage:init()", "function RulesPage:refresh()", -3)
    assert min(army) == 0 and max(army) <= visible - 4, (min(army), max(army))   # the help text wraps 2-3 rows
    # the controls moved are on the Army page, and refreshed there
    mil = GUI[GUI.index("function MilitaryPage:init()"):GUI.index("function RulesPage:refresh()")]
    for v in ("attack_policy", "disposal", "keep_enemy_gear", "squads_shelter", "gear_weapon", "prisoners"):
        assert f"view_id = '{v}'" in mil, v
    ref = GUI[GUI.index("function MilitaryPage:refresh()"):]
    ref = ref[:ref.index("\nend\n")]
    for v in ("attack_policy", "disposal", "keep_enemy_gear", "squads_shelter", "gear_weapon", "prisoners",
              "moon_cells", "seal_caverns"):
        assert f"self.subviews.{v}:setOption" in ref, v
    # ten tabs of #label + 4 fit the 120 columns inside on one row
    assert code_has(GUI, "table.insert(labels, 'Army')")
    labels = ["Temperament", "Construction", "Economy", "Society", "AI & tokens", "Rules", "Army",
              "Needs you", "Culture", "Camera"]
    assert sum(len(x) + 4 for x in labels) <= 120


# --- L8 title 120-129/176-188: Enter on the highlighted line when the scroll won't hold -------------

TITLE_FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
env.dfhack_flags = {module = true}
env.LOG = {}
env.TIMERS = {}
env.dfhack = {timeout = function(n, u, f) table.insert(env.TIMERS, f) end, isWorldLoaded = function() return false end,
              gui = {}, screen = {}}
env.require = function() return {simulateInput = function(scr, key) table.insert(env.LOG, key) end} end
assert(load(src, 'ai-title', 't', env))()
env.LOAD_LOG = {steps = {}}
return env
"""


@test("L8 title then_if_scrolled: the scroll pulled back, the line highlighted -> Enter on it; neither -> stop")
def _():
    L = LuaRuntime(unpack_returned_tuples=True)
    env = L.execute(TITLE_FAKE, (LUA_DIR / "ai-title.lua").read_text(encoding="utf-8"))
    run = L.eval("function(env) local f = table.remove(env.TIMERS, 1); f() end")
    scr = L.table_from({"scroll_position_world_choice": 0, "selected": 2})
    went = []
    env.then_if_scrolled(scr, "scroll_position_world_choice", 2, lambda: went.append("click"),
                         lambda: (went.append("key"), env.press_select(scr)))
    run(env)
    assert went == ["key"] and list(env.LOG.values()) == ["SELECT"], (went, list(env.LOG.values()))
    scr2 = L.table_from({"scroll_position_world_choice": 0, "selected": 0})
    went.clear()
    env.then_if_scrolled(scr2, "scroll_position_world_choice", 2, lambda: went.append("click"),
                         lambda: went.append("key"))
    run(env)
    assert went == [], went
    steps = env.LOAD_LOG.steps
    assert "stopped" in steps[len(steps)].step, steps[len(steps)].step
    scr3 = L.table_from({"scroll_position_world_choice": 2, "selected": 2})
    env.then_if_scrolled(scr3, "scroll_position_world_choice", 2, lambda: went.append("click"),
                         lambda: went.append("key"))
    run(env)
    assert went == ["click"], went
    src = (LUA_DIR / "ai-title.lua").read_text(encoding="utf-8")
    assert "STEP_FRAMES" not in src
    assert src.count("function() saves_step(press_select) end") == 1 and src.count("function() load_step(press_select) end") == 1


# --- trivial Lows: threats, nobles, missions, the probes -------------------------------------------

@test("L7 Lows: seal_cavern counts a lever only when it pulled; the messenger's mothers once; Skirmishing hostile")
def _():
    th = (LUA_DIR / "ai-threats.lua").read_text(encoding="utf-8")
    i = th.index("local okp, pulled = pcall(function() return reqscript('ai-gates').pull_instant(lever) end)")
    seg = th[i:i + 400]
    assert "n = n + 1" in seg[seg.index("if okp and pulled then"):seg.index("else")], seg
    assert code_has(th, "pull_failed = pull_failed > 0 and pull_failed or nil")
    nb = (LUA_DIR / "ai-nobles.lua").read_text(encoding="utf-8")
    assert "mothers()[u.id]" not in nb and code_has(nb, "(military or CIVILIAN_AWAY_OFFICES[code]) and mothers()")
    ms = (LUA_DIR / "ai-missions.lua").read_text(encoding="utf-8")
    assert code_has(ms, "rel == 'Skirmishing'")
    for f in ("ai-probe-axes.lua", "ai-probe-gear.lua"):
        assert not (LUA_DIR / f).exists(), f


@test("every lua/*.lua and lua/gui/*.lua still compiles")
def _():
    L = LuaRuntime(unpack_returned_tuples=True)
    chk = L.eval("function(src, n) local f, e = load(src, n, 't', {}); return f ~= nil, e end")
    for p in sorted(list(LUA_DIR.glob("*.lua")) + list((LUA_DIR / "gui").glob("*.lua"))):
        ok = chk(p.read_text(encoding="utf-8"), p.name)
        assert ok[0], (p.name, ok[1])


if __name__ == "__main__":
    finish()

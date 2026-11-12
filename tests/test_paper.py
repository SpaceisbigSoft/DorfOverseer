"""(item9) Paper for the library: brain/planner_paper.py (the plant route:
slurry pressed, papyrus sheets, plants milled into slurry only when the game
can press it and food and drink are in hand; the missing quern or screw
press built; scrolls and codices once the library has its paper; nothing
without a library or a paper section; one step a cycle beside the kiln
chain), lua/ai-paper.lua in a fake game (the reactions found by code or by
shape, their workshops and free inputs; quires, scrolls, codices, rollers
and bindings counted), and the bridge's wiring (the recipes, the section,
the module, the screw press's Quickfort key).

    python tests/test_paper.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import make_test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

import planner_paper as PP  # noqa: E402
import planner_core  # noqa: E402
import planner_industry  # noqa: E402
import digest  # noqa: E402
from planner import Memory, plan, PLANNER_CONFIG as CFG  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

test = make_test()
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
LUA = ROOT / "lua"


def rx(code, shops, inputs=None):
    e = {"code": code, "shops": shops}
    if inputs is not None:
        e["inputs"] = inputs
    return e


def fort(have=0, want=10, sheets=0, paper=None, shops=None, flags=None) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["locations"]["list"] = [{"id": 7, "type": "LIBRARY", "have": {"paper": have}, "want": {"paper": want},
                               "jobs": {}, "zones": [70], "chests": 1,
                               "flags": flags if flags is not None else ["VISITORS_ALLOWED"]}]
    s["supplies"].update(sheets=sheets, blank_quires=0, gypsum=0, calcium_carbonate=0, empty_bags=0)
    if shops is not None:
        s["buildings"]["workshops"] = dict(shops)
    p = {"reactions": {"slurry": rx("MAKE_SLURRY_FROM_PLANT", ["Quern", "Millstone"], 40),
                       "press": rx("PRESS_PLANT_PAPER", ["ScrewPress"], 0),
                       "papyrus": rx("MAKE_PAPYRUS", ["Farmers"], 0),
                       "scroll": rx("MAKE_SCROLL", ["Craftsdwarfs"]),
                       "codex": rx("BIND_BOOK", ["Craftsdwarfs"])},
         "quires_blank": 0, "quires_written": 0, "scrolls_blank": 0, "scrolls_written": 0,
         "codices": 0, "rollers": 0, "bindings": 0, "sheets": sheets}
    for k, v in (paper or {}).items():
        if k in p["reactions"]:
            p["reactions"][k] = v
        else:
            p[k] = v
    s["paper"] = p
    s["orders"] = [o for o in s["orders"] if o.get("recipe") not in PP.PAPER_RECIPES + PP.KILN_PAPER]
    return digest.normalize(s)


WORKS = {"Millstone": 1, "Farmers": 1, "Craftsdwarfs": 1, "Carpenters": 1, "ScrewPress": 1, "Kitchen": 2, "Still": 2}


def run(s, memory=None):
    props, notes = [], []
    PP._paper_rule(s, CFG, props, notes, memory)
    return props, notes


def recipe(props):
    return [(p.rule, p.action.get("recipe") or tuple(p.action.get("shops") or ()), p.action.get("amount"))
            for p in props]


# --- the brain ------------------------------------------------------------------------------

@test("slurry in stock and a screw press: pressed into sheets (capped by the need and the batch)")
def _():
    s = fort(have=5, want=10, shops=WORKS, paper={"press": rx("PRESS_PLANT_PAPER", ["ScrewPress"], 3)})
    p, _ = run(s)
    assert recipe(p) == [("paper", "press_paper", 3)], recipe(p)
    assert p[0].is_order and "5 of 10" in p[0].reason


@test("plants and both shops: milled into slurry, keeping paper_plants_keep")
def _():
    s = fort(have=0, want=10, shops=WORKS)
    p, _ = run(s)
    assert recipe(p) == [("paper", "make_slurry", CFG["paper_batch"])], recipe(p)
    s = fort(have=0, want=10, shops=WORKS, paper={"slurry": rx("X", ["Quern"], CFG["paper_plants_keep"] + 2)})
    s["buildings"]["workshops"]["Quern"] = 1
    assert recipe(run(s)[0]) == [("paper", "make_slurry", 2)]
    s = fort(have=0, want=10, shops=WORKS, paper={"slurry": rx("X", ["Quern"], CFG["paper_plants_keep"])})
    p, notes = run(s)
    assert not p and any("no papyrus sedge or plants" in n for n in notes), notes


@test("papyrus sedge before slurry; at its workshop")
def _():
    s = fort(have=0, want=10, shops=WORKS, paper={"papyrus": rx("MAKE_PAPYRUS", ["Farmers"], 30)})
    assert recipe(run(s)[0]) == [("paper", "make_papyrus", CFG["paper_batch"])]


@test("no screw press: built first (one workshops project at a time); no quern: a quern")
def _():
    shops = dict(WORKS)
    shops.pop("ScrewPress")
    s = fort(shops=shops)
    p, _ = run(s)
    assert recipe(p) == [("paper_shop", ("ScrewPress",), None)], recipe(p)
    assert p[0].action == {"type": "start_project", "kind": "workshops", "shops": ["ScrewPress"]}
    s["projects"]["open"] = [{"kind": "workshops", "furnish": {"days": 1}}]
    p, notes = run(s)
    assert not p and any("another workshops project" in n for n in notes), notes
    shops.pop("Millstone")
    shops["ScrewPress"] = 1
    p, _ = run(fort(shops=shops))
    assert recipe(p) == [("paper_shop", ("Quern",), None)], recipe(p)


@test("the game can't press slurry: no slurry milled, said")
def _():
    s = fort(shops=WORKS, paper={"press": {"code": False}})
    p, notes = run(s)
    assert not p and any("no reaction pressing slurry" in n for n in notes), notes


@test("food or drink short: no plants to paper (slurry already made is still pressed)")
def _():
    s = fort(shops=WORKS)
    s["dwarves"]["total"] = 100000
    p, notes = run(s)
    assert not p and any("food and drink are well in hand" in n for n in notes), notes
    s = fort(shops=WORKS, paper={"press": rx("P", ["ScrewPress"], 2)})
    s["dwarves"]["total"] = 100000
    assert recipe(run(s)[0]) == [("paper", "press_paper", 2)]


@test("sheets in stock: the kiln rule binds them (nothing here); blank quires count as on the way")
def _():
    assert not run(fort(sheets=3, shops=WORKS))[0]
    s = fort(have=0, want=10, shops=WORKS, paper={"quires_blank": 10})
    p, _ = run(s)
    assert not p, recipe(p)
    s = fort(have=0, want=10, shops=WORKS, paper={"quires_blank": 8})
    assert recipe(run(s)[0]) == [("paper", "make_slurry", 2)]


@test("one step a cycle: nothing while a paper or kiln-chain order waits, or the kiln proposed one")
def _():
    for r in ("make_slurry", "make_parchment", "make_quire"):
        s = fort(shops=WORKS)
        s["orders"].append({"id": 99, "recipe": r, "amount_left": 1, "by_ai": True})
        assert not run(s)[0], r
    s = fort(shops=WORKS)
    props = [planner_core.Proposal("kiln", {"type": "work_order", "recipe": "make_quicklime", "amount": 1}, "x", 5, True)]
    PP._paper_rule(s, CFG, props, [], None)
    assert len(props) == 1


@test("no library, no paper section, or a young fort: nothing")
def _():
    s = fort(shops=WORKS)
    s["locations"]["list"] = []
    assert not run(s)[0]
    s = fort(shops=WORKS)
    s["paper"] = {}
    assert not run(s)[0]
    s = fort(shops=WORKS)
    s["dwarves"]["total"] = 3
    s["stocks"] = {}
    assert not run(s)[0]


@test("library supplied: scroll rollers carved, then blank scrolls from spare sheets (sheets kept for quires)")
def _():
    s = fort(have=10, want=10, sheets=5, shops=WORKS)
    assert recipe(run(s)[0]) == [("paper", "wooden_scroll_rollers", 2)]
    s = fort(have=10, want=10, sheets=5, shops=WORKS, paper={"rollers": 4})
    n = min(4, 5 - CFG["paper_scroll_sheets_spare"], CFG["paper_scrolls_keep"])
    assert recipe(run(s)[0]) == [("paper", "make_scroll", n)]
    s = fort(have=10, want=10, sheets=CFG["paper_scroll_sheets_spare"], shops=WORKS, paper={"rollers": 4})
    assert not run(s)[0]
    s = fort(have=10, want=10, sheets=5, shops=WORKS, paper={"rollers": 4, "scrolls_blank": CFG["paper_scrolls_keep"]})
    assert not run(s)[0]


@test("written quires: book bindings carved, then bound into codices")
def _():
    s = fort(have=10, want=10, shops=WORKS, paper={"quires_written": 3})
    assert recipe(run(s)[0]) == [("paper", "wooden_book_binding", CFG["paper_codex_batch"])]
    s = fort(have=10, want=10, shops=WORKS, paper={"quires_written": 3, "bindings": 1})
    assert recipe(run(s)[0]) == [("paper", "bind_codex", 1)]
    s = fort(have=4, want=10, shops=WORKS, paper={"quires_written": 3, "bindings": 1, "quires_blank": 6})
    assert not run(s)[0]                      # blank ones still on their way: no codex yet
    # (fix6) vanilla BIND_BOOK takes any quire: never bound (nor bindings carved) while a blank one lies free
    s = fort(have=10, want=10, shops=WORKS, paper={"quires_written": 3, "bindings": 1, "quires_blank": 2})
    assert not run(s)[0], recipe(run(s)[0])
    s = fort(have=10, want=10, shops=WORKS, paper={"quires_written": 3, "quires_blank": 1})
    assert not run(s)[0], recipe(run(s)[0])
    s = fort(have=10, want=10, shops=WORKS, paper={"quires_written": 3, "bindings": 1})
    s["supplies"]["blank_quires"] = 1         # the supplies' count of blank quires counts too
    assert not run(s)[0], recipe(run(s)[0])


@test("scholars: a library the player shut to visitors is said; the AI's own shut is not")
def _():
    s = fort(flags=[], shops=WORKS, have=10, want=10)
    _, notes = run(s)
    assert any("visiting scholars can't come" in n for n in notes), notes
    m = Memory()
    m.locations_closed = [7]
    _, notes = run(s, m)
    assert not any("visiting scholars" in n for n in notes), notes


@test("plan(): the paper rule runs after the kiln (a full report); its recipes and shops are known")
def _():
    s = fort(shops=WORKS)
    p, _ = plan(s, Memory())
    assert [x for x in p if x.rule == "paper"], [x.rule for x in p]
    assert "ScrewPress" in planner_core.BUILDABLE_SHOPS
    assert planner_industry.EXCESS_SHOPS.get("ScrewPress") == 2
    assert "paper" in digest.SECTION_DEFAULTS
    for k in ("paper_batch", "paper_plants_keep", "paper_food_per_dwarf_min", "paper_scrolls_keep",
              "paper_scroll_sheets_spare", "paper_codex_batch", "paper_wood_min", "paper_cooldown_ticks",
              "paper_shop_cooldown_ticks"):
        assert k in CFG, k


@test("plan() without a paper section: no paper proposals")
def _():
    s = copy.deepcopy(BASE)
    s.pop("paper", None)
    p, _ = plan(s, Memory())
    assert not [x for x in p if x.rule in ("paper", "paper_shop")]


# --- the bridge's wiring --------------------------------------------------------------------

ORDERS = (LUA / "ai-bridge-orders.lua").read_text(encoding="utf-8")
BRIDGE = (LUA / "ai-bridge.lua").read_text(encoding="utf-8")


@test("bridge: every paper recipe is an order recipe; the section, its cache and the module are wired")
def _():
    for r in PP.PAPER_RECIPES:
        assert re.search(rf"\n    {r} = {{job = '", ORDERS), r
    for kind in ("slurry", "press", "papyrus", "scroll", "codex"):
        assert f"paper = '{kind}'" in ORDERS, kind
    assert "if r.paper and r.job == job then reaction = paper_reaction(r.paper) or '' end" in ORDERS
    assert "local v = safe(function() return reqscript('ai-paper').report() end)" in BRIDGE
    # (fix6) not cached while a paper order is open; a paper step's work order clears the cached copy
    assert "return v, (oko and open) or nil" in BRIDGE
    assert "stale = paper_step and {'paper'} or nil" in ORDERS
    for r in PP.PAPER_RECIPES:
        e = re.search(rf"\n    {r} = {{(.*?)}},?\n", ORDERS).group(1)
        assert "paper = '" in e or "ITEM_TOOL_SCROLL_ROLLERS" in e or "ITEM_TOOL_BOOK_BINDING" in e, r
    assert "SECTION_CACHE_DAYS.paper = 1" in BRIDGE
    assert "'ai-paper'" in BRIDGE
    assert "ScrewPress = 'wp'" in (LUA / "ai-layouts.lua").read_text(encoding="utf-8")


def _lua_fn(src: str, name: str) -> str:
    m = re.search(r"\nfunction " + name + r"\(.*?\nend\n", src, re.S)
    assert m, name
    return m.group(0)


@test("bridge (lua): paper_reaction asks ai-paper, nil when it fails")
def _():
    if LuaRuntime is None:
        return
    L = LuaRuntime()
    L.execute("CODES = {slurry = 'MAKE_SLURRY_FROM_PLANT'}\n"
              "function reqscript(n) assert(n == 'ai-paper'); return {reaction = function(k) return CODES[k] end} end\n"
              + _lua_fn(ORDERS, "paper_reaction"))
    assert L.eval("paper_reaction('slurry')") == "MAKE_SLURRY_FROM_PLANT"
    assert L.eval("paper_reaction('codex')") is None
    L.execute("function reqscript(n) error('no module') end")
    assert L.eval("paper_reaction('slurry')") is None


# --- lua/ai-paper.lua in a fake game ---------------------------------------------------------

FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local T = {NONE = -1, PLANT = 1, GLOB = 2, SHEET = 3, TOOL = 4, BOOK = 5, BUCKET = 6, CORPSEPIECE = 7}
local item_type = {}
for k, v in pairs(T) do item_type[k] = v; item_type[v] = k end
local BT = {Workshop = 1, Furnace = 2}
local building_type = {}
for k, v in pairs(BT) do building_type[k] = v; building_type[v] = k end
local WT = {Quern = 10, Millstone = 11, Farmers = 12, Craftsdwarfs = 13, Custom = 14}
local workshop_type = {}
for k, v in pairs(WT) do workshop_type[k] = v; workshop_type[v] = k end
local TOOLS = {[1] = 'ITEM_TOOL_SCROLL', [2] = 'ITEM_TOOL_QUIRE'}
local G = {reactions = {}, lists = {PLANT = {}, GLOB = {}, TOOL = {}, BOOK = {}, SHEET = {}}, mats = {}}
local function shop(names)
    local b = {type = {}, subtype = {}, custom = {}}
    for i, n in ipairs(names) do
        b.type[i] = BT.Workshop
        if n == 'SCREW_PRESS' then b.subtype[i] = WT.Custom; b.custom[i] = 99
        else b.subtype[i] = WT[n] end
    end
    return b
end
function G.rx(code, ins, outs, shops, want)
    local r = {code = code, name = code:lower(), reagents = {}, products = {}, building = shop(shops or {})}
    for i, t in ipairs(ins) do
        r.reagents[i] = {item_type = T[t], has_material_reaction_product = (i == 1 and want) or ''}
    end
    for i, t in ipairs(outs) do
        local typ, sub = t:match('^(%u+):?(%d*)$')
        r.products[i] = {item_type = T[typ], item_subtype = tonumber(sub) or -1}
    end
    table.insert(G.reactions, r)
    return r
end
function G.item(kind, mat, n, t)
    t = t or {}
    t.flags = t.flags or {}
    t.mat = mat
    t.getMaterial = function(self) return 0 end
    t.getMaterialIndex = function(self) return self.mat end
    t.getStackSize = function(self) return n or 1 end
    t.improvements = t.improvements or {}
    table.insert(G.lists[kind], t)
    return t
end
local function rp(list)
    local out = {}
    for i, v in ipairs(list) do out[i] = {value = v} end
    return out
end
G.mats[1] = rp({'PAPER_SLURRY_MAT'})       -- a slurry plant
G.mats[2] = rp({'DRINK_MAT', 'SEED_MAT'})  -- a brewing plant
G.mats[3] = rp({'PRESS_PAPER_MAT'})        -- slurry
G.mats[4] = rp({'PAPYRUS_MAT'})            -- papyrus sedge
env.SC_WORLD_UNLOADED, env.SC_MAP_UNLOADED = 1, 2
env.df = {
    global = {world = {raws = {reactions = {reactions = G.reactions}}, items = {other = G.lists},
                       cur_savegame = {save_dir = 'region1'}}},
    item_type = item_type, building_type = building_type, workshop_type = workshop_type,
    furnace_type = {}, improvement_type = {WRITING = 5},
    building_def = {find = function(id) if id == 99 then return {code = 'SCREW_PRESS'} end end},
}
env.dfhack = {
    matinfo = {decode = function(it) return {material = {reaction_product = {id = G.mats[it.mat] or {}}}} end},
    items = {getSubtypeDef = function(t, sub) return TOOLS[sub] and {id = TOOLS[sub]} end},
}
assert(load(src, 'ai-paper', 't', env))()
return env, G
"""


def game():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, g = lua.execute(FAKE, module_src("ai-paper.lua"))
    return lua, env, g


@test("ai-paper (lua): vanilla codes found; their workshops and free inputs reported")
def _():
    if LuaRuntime is None:
        return
    lua, env, g = game()
    lua.execute("""
        local env, G = ...
        G.rx('MAKE_SLURRY_FROM_PLANT', {'PLANT'}, {'GLOB'}, {'Quern', 'Millstone'}, 'PAPER_SLURRY_MAT')
        G.rx('PRESS_PLANT_PAPER', {'GLOB'}, {'SHEET'}, {'SCREW_PRESS'}, 'PRESS_PAPER_MAT')
        G.rx('MAKE_SCROLL', {'SHEET', 'TOOL'}, {'TOOL:1'}, {'Craftsdwarfs'})
        G.rx('BIND_BOOK', {'TOOL', 'TOOL'}, {'BOOK'}, {'Craftsdwarfs'})
        G.item('PLANT', 1, 5); G.item('PLANT', 1, 3); G.item('PLANT', 2, 50)
        G.item('PLANT', 1, 4, {flags = {forbid = true}}); G.item('PLANT', 1, 2, {flags = {in_job = true}})
        G.item('GLOB', 3, 2)
        G.item('SHEET', 3, 3)
    """, env, g)
    q = lua.execute("local env, G = ...; return env.report()", env, g)
    r = q["reactions"]
    assert r["slurry"]["code"] == "MAKE_SLURRY_FROM_PLANT" and r["slurry"]["inputs"] == 8
    assert list(r["slurry"]["shops"].values()) == ["Quern", "Millstone"]
    assert r["press"]["code"] == "PRESS_PLANT_PAPER" and r["press"]["inputs"] == 2
    assert list(r["press"]["shops"].values()) == ["ScrewPress"]
    assert r["papyrus"]["code"] is False
    assert r["scroll"]["code"] == "MAKE_SCROLL" and r["codex"]["code"] == "BIND_BOOK"
    assert q["sheets"] == 3
    assert env.reaction("press") == "PRESS_PLANT_PAPER" and env.reaction("papyrus") is None


@test("ai-paper (lua): other codes found by the reaction's shape (a papyrus sheet from a plant; parchment isn't paper)")
def _():
    if LuaRuntime is None:
        return
    lua, env, g = game()
    lua.execute("""
        local env, G = ...
        G.rx('MAKE_PARCHMENT', {'CORPSEPIECE', 'BUCKET'}, {'SHEET'}, {'Craftsdwarfs'})
        G.rx('MOD_PULP_MILL', {'PLANT', 'BUCKET'}, {'GLOB'}, {'Quern'}, 'PAPER_SLURRY_MAT')
        G.rx('MOD_SHEET_PRESS', {'GLOB'}, {'SHEET'}, {'SCREW_PRESS'}, 'PRESS_PAPER_MAT')
        G.rx('MOD_SEDGE_SHEET', {'PLANT'}, {'SHEET'}, {'Farmers'}, 'PAPYRUS_MAT')
        G.item('PLANT', 4, 7)
    """, env, g)
    assert env.reaction("slurry") == "MOD_PULP_MILL"
    assert env.reaction("press") == "MOD_SHEET_PRESS"
    assert env.reaction("papyrus") == "MOD_SEDGE_SHEET"
    assert env.reaction("codex") is None
    q = lua.execute("local env, G = ...; return env.report()", env, g)
    assert q["reactions"]["papyrus"]["inputs"] == 7
    assert list(q["reactions"]["papyrus"]["shops"].values()) == ["Farmers"]


@test("ai-paper (lua): quires and scrolls blank and written, codices, rollers and bindings counted")
def _():
    if LuaRuntime is None:
        return
    lua, env, g = game()
    lua.execute("""
        local env, G = ...
        local W = {getType = function() return 5 end}
        local function tool(id, written, flags)
            G.item('TOOL', 0, 1, {subtype = {id = id}, improvements = written and {W} or {}, flags = flags})
        end
        tool('ITEM_TOOL_QUIRE', false); tool('ITEM_TOOL_QUIRE', false); tool('ITEM_TOOL_QUIRE', true)
        tool('ITEM_TOOL_QUIRE', false, {forbid = true})
        tool('ITEM_TOOL_SCROLL', false); tool('ITEM_TOOL_SCROLL', true); tool('ITEM_TOOL_SCROLL', true)
        tool('ITEM_TOOL_SCROLL_ROLLERS'); tool('ITEM_TOOL_BOOK_BINDING'); tool('ITEM_TOOL_BOOK_BINDING')
        tool('ITEM_TOOL_LARGE_POT')
        G.item('BOOK', 0, 1); G.item('BOOK', 0, 1)
    """, env, g)
    q = lua.execute("local env, G = ...; return env.report()", env, g)
    got = {k: q[k] for k in ("quires_blank", "quires_written", "scrolls_blank", "scrolls_written", "codices",
                             "rollers", "bindings")}
    assert got == {"quires_blank": 2, "quires_written": 1, "scrolls_blank": 1, "scrolls_written": 2,
                   "codices": 2, "rollers": 1, "bindings": 2}, got


@test("ai-paper (lua): orders_open (fix6): a paper reaction's or a roller/binding order open; others not")
def _():
    if LuaRuntime is None:
        return
    lua, env, g = game()
    lua.execute("""
        local env, G = ...
        G.rx('PRESS_PLANT_PAPER', {'GLOB'}, {'SHEET'}, {'SCREW_PRESS'}, 'PRESS_PAPER_MAT')
        G.orders = {}
        env.df.global.world.manager_orders = {all = G.orders}
        env.df.job_type = {[1] = 'CustomReaction', [2] = 'MakeTool', CustomReaction = 1, MakeTool = 2}
        local subs = {[1] = 'ITEM_TOOL_SCROLL', [2] = 'ITEM_TOOL_QUIRE', [3] = 'ITEM_TOOL_BOOK_BINDING'}
        env.dfhack.items.getSubtypeDef = function(t, sub) return subs[sub] and {id = subs[sub]} end
    """, env, g)
    assert env.orders_open() is False
    lua.execute("local env, G = ...; G.orders[1] = {reaction_name = 'BREW_DRINK', item_subtype = -1, job_type = 1}"
                "; G.orders[2] = {reaction_name = '', item_subtype = 1, job_type = 2}", env, g)
    assert env.orders_open() is False           # brewing, and a tool that isn't a paper step's
    lua.execute("local env, G = ...; G.orders[3] = {reaction_name = 'PRESS_PLANT_PAPER', item_subtype = -1, "
                "job_type = 1}", env, g)
    assert env.orders_open() is True
    lua.execute("local env, G = ...; G.orders[3] = {reaction_name = '', item_subtype = 3, job_type = 2}", env, g)
    assert env.orders_open() is True            # a book binding carved


@test("ai-paper (lua): the reaction codes cached a world (none is cached too)")
def _():
    if LuaRuntime is None:
        return
    lua, env, g = game()
    assert env.reaction("slurry") is None
    lua.execute("local env, G = ...; G.rx('MAKE_SLURRY_FROM_PLANT', {'PLANT'}, {'GLOB'}, {'Quern'}, 'X')", env, g)
    assert env.reaction("slurry") is None                  # cached as none for this world
    lua.execute("local env, G = ...; env.CACHE = {}", env, g)
    assert env.reaction("slurry") == "MAKE_SLURRY_FROM_PLANT"


@test("lua files compile")
def _():
    if LuaRuntime is None:
        return
    L = LuaRuntime()
    load = L.eval("function(src, name) local f, e = load(src, name, 't', {}); return e end")
    for name in ("ai-paper.lua", "ai-bridge-orders.lua", "ai-bridge-probes.lua", "ai-bridge.lua", "ai-layouts.lua"):
        err = load((LUA / name).read_text(encoding="utf-8"), name)
        assert err is None, err


finish()

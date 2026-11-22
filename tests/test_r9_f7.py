"""(r9 f7) 13c's open Medium/Low items, builder f7:

  1. gate_parts (lua/ai-gates-wings.lua) counts a free hatch cover or door
     with ai-util's one list (U.item_unfree): its own copy counted an encased
     or rotten one free and dropped one in a bin (in_inventory);
  2. the wing walls' record (ai-overseer/wings) is found on any tile of the
     way in's opening, not only on the anchor a rescan may move;
  3. logs/keeper-preset.json's entries are matched by the world too (the
     report's), so another world's fort with the same site id is not taken
     for this one; older entries (no world) still match by site;
  4. the README says where the version is read, not a number;
  5. the dump zone's texts name ai-builder-dump (place_dump_zone's file).
  (test_df_names.py checks the df.<type>.T_* names now.)

    python tests/test_r9_f7.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

import overseer  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

HARNESS = r"""
local src = ...
PERSIST = {}
dfhack = {persistent = {getSiteData = function(k, d) local v = PERSIST[k]; if v == nil then return d end; return v end,
                        saveSiteData = function(k, v) PERSIST[k] = v end},
          items = {getHolderUnit = function(it) return it._holder end}}
ITEMS = {HATCH_COVER = {}, DOOR = {}}
df = {global = {world = {items = {other = ITEMS}}}}
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-gates', 't', env))()
return env
"""

if LuaRuntime is not None:
    L = LuaRuntime(unpack_returned_tuples=True)
    M = L.execute(HARNESS, module_src("ai-gates.lua"))


def key(x, y, z):
    return (z * 4096 + y) * 4096 + x


@test("gate_parts: ai-util's free-item list: encased, rotten, a web, a dead dwarf's not free; one in a bin is")
def _():
    need_lua()
    L.execute("""
        local function item(f) return {flags = f} end
        ITEMS.HATCH_COVER = {                                 -- (a Lua list: the stub's ipairs counts from 1)
            item({}),                                         -- free
            item({in_inventory = true}),                      -- in a bin: free (DF sets in_inventory there too)
            item({encased = true}), item({rotten = true}), item({spider_web = true}), item({dead_dwarf = true}),
            item({forbid = true}), item({artifact = true}), item({melt = true}),
            item({in_job = true}),                            -- on its way to a job: held
            item({in_job = true, in_inventory = true, _x = 1}),
        }
        ITEMS.HATCH_COVER[11]._holder = {id = 5}              -- a dwarf carries it: neither
        ITEMS.DOOR = {item({}), item({in_inventory = true, _y = 1})}
        ITEMS.DOOR[2]._holder = {id = 6}                      -- carried, no job: not free
    """)
    r = M.gate_parts()
    assert (r.hatch_covers, r.hatch_covers_held, r.doors, r.doors_held) == (2, 1, 1, 0), dict(r)


@test("wings: the record kept under another tile of the opening is found (a rescan moved the anchor)")
def _():
    need_lua()
    L.execute("""PERSIST['ai-overseer/wings'] = {['10,5,100'] = {'13,5,100', '14,5,100'}}""")
    e = L.table_from({"x": 11, "y": 5, "z": 100,
                      "inside_list": L.table_from([key(11, 5, 100), key(10, 5, 100)])})
    got = M.wing_pieces_of(e)
    assert got is not None and list(got.values()) == ["13,5,100", "14,5,100"]
    e0 = L.table_from({"x": 10, "y": 5, "z": 100})               # the anchor itself, as before
    assert M.wing_pieces_of(e0) is not None
    other = L.table_from({"x": 40, "y": 5, "z": 100, "inside_list": L.table_from([key(40, 5, 100)])})
    assert M.wing_pieces_of(other) is None
    src = (ROOT / "lua" / "ai-gates-wings.lua").read_text(encoding="utf-8")
    body = src[src.index("local function note_wings"):src.index("-- Zones, farm plots")]
    assert "record_spot(e, d)" in body and "d[spot] = list" in body   # built again: the same record grows


@test("preset_due: another world's fort with the same site id is not this one; older entries match by site")
def _():
    overseer.PRESET_FILE.parent.mkdir(parents=True, exist_ok=True)
    overseer.PRESET_FILE.write_text(json.dumps({
        "Usnuspbuzong#7": {"name": "War-hold", "run": "r1", "world": "Usnuspbuzong"},
        "region1#9": {"name": "Monastery", "run": "r0"},          # from before the world was kept
    }))
    try:
        # the same world, under an autosave's key or its own: applied already
        assert overseer.preset_due("Usnuspbuzong#7", "War-hold", "Peaceful", "Usnuspbuzong") is None
        assert overseer.preset_due("autosave 2#7", "War-hold", "Peaceful", "Usnuspbuzong") is None
        # another world, the same site id: a first time, and a run of its own
        assert overseer.preset_due("Otherworld#7", "War-hold", "Peaceful", "Otherworld") == "first time for this fort"
        assert overseer.fort_run("Otherworld#7", "Otherworld") is None
        assert overseer.fort_run("Usnuspbuzong#7", "Usnuspbuzong") == "r1"
        assert overseer.design_due("Otherworld#7", {"design": "scripts"}, "Otherworld")
        # an older entry (no world) and a report with no world name: by site, as before
        assert overseer.preset_due("Anyworld#9", "Monastery", "Peaceful", "Anyworld") is None
        assert overseer.preset_due("autosave 1#7", "War-hold", "Peaceful") is None
        # note_preset keeps the world on the entry; another world's start gets its own run stamp
        overseer.note_preset("Otherworld#7", "War-hold", world="Otherworld")
        done = json.loads(overseer.PRESET_FILE.read_text())
        assert done["Otherworld#7"]["world"] == "Otherworld"
        assert done["Otherworld#7"]["run"] != "r1"
        overseer.note_preset("Usnuspbuzong#7", "War-hold", world="Usnuspbuzong")
        assert json.loads(overseer.PRESET_FILE.read_text())["Usnuspbuzong#7"]["run"] == "r1"
        assert overseer.world_of({"fort": {"world": " Usnuspbuzong "}}) == "Usnuspbuzong"
        assert overseer.world_of({"fort": {"world": ""}}) is None and overseer.world_of({}) is None
    finally:
        overseer.PRESET_FILE.unlink()


@test("README: the version is read from BRIDGE_VERSION, no number written in the status line")
def _():
    src = (ROOT / "README.md").read_text(encoding="utf-8")
    line = next(ln for ln in src.splitlines() if ln.startswith("**Status:**"))
    assert "BRIDGE_VERSION" in line and "lua/ai-bridge.lua" in line, line
    assert "0.105." not in line, line


@test("place_dump: the texts name ai-builder-dump, where place_dump_zone lives")
def _():
    civic = (ROOT / "lua" / "ai-bridge-actions-civic.lua").read_text(encoding="utf-8")
    body = civic[civic.index("-- A garbage dump zone"):civic.index("function act_place_dump")]
    body += civic[civic.index("function act_place_dump"):civic.index("return r\nend", civic.index("function act_place_dump"))]
    assert "ai-builder-surface" not in body and body.count("ai-builder-dump") == 2, body
    assert "function place_dump_zone(" in (ROOT / "lua" / "ai-builder-dump.lua").read_text(encoding="utf-8")


if __name__ == "__main__":
    finish()

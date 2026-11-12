"""(D0 G4) The layouts snapshot: every level kind with today's style fields,
serialized and hashed, so the Design track's new style keys can be shown to
leave every old layout byte-identical.

    python tests/d0_layout_snapshot.py --write    regenerate the fixture (only from main's ai-layouts.lua)

tests/test_d0_layouts.py compares against tests/fixtures/d0_layouts_snapshot.json.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "d0_layouts_snapshot.json"

# (kind, params) the snapshot covers: each kind at a small and a large size
BASES = [
    ("bedrooms", {"rooms": 3, "room_size": 2}), ("bedrooms", {"rooms": 16, "room_size": 3}),
    ("bedrooms", {"rooms": 9, "room_size": 4}),
    ("bedrooms", {"rooms": 10, "dormitory": True}),
    ("suites", {"suites": 1}), ("suites", {"suites": 5}),
    ("jail", {"cells": 3}), ("jail", {"cells": 8}),
    ("dining", {"tables": 4}), ("dining", {"tables": 31}),
    ("storage", {"piles": ["food", "stone", "wood"], "room_size": 5}),
    ("storage", {"piles": ["food", "stone", "wood", "furniture", "gems", "ammo", "cloth"], "room_size": 9}),
    ("workshops", {"shops": ["Still", "Kitchen", "Masons"]}),
    ("workshops", {"shops": ["Still", "Kitchen", "Masons", "Carpenters", "Craftsdwarfs", "Loom", "Smelter"]}),
    ("temple", {"size": "shrine"}), ("temple", {"size": "grand"}),
    ("temple", {"size": "grand", "deity_hf": 12}),
    ("memorial", {"name": "Shulmik the Jackalowls"}),
    ("garden", {"name": "Copper"}),
    ("hospital", {"beds": 5}), ("hospital", {"beds": 20}),
    ("barracks", {"beds": 8}),
    ("tombs", {"coffins": 4}), ("tombs", {"coffins": 27}),
    ("tavern", {"tables": 9}),
    ("library", {"bookcases": 12}),
    ("archery", {"lanes": 2, "length": 12}),
    ("farms", {"plots": 5}),
]

# today's style fields (bridge 0.105.36)
STYLE_AXES = {
    "hall": ["plain", "rounded", "pillared"],
    "smooth": [0, 3],
    "statues": [0, 4],
    "orient": [0, 3],
    "rhythm": [3, 6],
    "spacing": [0, 60],
    "customs": [None, ["cloister", "armoury", "ore_piles"]],
}


def cases():
    keys = list(STYLE_AXES)
    for bi, (kind, params) in enumerate(BASES):
        yield f"{bi}:{kind}:nostyle", kind, dict(params), None
        for combo in itertools.product(*(STYLE_AXES[k] for k in keys)):
            style = {k: v for k, v in zip(keys, combo) if v is not None}
            cid = f"{bi}:{kind}:" + ",".join(f"{k}={v if not isinstance(v, list) else '+'.join(v)}"
                                           for k, v in style.items())
            yield cid, kind, dict(params), style


def lua_runtime():
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    src = (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8")
    env = lua.eval("function(src) local env = setmetatable({}, {__index=_G}); "
                   "assert(load(src, 'ai-layouts', 't', env))(); return env end")(src)
    ser = lua.eval(r"""function(L)
      local function sorted_set(set)
        local out = {}
        for x, col in pairs(set or {}) do for y in pairs(col) do table.insert(out, x .. ',' .. y) end end
        table.sort(out)
        return table.concat(out, ' ')
      end
      local function cells(list, sort)
        local out = {}
        for _, c in ipairs(list or {}) do table.insert(out, c.x .. ',' .. c.y .. '=' .. tostring(c.text)) end
        if sort then table.sort(out) end
        return table.concat(out, ' ')
      end
      local function kv(t)
        local out = {}
        for k, v in pairs(t or {}) do
          if type(v) == 'table' then
            local parts = {}
            for _, e in ipairs(v) do table.insert(parts, tostring(e)) end
            v = '[' .. table.concat(parts, ',') .. ']'
          end
          table.insert(out, tostring(k) .. '=' .. tostring(v))
        end
        table.sort(out)
        return table.concat(out, ' ')
      end
      local halls = {}
      for _, h in ipairs(L.halls or {}) do table.insert(halls, ('%d,%d,%d,%d'):format(h.x, h.y, h.w, h.h)) end
      local b = L.bounds
      return table.concat({
        'kind ' .. tostring(L.kind), 'orient ' .. tostring(L.orient),
        'dig ' .. cells(L.dig), 'build ' .. cells(L.build), 'place ' .. cells(L.place), 'zone ' .. cells(L.zone),
        'smooth ' .. cells(L.smooth, true), 'engrave ' .. cells(L.engrave, true),
        'tiles ' .. sorted_set(L.tiles), 'soil ' .. sorted_set(L.soil),
        'bounds ' .. ('%d,%d,%d,%d'):format(b.x1, b.y1, b.x2, b.y2),
        'furniture ' .. kv(L.furniture), 'summary ' .. kv(L.summary), 'halls ' .. table.concat(halls, ' '),
      }, '\n')
    end""")
    return lua, env, ser


def to_lua(lua, v):
    if isinstance(v, dict):
        t = lua.table()
        for k, x in v.items():
            t[k] = to_lua(lua, x)
        return t
    if isinstance(v, list):
        return lua.table_from([to_lua(lua, x) for x in v])
    return v


def serialize(lua, env, ser, kind, params, style):
    p = dict(params)
    if style is not None:
        p["style"] = style
    res = env.make(kind, to_lua(lua, p))
    L, err = res if isinstance(res, tuple) else (res, None)
    assert L is not None, err
    return ser(L)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def group_of(cid: str) -> str:
    return ":".join(cid.split(":")[:2])


def snapshot() -> dict:
    """{"<base>:<kind>": [hash of each case, in cases() order]}"""
    lua, env, ser = lua_runtime()
    out: dict[str, list[str]] = {}
    for cid, kind, params, style in cases():
        out.setdefault(group_of(cid), []).append(digest(serialize(lua, env, ser, kind, params, style)))
    return out


if __name__ == "__main__":
    if "--write" in sys.argv:
        snap = snapshot()
        FIXTURE.write_text(json.dumps({"_doc": "D0 G4: ai-layouts.lua output hashes at bridge 0.105.36 "
                                               "(main), today's style fields; see tests/d0_layout_snapshot.py",
                                       "cases": snap}, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {sum(map(len, snap.values()))} cases to {FIXTURE}")
    else:
        print(__doc__)

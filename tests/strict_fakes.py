"""Strict df fakes for the lupa Lua tests: an unknown field raises, as DFHack does.

A hand-written fake such as `{flags = {}, mat_type = 100}` answers nil to any
read, so a bridge that reads `it.flags.forbidden` (DFHack: forbid) or
`fish.mat_type` (an item_fishst has none) passes its test and throws in every
fort. A strict fake knows the fields of its df type, from
tests/fixtures/df_fields_53_17.json (brain/tools/gen_df_fields.py, df-structures
53.17-r1), and

- reading or writing a field the type (with its parents) does not have raises
  "Cannot read field item_fishst.mat_type: not found." (DFHack's own words,
  library/LuaWrapper.cpp field_error);
- a field the type has but the test did not set reads nil (a bitfield bit reads
  false, `whole` 0): give the fake every field the code under test should see;
- making the fake with a key the type does not have raises too (a fake that
  invents a field hides the bug it should catch): keep test scaffolding (a
  value for a stubbed dfhack.items.getValue, say) in a side table of the test;
- a plain table under a field whose df type is known is made strict too:
  `strict('item_fishst', {flags = {}, pos = {x = 1, y = 2, z = 3}})` gives an
  item_flags and a coord.
- vectors, numbers, strings and enum values are left as the test made them.

Use (lupa):

    from strict_fakes import install
    S = install(LUA, H)        # also H.strict, for the Lua chunks of a test
    LUA.execute("local H = ... ; local fish = H.strict('item_fishst', {flags = {}, race = 3})", H)

`H.strict_type(obj)` gives the df type name of a strict fake (nil otherwise).
`known(type, field)` and `fields(type)` answer the same from Python.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "fixtures" / "df_fields_53_17.json"
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


@lru_cache(maxsize=1)
def data() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def fields(tname: str) -> dict[str, str]:
    """Every field and method name of a df type with its parents: {name: type or ""}."""
    types = data()["types"]
    if tname not in types:
        raise KeyError(f"no df type {tname} in {DATA.name}")
    out: dict[str, str] = {}
    seen: set[str] = set()
    t = tname
    while t and t in types and t not in seen:
        seen.add(t)
        e = types[t]
        for m in e.get("m", []):
            out.setdefault(m, "")
        for f, v in e.get("f", {}).items():
            out.setdefault(f, v)
        t = e.get("p")
    return out


def known(tname: str, field: str) -> bool:
    d = data()
    builtins = d["bitfield_builtins"] if d["types"][tname]["k"] == "bitfield" else d["builtins"]
    return field in fields(tname) or field in builtins


def _q(s: str) -> str:
    if not _NAME.match(s):
        raise ValueError(f"unexpected name {s!r} in {DATA.name}")
    return '"' + s + '"'


@lru_cache(maxsize=1)
def lua_types() -> str:
    """The types as one Lua table constructor."""
    parts = []
    for n, e in data()["types"].items():
        f = ",".join(f"[{_q(k)}]={_q(v) if v else chr(34) * 2}" for k, v in e.get("f", {}).items())
        m = ",".join(f"[{_q(k)}]=true" for k in e.get("m", []))
        p = f"p={_q(e['p'])}," if e.get("p") else ""
        parts.append(f"[{_q(n)}]={{k={_q(e['k'])},{p}f={{{f}}},m={{{m}}}}}")
    return "{\n" + ",\n".join(parts) + "\n}"


def _set(names: list[str]) -> str:
    return "{" + ",".join(f"[{_q(k)}]=true" for k in names) + "}"


STRICT_LUA = r"""
local TYPES, BUILTINS, BITB = ...
local kind_of = setmetatable({}, {__mode = 'k'})   -- fake -> df type name
local metas = {}

-- (found, field type or '') of a field or method of tname or a parent
local function lookup(tname, k)
  local t, guard = TYPES[tname], 0
  while t and guard < 64 do
    local f = t.f[k]
    if f ~= nil then return true, f end
    if t.m[k] then return true, '' end
    t = t.p and TYPES[t.p]
    guard = guard + 1
  end
  return false, nil
end

local strict

local function meta(tname)
  local mt = metas[tname]
  if mt then return mt end
  local bit = TYPES[tname].k == 'bitfield'
  local built = bit and BITB or BUILTINS
  mt = {__name = tname}
  mt.__index = function(_, k)
    if type(k) == 'string' then
      if lookup(tname, k) then
        if bit then return false end
        return nil
      end
      if built[k] then
        if k == 'whole' then return 0 end
        if k == '_type' then return tname end
        return nil
      end
    elseif bit and math.type(k) == 'integer' and k >= 0 then
      return false
    end
    error(('Cannot read field %s.%s: not found.'):format(tname, tostring(k)), 2)
  end
  mt.__newindex = function(t, k, v)
    local ok, ft = false, nil
    if type(k) == 'string' then ok, ft = lookup(tname, k) end
    if not ok and bit and math.type(k) == 'integer' and k >= 0 then ok = true end
    if not ok then
      error(('Cannot write field %s.%s: not found.'):format(tname, tostring(k)), 2)
    end
    if ft and ft ~= '' and type(v) == 'table' and getmetatable(v) == nil then v = strict(ft, v) end
    rawset(t, k, v)
  end
  metas[tname] = mt
  return mt
end

strict = function(tname, tbl)
  if TYPES[tname] == nil then error('strict: no df type ' .. tostring(tname), 2) end
  tbl = tbl or {}
  if getmetatable(tbl) ~= nil then error('strict: the ' .. tname .. ' fake has a metatable already', 2) end
  local bit = TYPES[tname].k == 'bitfield'
  local wrap = {}
  for k, v in pairs(tbl) do
    local ok, ft = false, nil
    if type(k) == 'string' then ok, ft = lookup(tname, k) end
    if not ok and bit and math.type(k) == 'integer' and k >= 0 then ok = true end
    if not ok then
      error(("strict: the %s fake has a field '%s' DFHack's %s has not (keep test scaffolding in a side table)")
            :format(tname, tostring(k), tname), 2)
    end
    if ft and ft ~= '' and type(v) == 'table' and getmetatable(v) == nil then wrap[k] = ft end
  end
  for k, ft in pairs(wrap) do tbl[k] = strict(ft, tbl[k]) end
  kind_of[tbl] = tname
  return setmetatable(tbl, meta(tname))
end

local function strict_type(obj) return kind_of[obj] end
return strict, strict_type
"""


def lua_source() -> str:
    """A Lua chunk that returns strict, strict_type (no lupa needed: texlua runs it too)."""
    d = data()
    return ("local strict, strict_type = (function(...)\n" + STRICT_LUA + "\nend)("
            + lua_types() + ", " + _set(d["builtins"]) + ", " + _set(d["bitfield_builtins"]) + ")\n")


def install(lua, H=None):
    """Load the strict maker into a lupa LuaRuntime; set H.strict and H.strict_type
    when a harness table is given. Returns the Lua function strict(type, table)."""
    strict, strict_type = lua.execute(lua_source() + "return strict, strict_type\n")
    if H is not None:
        H.strict = strict
        H.strict_type = strict_type
    return strict

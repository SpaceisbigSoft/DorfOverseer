"""Make tests/fixtures/df-names.json: the DF and DFHack names the Lua may use.

    python brain/tools/gen_df_names.py                   # clone both at the tag into a temp folder
    python brain/tools/gen_df_names.py DFS_DIR DFHACK_DIR   # or use clones you have

Reads DFHack/df-structures (every df.*.xml) and DFHack/dfhack (library/LuaApi.cpp,
LuaTools.cpp, LuaWrapper.cpp, lua/dfhack.lua) at TAG and writes one JSON list:

  types    {name: {"k": kind, "p": parent, "f": {field: type or ""}, "v": [items]}}
           kind is struct/class/enum/bitfield/other; "" in "f" means the walk stops
           there (a vector, a number, a string, an enum value); an inline compound
           gets a type of its own named "<parent>.<field>".
  globals  {name: type or ""}           (df.global.<name>)
  dfhack   {module: [functions]}         ("" holds the top level: dfhack.<fn>)
  dfhack_require {module: [functions]}   only after require('dfhack.<module>')

tests/test_df_names.py checks every lua/*.lua against it, offline. Run this
again (and commit the JSON) when the project moves to another DFHack tag.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

TAG = "53.17-r1"
OUT = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "df-names.json"

PRIMS = {"int8_t", "uint8_t", "int16_t", "uint16_t", "int32_t", "uint32_t", "int64_t", "uint64_t",
         "bool", "long", "ulong", "s-float", "d-float", "size_t", "padding", "ptr-string",
         "static-string", "stl-string", "flag-bit", "int", "uint"}
CONTAINERS = {"stl-vector", "static-array", "df-flagarray", "stl-bit-vector", "stl-deque", "stl-map",
              "stl-set", "stl-unordered-map", "stl-unordered-set", "df-array", "df-linked-list",
              "stl-shared-ptr", "stl-weak-ptr", "stl-function", "stl-variant", "stl-fs-path",
              "stl-mutex", "stl-condition-variable", "stl-future", "stl-fstream", "stl-fs-filetime",
              "stl-optional"}
SKIP = {"virtual-methods", "vmethod", "custom-methods", "cmethod", "code-helper", "comment",
        "extra-include", "enum-attr", "item-attr", "codegen-override", "ret-type", "key-type",
        "value-type", "enum-item"}
KINDS = {"struct-type": "struct", "class-type": "class", "enum-type": "enum",
         "bitfield-type": "bitfield", "df-other-vectors-type": "struct",
         "df-linked-list-type": "other"}


class Gen:
    def __init__(self) -> None:
        self.types: dict[str, dict] = {}
        self.globals: dict[str, str] = {}

    def items(self, el, tag: str) -> list[str]:
        return [c.get("name") for c in el if c.tag == tag and c.get("name")]

    def fields(self, el, owner: str, into: dict) -> None:
        """The named members of a compound element (unnamed compounds and
        unions are flattened into their parent, as DFHack does)."""
        for c in el:
            if c.tag in SKIP or not isinstance(c.tag, str):
                continue
            name = c.get("name")
            if not name:
                if c.tag == "compound":
                    self.fields(c, owner, into)
                continue
            into[name] = self.target(c, f"{owner}.{name}")

    def target(self, c, anon: str) -> str:
        """What a member leads to: a type name to walk on, or "" to stop."""
        tag = c.tag
        if tag in CONTAINERS or tag in PRIMS or tag == "enum":
            return ""
        if tag == "pointer":
            if c.get("type-name"):
                return c.get("type-name")
            inner = [x for x in c if isinstance(x.tag, str) and x.tag not in SKIP]
            return self.target(inner[0], anon) if inner else ""
        if tag == "compound":
            if c.get("type-name"):
                return c.get("type-name")
            f: dict = {}
            self.fields(c, anon, f)
            self.types[anon] = {"k": "struct", "f": f}
            return anon
        if tag == "bitfield":
            if c.get("type-name"):
                return c.get("type-name")
            self.types[anon] = {"k": "bitfield", "v": self.items(c, "flag-bit")}
            return anon
        return ""

    def toplevel(self, el) -> None:
        tag = el.tag
        if tag == "global-object":
            name = el.get("name")
            if el.get("type-name"):
                t = el.get("type-name")
                self.globals[name] = "" if t in PRIMS else t
            else:
                inner = [x for x in el if isinstance(x.tag, str) and x.tag not in SKIP]
                self.globals[name] = self.target(inner[0], f"global.{name}") if inner else ""
            return
        kind = KINDS.get(tag)
        if not kind:
            return
        name = el.get("type-name")
        t: dict = {"k": kind}
        if el.get("inherits-from"):
            t["p"] = el.get("inherits-from")
        if kind == "enum":
            t["v"] = self.items(el, "enum-item")
        elif kind == "bitfield":
            t["v"] = self.items(el, "flag-bit")
        elif kind in ("struct", "class"):
            f: dict = {}
            self.fields(el, name, f)
            if tag == "df-other-vectors-type":       # one vector a value of the index enum
                f.update({v: "" for v in self.enum_items(el.get("index-enum"))})
            t["f"] = f
        self.types[name] = t

    def enum_items(self, name: str | None) -> list[str]:
        return list(self.types.get(name or "", {}).get("v", []))

    def prune(self) -> None:
        """Keep the fields only of types a df.global chain can reach: the
        others are checked by name (df.unit.find) and their fields are not."""
        seen: set[str] = set()
        stack = [v for v in self.globals.values() if v]
        while stack:
            t = stack.pop()
            if t in seen or t not in self.types:
                continue
            seen.add(t)
            x = self.types[t]
            stack += [v for v in x.get("f", {}).values() if v] + ([x["p"]] if x.get("p") else [])
        for name in list(self.types):
            if name not in seen:
                self.types[name].pop("f", None)
                if "." in name:
                    del self.types[name]

    def run(self, dfs: Path) -> None:
        roots = [ET.parse(p).getroot() for p in sorted(dfs.glob("df.*.xml"))]
        for pass_ in (0, 1):            # enums first: the other-vectors types read them
            for r in roots:
                for el in r:
                    if isinstance(el.tag, str) and ((el.tag == "enum-type") == (pass_ == 0)):
                        self.toplevel(el)


ENTRY = re.compile(r'(?:WRAPM(?:_D)?\(\s*\w+(?:::\w+)*\s*,\s*(\w+)'
                   r'|WRAP(?:_D)?\(\s*(\w+)|WRAPN(?:_D)?\(\s*(\w+)|CWRAP\(\s*(\w+)'
                   r'|WRAP_VERSION_FUNC\(\s*(\w+)|WORLD_GAMEMODE_FUNC\(\s*(\w+)|\{\s*"(\w+)"\s*,)')


def array_entries(src: str, decl: str) -> list[str]:
    m = re.search(re.escape(decl) + r"\s*\[\]\s*=\s*\{(.*?)\n\};", src, re.S)
    if not m:
        return []
    return [next(g for g in e if g) for e in ENTRY.findall(m.group(1))]


def dfhack_api(dfh: Path) -> dict[str, list[str]]:
    lib = dfh / "library"
    api = (lib / "LuaApi.cpp").read_text(encoding="utf-8", errors="replace")
    tools = (lib / "LuaTools.cpp").read_text(encoding="utf-8", errors="replace")
    mods: dict[str, set] = {"": set()}
    for m in re.finditer(r'OpenModule\(state,\s*"(\w+)",\s*(\w+)(?:,\s*(\w+))?\)', api):
        mods.setdefault(m.group(1), set())
        for arr in (m.group(2), m.group(3)):
            if arr:
                mods[m.group(1)].update(array_entries(api, arr))
    for sub in ("persistent", "matinfo", "pen", "penarray", "random"):
        mods.setdefault(sub, set()).update(array_entries(api, f"dfhack_{sub}_funcs"))
    for sub in ("persistent", "matinfo", "pen", "penarray", "random"):
        mods[""].add(sub)
    mods[""].update(array_entries(api, "LuaWrapper::FunctionReg dfhack_module"))
    mods[""].update(array_entries(api, "luaL_Reg dfhack_funcs"))
    mods[""].update(array_entries(tools, "luaL_Reg dfhack_funcs"))
    # fields LuaTools sets on the dfhack table by hand (timeout, onStateChange, ...)
    mods[""].update(re.findall(r'lua_setfield\(\s*\w+\s*,\s*-2\s*,\s*"([A-Za-z_]\w*)"\s*\)', tools))
    mods[""].update(mods.keys() - {""})
    # the Lua half: library/lua/dfhack.lua and its modules
    for p in [lib / "lua" / "dfhack.lua"]:
        s = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'^\s*(?:function\s+dfhack\.([\w.]+)\s*\(|dfhack\.([\w.]+)\s*=)', s, re.M):
            parts = (m.group(1) or m.group(2)).split(".")
            if len(parts) == 1:
                mods[""].add(parts[0])
            else:
                mods.setdefault(parts[0], set()).add(parts[1])
                mods[""].add(parts[0])
    return {k: sorted(v) for k, v in sorted(mods.items())}


def dfhack_required(dfh: Path) -> dict[str, list[str]]:
    """Functions library/lua/dfhack/<m>.lua adds to dfhack.<m>: there only
    after require('dfhack.<m>') (by this script or by a plugin before it)."""
    out: dict[str, list[str]] = {}
    for p in sorted((dfh / "library" / "lua" / "dfhack").glob("*.lua")):
        s = p.read_text(encoding="utf-8", errors="replace")
        m = next((m for m in re.finditer(r"^local\s+(\w+)\s*=\s*dfhack\.(\w+)\s*$", s, re.M)
                  if m.group(2) != "BASE_G"), None)
        if not m:
            continue
        local, mod = m.group(1), m.group(2)
        names = re.findall(rf"^\s*(?:function\s+{local}\.(\w+)\s*\(|{local}\.(\w+)\s*=)", s, re.M)
        out[mod] = sorted({a or b for a, b in names})
    return out


def df_funcs(dfh: Path) -> list[str]:
    """df.<name> that are functions or values of the df table itself."""
    w = (dfh / "library" / "LuaWrapper.cpp").read_text(encoding="utf-8", errors="replace")
    names = set(re.findall(r'lua_setfield\(state,\s*-2,\s*"([A-Za-z_]\w*)"\)', w))
    return sorted(names | {"global", "new", "delete", "sizeof", "assign", "_displace",
                           "is_instance", "reinterpret_cast", "NULL", "isvalid", "isnull"})


def main(argv: list[str]) -> int:
    if len(argv) == 2:
        dfs, dfh = Path(argv[0]), Path(argv[1])
    else:
        tmp = Path(tempfile.mkdtemp(prefix="df-names-"))
        dfs, dfh = tmp / "df-structures", tmp / "dfhack"
        for repo, dest in (("df-structures", dfs), ("dfhack", dfh)):
            subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", TAG,
                            f"https://github.com/DFHack/{repo}", str(dest)], check=True)
    g = Gen()
    g.run(dfs)
    g.prune()
    data = {"tag": TAG, "source": "github.com/DFHack/df-structures and github.com/DFHack/dfhack",
            "df_funcs": df_funcs(dfh), "globals": dict(sorted(g.globals.items())),
            "dfhack": dfhack_api(dfh), "dfhack_require": dfhack_required(dfh),
            "types": {k: g.types[k] for k in sorted(g.types)}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":"), sort_keys=False) + "\n", encoding="utf-8")
    print(f"{OUT}: {len(g.types)} types, {len(g.globals)} globals, "
          f"{sum(len(v) for v in data['dfhack'].values())} dfhack names, {OUT.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

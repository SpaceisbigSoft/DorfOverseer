"""Make tests/fixtures/df_fields_53_17.json: the fields of the df types the bridge reads.

    python brain/tools/gen_df_fields.py                 # clone df-structures at the tag into a temp folder
    python brain/tools/gen_df_fields.py DFS_DIR         # or use a clone you have
    python brain/tools/gen_df_fields.py --live DUMP.json   # or a dump from the live game (below)

The strict fakes of the Lua tests (tests/strict_fakes.py) are built from it: a
fake item, unit or building that reads a field its df type does not have
raises as DFHack does ("Cannot read field item_fishst.mat_type: not found."),
so a test can catch `it.flags.forbidden` or `fish.mat_type` before a fort does.

It reuses gen_df_names.Gen (the same df-structures walk as tests/fixtures/df-names.json)
but keeps every field of the chosen types (df-names.json prunes the fields of types
no df.global chain reaches, which is most item and building subclasses), and adds
the named virtual and custom methods (`it:getStackSize()` is a field read too).

Types kept: ROOTS, every class that inherits from one of them (all item_*st,
building_*st, general_ref_*), and every struct, class or bitfield a field of a
kept type leads to (transitively). Written as

  types  {name: {"k": kind, "p": parent, "f": {field: type or ""}, "m": [methods]}}
         a bitfield's "f" holds its bits, each "" ; a field's type is the df type
         its value has (a struct, class or bitfield kept here) or "" (a number, a
         string, a vector, an enum value: the fake keeps whatever the test put).
  builtins / bitfield_builtins   what every object / bitfield also answers
         (_type, _field, sizeof, ...; whole on a bitfield).

Regenerate it when the project moves to another DFHack tag (change TAG), and
commit the JSON. From the live game instead (when df-structures and the running
DFHack disagree), run in the DFHack console

    lua local j=require('json') local function tn(x) return x and tostring(x):match('<type: ([%w_.]+)>') or '' end local o={} for _,n in ipairs({'item','item_actual','item_crafted','item_fishst','item_eggst','item_foodst','unit','building','building_actual','job','squad','burrow','item_flags','unit_flags1','unit_flags2','unit_flags3','unit_flags4','building_flags','job_flags'}) do local t=df[n] local f={} if t then if t._kind=='bitfield-type' then for i=0,(t._last_item or 31) do if t[i] then f[t[i]]='' end end else for k,v in pairs(t._fields or {}) do if type(k)=='string' then f[k]=tn(v.type) end end end end o[n]={k=t and t._kind or '?',p=t and t._super and tn(t._super) or nil,f=f} end j.encode_file(o,'df-fields-live.json')

(df.<type>._fields: the field descriptors keyed by name, .type the df type of a
compound field; _super the parent type; a bitfield's names are its numbered
items. Not yet run in game: check the dump looks right before --live) and pass the file
with --live: its types replace the ones generated here, their methods kept.
Add any type the bridge reads to the list (and to ROOTS here).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_df_names import TAG, Gen  # noqa: E402

OUT = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "df_fields_53_17.json"

# The types the bridge reads most (grep lua/ for `.flags.`, `mat_type`, `u.pos`):
# items, units, buildings and their flags, jobs, squads, burrows, refs, orders.
ROOTS = ["item", "unit", "building", "job", "squad", "burrow", "general_ref", "specific_ref",
         "manager_order", "historical_figure", "unit_health_info", "plotinfost", "construction",
         "activity_entry", "caravan_state", "mandate", "invasion_info"]
# The classes whose every subclass is kept too.
FAMILIES = ["item", "building", "general_ref", "specific_ref"]
# Reached by a field but too wide to be worth keeping (the walk stops there).
STOP = {"world", "world_data", "world_raws", "creature_raw", "caste_raw", "map_block",
        "historical_entity", "entity_raw", "language_name", "material", "matgloss",
        "graphic", "interface", "gview", "enabler", "renderer", "plant_raw", "inorganic_raw",
        "itemdef", "texture_handlerst", "plotinfost.main"}

# What DFHack answers on every struct (LuaWrapper.cpp MakeMetatable) and bitfield.
BUILTINS = ["_type", "_kind", "_field", "sizeof", "new", "delete", "assign", "_displace"]
BITFIELD_BUILTINS = BUILTINS + ["whole"]


def methods(dfs: Path) -> dict[str, list[str]]:
    """The named vmethods and cmethods of each struct or class: Lua reaches
    them as fields (it:getStackSize())."""
    out: dict[str, list[str]] = {}
    for p in sorted(dfs.glob("df.*.xml")):
        for el in ET.parse(p).getroot():
            if not isinstance(el.tag, str) or el.tag not in ("class-type", "struct-type"):
                continue
            names: set[str] = set()
            for block in el:
                if block.tag in ("virtual-methods", "custom-methods"):
                    names.update(m.get("name") for m in block
                                 if m.tag in ("vmethod", "cmethod") and m.get("name"))
            if names:
                out[el.get("type-name")] = sorted(names)
    return out


def descends(types: dict, name: str, family: str) -> bool:
    seen = set()
    while name and name not in seen:
        if name == family:
            return True
        seen.add(name)
        name = types.get(name, {}).get("p")
    return False


def select(types: dict) -> dict:
    keep: set[str] = set()
    stack = [r for r in ROOTS if r in types]
    stack += [n for n in types for fam in FAMILIES if descends(types, n, fam)]
    while stack:
        n = stack.pop()
        if n in keep or n in STOP or n not in types:
            continue
        t = types[n]
        if t.get("k") not in ("struct", "class", "bitfield"):
            continue
        keep.add(n)
        if t.get("p"):
            stack.append(t["p"])
        stack += [v for v in t.get("f", {}).values() if v]
    return {n: types[n] for n in sorted(keep)}


def build(types: dict, meth: dict) -> dict:
    out = {}
    for n, t in select(types).items():
        e: dict = {"k": t["k"]}
        if t.get("p"):
            e["p"] = t["p"]
        if t["k"] == "bitfield":
            e["f"] = {b: "" for b in t.get("v", [])}
        else:
            # a field leading to a type not kept here is just a value to the fake
            e["f"] = {f: (v if v in types and v not in STOP
                          and types[v].get("k") in ("struct", "class", "bitfield") else "")
                      for f, v in t.get("f", {}).items()}
            if meth.get(n):
                e["m"] = meth[n]
        out[n] = e
    # a type a field names but select() did not keep (STOP) is "" in the parents
    for e in out.values():
        if e["k"] != "bitfield":
            e["f"] = {f: (v if v in out else "") for f, v in e["f"].items()}
    return out


def live(path: Path, out: dict) -> None:
    """Replace the generated types with those of a live dump (the docstring's one-liner)."""
    for n, t in json.loads(path.read_text(encoding="utf-8")).items():
        if t.get("k") == "?":
            continue
        kind = "bitfield" if "bitfield" in str(t.get("k")) else ("class" if "class" in str(t.get("k")) else "struct")
        e = {"k": kind, "f": {f: (v if v in out else "") for f, v in t.get("f", {}).items()}}
        if t.get("p"):
            e["p"] = t["p"]
        if out.get(n, {}).get("m"):
            e["m"] = out[n]["m"]
        out[n] = e


def main(argv: list[str]) -> int:
    live_dump = None
    if len(argv) >= 2 and argv[0] == "--live":
        live_dump, argv = Path(argv[1]), argv[2:]
    if argv:
        dfs = Path(argv[0])
    else:
        dfs = Path(tempfile.mkdtemp(prefix="df-fields-")) / "df-structures"
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", TAG,
                        "https://github.com/DFHack/df-structures", str(dfs)], check=True)
    g = Gen()
    g.run(dfs)                      # no prune(): every field of every type
    types = build(g.types, methods(dfs))
    if live_dump:
        live(live_dump, types)
    data = {"tag": TAG, "source": "github.com/DFHack/df-structures (brain/tools/gen_df_fields.py)"
            + (f" + live dump {live_dump.name}" if live_dump else ""),
            "roots": ROOTS, "builtins": BUILTINS, "bitfield_builtins": BITFIELD_BUILTINS,
            "types": types}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{OUT}: {len(types)} types, {OUT.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

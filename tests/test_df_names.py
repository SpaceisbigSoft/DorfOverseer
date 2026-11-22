"""(0.105.48 K10) Every DF and DFHack name in lua/*.lua exists in DFHack 53.17-r1.

The Lua tests run the bridge against stub df/dfhack tables written from the
module under test, so a wrong name is stubbed as wrong as it is written, and
in the game a pcall then hides it (audit A12, findings 2, 11, 12, 16). This
file checks the names themselves against tests/fixtures/df-names.json, a list
made from DFHack/df-structures and DFHack/dfhack at the 53.17-r1 tag by
brain/tools/gen_df_names.py. It runs offline, without lupa, in a few seconds.

Checked, with comments and strings left out:
  df.global.<chain>    each step a field of the type before it, until a vector,
                       a number or an enum value ends the walk; also a local
                       set once to such a chain (local other = df.global.world.items.other)
  df.<type>            a type of df-structures, or a function of the df table
  df.<enum>.<NAME>     a value of that enum (or bitfield), or attrs/_first_item/...
  df.<type>.T_<f>...   (r9) the type DFHack makes for an inline enum, bitfield or
                       compound field (no type-name), and a value of it
  dfhack.<fn>          a top-level DFHack Lua function or module
  dfhack.<module>.<fn> a function of that module (LuaApi.cpp and dfhack.lua)

ALLOWED lists the names that are wrong in DFHack 53.17 on purpose: second
tries after the right name, each behind a pcall. EXPECTED_WRONG lists the
ones the audit found wrong in code other 0.105.48 groups fix; when a fix lands
its entry must go (the "still wrong" test says so).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import ROOT, finish, test  # noqa: E402

NAMES = json.loads((ROOT / "tests" / "fixtures" / "df-names.json").read_text(encoding="utf-8"))
TYPES, GLOBALS, API = NAMES["types"], NAMES["globals"], NAMES["dfhack"]
NEEDS_REQUIRE = NAMES["dfhack_require"]
DF_FUNCS = set(NAMES["df_funcs"])
NESTED = NAMES["nested"]   # (r9) "<type>.T_<field>": the inline enums', bitfields' and compounds' types
ENUM_MEMBERS = {"attrs", "next_item", "is_valid", "_first_item", "_last_item", "_complex",
                "whole", "_enum", "_index_table"}
TYPE_MEMBERS = {"find", "get_vector", "new", "sizeof", "is_instance", "delete", "assign"}

# (file, name): why the wrong name is there. Each one sits behind a pcall,
# after (or before) the 53.17 name, for an older or newer DFHack.
ALLOWED = {
    # dfhack.TranslateName: DFHack before 50.15; read only when dfhack.translation is missing
    **{(f, "dfhack.TranslateName"): "fallback for DFHack < 50.15" for f in (
        "ai-artifacts.lua", "ai-diplomacy.lua", "ai-bridge.lua", "ai-camera.lua",
        "ai-missions.lua", "ai-raids.lua", "ai-nobles.lua", "ai-trade.lua", "ai-thirst.lua")},
    ("ai-bridge-actions-fort.lua", "df.global.announcements"): "second try after df.global.d_init.announcements",
    ("ai-constructions.lua", "df.global.world.constructions"): "second try after world.event.constructions",
    ("ai-disposal.lua", "df.civzone_type.GarbageDump"): "second try after civzone_type.Dump",
    ("ai-herd.lua", "df.global.plotinfo.equipment.training_assignments"): "second try after plotinfo.training.training_assignments",
    ("ai-society-animals.lua", "df.global.plotinfo.equipment.training_assignments"): "second try after plotinfo.training.training_assignments",
    ("ai-noble-demands.lua", "df.global.world.engravings"): "first try; world.event.engravings (right) follows",
    # (r9) the T_ names: an inline enum's type in DFHack before the enum got a name of its own
    ("ai-gates-works.lua", "df.job_item_ref.T_role"): "second try after df.job_role_type",
    ("ai-bridge-probes.lua", "df.job_item_ref.T_role"): "the probe reports both names, each in a pcall",
    ("ai-military-gear.lua", "df.unit_inventory_item.T_mode"): "second try after df.inv_item_role_type",
    ("ai-military.lua", "df.unit_inventory_item.T_mode.Worn"): "second try after df.inv_item_role_type.Worn",
    ("ai-society-needs.lua", "df.unit_inventory_item.T_mode.Worn"): "first try; df.inv_item_role_type.Worn follows",
    # (0.105.51) a Lua table, not a C++ function: library/lua/dfhack.lua sets it
    # (internal.scripts = internal.scripts or {}, the Script objects by path)
    ("ai-util-doors.lua", "dfhack.internal.scripts"): "dfhack.lua's own table of loaded scripts (module_flags_reset)",
    # (r8 s9) seen since ai-threats.lua was split: a table key `other = 0` further down the one file (now in
    # ai-threats-survey.lua) kept this check from following the alias `local other = df.global...`
    ("ai-threats.lua", "df.global.world.buildings.other.ZONE_PIT_POND"): "second try after other.ZONE_POND",
    ("ai-homes-furnish.lua", "dfhack.buildings.constructBuilding"): "(r9 t6) its hub ai-homes.lua requires dfhack.buildings before loading it",
}

# (file, name): wrong in 53.17, found by this check in 0.105.48 and reported,
# not yet given to a group. Each sits behind a pcall, so the game runs on
# without it, but what it was for never happens.
REPORTED: dict = {}   # (0.105.48 round 2: builder 19 fixed job.getSpecificLabor/getSkill and the
                      # constructBuilding requires)

# (file, name): wrong in 53.17, fixed by another 0.105.48 group (remove at merge).
EXPECTED_WRONG: dict = {}   # (0.105.48 merge: builder 9 fixed the three)

LONG_COMMENT = re.compile(r"--\[(=*)\[.*?\]\1\]", re.S)
LONG_STRING = re.compile(r"\[(=*)\[.*?\]\1\]", re.S)
SHORT = re.compile(r"""("(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|--[^\n]*)""")
NAME = re.compile(r"(?<![\w.:])(df|dfhack)((?:\.[A-Za-z_]\w*)+)")
ALIAS = re.compile(r"\blocal\s+([A-Za-z_]\w*)\s*=\s*df\.global((?:\.[A-Za-z_]\w*)+)\s*(?:$|;|\n)", re.M)


def blank(m: re.Match) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def code_only(src: str) -> str:
    """The source with comments and strings blanked out, lines kept."""
    src = LONG_COMMENT.sub(blank, src)
    out, i = [], 0
    for m in SHORT.finditer(src):          # strings and line comments, left to right
        out.append(src[i:m.start()])
        out.append(blank(m))
        i = m.end()
    out.append(src[i:])
    return LONG_STRING.sub(blank, "".join(out))


def fields_of(t: str) -> dict | None:
    """All fields of a type with its parents', or None if not known here."""
    out: dict = {}
    seen = set()
    while t and t in TYPES and t not in seen:
        seen.add(t)
        x = TYPES[t]
        if "f" not in x:
            return None
        for k, v in x["f"].items():
            out.setdefault(k, v)
        t = x.get("p", "")
    return out if seen else None


def walk(t: str, parts: list[str]) -> str | None:
    """Walk fields from type t; the first part that is not there, or None."""
    for p in parts:
        if not t or t not in TYPES:
            return None
        x = TYPES[t]
        if x["k"] in ("enum", "bitfield"):
            if x["k"] == "bitfield" and p not in x.get("v", []) and not p.startswith("_") \
                    and p not in ENUM_MEMBERS:
                return p
            return None
        f = fields_of(t)
        if f is None or p.startswith("_"):
            return None
        if p not in f:
            return p
        t = f[p]
    return None


def check_df(parts: list[str]) -> str | None:
    """None if df.<parts> exists, else why not."""
    head = parts[0]
    if head == "global":
        if len(parts) == 1:
            return None
        if parts[1] not in GLOBALS:
            return f"no global {parts[1]}"
        bad = walk(GLOBALS[parts[1]], parts[2:])
        return f"no field {bad}" if bad else None
    if head in DF_FUNCS:
        return None
    if head not in TYPES:
        return f"no type {head}"
    if len(parts) == 1:
        return None
    x, p = TYPES[head], parts[1]
    if x["k"] in ("enum", "bitfield"):
        if p in x.get("v", []) or p in ENUM_MEMBERS or p in TYPE_MEMBERS or p.startswith("_"):
            return None
        return f"no value {p} in {head}"
    if p.startswith("T_"):
        return check_nested(head, parts[1:])
    if p in TYPE_MEMBERS or p.startswith("_"):
        return None
    return f"no member {p} of type {head}"


def check_nested(head: str, parts: list[str]) -> str | None:
    """(r9) df.<head>.T_<a>[.T_<b>...][.<VALUE>]: the T_ types DFHack makes for
    an inline enum, bitfield or compound (one with no type-name of its own),
    on the type or a parent of it; then a value of the enum or bitfield."""
    owners, seen = [], set()
    t = head
    while t and t in TYPES and t not in seen:
        seen.add(t)
        owners.append(t)
        t = TYPES[t].get("p", "")
    path = next((o + "." + parts[0] for o in owners if o + "." + parts[0] in NESTED), None)
    if path is None:
        return f"no nested type {parts[0]} in {head}"
    for p in parts[1:]:
        x = NESTED[path]
        if p.startswith("T_") and x["k"] == "struct":
            if path + "." + p not in NESTED:
                return f"no nested type {p} in {path}"
            path += "." + p
            continue
        if x["k"] in ("enum", "bitfield"):
            if p in x["v"] or p in ENUM_MEMBERS or p in TYPE_MEMBERS or p.startswith("_"):
                return None
            return f"no value {p} in {path}"
        return None                  # a compound's member (new, sizeof, ...): not checked here
    return None


def check_dfhack(parts: list[str], required: set[str] = frozenset()) -> str | None:
    top = API[""]
    if len(parts) > 1 and parts[1] in NEEDS_REQUIRE.get(parts[0], ()):
        return None if parts[0] in required else f"only after require('dfhack.{parts[0]}')"
    if parts[0] not in top and not parts[0].startswith("_"):
        return f"no dfhack.{parts[0]}"
    if len(parts) > 1 and parts[0] in API and parts[0] != "":
        if parts[1] not in API[parts[0]] and not parts[1].startswith("_"):
            return f"no function {parts[1]} in dfhack.{parts[0]}"
    return None


def aliases(code: str) -> dict[str, list[str]]:
    """local NAME = df.global.a.b, kept only if NAME is never set otherwise."""
    found: dict[str, list[str]] = {}
    for m in ALIAS.finditer(code):
        name, chain = m.group(1), m.group(2).lstrip(".").split(".")
        if found.get(name, chain) != chain:
            found[name] = []                 # two different chains: drop
        else:
            found[name] = chain
    out = {}
    for name, chain in found.items():
        if not chain:
            continue
        sets = re.findall(rf"(?<![\w.:])(?:local\s+)?{name}\s*=(?!=)\s*([^\n]*)", code)
        params = re.search(rf"function[^(\n]*\([^)]*\b{name}\b[^)]*\)", code)
        others = [s for s in sets if not s.strip().startswith("df.global." + ".".join(chain))
                  or not re.match(r"df\.global[\w.]*\s*(?:$|;)", s.strip())]
        if not others and not params and not re.search(rf"\blocal\s+{name}\s*(?:$|[,\n;])", code, re.M) \
                and not re.search(rf"\bfor\b[^\n]*\b{name}\b[^\n]*\bin\b", code):
            out[name] = chain
    return out


def scan(path: Path) -> list[tuple[int, str, str]]:
    """(line, name, why) for every name in a Lua file DFHack 53.17 lacks."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    code = code_only(raw)
    required = set(re.findall(r"""require\s*\(?\s*['"]dfhack\.(\w+)['"]""", raw))
    out = []
    seen = set()
    for m in NAME.finditer(code):
        parts = m.group(2).lstrip(".").split(".")
        why = check_df(parts) if m.group(1) == "df" else check_dfhack(parts, required)
        if why:
            name = m.group(1) + m.group(2)
            line = code.count("\n", 0, m.start()) + 1
            if (name, why) not in seen:
                seen.add((name, why))
                out.append((line, name, why))
    for alias, chain in aliases(code).items():
        for m in re.finditer(rf"(?<![\w.:]){alias}((?:\.[A-Za-z_]\w*)+)", code):
            parts = ["global"] + chain + m.group(1).lstrip(".").split(".")
            why = check_df(parts)
            if why:
                name = "df." + ".".join(parts)
                if (name, why) not in seen:
                    seen.add((name, why))
                    out.append((code.count("\n", 0, m.start()) + 1, name, why))
    return out


def shown_as(name: str, why: str) -> str:
    """The name cut back to the part that is wrong (what ALLOWED holds)."""
    bad = why.split()[-1] if why.startswith(("no field", "no global")) else None
    if bad and "." + bad in name:
        return name[:name.index("." + bad) + len(bad) + 1]
    return name


LUA = sorted((ROOT / "lua").glob("*.lua"))
FOUND = {(p.name, shown_as(n, w)): (ln, w) for p in LUA for ln, n, w in scan(p)}


@test("the names list is DFHack 53.17-r1's and holds what the checks need")
def _():
    assert NAMES["tag"] == "53.17-r1"
    assert GLOBALS["world"] == "world" and "plotinfo" in GLOBALS
    assert "ZONE_POND" in TYPES["buildings_other"]["f"]
    assert "findByName" in API["burrows"] and "translateName" in API["translation"]
    assert "Lever" in TYPES["trap_type"]["v"] and TYPES["unit"]["k"] in ("struct", "class")
    assert "AtDepot" in NESTED["caravan_state.T_trade_state"]["v"]   # (r9) the T_ types are in the list


@test("the checker finds wrong names (planted ones)")
def _():
    assert check_df(["global", "world", "buildings", "other", "ZONE_PIT_POND"]) == "no field ZONE_PIT_POND"
    assert check_df(["global", "world", "buildings", "other", "ZONE_POND"]) is None
    assert check_df(["global", "no_such_global"]) == "no global no_such_global"
    assert check_df(["building_type", "Hatch"]) is None
    assert check_df(["building_type", "Hach"]) == "no value Hach in building_type"
    assert check_df(["no_such_typest"]) == "no type no_such_typest"
    assert check_df(["unit", "find"]) is None
    # (r9) the T_ types of inline enums: checked, values and all
    assert check_df(["caravan_state", "T_trade_state"]) is None
    assert check_df(["caravan_state", "T_trade_state", "AtDepot"]) is None
    assert check_df(["caravan_state", "T_trade_state", "AtDepo"]) == "no value AtDepo in caravan_state.T_trade_state"
    assert check_df(["caravan_state", "T_trade_stat"]) == "no nested type T_trade_stat in caravan_state"
    assert check_df(["job_item_ref", "T_role"]) == "no nested type T_role in job_item_ref"   # named: job_role_type
    assert check_df(["historical_entity", "T_resources", "T_metal"]) is None
    assert check_df(["historical_entity", "T_resources", "T_nope"]) == "no nested type T_nope in historical_entity.T_resources"
    assert check_dfhack(["burrows", "listUnits"]) == "no function listUnits in dfhack.burrows"
    assert check_dfhack(["burrows", "findByName"]) is None
    assert check_dfhack(["units", "isCitizen"]) is None
    assert check_dfhack(["TranslateName"]) == "no dfhack.TranslateName"
    assert check_dfhack(["buildings", "constructBuilding"]) == "only after require('dfhack.buildings')"
    assert check_dfhack(["buildings", "constructBuilding"], {"buildings"}) is None
    assert check_dfhack(["world", "isFortressMode"]) is None
    assert check_dfhack(["timeout"]) is None and check_dfhack(["persistent", "getSiteData"]) is None


@test("comments and strings are not read; a local set once to a df.global chain is")
def _():
    src = ("-- df.global.world.nope\nlocal s = 'dfhack.nope.x'\n--[[ df.nope ]]\n"
           "local other = df.global.world.buildings.other\nlocal a = other.ZONE_PIT_POND\n"
           "local x = df.global.world.units.active\n")
    tmp = ROOT / "tests" / "__pycache__"
    tmp.mkdir(exist_ok=True)
    p = tmp / "k48_names_probe.lua"
    p.write_text(src, encoding="utf-8")
    try:
        got = [(n, w) for _, n, w in scan(p)]
    finally:
        p.unlink()
    assert got == [("df.global.world.buildings.other.ZONE_PIT_POND", "no field ZONE_PIT_POND")], got


@test("every df.* and dfhack.* name in lua/*.lua exists in DFHack 53.17-r1")
def _():
    bad = [f"{f}:{ln}: {n} ({w})" for (f, n), (ln, w) in sorted(FOUND.items())
           if (f, n) not in ALLOWED and (f, n) not in EXPECTED_WRONG and (f, n) not in REPORTED]
    assert not bad, "names DFHack 53.17-r1 does not have:\n" + "\n".join(bad)


@test("each allowed or expected-wrong name is still there (remove the entry once fixed)")
def _():
    gone = [f"{f}: {n}" for f, n in list(ALLOWED) + list(EXPECTED_WRONG) + list(REPORTED) if (f, n) not in FOUND]
    assert not gone, "no longer in the code, drop from test_df_names.py:\n" + "\n".join(gone)


if __name__ == "__main__":
    finish()

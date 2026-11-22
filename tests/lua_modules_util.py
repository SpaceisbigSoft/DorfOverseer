"""(13c lua-modules) Support for the Lua tests: lua/ai-util.lua for a module
loaded into a test's fake game.

The modules take ai-util with reqscript('ai-util') as they load. A test
that loads a module's source into a fake env reads it with `module_src(name)`
(or wraps text it already read with `with_util`): one line is put before the
module's first line (so its line numbers stay) that makes the env's
reqscript answer 'ai-util' (and a split module's other half) with the real
module, loaded over the env (so it sees the fake df and dfhack), and pass
every other name to the env's own reqscript (if any) as before.

Not a test file itself (run_all runs test_*.py only).
"""

from __future__ import annotations

from pathlib import Path

LUA_DIR = Path(__file__).resolve().parent.parent / "lua"
UTIL_SRC = (LUA_DIR / "ai-util.lua").read_text(encoding="utf-8")


def _lua_string(s: str) -> str:
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


# (13c) a module split in two: the half the first loads on call, by name
COMPANIONS = {"ai-military.lua": ["ai-military-gear"], "ai-society.lua": ["ai-society-burrows"]}

# (13e) a module split into a hub and parts (lua/ai-gates.lua): the hub loads
# its parts (PARTS) from the files beside it; loaded from text in a test, it
# takes their texts from PART_SOURCES, which the prelude sets
SPLIT = ("ai-gates.lua", "ai-society.lua", "ai-military.lua", "ai-threats.lua", "ai-waterworks.lua")


def split_parts(name: str) -> list[str]:
    """The parts' module names ('ai-gates-scan', ...) of a split hub, from its PARTS line."""
    import re
    hub = (LUA_DIR / name).read_text(encoding="utf-8")
    listed = re.search(r"^PARTS = (\{[^}]*\})", hub, re.M)
    stem = name[:-4]
    return [f"{stem}-{p}" for p in re.findall(r"'([\w-]+)'", listed.group(1))] if listed else []


# (r6) the bridge parts split into themed files: the first file's name ->
# the later ones (loaded right after it, in this order, by ai-bridge.lua's
# BRIDGE_PARTS), read from the hub's list
def bridge_later_parts(stem: str) -> list[str]:
    import re
    hub = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    listed = re.findall(r"'([\w-]+)'", re.search(r"^BRIDGE_PARTS = \{(.*?)\}", hub, re.M).group(1))
    return [n for n in listed if n.startswith(stem + "-") and n != stem]


BRIDGE_SPLIT = ("ai-bridge-report", "ai-bridge-actions")


def bridge_part_src(name: str) -> str:
    """(r6) A bridge part's text as when it was one file: lua/<name>.lua and the
    files split off it (ai-bridge-report -> -supplies, -fort, -world;
    ai-bridge-actions -> -fort, -works, -civic) after it, in load order. Run in
    one env it does what the parts do loaded one after another."""
    stem = name[:-4] if name.endswith(".lua") else name
    out = (LUA_DIR / (stem + ".lua")).read_text(encoding="utf-8")
    for p in bridge_later_parts(stem) if stem in BRIDGE_SPLIT else []:
        out += "\n" + (LUA_DIR / (p + ".lua")).read_text(encoding="utf-8")
    return out


def split_src(name: str) -> str:
    """lua/<name> and, for a split hub, its parts' texts after it (for tests
    that read the source itself, not run it)."""
    if name[:-4] in BRIDGE_SPLIT:
        return bridge_part_src(name)
    out = (LUA_DIR / name).read_text(encoding="utf-8")
    for p in split_parts(name) if name in SPLIT else []:
        out += "\n" + (LUA_DIR / (p + ".lua")).read_text(encoding="utf-8")
    return out


def prelude(name: str = "") -> str:
    """The one line put before a module's first line. `name` (the module's
    file name) makes reqscript of the module itself answer with its env, and
    of its companions (COMPANIONS) with theirs, loaded over it."""
    srcs = {"ai-util": UTIL_SRC}
    for c in COMPANIONS.get(name, []):
        srcs[c] = (LUA_DIR / (c + ".lua")).read_text(encoding="utf-8")
    table = ", ".join(f"[{_lua_string(k)}] = {_lua_string(v)}" for k, v in srcs.items())
    me = _lua_string(name[:-4]) if name.endswith(".lua") else "nil"
    parts = ""
    if name in SPLIT:
        parts = "PART_SOURCES = {" + ", ".join(
            f"[{_lua_string(p)}] = {_lua_string((LUA_DIR / (p + '.lua')).read_text(encoding='utf-8'))}"
            for p in split_parts(name)) + "}; "
    return (
        parts +
        "do local real_req, loaded, srcs, me = reqscript, {}, {" + table + "}, " + me + "; "
        "reqscript = function(n, ...) "
        "if n == me then return _ENV end "
        "if srcs[n] then "
        "if not loaded[n] then local e = setmetatable({}, {__index = _ENV}); loaded[n] = e; "
        "assert(load(srcs[n], n, 't', e))() end "
        "return loaded[n] end "
        "if real_req then return real_req(n, ...) end "
        "error('reqscript ' .. tostring(n)) end end "
    )


PRELUDE = prelude()


def with_util(src: str, name: str = "") -> str:
    """A module's source with the one-line prelude in front of its first line."""
    return prelude(name) + src


def module_src(name: str) -> str:
    """lua/<name> read, with the prelude."""
    src = bridge_part_src(name) if name[:-4] in BRIDGE_SPLIT else (LUA_DIR / name).read_text(encoding="utf-8")
    return with_util(src, name)


def builder_part_src(name: str) -> str:
    """(r8) A builder part's text as when it was one file: lua/<name>.lua and the
    files split off it (ai-builder-projects -> ai-builder-projects-progress, ...)
    after it, in ai-builder.lua's PARTS order."""
    import re
    stem = name[:-4] if name.endswith(".lua") else name
    hub = (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8")
    listed = ["ai-builder-" + p for p in re.findall(r"'([\w-]+)'", re.search(r"^PARTS = \{(.*?)\}", hub, re.M | re.S).group(1))]
    return "\n".join((LUA_DIR / (n + ".lua")).read_text(encoding="utf-8")
                     for n in listed if n == stem or n.startswith(stem + "-"))

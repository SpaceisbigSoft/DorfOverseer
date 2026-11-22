"""Draw a level layout as text, without the game.

    python3 brain/tools/draw_level.py workshops                  one kind, default size
    python3 brain/tools/draw_level.py workshops --param rooms=6  six workshop rooms
    python3 brain/tools/draw_level.py bedrooms --param rooms=8 --param room_size=3
    python3 brain/tools/draw_level.py dining --param tables=20 --param style.hall=round
    python3 brain/tools/draw_level.py --all                      every kind, default size
    python3 brain/tools/draw_level.py --all --out levels.txt     into a file
    python3 brain/tools/draw_level.py --list                     the kinds and their defaults

The layouts come from lua/ai-layouts.lua's make(kind, params), run in a Lua
engine as the tests run it (pip install lupa). Nothing touches the game.

--param KEY=VALUE (repeatable): a number, true/false, a list (a,b,c or JSON)
or a text. `style.hall=rounded` (or `style=hall=rounded,arms=ring`, or
`style={...}` as JSON) sets a field of the level's style. For workshops and
storage, `rooms=N` is a short way to ask for N rooms (the first N of the
default shops or piles).

The picture: `#` rock, `.` dug floor, `X` the stair, `:` the 3x3 hub round
it, and a letter or digit for each door, piece of furniture, workshop and
stockpile area (the legend under the picture names them). North is up.

Other code can draw any set of tiles with render():

    from draw_level import render
    print(render([(0, 0), (1, 0), (2, 0)], marks=[(2, 0, "door")]))

render() needs no lupa; only loading ai-layouts.lua does.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LAYOUTS_LUA = ROOT / "lua" / "ai-layouts.lua"

ROCK, FLOOR, STAIR, HUB = "#", ".", "X", ":"

# Default parameters for each kind (--all, and a kind given without --param).
DEFAULTS: dict[str, dict] = {
    "bedrooms": {"rooms": 8, "room_size": 3},
    "suites": {"suites": 2},
    "jail": {"cells": 4},
    "dining": {"tables": 12},
    "storage": {"piles": ["food", "stone", "wood", "furniture"], "room_size": 5},
    "workshops": {"shops": ["Still", "Kitchen", "Masons", "Carpenters"]},
    "temple": {"size": "shrine"},
    "memorial": {"name": "the Fallen"},
    "hospital": {"beds": 8},
    "barracks": {"beds": 8},
    "tombs": {"coffins": 8},
    "tavern": {"tables": 8},
    "library": {"bookcases": 8},
    "archery": {"lanes": 2, "length": 12},
    "garden": {"name": "Copper"},
    "farms": {"plots": 4},          # make() knows it, though it is not in KINDS
}
# rooms=N for these kinds: the first N of this list
ROOM_LISTS = {
    "workshops": ("shops", ["Still", "Kitchen", "Masons", "Carpenters", "Craftsdwarfs", "Loom", "Smelter",
                            "Tanners", "Bowyers", "Mechanics", "Butchers", "Clothiers"]),
    "storage": ("piles", ["food", "stone", "wood", "furniture", "bars_blocks", "finished_goods", "cloth",
                          "leather", "gems", "ammo", "weapons", "armor"]),
}
LIST_PARAMS = {"shops", "piles", "spare_for", "customs"}

# Quickfort build keys the layouts use: key -> (name, the glyph it would like)
FURNITURE = {
    "d": ("door", "D"), "b": ("bed", "b"), "c": ("chair", "c"), "t": ("table", "t"),
    "f": ("cabinet", "f"), "h": ("chest", "h"), "n": ("coffin", "n"), "r": ("weapon rack", "r"),
    "a": ("armor stand", "a"), "s": ("statue", "s"), "v": ("chain", "v"), "A": ("archery target", "A"),
    "p": ("farm plot", "p"), "~c": ("bookcase", "k"),
}
# Quickfort stockpile keys -> the glyph a pile of that kind would like (upper case)
PILE_GLYPHS = {"food": "F", "stone": "S", "wood": "W", "furniture": "U", "bars_blocks": "B",
               "finished_goods": "G", "cloth": "H", "leather": "L", "gems": "E", "ammo": "Z",
               "weapons": "P", "armor": "R"}
WORKSHOP_GLYPH = "w"                 # a workshop's 3x3; its centre tile is its own digit
_POOL = "123456789" + "ABCDEFGHIJKLMNOPQRSTUVWYZ" + "abcdefghijklmnopqrstuvwxyz" + "@&%$*=+~^!?/<>"
_RESERVED = {ROCK, FLOOR, STAIR, HUB, " "}

_CELL = re.compile(r"^(.*?)(?:\((\d+)x(\d+)\))?$", re.S)


# ---------------------------------------------------------------------------
# Drawing (plain Python data; no Lua)
# ---------------------------------------------------------------------------

def _norm_cells(cells) -> set[tuple[int, int]]:
    return {(int(c[0]), int(c[1])) for c in cells}


def _norm_marks(marks) -> list[dict]:
    """Marks in any accepted form -> [{x, y, w, h, label, glyph}].

    Accepted: a list of (x, y, label) or (x, y, label, glyph) tuples; a list
    of dicts {x, y, label, glyph?, w?, h?} (w x h tiles from the top-left
    (x, y)); or a dict {label: [(x, y), ...]}. A later mark draws over an
    earlier one on the same tile."""
    out: list[dict] = []
    if not marks:
        return out
    if isinstance(marks, dict):
        marks = [(x, y, label) for label, pts in marks.items() for x, y in pts]
    for m in marks:
        if isinstance(m, dict):
            out.append({"x": int(m["x"]), "y": int(m["y"]), "w": int(m.get("w", 1)), "h": int(m.get("h", 1)),
                        "label": str(m.get("label", "mark")), "glyph": m.get("glyph")})
        else:
            out.append({"x": int(m[0]), "y": int(m[1]), "w": 1, "h": 1, "label": str(m[2]),
                        "glyph": m[3] if len(m) > 3 else None})
    return out


def _assign_glyphs(marks: list[dict]) -> dict[str, str]:
    """One glyph a label: the one asked for (or the label's first letter)
    when it is free, else the next free one from the pool."""
    by_label: dict[str, str] = {}
    used = set(_RESERVED)
    for m in marks:
        label = m["label"]
        if label in by_label:
            continue
        want = m["glyph"] or (label[:1] if label[:1].isalnum() else None)
        if not want or len(want) != 1 or want in used:
            alt = want.swapcase() if want and len(want) == 1 else None
            want = alt if alt and alt != want and alt not in used and not m["glyph"] else None
        if not want:
            want = next((g for g in _POOL if g not in used), "?")
        by_label[label] = want
        used.add(want)
    return by_label


def narrowest(cells) -> int:
    """The narrowest way through a set of dug tiles: the smallest, over all
    tiles, of the shorter of the tile's row run and column run. A doorway 1
    wide gives 1, a 2-wide corridor 2. Furniture is not counted; 0 if empty."""
    dug = _norm_cells(cells)
    best = 0
    runs_h: dict[tuple[int, int], int] = {}
    runs_v: dict[tuple[int, int], int] = {}
    for (x, y) in dug:
        if (x - 1, y) not in dug:
            n = 0
            while (x + n, y) in dug:
                n += 1
            for i in range(n):
                runs_h[(x + i, y)] = n
        if (x, y - 1) not in dug:
            n = 0
            while (x, y + n) in dug:
                n += 1
            for i in range(n):
                runs_v[(x, y + i)] = n
    for t in dug:
        w = min(runs_h[t], runs_v[t])
        best = w if best == 0 else min(best, w)
    return best


def render(layout_dict_or_cells, marks=None) -> str:
    """Draw dug tiles and labelled marks as text.

    layout_dict_or_cells is a list (or set) of dug (x, y) tiles, or a dict:
        cells    the dug (x, y) tiles (needed)
        marks    marks, as below (the marks argument is drawn after these)
        stair    (x, y) of the stair, drawn X (the tiles round it that are
                 dug are drawn ':' when hub is not False), or None
        hub      False: do not mark the hub
        title    a first line
        rooms    a room count for the summary line
        corridor the corridor's width, for the summary line
        notes    more lines after the legend (a list of text)
    marks: see _norm_marks: (x, y, label[, glyph]) tuples, dicts with
    x, y, label and optionally glyph, w, h, or {label: [(x, y), ...]}.

    +x is east, +y is south (north is up). The picture has one tile of rock
    round it. Returns the text: title, picture, summary line, legend."""
    if isinstance(layout_dict_or_cells, dict):
        d = layout_dict_or_cells
        cells = d.get("cells") or []
        all_marks = _norm_marks(d.get("marks")) + _norm_marks(marks)
    else:
        d = {}
        cells = layout_dict_or_cells or []
        all_marks = _norm_marks(marks)
    dug = _norm_cells(cells)
    stair = tuple(d["stair"]) if d.get("stair") is not None else None
    glyphs = _assign_glyphs(all_marks)

    grid: dict[tuple[int, int], str] = {}
    counts: dict[str, int] = {}
    order: list[str] = []
    for m in all_marks:
        if m["label"] not in counts:
            counts[m["label"]] = 0
            order.append(m["label"])
        counts[m["label"]] += 1
        for dx in range(m["w"]):
            for dy in range(m["h"]):
                grid[(m["x"] + dx, m["y"] + dy)] = glyphs[m["label"]]
    hub_seen = False
    if stair is not None:
        if d.get("hub", True) is not False:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    t = (stair[0] + dx, stair[1] + dy)
                    if t != stair and t in dug and t not in grid:
                        grid[t] = HUB
                        hub_seen = True
        grid[stair] = STAIR

    pts = list(dug) + list(grid)
    lines: list[str] = []
    if d.get("title"):
        lines.append(str(d["title"]))
    if not pts:
        lines.append("(nothing to draw)")
        return "\n".join(lines) + "\n"
    x1, x2 = min(x for x, _ in pts) - 1, max(x for x, _ in pts) + 1
    y1, y2 = min(y for _, y in pts) - 1, max(y for _, y in pts) + 1
    for y in range(y1, y2 + 1):
        lines.append("".join(grid.get((x, y)) or (FLOOR if (x, y) in dug else ROCK) for x in range(x1, x2 + 1)))

    if dug:
        w = max(x for x, _ in dug) - min(x for x, _ in dug) + 1
        h = max(y for _, y in dug) - min(y for _, y in dug) + 1
    else:
        w = h = 0
    parts = [f"{w} x {h}", f"{len(dug)} dug tiles"]
    if d.get("rooms") is not None:
        parts.append(f"{d['rooms']} rooms" if d["rooms"] != 1 else "1 room")
    if d.get("corridor") is not None:
        parts.append(f"corridor {d['corridor']} wide")
    if dug:                                 # the stair is walked over, though never dug
        parts.append(f"narrowest way {narrowest(dug | {stair} if stair else dug)} wide")
    lines.append(", ".join(parts))

    legend = [f"{ROCK} rock", f"{FLOOR} dug floor"]
    if stair is not None:
        legend.append(f"{STAIR} stair")
    if hub_seen:
        legend.append(f"{HUB} hub")
    for label in order:
        n = counts[label]
        legend.append(f"{glyphs[label]} {label}" + (f" ({n})" if n > 1 else ""))
    line = "legend:"
    for item in legend:                     # wrapped at about 100 columns
        if len(line) + len(item) + 2 > 100 and line.strip() != "legend:":
            lines.append(line.rstrip(","))
            line = "       "
        line += " " + item + ","
    lines.append(line.rstrip(","))
    for note in d.get("notes") or []:
        lines.append(str(note))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# ai-layouts.lua (needs lupa)
# ---------------------------------------------------------------------------

_LUA = None

_FLAT = r"""function(L)
  local out = {tiles = {}, build = {}, place = {}, zone = {}, rooms_at = {}, halls = {}}
  for x, col in pairs(L.tiles) do for y in pairs(col) do table.insert(out.tiles, {x, y}) end end
  for _, phase in ipairs({'build', 'place', 'zone', 'rooms_at'}) do
    for _, c in ipairs(L[phase] or {}) do table.insert(out[phase], {c.x, c.y, tostring(c.text)}) end
  end
  out.nhalls = #(L.halls or {})
  out.kind = L.kind
  out.bounds = {L.bounds.x1, L.bounds.y1, L.bounds.x2, L.bounds.y2}
  out.corridor = L.corridor and L.corridor.width or false
  out.arms = L.corridor and L.corridor.arms or false
  out.orient = L.orient or (L.style and L.style.orient) or 0
  return out
end"""


def load_layouts():
    """(lua, module): lua/ai-layouts.lua loaded in a Lua engine, as the tests
    load it (its own environment; no game). Raises ImportError without lupa."""
    global _LUA
    if _LUA is None:
        from lupa.lua53 import LuaRuntime
        lua = LuaRuntime(unpack_returned_tuples=True)
        src = LAYOUTS_LUA.read_text(encoding="utf-8")
        # (r9) the module is a hub: its parts (PARTS, beside it) are handed as texts
        listed = re.search(r"^PARTS = \{(.*)\}", src, re.M)
        parts = {f"ai-layouts-{p}": (LAYOUTS_LUA.parent / f"ai-layouts-{p}.lua").read_text(encoding="utf-8")
                 for p in (re.findall(r"'([\w-]+)'", listed.group(1)) if listed else [])}
        env = lua.eval("function(src, parts) local env = setmetatable({PART_SOURCES = parts}, {__index=_G}); "
                       "assert(load(src, 'ai-layouts', 't', env))(); return env end")(src, lua.table_from(parts))
        _LUA = (lua, env, lua.eval(_FLAT))
    return _LUA[0], _LUA[1]


def kinds() -> list[str]:
    """Every kind make() draws: ai-layouts.lua's KINDS, then the kinds only
    DEFAULTS knows (farms)."""
    _, M = load_layouts()
    out = [M.KINDS[i] for i in range(1, len(M.KINDS) + 1)]
    return out + [k for k in DEFAULTS if k not in out]


def _to_lua(lua, v):
    if isinstance(v, dict):
        return lua.table_from({k: _to_lua(lua, x) for k, x in v.items()})
    if isinstance(v, (list, tuple)):
        return lua.table_from([_to_lua(lua, x) for x in v])
    return v


def params_for(kind: str, params: dict | None = None) -> dict:
    """The kind's defaults with params over them; rooms=N for workshops and
    storage becomes the first N shops or piles (unless they are given)."""
    given = dict(params or {})
    p = dict(DEFAULTS.get(kind, {}))
    if kind in ROOM_LISTS and "rooms" in given:
        key, names = ROOM_LISTS[kind]
        n = given.pop("rooms")
        if key not in given:
            given[key] = names[:max(1, min(len(names), int(n)))]
    p.update(given)
    return p


def _split(text: str):
    m = _CELL.match(text)
    key = m.group(1)
    return key, int(m.group(2) or 1), int(m.group(3) or 1)


def _zone_name(key: str) -> str:
    base = key.split("{", 1)[0]
    names = {"b": "bedroom", "o": "office", "j": "jail cell", "h": "dining hall", "D": "dormitory",
             "B": "barracks", "a": "archery range", "T": "tomb", "m": "meeting area"}
    name = names.get(base, f"zone '{base}'")
    loc = re.search(r"location=(\w+)", key)
    if loc:
        name = loc.group(1)
    return name


def layout_data(kind: str, params: dict | None = None, defaults: bool = True) -> dict:
    """make(kind, params) as plain Python data, ready for render():
    {kind, params, cells, marks, stair, rooms, corridor, title, notes, bounds,
    summary}. ValueError when make() refuses (unknown kind, no valid shops)."""
    lua, M = load_layouts()
    p = params_for(kind, params) if defaults else dict(params or {})
    res = M.make(kind, _to_lua(lua, p))
    L, err = res if isinstance(res, tuple) else (res, None)
    if L is None:
        raise ValueError(f"{kind}: {err}")
    raw = _LUA[2](L)

    def rows(t):
        return [tuple(r.values()) for r in t.values()]

    cells = sorted((int(x), int(y)) for x, y in rows(raw.tiles))
    shops_by_key = {v: k for k, v in M.WORKSHOPS.items()}
    piles_by_key = {v: k for k, v in M.STOCKPILES.items()}
    piles, shops, furniture = [], [], []
    for x, y, text in rows(raw.place):
        key, w, h = _split(text)
        name = piles_by_key.get(key, key)
        piles.append({"x": int(x), "y": int(y), "w": w, "h": h, "label": f"{name} stockpile",
                      "glyph": PILE_GLYPHS.get(name)})
    nshop = 0
    for x, y, text in rows(raw.build):
        key, w, h = _split(text)
        x, y = int(x), int(y)
        if key in shops_by_key:              # 3x3, placed by its centre tile
            nshop += 1
            shops.append({"x": x - 1, "y": y - 1, "w": 3, "h": 3, "label": "workshop",
                          "glyph": WORKSHOP_GLYPH})
            shops.append({"x": x, "y": y, "label": f"{shops_by_key[key]}",
                          "glyph": _POOL[nshop - 1] if nshop <= 9 else None})
        else:
            name, glyph = FURNITURE.get(key, (f"build '{key}'", key[:1]))
            furniture.append({"x": x, "y": y, "w": w, "h": h, "label": name, "glyph": glyph})
    # stockpiles under workshops under furniture; a pile only on dug floor
    dug = set(cells)
    marks = []
    for m in piles:
        for dx in range(m["w"]):
            for dy in range(m["h"]):
                if (m["x"] + dx, m["y"] + dy) in dug:
                    marks.append({"x": m["x"] + dx, "y": m["y"] + dy, "label": m["label"], "glyph": m["glyph"]})
    marks += shops + furniture

    zones: dict[str, int] = {}
    room_rects = set()
    for x, y, text in rows(raw.zone):
        key, w, h = _split(text)
        zones[_zone_name(key)] = zones.get(_zone_name(key), 0) + 1
        if w * h > 1:                        # a coffin's 1x1 tomb zone is not a room
            room_rects.add((int(x), int(y), w, h))
    for m in piles:
        room_rects.add((m["x"], m["y"], m["w"], m["h"]))
    rooms_at = rows(raw.rooms_at)
    nhalls = int(raw.nhalls)
    if rooms_at:
        rooms = len(rooms_at)
    elif nhalls:
        rooms = nhalls
    else:
        rooms = len(room_rects) or 1         # farms: the one field

    notes = []
    if zones:
        notes.append("zones (not drawn): " + ", ".join(f"{n} x {name}" if n > 1 else name
                                                         for name, n in zones.items()))
    free = [t for _, _, t in rooms_at if str(t).startswith("free")]
    if free:
        notes.append(f"free rooms: {len(free)}")
    shown = ", ".join(f"{k}={json.dumps(v) if isinstance(v, (list, dict)) else v}" for k, v in p.items())
    arms = f", arms {raw.arms}" if raw.arms else ""
    return {"kind": kind, "params": p, "cells": cells, "marks": marks, "stair": (0, 0),
            "rooms": rooms, "corridor": int(raw.corridor) if raw.corridor else None,
            "title": f"== {kind} ({shown}){arms}", "notes": notes,
            "bounds": tuple(int(v) for v in raw.bounds.values()),
            "summary": L.summary}


def draw(kind: str, params: dict | None = None) -> str:
    """The picture of make(kind, params) (defaults filled in)."""
    return render(layout_data(kind, params))


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def _value(key: str, text: str):
    t = text.strip()
    if t[:1] in "[{":
        return json.loads(t)
    if key in LIST_PARAMS:
        return [v for v in re.split(r"[,+]", t) if v]
    if t.lower() in ("true", "false"):
        return t.lower() == "true"
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    return t


def parse_params(items) -> dict:
    """--param texts -> a params dict. KEY=VALUE; style.KEY=VALUE or
    style=KEY=VALUE,KEY=VALUE (customs joined with +) for the style."""
    out: dict = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"--param {item!r}: expected KEY=VALUE")
        key, text = item.split("=", 1)
        key = key.strip()
        if key.startswith("style."):
            out.setdefault("style", {})[key[6:]] = _value(key[6:], text)
        elif key == "style" and text.strip()[:1] != "{":
            style = out.setdefault("style", {})
            for pair in text.split(","):
                if "=" not in pair:
                    raise ValueError(f"--param {item!r}: expected style=KEY=VALUE,KEY=VALUE")
                k, v = pair.split("=", 1)
                style[k.strip()] = _value(k.strip(), v)
        else:
            out[key] = _value(key, text)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Draw a level layout (lua/ai-layouts.lua) as text, without the game.")
    ap.add_argument("kind", nargs="?", help="the level kind (see --list)")
    ap.add_argument("--param", action="append", default=[], metavar="KEY=VALUE",
                    help="a parameter of the layout (repeatable); style.hall=rounded sets a style field")
    ap.add_argument("--all", action="store_true", help="draw every kind (default parameters, plus any --param)")
    ap.add_argument("--list", action="store_true", help="list the kinds and their default parameters")
    ap.add_argument("--out", metavar="FILE", help="write the text to FILE instead of printing it")
    args = ap.parse_args(argv)
    try:
        load_layouts()
    except ImportError:
        print("draw_level needs the lupa package: pip install lupa", file=sys.stderr)
        return 2
    try:
        params = parse_params(args.param)
        if args.list:
            text = "".join(f"{k}: {json.dumps(DEFAULTS.get(k, {}))}\n" for k in kinds())
        elif args.all:
            # only the style goes to every kind; a size belongs to one kind
            common = {k: v for k, v in params.items() if k == "style"}
            text = "\n".join(draw(k, common) for k in kinds())
        elif args.kind:
            text = draw(args.kind, params)
        else:
            ap.error("give a kind, --all or --list")
    except (ValueError, json.JSONDecodeError) as e:
        print(f"draw_level: {e}", file=sys.stderr)
        return 1
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out} ({len(text.splitlines())} lines)")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

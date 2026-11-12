"""Blueprints for landmarks (the Design track, D0): the brain's mirror of
lua/ai-blueprints.lua, so a bad drawing is refused before any bridge call.

The bridge is the authority on the format. `check_format` here gives the
same codes, in the same order, with the same words and positions, as the
Lua one; tests/test_d0_blueprints.py runs both over the same fixtures
(tests/fixtures/blueprints/) and the library (brain/landmarks/*.json).

A reason is {"code", "level", "x", "y", "words"}: level from 1, x the
column and y the row (both from 0) on the drawing as given, or None where a
position doesn't apply. The codes: FORMAT SIZE SYMBOL LEGEND JOIN STAIRS
REACH OPEN RAIL SUPPORT LIMIT. A blueprint's positions describe its own shape
only; they are never map coordinates.

(E1) Multi-storey openings, rock: '*' is open to the level below (dug, then
cut as a channel once the level below is dug), 'O' a rail (a fortification:
dug, the openings cut from it, then built). The tile below a '*' is dug in
the drawing (or another '*'); every tile beside a '*' is '*', '#', 'O' or '_';
every '*' is reached from an 'O' beside it; nothing is left hanging over a
hole (SUPPORT).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

LIMITS = {"w": 31, "h": 31, "levels": 5, "dug": 700, "built": 400, "items": 40, "statues": 16, "doors": 8,
          "stairs": 4, "legend": 12, "cost_max": 2500}
ALPHABET = {"rock": "_#.,@<>X^+*O", "surface": "_.@WFRUDIO+"}
MAX_REASONS = 24
CODES = ("FORMAT", "SIZE", "SYMBOL", "LEGEND", "JOIN", "STAIRS", "REACH", "OPEN", "RAIL", "SUPPORT", "LIMIT")

FURNITURE = ("Statue", "Table", "Chair", "Bed", "Coffin", "Cabinet", "Chest", "Bookcase", "ArmorStand",
             "WeaponRack")
# ai-layouts.WORKSHOPS and STOCKPILES (the test checks them against the Lua)
WORKSHOPS = ("Carpenters", "Masons", "Craftsdwarfs", "Still", "Kitchen", "Butchers", "Tanners", "Leatherworks",
             "Loom", "Clothiers", "Farmers", "Fishery", "Mechanics", "Jewelers", "Ashery", "Millstone", "Quern",
             "Bowyers", "SoapMaker", "WoodFurnace", "Smelter", "MetalsmithsForge", "Kiln", "GlassFurnace",
             "ScrewPress")      # (item9) paper from slurry
PILES = ("food", "stone", "wood", "furniture", "bars_blocks", "finished_goods", "cloth", "leather", "gems",
         "ammo", "weapons", "armor")
ITEM_KIND = {**{k: "furniture" for k in FURNITURE}, **{k: "workshop" for k in WORKSHOPS},
             **{"pile:" + k: "pile" for k in PILES}}
ITEMS = tuple(sorted(ITEM_KIND))            # every legend name (the bridge's blueprint_items)
BLOCKING = {"Statue"}
ZONES = ("temple", "tomb", "dining", "meeting", "library", "none")
LANDMARK_KINDS = ("descent", "god_hall", "ziggurat", "chronicle_hall", "great_hall", "tower", "necropolis",
                  "gate_hall", "garden_court")
ENGRAVE = ("none", "halls", "all")

ROCK_WALK = set(".,@<>X^+")
ROCK_DUG = ROCK_WALK | {"*", "O"}
RAIL_OK = set("*#O_")
N4 = ((0, -1), (-1, 0), (1, 0), (0, 1))
SURF_WALK = set(".@FRUDI+")
SURF_BUILT = set("WFRUDIO")
SURF_UNDER = set("WFRUDI")
N8 = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))
LIBRARY_DIR = Path(__file__).resolve().parent / "landmarks"

_NAME = re.compile(r"[A-Za-z' ]+")
_SHOWN = re.compile(r"[A-Za-z0-9_:]+")


def _int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None


def _is_object(v) -> bool:
    return isinstance(v, dict) or v == []


def _is_list(v) -> bool:
    return isinstance(v, list) and len(v) >= 1


def _blen(s: str) -> int:
    return len(s.encode("utf-8"))


def _bytes(s: str) -> str:
    """One character a byte, as Lua sees a string."""
    return s.encode("utf-8").decode("latin-1")


def _is_letter(ch) -> bool:
    return ch is not None and len(ch) == 1 and "a" <= ch <= "z"


def _shown(s) -> str:
    if not isinstance(s, str):
        return "a name"
    if _blen(s) <= 20 and _SHOWN.fullmatch(s):
        return "'" + s + "'"
    return "a name"


def _char_words(ch) -> str:
    b = ord(ch)
    if b < 33 or b > 126:
        return "character code %d" % b
    return "'" + ch + "'"


def _where(level, x, y) -> str:
    if level is not None and x is not None and y is not None:
        return "L%d x%d y%d: " % (level, x, y)
    if level is not None and y is not None:
        return "L%d y%d: " % (level, y)
    if level is not None:
        return "L%d: " % level
    return ""


def _legend(bp) -> dict:
    lg = bp.get("legend") if isinstance(bp, dict) else None
    return lg if isinstance(lg, dict) else {}


def _item(legend: dict, ch):
    v = legend.get(ch)
    return v if isinstance(v, str) and v in ITEM_KIND else None


def _needs_floor(i, ch, below) -> bool:
    """A door or an item above the surface's first level stands on a floor
    built for it (counted as built), unless a wall below gives one."""
    return i > 1 and (ch == "+" or _is_letter(ch)) and below is not None and below not in ("W", "_")


def _grids(bp) -> list[list[str]]:
    return [[_bytes(r) for r in lv["grid"]] for lv in bp["levels"]]


def cost(bp) -> dict:
    """dug and built tiles, items (furniture and workshops; piles are free),
    statues, doors, stair columns, and jobs = dug + 4 x built + 10 x items."""
    out = {"dug": 0, "built": 0, "items": 0, "statues": 0, "doors": 0, "stairs": 0, "open": 0, "jobs": 0}
    if not isinstance(bp, dict) or not isinstance(bp.get("levels"), list):
        return out
    surface = bp.get("ground") == "surface"
    legend = _legend(bp)
    columns = set()

    def below_of(i, y, x):
        if i < 2:
            return None
        lv = bp["levels"][i - 2]
        grid = lv.get("grid") if isinstance(lv, dict) else None
        if not isinstance(grid, list) or y >= len(grid) or not isinstance(grid[y], str):
            return None
        row = _bytes(grid[y])
        return row[x] if x < len(row) else None

    for lv_i, lv in enumerate(bp["levels"], 1):
        grid = lv.get("grid") if isinstance(lv, dict) else None
        for y, row in enumerate(grid if isinstance(grid, list) else []):
            if not isinstance(row, str):
                continue
            for x, ch in enumerate(_bytes(row)):
                if surface:
                    if ch in SURF_BUILT or _needs_floor(lv_i, ch, below_of(lv_i, y, x)):
                        out["built"] += 1
                elif ch in ROCK_DUG or _is_letter(ch):
                    out["dug"] += 1
                    if ch == "O":
                        out["built"] += 1
                    if ch == "*":
                        out["open"] += 1
                if ch == "+":
                    out["doors"] += 1
                if (surface and ch in "UDI") or (not surface and ch in "<>X"):
                    columns.add((x, y))
                if _is_letter(ch):
                    name = _item(legend, ch)
                    if name and ITEM_KIND[name] != "pile":
                        out["items"] += 1
                    if name == "Statue":
                        out["statues"] += 1
    out["stairs"] = len(columns)
    out["jobs"] = out["dug"] + out["open"] + 4 * out["built"] + 10 * out["items"]
    return out


def open_distances(at, h, w) -> tuple[dict, int]:
    """(E1) Each '*' of a level: its distance (4 ways, through '*') from an
    'O' beside it, and the largest (0 with no '*'). The farthest are cut
    first. at(x, y) -> the symbol or None."""
    dist: dict = {}
    queue = []
    far = 0
    for y in range(h):
        for x in range(w):
            if at(x, y) == "*":
                for dx, dy in N4:
                    if at(x + dx, y + dy) == "O" and (x, y) not in dist:
                        dist[(x, y)] = 1
                        queue.append((x, y))
    head = 0
    while head < len(queue):
        x, y = queue[head]
        head += 1
        dd = dist[(x, y)]
        far = max(far, dd)
        for dx, dy in N4:
            nx, ny = x + dx, y + dy
            if at(nx, ny) == "*" and (nx, ny) not in dist:
                dist[(nx, ny)] = dd + 1
                queue.append((nx, ny))
    return dist, far


def check_format(bp) -> tuple[bool, list[dict]]:
    """Every check of the format, in the bridge's order: FORMAT SIZE SYMBOL
    (each stops the check when it fails), then LEGEND JOIN STAIRS REACH
    OPEN RAIL SUPPORT LIMIT. Returns (ok, reasons), MAX_REASONS at most."""
    reasons: list[dict] = []

    def why(code, level, x, y, words):
        if len(reasons) < MAX_REASONS:
            reasons.append({"code": code, "level": level, "x": x, "y": y, "words": _where(level, x, y) + words})

    def done():
        return (not reasons), reasons

    # FORMAT
    if bp == []:
        bp = {}
    if not isinstance(bp, dict):
        why("FORMAT", None, None, None, "a blueprint is one object")
        return done()
    if bp.get("v") is not None and _int(bp.get("v")) != 1:
        why("FORMAT", None, None, None, "v must be 1")
    if bp.get("ground") not in ("rock", "surface"):
        why("FORMAT", None, None, None, "ground must be 'rock' or 'surface'")
    nlev = None
    levels = bp.get("levels")
    if not _is_list(levels):
        why("FORMAT", None, None, None, "levels must be a list of 1 to 5 levels")
    else:
        nlev = len(levels)
        for i, lv in enumerate(levels, 1):
            if not _is_object(lv) or not isinstance(lv, dict) or not _is_list(lv.get("grid")):
                why("FORMAT", i, None, None, 'a level is {"grid": [rows]}')
            else:
                for y, row in enumerate(lv["grid"]):
                    if not isinstance(row, str):
                        why("FORMAT", i, None, y, "a row must be a string")
    if bp.get("legend") is not None and not _is_object(bp.get("legend")):
        why("FORMAT", None, None, None, "legend must be an object")
    zone = bp.get("zone")
    if zone is not None:
        if not isinstance(zone, dict) or not isinstance(zone.get("kind"), str) or zone.get("kind") not in ZONES:
            why("FORMAT", None, None, None,
                'zone must be {"kind": temple, tomb, dining, meeting, library or none, "level"}')
        elif zone.get("level") is not None:
            zl = _int(zone.get("level"))
            if zl is None or zl < 1 or (nlev is not None and zl > nlev):
                why("FORMAT", None, None, None, "zone level must be one of the levels")
    fin = bp.get("finish")
    if fin is not None:
        if not _is_object(fin):
            why("FORMAT", None, None, None, "finish must be an object")
        else:
            fin = fin if isinstance(fin, dict) else {}
            s = 0 if fin.get("smooth") is None else _int(fin.get("smooth"))
            if s is None or s < 0 or s > 3:
                why("FORMAT", None, None, None, "finish smooth must be 0 to 3")
            if fin.get("engrave") is not None and fin.get("engrave") not in ENGRAVE:
                why("FORMAT", None, None, None, "finish engrave must be 'none', 'halls' or 'all'")
    if bp.get("materials") is not None and not _is_object(bp.get("materials")):
        why("FORMAT", None, None, None, "materials must be an object")
    if bp.get("purpose") is not None and bp.get("purpose") not in LANDMARK_KINDS:
        why("FORMAT", None, None, None, "purpose must be a landmark kind")
    name = bp.get("name")
    if name is not None and (not isinstance(name, str) or _blen(name) > 40 or not _NAME.fullmatch(name)):
        why("FORMAT", None, None, None, "name: letters, spaces and apostrophes, up to 40")
    whom = bp.get("for")
    if whom is not None and (not isinstance(whom, str) or _blen(whom) > 60):
        why("FORMAT", None, None, None, "'for' must be a name, up to 60 characters")
    if reasons:
        return done()

    # SIZE
    g = _grids(bp)
    n = len(g)
    if n > LIMITS["levels"]:
        why("SIZE", None, None, None, "%d levels; at most %d" % (n, LIMITS["levels"]))
    h, w = len(g[0]), len(g[0][0])
    if w < 1 or w > LIMITS["w"]:
        why("SIZE", 1, None, None, "%d tiles wide; 1 to %d" % (w, LIMITS["w"]))
    if h > LIMITS["h"]:
        why("SIZE", 1, None, None, "%d rows; at most %d" % (h, LIMITS["h"]))
    for i in range(1, n + 1):
        if len(g[i - 1]) != h:
            why("SIZE", i, None, None, "%d rows; level 1 has %d" % (len(g[i - 1]), h))
        for y, row in enumerate(g[i - 1]):
            if len(row) != w:
                why("SIZE", i, None, y, "%d tiles wide; row 0 of level 1 has %d" % (len(row), w))
    if reasons:
        return done()

    def cell(i, x, y):
        if i < 1 or i > n or y < 0 or y >= h or x < 0 or x >= w:
            return None
        return g[i - 1][y][x]

    # SYMBOL
    ground = bp["ground"]
    alphabet = ALPHABET[ground]
    for i in range(1, n + 1):
        for y in range(h):
            for x in range(w):
                ch = cell(i, x, y)
                if not _is_letter(ch) and ch not in alphabet:
                    why("SYMBOL", i, x, y, "%s is not in the %s alphabet" % (_char_words(ch), ground))
    if reasons:
        return done()

    surface = ground == "surface"
    legend = _legend(bp)

    # LEGEND
    keys = sorted(legend, key=lambda k: k.encode("utf-8"))
    if len(keys) > LIMITS["legend"]:
        why("LEGEND", None, None, None, "%d legend entries; at most %d" % (len(keys), LIMITS["legend"]))
    for k in keys:
        if not _is_letter(k):
            why("LEGEND", None, None, None, "legend key %s must be one letter, a to z" % _shown(k))
        elif not _item(legend, k):
            why("LEGEND", None, None, None, "legend '%s': %s is not an item" % (k, _shown(legend[k])))
    missing, claimed = set(), set()
    floor = {".", "F"} if surface else {".", ","}
    for i in range(1, n + 1):
        for y in range(h):
            for x in range(w):
                ch = cell(i, x, y)
                if not _is_letter(ch):
                    continue
                name = _item(legend, ch)
                if ch not in legend and ch not in missing:
                    missing.add(ch)
                    why("LEGEND", i, x, y, "'%s' is not in the legend" % ch)
                elif name and ITEM_KIND[name] == "workshop":
                    ok = (i, x, y) not in claimed
                    for dx, dy in N8:
                        c = cell(i, x + dx, y + dy)
                        if c is None or c not in floor or (i, x + dx, y + dy) in claimed:
                            ok = False
                    if ok:
                        for dy in (-1, 0, 1):
                            for dx in (-1, 0, 1):
                                claimed.add((i, x + dx, y + dy))
                    else:
                        why("LEGEND", i, x, y, "a workshop (%s) needs the 8 tiles around it as plain floor, "
                                               "not shared" % name)

    # JOIN
    joins, jl, jx, jy = 0, None, None, None
    for i in range(1, n + 1):
        for y in range(h):
            for x in range(w):
                if cell(i, x, y) == "@":
                    joins += 1
                    if joins == 1:
                        jl, jx, jy = i, x, y
                    else:
                        why("JOIN", i, x, y, "a second '@'; the join is one tile")
    if joins == 0:
        why("JOIN", None, None, None, "no '@' (the join, in row 0 of level 1)")
    elif jl != 1 or jy != 0:
        why("JOIN", jl, jx, jy, "'@' must be in row 0 of level 1")
    join_ok = joins == 1 and jl == 1 and jy == 0

    # STAIRS
    for i in range(1, n + 1):
        for y in range(h):
            for x in range(w):
                ch = cell(i, x, y)
                if surface:
                    up = cell(i + 1, x, y) if i < n else None
                    down = cell(i - 1, x, y) if i > 1 else None
                else:
                    up = cell(i - 1, x, y) if i > 1 else None
                    down = cell(i + 1, x, y) if i < n else None
                bad = None
                if not surface:
                    if ch == ">":
                        if down is None:
                            bad = "a down stair on the lowest level"
                        elif down not in ("<", "X"):
                            bad = "a down stair needs '<' or 'X' below it"
                    elif ch == "<":
                        if up is None:
                            bad = "an up stair on level 1 leads out of the blueprint"
                        elif up not in (">", "X"):
                            bad = "an up stair needs '>' or 'X' above it"
                    elif ch == "X":
                        if up is None:
                            bad = "'X' on level 1 leads out of the blueprint; use '>'"
                        elif down is None:
                            bad = "'X' on the lowest level; use '<'"
                        elif up not in (">", "X"):
                            bad = "'X' needs '>' or 'X' above it"
                        elif down not in ("<", "X"):
                            bad = "'X' needs '<' or 'X' below it"
                    elif ch == "^":
                        if up is None:
                            bad = "a ramp on level 1 leads out of the blueprint"
                        elif up not in (".", ","):
                            bad = "a ramp needs dug floor ('.' or ',') above it"
                else:
                    if ch == "U":
                        if up is None:
                            bad = "an up stair on the top level"
                        elif up not in ("D", "I"):
                            bad = "an up stair needs 'D' or 'I' above it"
                    elif ch == "D":
                        if down is None:
                            bad = "a down stair on level 1 (the ground)"
                        elif down not in ("U", "I"):
                            bad = "a down stair needs 'U' or 'I' below it"
                    elif ch == "I":
                        if down is None:
                            bad = "'I' on level 1 (the ground); use 'U'"
                        elif up is None:
                            bad = "'I' on the top level; use 'D'"
                        elif up not in ("D", "I"):
                            bad = "'I' needs 'D' or 'I' above it"
                        elif down not in ("U", "I"):
                            bad = "'I' needs 'U' or 'I' below it"
                    elif ch == "R":
                        if up is None:
                            bad = "a ramp on the top level leads out of the blueprint"
                        elif up != "_":
                            bad = "a ramp needs open air ('_') above it"
                if bad:
                    why("STAIRS", i, x, y, bad)

    # REACH
    if join_ok:
        walkset = SURF_WALK if surface else ROCK_WALK

        def walkable(ch):
            if ch is None:
                return False
            if ch in walkset:
                return True
            if _is_letter(ch):
                return _item(legend, ch) not in BLOCKING
            return False

        up_stairs = {"U", "I"} if surface else {"<", "X"}
        down_stairs = {"D", "I"} if surface else {">", "X"}
        ramp = "R" if surface else "^"
        seen = {(1, jx, jy)}
        queue = [(1, jx, jy)]

        def go(i, x, y):
            if (i, x, y) not in seen and walkable(cell(i, x, y)):
                seen.add((i, x, y))
                queue.append((i, x, y))

        head = 0
        while head < len(queue):
            i, x, y = queue[head]
            head += 1
            ch = cell(i, x, y)
            for dx, dy in N8:
                go(i, x + dx, y + dy)
            ui = i + 1 if surface else i - 1
            di = i - 1 if surface else i + 1
            upc, dnc = cell(ui, x, y), cell(di, x, y)
            if ch in up_stairs and upc in down_stairs:
                go(ui, x, y)
            if ch in down_stairs and dnc in up_stairs:
                go(di, x, y)
            if ch == ramp:
                for dx, dy in N8:
                    go(ui, x + dx, y + dy)
            for dx, dy in N8:
                if cell(di, x + dx, y + dy) == ramp:
                    go(di, x + dx, y + dy)
        for i in range(1, n + 1):
            drawn = any((ch != "_") if surface else (ch in ROCK_DUG or _is_letter(ch))
                        for row in g[i - 1] for ch in row)
            if not drawn:
                why("REACH", i, None, None, "nothing drawn on this level")
                continue
            for y in range(h):
                for x in range(w):
                    ch = cell(i, x, y)
                    rail = not surface and ch == "O"
                    must = ch in walkset or _is_letter(ch) or rail
                    if must and (i, x, y) not in seen:
                        near = False
                        if (_is_letter(ch) and not walkable(ch)) or rail:
                            near = any((i, x + dx, y + dy) in seen for dx, dy in N8)
                        if not near:
                            why("REACH", i, x, y, "not reached from '@'")

    # OPEN (E1)
    any_open = not surface and any("*" in row for rows in g for row in rows)
    if any_open:
        for i in range(1, n + 1):
            for y in range(h):
                for x in range(w):
                    if cell(i, x, y) != "*":
                        continue
                    below = cell(i + 1, x, y) if i < n else None
                    if below is None:
                        why("OPEN", i, x, y, "an opening ('*') on the lowest level: no level below it in the drawing")
                    elif not (below == "*" or below in ROCK_WALK or _is_letter(below)):
                        why("OPEN", i, x, y, "an opening ('*') needs the level below dug here, not %s"
                            % _char_words(below))
            dist, _ = open_distances(lambda x, y, i=i: cell(i, x, y), h, w)
            told = set()
            for y in range(h):
                for x in range(w):
                    if cell(i, x, y) == "*" and (x, y) not in dist and (x, y) not in told:
                        why("OPEN", i, x, y, "no rail ('O') leads to this opening: the dwarves cut it standing on an "
                                             "'O' beside it")
                        stack = [(x, y)]
                        told.add((x, y))
                        while stack:
                            px, py = stack.pop()
                            for dx, dy in N4:
                                nx, ny = px + dx, py + dy
                                if cell(i, nx, ny) == "*" and (nx, ny) not in told:
                                    told.add((nx, ny))
                                    stack.append((nx, ny))

    # RAIL (E1)
    if any_open:
        for i in range(1, n + 1):
            told = set()
            for y in range(h):
                for x in range(w):
                    if cell(i, x, y) != "*":
                        continue
                    for dx, dy in N8:
                        nx, ny = x + dx, y + dy
                        c = cell(i, nx, ny)
                        if c is not None and c not in RAIL_OK and (nx, ny) not in told:
                            told.add((nx, ny))
                            why("RAIL", i, nx, ny, "%s beside an opening: a dwarf could fall; rail the edge "
                                                   "with '#' or 'O'" % _char_words(c))

    # SUPPORT
    if surface:
        for i in range(2, n + 1):
            for y in range(h):
                for x in range(w):
                    ch, below = cell(i, x, y), cell(i - 1, x, y)
                    if ch == "_":
                        continue
                    if below == "_":
                        why("SUPPORT", i, x, y, "nothing to stand on: open air ('_') below")
                    elif ch in (".", "R") and below != "W":
                        why("SUPPORT", i, x, y, "%s above the ground needs a wall ('W') below; use 'F' "
                                                "for a floor" % _char_words(ch))
                    elif ch == "F" and below == "W":
                        why("SUPPORT", i, x, y, "the wall below already makes a floor here; use '.'")
    elif any_open:
        # (E1) the cave-in check: every tile but the openings is held by the
        # rock outside the drawing, by rock below it, or through a held tile
        # beside it (4 ways)
        for i in range(1, n + 1):
            held = set()
            queue = []
            for y in range(h):
                for x in range(w):
                    ch = cell(i, x, y)
                    if ch == "*":
                        continue
                    below = cell(i + 1, x, y) if i < n else "#"
                    if ch == "_" or x == 0 or y == 0 or x == w - 1 or y == h - 1 or below in ("#", "_"):
                        held.add((x, y))
                        queue.append((x, y))
            head = 0
            while head < len(queue):
                x, y = queue[head]
                head += 1
                for dx, dy in N4:
                    nx, ny = x + dx, y + dy
                    c = cell(i, nx, ny)
                    if c is not None and c != "*" and (nx, ny) not in held:
                        held.add((nx, ny))
                        queue.append((nx, ny))
            for y in range(h):
                for x in range(w):
                    if cell(i, x, y) != "*" and (x, y) not in held:
                        why("SUPPORT", i, x, y, "nothing holds this over the opening below: it would cave in")

    # LIMIT
    c = cost(bp)
    L = LIMITS
    if c["dug"] > L["dug"]:
        why("LIMIT", None, None, None, "%d dug tiles; at most %d" % (c["dug"], L["dug"]))
    if c["built"] > L["built"]:
        why("LIMIT", None, None, None, "%d built tiles; at most %d" % (c["built"], L["built"]))
    if c["items"] > L["items"]:
        why("LIMIT", None, None, None, "%d items; at most %d" % (c["items"], L["items"]))
    if c["statues"] > L["statues"]:
        why("LIMIT", None, None, None, "%d statues; at most %d" % (c["statues"], L["statues"]))
    if c["doors"] > L["doors"]:
        why("LIMIT", None, None, None, "%d doors; at most %d" % (c["doors"], L["doors"]))
    if c["stairs"] > L["stairs"]:
        why("LIMIT", None, None, None, "%d stair columns; at most %d" % (c["stairs"], L["stairs"]))
    if c["jobs"] > L["cost_max"]:
        why("LIMIT", None, None, None, "%d jobs; at most %d" % (c["jobs"], L["cost_max"]))
    return done()


def env_of(bp) -> tuple[int, int, int, str]:
    """(w, h, levels, ground) of a well-formed drawing, as given (unturned)."""
    levels = bp.get("levels") or []
    grid = levels[0].get("grid") if levels else []
    h = len(grid)
    w = _blen(grid[0]) if grid else 0
    return w, h, len(levels), bp.get("ground", "rock")


def fits(bp, site) -> bool:
    """Whether a drawing fits a site from blueprint_sites ({ground, w, h,
    levels}): the same ground, no more levels, and its footprint inside the
    site's envelope once its '@' is lined up with the middle of row 0 (where
    the site's join corridor ends)."""
    if not isinstance(site, dict):
        return False
    w, h, n, ground = env_of(bp)
    sw, sh, sn = _int(site.get("w")), _int(site.get("h")), _int(site.get("levels"))
    if None in (sw, sh, sn) or site.get("ground") != ground:
        return False
    if w > sw or h > sh or n > sn:
        return False
    row0 = _bytes(bp["levels"][0]["grid"][0])
    at = row0.find("@")
    if at < 0:
        return False
    mid = sw // 2
    return at <= mid and (w - 1 - at) <= (sw - 1 - mid)


def load_library(folder: Path | None = None) -> dict:
    """{kind: bp} from brain/landmarks/*.json (the kind: the file's "kind",
    else its "purpose", else the file's name). A file that doesn't parse is
    left out."""
    out: dict = {}
    folder = Path(folder) if folder else LIBRARY_DIR
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.json")):
        try:
            bp = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(bp, dict):
            continue
        kind = bp.get("kind") or bp.get("purpose") or path.stem
        if isinstance(kind, str) and kind not in out:
            out[kind] = bp
    return out

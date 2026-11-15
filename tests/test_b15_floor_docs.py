"""(Layout option B, B15) The docs of the hallway-first floors: the new
section of docs/building.md (what a floor is, the fallback, the kinds that
stay classic, the slider table), the Rules cycle `floor_layout` in
docs/controls.md, and the watch list at the top of docs/watch-in-game.md.
Words only: no code is read or run.

    python tests/test_b15_floor_docs.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import make_test, finish  # noqa: E402

DOCS = ROOT / "docs"
BUILDING_HEAD = "## Hallway-first floors (layout option B)"
WATCH_HEAD = "## Layout option B: hallway-first floors"
CYCLE = ("along a main hall on each floor", "each on its own (classic)")
SLIDERS = ("Spacing", "Room size", "Depth", "Grandeur", "Fortification", "Reserves")
SLACK = 20          # "a little": a new line may pass the file's longest old line by this much

test = make_test()


def read(name: str) -> str:
    return (DOCS / name).read_bytes().decode("utf-8")        # strict: raises on anything not UTF-8


def section(text: str, head: str, level: str = "## ") -> list[str]:
    """The lines of the section under `head`, up to the next heading of the
    same level (or a higher one); [] when the heading is missing."""
    lines = text.splitlines()
    if head not in lines:
        return []
    i = lines.index(head)
    out, fence = [], False
    for line in lines[i + 1:]:
        if line.startswith("```"):
            fence = not fence
        if not fence and re.match(r"^#{1,%d} " % len(level.strip()), line):
            break
        out.append(line)
    return out


def rest(text: str, sec: list[str], head: str) -> list[str]:
    """The file's lines without the section (what stood there before)."""
    lines = text.splitlines()
    i = lines.index(head)
    return lines[:i] + lines[i + 1 + len(sec):]


def table_after(sec: list[str], head: str) -> dict[str, str]:
    """The first table under a `### ` heading inside a section: first cell -> the row."""
    if head not in sec:
        return {}
    rows = {}
    for line in sec[sec.index(head) + 1:]:
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows[cells[0]] = line
        elif rows:
            break
    return rows


def controls_item(text: str) -> list[str]:
    """The Rules tab's "New levels" item: its first line and the lines that continue it."""
    lines = text.splitlines()
    starts = [i for i, l in enumerate(lines) if l.startswith("- **New levels:**")]
    assert len(starts) == 1, starts
    out = [lines[starts[0]]]
    for line in lines[starts[0] + 1:]:
        if not line.startswith("  "):
            break
        out.append(line)
    return out


@test("building.md: the section stands after 'Where a new level goes' and before 'Phases'")
def _():
    heads = [l for l in read("building.md").splitlines() if l.startswith("## ")]
    i = heads.index("## Where a new level goes")
    assert heads[i + 1] == BUILDING_HEAD, heads[i:i + 3]
    assert heads[i + 2] == "## Phases", heads[i:i + 3]
    assert len(section(read("building.md"), BUILDING_HEAD)) > 100


@test("building.md: 'Where a new level goes' says at its top that it is the classic placement")
def _():
    sec = section(read("building.md"), "## Where a new level goes")
    top = " ".join(sec[:8])
    assert "classic placement" in top, top
    assert "`floor_layout`" in top and "classic" in top and "fallback" in top, top
    assert sec.index("1. **Find the staircases:** the stair columns with the most stair tiles on the") > 4


@test("building.md: the section names floor_layout, the hall, the slots and the words")
def _():
    sec = "\n".join(section(read("building.md"), BUILDING_HEAD))
    flat = " ".join(sec.split())
    for k in ("`floor_layout`", "`hallway`", "`classic`", "3-wide main hall", "central stair", "3x3 hub",
              "at least 10 free columns", "both sides", "wall row", "It turns", "More arms", "5x5",
              "Old corridors", "pile room", "Linked at once", "industry group",
              "A free room in a standing workshops level is still used first",
              "Nothing of an old level is moved or dug again", "no dwarf is walled in"):
        assert k in flat, k
    for word in ("level", "floor", "run", "slot", "unit"):
        assert re.search(r"^\| %s \| " % word, sec, re.M), word


@test("building.md: the fallback, its order, its numbers")
def _():
    sec = " ".join("\n".join(section(read("building.md"), BUILDING_HEAD)).split())
    assert "### The checks, and the fallback" in sec
    for k in ("**the fallback**", "1.5 seconds", "`not_on_floor`", "28 days", "for 3 days",
              "never a refusal of the level", "Nothing is designated until the whole request has a place"):
        assert k in sec, k
    a, b, c = (sec.index(k) for k in ("1. a free room in a standing workshops level", "2. the floors", "3. **the fallback**"))
    assert a < b < c


@test("building.md: the kinds that stay classic are listed")
def _():
    sec = " ".join("\n".join(section(read("building.md"), BUILDING_HEAD)).split())
    i = sec.index("**These kinds stay classic**")
    part = sec[i:sec.index("### Workshops with their pile rooms")]
    for k in ("farms", "landmark levels", "multi-storey openings", "wells", "the cistern", "galleries", "ways in",
              "stairwells", "the cavern crossing", "the deep depot", "the keep", "surface hall", "gate wings",
              "gatehouse", "garden court", "pastures", "`field_hall`", "`field_kitchens`"):
        assert k in part, k


@test("building.md: every kind that goes on a floor has a row in both tables")
def _():
    sec = section(read("building.md"), BUILDING_HEAD)
    sits = " ".join(table_after(sec, "### How each kind of level sits on a floor"))
    where = " ".join(table_after(sec, "### Which floor a level goes to"))
    for kind in ("bedrooms", "suites", "jail", "storage", "workshops", "dining", "tavern", "temple", "library",
                 "garden", "memorial", "hospital", "barracks", "archery", "tombs"):
        assert kind in sits, ("sits", kind)
        assert kind in where, ("where", kind)
    rows = "\n".join(table_after(sec, "### Which floor a level goes to").values())
    for k in ("homes", "halls", "storage", "industry", "defence", "sleeping", "common", "worship", "crypt",
              "stores", "crafts", "forges", "kitchens", "guard"):
        assert k in rows, k


@test("building.md: the slider table has a row each for the six sliders, with the design's numbers")
def _():
    rows = table_after(section(read("building.md"), BUILDING_HEAD), "### Which slider does what on a floor")
    for s in SLIDERS:
        assert s in rows, (s, list(rows))
        assert len(rows[s].split("|")) == 4 and len(rows[s]) > 60, rows[s]
    for s, needs in {"Spacing": ("2 at +50", "3 at +100", "0, 2, 4, 6", "1, 3, 5"),
                     "Room size": ("2x2, 3x3 or 4x4", "5 wide, 7 at +50", "15%"),
                     "Depth": ("40+", "20 columns", "14 at 100+", "runs of 30", "-40 or lower", "44", "60", "up to 4 halls"),
                     "Grandeur": ("40+", "60+", "5x5"),
                     "Fortification": ("50+", "0.6", "70+", "neck"),
                     "Reserves": ("50+", "second pile room")}.items():
        for k in needs:
            assert k in rows[s], (s, k)


@test("building.md: the worked example is the design's drawing, unchanged")
def _():
    sec = section(read("building.md"), BUILDING_HEAD)
    fences = [i for i, l in enumerate(sec) if l.startswith("```")]
    assert len(fences) == 2, fences
    art = sec[fences[0] + 1:fences[1]]
    assert len(art) == 14, len(art)
    assert art[0] == "      x=321012345678901234567890123456"
    assert art[6] == "y= -2   ########D###D####+++###+++####      s the Masons' stone pile     W the Masons' shop"
    assert art[8].startswith("y=  0   ##.S........................##")
    grid = [l[8:38] for l in art[1:]]
    assert all(len(g) == 30 for g in grid), grid
    hall = [g for g in grid[6:9]]
    assert all(g[2:28] == "." * 26 or g[2:28] == ".S" + "." * 24 for g in hall), hall     # 3 wide, x = -1 .. 24
    assert sum(g.count("D") for g in grid) == 4 and sum(g.count("+") for g in grid) == 6
    assert sum(g.count("W") for g in grid) == 9 and sum(g.count("s") for g in grid) == 25
    text = " ".join(" ".join(sec[:fences[0]]).split())
    assert "the hall dug to column 11" in text and "lengthened to column 24" in text and "39 new hall tiles" in text


@test("building.md: no hall project and no hall action is described")
def _():
    sec = " ".join("\n".join(section(read("building.md"), BUILDING_HEAD)).split())
    assert "no separate project for the hall and no action that digs one" in sec
    for bad in ("dig_hall", "hall project", "start_hall", "`dig the hall`"):
        assert bad not in sec, bad
    actions = set(re.findall(r"`([a-z]+_project)`", sec))
    assert actions == {"start_project"}, actions


@test("controls.md: the Rules tab names the cycle, its key and its default")
def _():
    text = read("controls.md")
    item = controls_item(text)
    flat = " ".join(" ".join(item).split())
    assert flat.startswith("- **New levels:** (`floor_layout`)"), flat[:60]
    for k in CYCLE + ("`hallway`", "`classic`", "the default", "new and running forts alike",
                      "a save without the key reads `hallway`", '{"rules": {"floor_layout": "classic"}}',
                      "No preset", "building.md"):
        assert k in flat, k
    assert flat.index(CYCLE[0]) < flat.index("the default") < flat.index(CYCLE[1])     # hallway is the default
    lines = text.splitlines()
    i = lines.index(item[0])
    heads = [l for l in lines[:i] if l.startswith("#")]
    assert heads[-2:] == ["## The Rules tab", "### The fort"], heads[-2:]


@test("watch-in-game.md: the new section is the first, with at least fourteen items, one line each")
def _():
    text = read("watch-in-game.md")
    heads = [l for l in text.splitlines() if l.startswith("## ")]
    assert heads[0] == WATCH_HEAD, heads[0]
    sec = section(text, WATCH_HEAD)
    items = [l for l in sec if l.startswith("- ")]
    assert len(items) >= 14, len(items)
    assert all(re.match(r"^- \*\*[^*]+\.\*\* \S", l) for l in items), [l[:40] for l in items]
    assert len(set(l.split("**")[1] for l in items)) == len(items)                  # no lead twice
    body = [l for l in sec if l.strip() and not l.startswith("- ")]
    assert len(body) == 1 and "building.md" in body[0], body                        # nothing wrapped onto a second line
    flat = "\n".join(items)
    for k in ("3-wide hall running out from the main stair", "dug before the rooms", "3-wide opening",
              "pile room next door", "linked to the shop", "lengthens the hall", "5x5 square with statues",
              "next floor", "Old levels are untouched", "aquifer", "doorless pocket", "far end of its floor",
              "wall to wall", "Deep mine", "Garden fort", "War-hold", "set to classic",
              '"on floor #3, along the east hall"', '"not on a floor: ..."', "`start_project`"):
        assert k in flat, k


@test("the three files are plain UTF-8, and the new sections keep the house wrapping")
def _():
    for name, head in (("building.md", BUILDING_HEAD), ("watch-in-game.md", WATCH_HEAD)):
        raw = (DOCS / name).read_bytes()
        text = raw.decode("utf-8")
        assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and "\t" not in text, name
        sec = section(text, head)
        assert sec, name
        longest = max(len(l) for l in rest(text, sec, head))
        over = [(len(l), l[:50]) for l in sec if len(l) > longest + SLACK]
        assert not over, (name, longest, over)
        assert not [l for l in sec if l != l.rstrip()], name                         # no trailing blanks
    raw = (DOCS / "controls.md").read_bytes()
    text = raw.decode("utf-8")
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw
    assert all(len(l) <= 80 for l in controls_item(text)), [len(l) for l in controls_item(text)]
    # building.md's prose is wrapped at 80; only tables and the drawing run longer
    sec = section(read("building.md"), BUILDING_HEAD)
    fence, long_prose = False, []
    for l in sec:
        if l.startswith("```"):
            fence = not fence
        elif not fence and not l.startswith("|") and len(l) > 80:
            long_prose.append(l)
    assert not long_prose, long_prose
    top = section(read("building.md"), "## Where a new level goes")[:6]
    assert all(len(l) <= 80 for l in top), top


@test("the new sections use plain characters (no dashes or quotes a console would garble)")
def _():
    for name, head in (("building.md", BUILDING_HEAD), ("watch-in-game.md", WATCH_HEAD)):
        sec = "\n".join(section(read(name), head))
        odd = sorted(set(ch for ch in sec if ord(ch) > 126))
        assert not odd, (name, odd)
    odd = sorted(set(ch for ch in "\n".join(controls_item(read("controls.md"))) if ord(ch) > 126))
    assert not odd, odd


if __name__ == "__main__":
    finish()

"""(F1, verify-v55 V1) Cancelling a floor level leaves designated the hub, hall and stair
tiles another live level of the same floor hangs on; only the cancelled level's own rooms
(and the hall columns no live level needs any more) are undone. The floor record's run
lengths (ai-floorplan.release) and what is still designated agree.

Runs on the fake fort of tests/test_b16_floors_end_to_end.py (its setup and helpers, up to
its first test): the real ai-floorplan, ai-floorplace, ai-floorunits and builder parts,
every level through the real B.start_project and B.cancel_project.

    python tests/test_f1_cancel_shared.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import finish, make_test  # noqa: E402

_B16 = ROOT / "tests" / "test_b16_floors_end_to_end.py"
_SRC = _B16.read_text(encoding="utf-8")
_NS: dict = {"__name__": "b16_top_for_f1", "__file__": str(_B16)}
exec(compile(_SRC[:_SRC.index("# ----------------------------------------------------------------"
                              "----------- 1. the worked example")], str(_B16), "exec"), _NS)

F = type("B16", (), {})()
F.__dict__.update(_NS)
test = make_test(before=lambda: F._reset())
ROCK_Z, SX, SY = F.ROCK_Z, F.SX, F.SY
STAIR_BOTTOM_Z = 60     # the fake fort's main stair ends here: a level on z59 extends it


def bedrooms(z=ROCK_Z, **hint):
    r = F.start(kind="bedrooms", rooms=4, room_size=3,
                floor=dict(dict(elevs=[z], tag="homes", dirs=["east"], arms_max=1, grow=["arm"]), **hint))
    assert r.ok and r.floor is not None, F.plain(r)
    return r


def walkable(x, y, z):
    t = F.W.peek(x, y, z)
    return t is not None and (bool(t.designated) or str(t.shape) != "WALL")


def reached(z, sx=SX, sy=SY):
    seen, todo = {(sx, sy)}, [(sx, sy)]
    while todo:
        x, y = todo.pop()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n not in seen and walkable(n[0], n[1], z):
                seen.add(n)
                todo.append(n)
    return seen


def rooms(pid):
    p = F.project(pid)
    return F.proj_tiles(p) - F.proj_links(p)


def record_hall(z=ROCK_Z, sx=SX, sy=SY):
    """The absolute tiles the floor record says are hall: each run that holds a live slot (or a
    live turning), its node and its columns up to its recorded length."""
    rec = F.floor_rec(z, sx, sy)
    runs = rec.get("runs", []) if rec else []
    live = {s["run"] for s in (rec.get("slots", []) if rec else []) if not s.get("dead")}
    for r in reversed(runs):
        if r["id"] in live and r.get("parent"):
            live.add(r["parent"])
    out = set()
    for r in runs:
        if r["id"] not in live:
            continue
        dx, dy, ox, oy = r["dx"], r["dy"], r["ox"], r["oy"]
        px, py = -dy, dx
        n = 2 if r.get("node") == 5 else 1
        for u in range(-n, n + 1):
            for v in range(-n, n + 1):
                out.add((sx + ox + u * dx + v * px, sy + oy + u * dy + v * py))
        for u in range(n + 1, n + r.get("len", 0) + 1):
            for v in (-1, 0, 1):
                out.add((sx + ox + u * dx + v * px, sy + oy + u * dy + v * py))
    out.discard((sx, sy))
    return out


def designated_xy(z):
    return {(x, y) for x, y, _ in F.designated(z)}


@test("1. cancelling a floor's first level: the next level keeps its way to the stair, the first level's "
      "rooms are undone, and the hall left designated is exactly what the record says the floor has")
def _():
    a, b = bedrooms(), bedrooms()
    pa = F.project(a.project_id)
    rooms_a, rooms_b = rooms(a.project_id), rooms(b.project_id)
    assert F.B.cancel_project(a.project_id).ok
    assert rooms_b <= reached(ROCK_Z), F.draw(ROCK_Z)
    left = designated_xy(ROCK_Z)
    assert not (left & rooms_a), f"the cancelled level's rooms stay designated: {sorted(left & rooms_a)[:5]}"
    hall = record_hall()
    # every tile still designated is the live level's or the record's hall
    stray = left - F.proj_tiles(F.project(b.project_id)) - hall
    assert not stray, f"designated tiles nobody needs: {sorted(stray)[:5]}\n" + F.draw(ROCK_Z)
    # and the record's hall is all there (designated now, or the live level's own)
    gone = hall - left
    assert not gone, f"the record says hall at {sorted(gone)[:5]} but it is not designated\n" + F.draw(ROCK_Z)
    # A's hall columns beyond what B needs (if any) were undone
    assert not ((F.proj_links(pa) - hall) & left), "A's own hall beyond B's need is undone"


@test("2. three levels on one floor: cancel the first, then the second; the third still reaches the stair; "
      "cancel the third (the floor's last live level) and nothing of the floor stays designated")
def _():
    a, b, c = bedrooms(), bedrooms(), bedrooms()
    assert F.B.cancel_project(a.project_id).ok
    assert F.B.cancel_project(b.project_id).ok
    rc = rooms(c.project_id)
    assert rc <= reached(ROCK_Z), F.draw(ROCK_Z)
    assert designated_xy(ROCK_Z) <= F.proj_tiles(F.project(c.project_id)) | record_hall(), F.draw(ROCK_Z)
    assert record_hall() <= designated_xy(ROCK_Z), sorted(record_hall() - designated_xy(ROCK_Z))[:5]
    assert F.B.cancel_project(c.project_id).ok
    assert not designated_xy(ROCK_Z), f"left designated after the last level went: {sorted(designated_xy(ROCK_Z))[:8]}"
    rec = F.floor_rec(ROCK_Z)
    assert all(s.get("dead") for s in rec["slots"]), rec


@test("3. a lone floor level cancelled is all undone, as before")
def _():
    a = bedrooms()
    assert designated_xy(ROCK_Z)
    assert F.B.cancel_project(a.project_id).ok
    assert not designated_xy(ROCK_Z)


@test("4. cancelling a later level leaves the first level (and its hall) whole; the later level's own new "
      "hall columns past the first level's need are undone and the record rolls back to match")
def _():
    a, b = bedrooms(), bedrooms()
    pa, pb = F.project(a.project_id), F.project(b.project_id)
    before_a = F.proj_tiles(pa)
    assert F.B.cancel_project(b.project_id).ok
    left = designated_xy(ROCK_Z)
    assert before_a <= left, f"the first level lost tiles: {sorted(before_a - left)[:5]}"
    assert not (left & (F.proj_tiles(pb) - record_hall())), F.draw(ROCK_Z)
    assert record_hall() <= left, sorted(record_hall() - left)[:5]
    assert F.proj_links(pb) - record_hall(), "the set-up: B lengthened the hall past A's need"


@test("5. the stair extension stays while another level of that floor lives, and goes with the last")
def _():
    z = STAIR_BOTTOM_Z - 1
    a = bedrooms(z)
    assert a.extends_stairs, F.plain(a)
    st = [(c.z, c.text) for c in F.lua_list(F.project(a.project_id).stairs)]
    assert st, "the set-up: A designated the stair extension"
    # a second level joins the floor only once the new stair is dug (the floor search says so) ...
    for sz, _ in st:
        t = F.W.peek(SX, SY, sz)
        t.shape, t.designated = "STAIR_UPDOWN", False
    b = bedrooms(z)
    assert not b.extends_stairs
    # ... so the stair is set back to "designated, not dug yet" here: what the cancel must keep
    for sz, _ in st:
        t = F.W.peek(SX, SY, sz)
        t.shape, t.designated = "WALL", True
    assert F.B.cancel_project(a.project_id).ok
    for sz, _ in st:
        assert F.W.peek(SX, SY, sz).designated, f"the stair on z{sz} was undone while level {b.project_id} lives"
    assert rooms(b.project_id) <= reached(z), F.draw(z)
    assert F.B.cancel_project(b.project_id).ok
    for sz, _ in st:
        assert not F.W.peek(SX, SY, sz).designated, f"the stair on z{sz} stays after the floor's last level went"
    assert not designated_xy(z), sorted(designated_xy(z))[:8]


@test("6. already dug tiles stay dug when a level is cancelled")
def _():
    a, b = bedrooms(), bedrooms()
    F.dig_all()
    tiles = F.proj_tiles(F.project(a.project_id))
    assert F.B.cancel_project(a.project_id).ok
    still = [xy for xy in tiles if str(F.W.peek(xy[0], xy[1], ROCK_Z).shape) == "WALL"]
    assert not still, still[:5]


@test("7. with the floor record lost, a live level of the same floor among the projects still keeps "
      "the cancelled level's hall and hub designated")
def _():
    a, b = bedrooms(), bedrooms()
    rooms_b = rooms(b.project_id)
    F.W.persist[F.KEY] = None
    assert F.B.cancel_project(a.project_id).ok
    assert rooms_b <= reached(ROCK_Z), F.draw(ROCK_Z)
    assert not (designated_xy(ROCK_Z) & rooms(a.project_id))


@test("8. floor_cells_without: rects split round the kept tiles, other cells passed on as they are")
def _():
    keep = F.LUA.table()
    F.B.add(keep, 2, 0)
    F.B.add(keep, 5, 5)
    cells = F.tbl([{"x": 0, "y": 0, "text": "d(4x1)"}, {"x": 9, "y": 9, "text": "d3"},
                   {"x": 5, "y": 5, "text": "d2"}, {"x": 0, "y": 3, "text": "d(2x2)"}])
    out = F.plain(F.B.floor_cells_without(cells, keep))
    assert out == [{"x": 0, "y": 0, "text": "d"}, {"x": 1, "y": 0, "text": "d"}, {"x": 3, "y": 0, "text": "d"},
                   {"x": 9, "y": 9, "text": "d3"}, {"x": 0, "y": 3, "text": "d(2x2)"}], out


@test("9. floor_cancel_keep never raises: junk in, nil out")
def _():
    for junk in (None, 5, F.tbl({}), F.tbl({"floor": 3}), F.tbl({"floor": {"id": 1}, "z": "x"})):
        r = F.LUA.eval("function(f, p) return {pcall(f, p, nil)} end")(F.B.floor_cancel_keep, junk)
        assert r[1] is True and r[2] is None, F.plain(r)


if __name__ == "__main__":
    finish()

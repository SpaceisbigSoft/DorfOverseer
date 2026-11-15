"""(verifier, 0.105.55 "layout option B") Proofs of the findings in verify-v55.md.

Each test FAILS on the code as delivered and passes once its finding is fixed.
They run on the fake fort of tests/test_b16_floors_end_to_end.py (its setup and
helpers, up to its first test, executed here: the real ai-floorplan,
ai-floorplace, ai-floorunits and builder parts, every level through the real
B.start_project).

    python tests/test_v55_floors_verify.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import finish, make_test  # noqa: E402

_B16 = ROOT / "tests" / "test_b16_floors_end_to_end.py"
_SRC = _B16.read_text(encoding="utf-8")
_NS: dict = {"__name__": "b16_top_for_v55", "__file__": str(_B16)}
# the B16 file's setup and helpers only (its tests start at "1. the worked example")
exec(compile(_SRC[:_SRC.index("# ----------------------------------------------------------------"
                              "----------- 1. the worked example")], str(_B16), "exec"), _NS)
# the six presets' hints as B16 wrote them out (test 13)
exec(compile(_SRC[_SRC.index("PRESET_HINTS = {"):_SRC.index("PRESET_SEQ = [")], str(_B16), "exec"), _NS)

F = type("B16", (), {})()
F.__dict__.update(_NS)
test = make_test(before=lambda: F._reset())
ROCK_Z, SX, SY = F.ROCK_Z, F.SX, F.SY


def bedrooms(**hint):
    return F.start(kind="bedrooms", rooms=4, room_size=3,
                   floor=dict(dict(elevs=[ROCK_Z], tag="homes", dirs=["east"], arms_max=1, grow=["arm"]), **hint))


def walkable(x, y, z):
    """Dug now, or designated to be dug (what the dwarves will walk once the digging is done)."""
    t = F.W.peek(x, y, z)
    return t is not None and (bool(t.designated) or str(t.shape) != "WALL")


def reached_from_stair(z, sx=SX, sy=SY):
    """The tiles 4-connected to the stair through dug or designated tiles."""
    seen, todo = {(sx, sy)}, [(sx, sy)]
    while todo:
        x, y = todo.pop()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n not in seen and walkable(n[0], n[1], z):
                seen.add(n)
                todo.append(n)
    return seen


# --------------------------------------------------------------------------- V1

@test("V1. cancelling a floor level never cuts another live level on the same floor off from the stair "
      "(the hub and the hall the later level hangs on stay designated)")
def _():
    a = bedrooms()
    b = bedrooms()
    assert a.ok and b.ok and a.floor is not None and b.floor is not None, (F.plain(a), F.plain(b))
    pb = F.project(b.project_id)
    rooms_b = F.proj_tiles(pb) - F.proj_links(pb)
    assert rooms_b <= reached_from_stair(ROCK_Z), "the set-up: B reachable before the cancel"
    assert F.B.cancel_project(a.project_id).ok
    cut = sorted(rooms_b - reached_from_stair(ROCK_Z))
    assert not cut, (f"after cancelling project {a.project_id}, {len(cut)} tiles of the live project "
                     f"{b.project_id} have no dug or designated way to the stair (e.g. {cut[:3]}); the floor "
                     f"record still says its hall runs {F.floor_rec(ROCK_Z)['runs'][0]['len']} columns\n"
                     + F.draw(ROCK_Z))


# --------------------------------------------------------------------------- V2

def sixty_marked_floors():
    """A record holding FLOORS_MAX (60) floors with nothing on them: what the marks leave behind (every
    level found 'no hall' or 'full' gets a record, and none is ever taken out)."""
    return {"v": 1, "next": 61, "fallbacks": 60,
            "floors": [{"id": i, "z": 200 + i, "stair": {"x": SX, "y": SY}, "made": 0, "hub": "found",
                        "runs": [], "slots": [], "full": {"*": 0}} for i in range(1, 61)]}


@test("V2a. a level the answer puts on a floor is in the floor record, even when the record already holds "
      "60 floors that are only marks (no runs, no slots)")
def _():
    F.W.persist[F.KEY] = F.tbl(sixty_marked_floors())
    r = bedrooms()
    assert r.ok and r.floor is not None, F.plain(r)
    fid = F.plain(r.floor)["id"]
    rec = F.floor_rec(ROCK_Z)
    assert rec is not None and any(s.get("pid") == r.project_id for s in rec.get("slots", [])), \
        (f"project {r.project_id} was dug as a level of floor #{fid} (the answer and p.floor say so) but the "
         f"floor record has no floor on z{ROCK_Z}: ai-floorplan.commit refused it ('floor record full') after "
         f"the level was designated; record: {len(F.store()['floors'])} floors")


@test("V2b. a workshops level that fits nowhere leaves no lasting empty floor records behind: the record's "
      "empty, only-marked floors are dropped once their marks are older than full_retry_days")
def _():
    # (0.105.55 merge) the set-up's 4-shop level now fits (F3 splits a workshops level per shop), and a
    # level too big for any run no longer marks; the marks are made here as a classic fallback writes them
    marks = [{"z": z, "sx": SX, "sy": SY, "tag": "industry"} for z in (ROCK_Z, ROCK_Z - 1, ROCK_Z - 2, ROCK_Z - 3)]
    F.B.floor_fallback("workshops", "no room", ROCK_Z, F.tbl(marks))
    empty = [f for f in F.store()["floors"] if not f.get("runs") and not f.get("slots")]
    assert len(empty) >= 3, F.store()       # the set-up: marks made records of empty levels
    F.E.tick = 400 * 1200                   # long after every mark has expired
    r2 = F.start(kind="storage", piles=["wood"], room_size=5, floor={"elevs": [ROCK_Z - 10], "tag": "storage"})
    assert r2.ok, F.plain(r2)
    left = [f for f in F.store()["floors"] if not f.get("runs") and not f.get("slots")
            and all(400 * 1200 - (t if isinstance(t, int) else 0) >= 28 * 1200 for t in f.get("full", {}).values())]
    assert not left, (f"{len(left)} floor records with no hall and only expired marks are kept for good; the "
                      f"record holds at most 60 floors (ai-floorplan FLOORS_MAX), after which no new floor can "
                      f"be recorded (V2a): {[(f['id'], f['z']) for f in left]}")


# --------------------------------------------------------------------------- V3

@test("V3a. Hermit hold (the preset's own grammar: run_max 18, piles_new 2): a one-shop workshops level "
      "goes onto an empty floor")
def _():
    g = dict(F.PRESET_HINTS["Hermit hold"], elevs=[ROCK_Z, ROCK_Z - 1])
    r = F.start(kind="workshops", shops=["Masons"], floor=g)
    assert r.ok and r.floor is not None, \
        (f"a single Masons' workshop never fits an empty floor of the Hermit hold: {r.not_on_floor!r} (two pile "
         f"rooms and the shop, 5+1+5+1+5 = 17 columns kept together, from column 4 with one ahead, past the "
         f"run's last column 19); every workshops level there goes the classic way and marks the floor full")


@test("V3b. Deep mine (run_max 14): a two-shop workshops level goes onto an empty floor")
def _():
    g = dict(F.PRESET_HINTS["Deep mine"], elevs=[ROCK_Z])
    r = F.start(kind="workshops", shops=["Masons", "Carpenters"], floor=g)
    assert r.ok and r.floor is not None, f"never fits a 14-column run: {r.not_on_floor!r}"


@test("V3c. a workshops level too long for any run (ten shops, one arm, no turn) does not mark "
      "the floor full for industry: a one-shop level right after still goes onto that (empty) floor")
def _():
    # (0.105.55 merge) 4 shops now fit a 30-column run split per shop (F3); a level that truly fits no run:
    # ten shops on one arm with no turns
    hint = {"elevs": [ROCK_Z], "tag": "industry", "arms_max": 1, "grow": ["arm"], "dirs": ["east"]}
    shops = ["Masons", "Carpenters", "Craftsdwarfs", "Mechanics", "Jewelers", "Bowyers", "Clothiers",
             "Leatherworks", "Kitchen", "Still"]
    big = F.start(kind="workshops", shops=shops, floor=dict(hint))
    assert big.ok and big.floor is None and "no room" in str(big.not_on_floor), F.plain(big)
    small = F.start(kind="workshops", shops=["Jewelers"], floor=dict(hint))
    assert small.ok and small.floor is not None, \
        (f"the one-shop level is kept off the empty floor for 28 days: {small.not_on_floor!r}; "
         f"record: {F.floor_rec(ROCK_Z)}")


# --------------------------------------------------------------------------- V4

@test("V4. a workshops level on a floor has no free room (unit_params drops the spares): p.free_left is not "
      "set, so save_projects does not keep it as a 'free level' nobody can join")
def _():
    r = F.start(kind="workshops", shops=["Masons"], spare=2, floor={"elevs": [ROCK_Z], "tag": "industry"})
    assert r.ok and r.floor is not None, F.plain(r)
    p = F.project(r.project_id)
    assert not p.free_left, f"floor workshops level {r.project_id} saved with free_left = {p.free_left}"


if __name__ == "__main__":
    finish()

"""(fix F3, verify-v55 V3) Workshops in rows along the hall, each shop beside its own pile rooms.

A workshops level on a floor is placed as clusters (a shop and its pile rooms side by side), not as one
unbroken row: the clusters follow each other along the hall, onto the other side or another run when one
is full. The pile rooms are capped so one shop and its piles fit one side of the shortest run the grammar
gives, and a 'no room' marks the floor full for the tag only when the request could have gone onto an
empty run of the floor's grammar.

Runs on the fake fort of tests/test_b16_floors_end_to_end.py (its setup and helpers executed here: the
real ai-floorplan, ai-floorplace, ai-floorunits and builder parts, every level through B.start_project).

    python tests/test_f3_workshop_rows.py
    DFAI_F3_DRAW=/path/f3-workshops.txt python tests/test_f3_workshop_rows.py    the 4-shop floor drawn there
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import finish, make_test  # noqa: E402

_B16 = ROOT / "tests" / "test_b16_floors_end_to_end.py"
_SRC = _B16.read_text(encoding="utf-8")
_NS: dict = {"__name__": "b16_top_for_f3", "__file__": str(_B16)}
exec(compile(_SRC[:_SRC.index("# ----------------------------------------------------------------"
                              "----------- 1. the worked example")], str(_B16), "exec"), _NS)
exec(compile(_SRC[_SRC.index("PRESET_HINTS = {"):_SRC.index("PRESET_SNAPSHOTS = {")], str(_B16), "exec"), _NS)

F = type("B16", (), {})()
F.__dict__.update(_NS)
test = make_test(before=lambda: F._reset())
ROCK_Z, SX, SY = F.ROCK_Z, F.SX, F.SY
PRESETS = F.PRESET_HINTS
FOUR = ["Masons", "Carpenters", "Craftsdwarfs", "Mechanics"]


def mods():
    return F.E.mods


def lua_grammar(hint):
    return mods()["ai-floorplan"].grammar(F.tbl(hint))


def shop_room(G):
    return int(G.run_max) - int(G.lead) - int(G.ahead) - (1 if G.neck else 0)


def slot_box(run, s):
    """A slot's tiles (stair-relative), as ai-floorplace draws it."""
    px, py = -run["dy"], run["dx"]
    side = s["side"]
    out = set()
    for u in range(s["u"], s["u"] + s["w"]):
        for r in range(2, 3 + s["d"]):
            v = r * side
            out.add((run["ox"] + u * run["dx"] + v * px, run["oy"] + u * run["dy"] + v * py))
    return out


def clusters_ok(r, z=ROCK_Z, what=""):
    """Every pile room of the level stands beside its own shop: the same run and side, the next slot
    along (one gap between). Returns the number of piles checked."""
    p = F.project(r.project_id)
    rec = F.floor_rec(z)
    runs = {x["id"]: x for x in rec["runs"]}
    slots = [s for s in rec["slots"] if s.get("pid") == r.project_id]
    gap = int(F.plain(r.floor)["gap"])
    a = p.anchor
    ws = F.LUA.globals().LAYOUTS.WORKSHOPS

    def slot_at(x, y):
        for s in slots:
            if (x, y) in slot_box(runs[s["run"]], s):
                return s
        return None

    builds = [(c.x + a.x - SX, c.y + a.y - SY, str(c.text)) for c in F.lua_list(p.cells.build)]
    piles = F.plain(p.floor.piles) or []
    for pile in piles:
        ps = slot_at(pile["x"] + a.x - SX, pile["y"] + a.y - SY)
        assert ps is not None and ps.get("role") == "pile", (what, pile, slots)
        key = ws[pile["shop"]]
        shop_slots = [slot_at(x, y) for x, y, t in builds if t == key]
        shop_slots = [s for s in shop_slots if s is not None]
        assert shop_slots, (what, "no shop slot for", pile["shop"])
        def beside(s):
            """the shop's slot follows the pile's along one row, only pile rooms (one gap apart) between"""
            if s["run"] != ps["run"] or s["side"] != ps["side"]:
                return False
            row = sorted((x for x in slots if x["run"] == ps["run"] and x["side"] == ps["side"]),
                         key=lambda x: x["u"])
            i, j = sorted((row.index(ps), row.index(s)))
            between = row[i:j + 1]
            return (all(x.get("role") == "pile" for x in row[i + 1:j])
                    and all(q["u"] == o["u"] + o["w"] + gap for o, q in zip(between, between[1:])))
        assert any(beside(s) for s in shop_slots), \
            (f"{what}: the {pile['flag']} pile of {pile['shop']} at slot {ps} is not beside its shop "
             f"{shop_slots}\n" + F.draw(z))
    return len(piles)


# --------------------------------------------------------------------------- the grammar


@test("the grammar: every preset, and every run_max from 12 to 80 with the widest lead, ahead, gap, neck and "
      "pile_w the ranges allow, leaves room on one side of a run for a shop (5) and one pile room")
def _():
    for name, g in PRESETS.items():
        G = lua_grammar(g)
        assert shop_room(G) >= 5 + int(G.gap) + int(G.pile_w), (name, shop_room(G))
        # (the presets are untouched by the clamp)
        for k in ("lead", "ahead", "gap", "pile_w", "run_max"):
            assert G[k] == g[k], (name, k, G[k], g[k])
    for run_max in range(12, 81):
        for neck in (False, True):
            G = lua_grammar({"run_max": run_max, "lead": 8, "ahead": 3, "gap": 4, "neck": neck, "pile_w": 11})
            assert shop_room(G) >= 5 + int(G.gap) + 5, (run_max, neck, shop_room(G), G.gap)
            assert 5 <= int(G.pile_w) <= shop_room(G) - 5 - int(G.gap), (run_max, neck, G.pile_w)
            # a shop with one pile room of that width fits an empty run of it
            req = {"kind": "workshops", "tag": "industry", "together": True, "clusters": [[1, 2]],
                   "units": [{"w": int(G.pile_w), "d": int(G.pile_w), "role": "pile", "flag": "stone"},
                             {"w": 5, "d": 5, "role": "shop"}]}
            assert mods()["ai-floorplace"].fits_empty(F.tbl(req), G), (run_max, neck)


@test("the brain's grammar keeps the same room: floor_grammar for extreme sliders gives a shop and a pile room a "
      "side of its run, and ai-floorplan.grammar passes it unchanged")
def _():
    import floor_grammar as FG
    for spacing in (-100, 0, 60, 100):
        for depth in (-120, 0, 120):
            for size in (-120, 0, 120):
                for fort in (0, 120):
                    traits = {"spacing": spacing, "verticality": depth, "size": size, "fortification": fort,
                              "stockpile": 60}
                    for style in ({}, {"aspect": "wide"}):
                        g = FG.grammar(traits, style, doors="fortified" if fort else None)
                        assert FG.shop_room(g) >= FG.SHOP_COLS + g["gap"] + FG.PILE_COLS, (traits, style, g)
                        assert g["pile_w"] <= FG.shop_room(g) - FG.SHOP_COLS - g["gap"], (traits, g)
                        G = lua_grammar(g)
                        for k in ("lead", "ahead", "gap", "pile_w", "run_max", "run_min"):
                            assert G[k] == g[k], (traits, style, k, G[k], g[k])
    # the clamp on a hand-made short run: the lead goes first, then ahead, then the gap
    g = {"run_max": 12, "lead": 8, "ahead": 3, "gap": 4, "neck": True, "pile_w": 11}
    FG._shop_room(g)
    assert (g["lead"], g["ahead"], g["gap"], g["pile_w"]) == (0, 0, 1, 5), g
    G = lua_grammar({"run_max": 12, "lead": 8, "ahead": 3, "gap": 4, "neck": True, "pile_w": 11})
    assert (G.lead, G.ahead, G.gap, G.pile_w) == (0, 0, 1, 5)


# --------------------------------------------------------------------------- every preset


@test("every preset: a one-shop level goes onto an empty floor with its pile room beside it")
def _():
    for name, g in PRESETS.items():
        F._reset()
        r = F.start(kind="workshops", shops=["Masons"], floor=dict(g, elevs=[ROCK_Z]))
        assert r.ok and r.floor is not None, (name, r.not_on_floor)
        assert F.plain(r.floor).get("piles") == ["stone"], (name, F.plain(r.floor))
        assert clusters_ok(r, what=name) == 1
        F.check_floor(ROCK_Z, what=f"F3 one shop {name}")


@test("every preset: a four-shop level goes onto an empty floor, split into clusters where one row is too long, "
      "each pile room beside its own shop")
def _():
    for name, g in PRESETS.items():
        F._reset()
        r = F.start(kind="workshops", shops=list(FOUR), floor=dict(g, elevs=[ROCK_Z]))
        assert r.ok and r.floor is not None, (name, r.not_on_floor)
        fr = F.plain(r.floor)
        n = clusters_ok(r, what=name)
        assert fr["units"] == 4 + n and n >= 1, (name, fr)
        rec = F.floor_rec(ROCK_Z)
        rows = {(s["run"], s["side"]) for s in rec["slots"] if s.get("pid") == r.project_id}
        assert len(rows) >= 2, (name, "five rooms of 5 columns never fit one side of these runs", rows)
        F.check_floor(ROCK_Z, what=f"F3 four shops {name}")
        # and a one-shop level after it still finds room on the floor
        r2 = F.start(kind="workshops", shops=["Jewelers"], floor=dict(g, elevs=[ROCK_Z]))
        assert r2.ok and r2.floor is not None, (name, r2.not_on_floor)
        F.check_floor(ROCK_Z, what=f"F3 four shops then one {name}")


@test("every preset: the ten-level sequence of B16 puts both workshops levels on a floor")
def _():
    for name, g in PRESETS.items():
        F._reset()
        for kind, kw in F.PRESET_SEQ:
            r = F.start(kind=kind, floor=dict(g, elevs=[ROCK_Z, ROCK_Z - 1]), **dict(kw))
            assert r.ok, (name, kind)
            if kind == "workshops":
                assert r.floor is not None, (name, kw, r.not_on_floor)


@test("the Hermit hold (piles_new 2, 14 columns a side): a mason gets one pile room, not two; two shops each "
      "get their own")
def _():
    g = dict(PRESETS["Hermit hold"], elevs=[ROCK_Z])
    r = F.start(kind="workshops", shops=["Masons"], floor=dict(g))
    assert r.ok and r.floor is not None, r.not_on_floor
    assert F.plain(r.floor)["piles"] == ["stone"], F.plain(r.floor)
    F._reset()
    r = F.start(kind="workshops", shops=["Masons", "Carpenters"], floor=dict(g))
    assert r.ok and r.floor is not None, r.not_on_floor
    piles = F.plain(F.project(r.project_id).floor.piles)
    assert sorted((p["flag"], p["shop"]) for p in piles) == [("stone", "Masons"), ("wood", "Carpenters")], piles
    assert clusters_ok(r, what="hermit 2") == 2


# --------------------------------------------------------------------------- the full mark


@test("a level too big for any run of the floor's grammar answers 'no room' but does not mark the floor full "
      "for its tag: a one-shop level right after goes onto the same empty floor")
def _():
    # (r3 g2) spill=False: one arm only (a full floor would else open more arms and take them all);
    # the answer is "too big for a run (...)" now, told apart from "no room"
    hint = {"elevs": [ROCK_Z], "tag": "industry", "arms_max": 1, "grow": ["arm"], "dirs": ["east"], "spill": False}
    shops = ["Masons", "Carpenters", "Craftsdwarfs", "Mechanics", "Jewelers", "Bowyers", "Clothiers",
             "Leatherworks", "Kitchen", "Still"]
    big = F.start(kind="workshops", shops=shops, floor=dict(hint))
    assert big.ok and big.floor is None and "too big for a run" in str(big.not_on_floor), F.plain(big)
    assert "too big" in str(big.not_on_floor), big.not_on_floor
    rec = F.floor_rec(ROCK_Z)
    assert rec is None or "industry" not in (rec.get("full") or {}), rec
    small = F.start(kind="workshops", shops=["Jewelers"], floor=dict(hint))
    assert small.ok and small.floor is not None, small.not_on_floor


@test("a floor really full for workshops is still marked: one run of 12 (one arm, no turn) holds a level, the "
      "next 'no room' marks it and a third is skipped as full for industry")
def _():
    hint = {"elevs": [ROCK_Z], "tag": "industry", "arms_max": 1, "grow": ["arm"], "dirs": ["east"],
            "run_max": 12, "lead": 0, "ahead": 0, "piles_new": 0, "sides": "one", "spill": False}   # (r3 g2) one arm
    a = F.start(kind="workshops", shops=["Masons", "Carpenters"], floor=dict(hint))
    assert a.ok and a.floor is not None, a.not_on_floor
    b = F.start(kind="workshops", shops=["Jewelers"], spare=0, floor=dict(hint))
    assert b.ok and b.floor is None and "no room" in str(b.not_on_floor) and "too big" not in str(b.not_on_floor), \
        b.not_on_floor
    assert "industry" in (F.floor_rec(ROCK_Z).get("full") or {}), F.floor_rec(ROCK_Z)
    c = F.start(kind="workshops", shops=["Bowyers"], floor=dict(hint))
    assert c.ok and c.floor is None and "full for industry" in str(c.not_on_floor), c.not_on_floor


# --------------------------------------------------------------------------- the placement module


@test("ai-floorplace: clusters are each one row; a cluster too wide for any run is 'no room'; a bad cluster list "
      "is refused; fits_empty answers for one empty run only")
def _():
    P = mods()["ai-floorplace"]
    G = lua_grammar({"run_max": 18, "lead": 2, "ahead": 1, "dirs": ["east"], "arms_max": 1, "grow": ["arm"]})
    env = F.LUA.execute("""
      local env = {seed = 0}
      function env.open() return 'rock' end
      function env.blocked() return false end
      function env.probe() return true end
      function env.late() return false end
      return env""")

    def unit(w, role="shop"):
        return {"w": w, "d": 5, "role": role}

    def req(units, clusters=None, together=True):
        q = {"kind": "workshops", "tag": "industry", "together": together, "units": units}
        if clusters is not None:
            q["clusters"] = clusters
        return F.tbl(q)

    floor = F.tbl({"id": 1, "runs": [], "slots": []})

    def place(q):
        r = P.place(floor, q, G, env)
        return r if isinstance(r, tuple) else (r, None)

    # three clusters of 11 columns: one a side of an 18-run (15 columns), the third has no room
    us = [unit(5, "pile"), unit(5), unit(5, "pile"), unit(5), unit(5, "pile"), unit(5)]
    pl, why = place(req(us, [[1, 2], [3, 4], [5, 6]]))
    assert pl is None and why == "no room", why
    pl, why = place(req(us[:4], [[1, 2], [3, 4]]))
    assert pl is not None, why
    puts = sorted(F.plain(pl.puts), key=lambda p: p["unit"])
    assert puts[0]["side"] == puts[1]["side"] and puts[1]["u"] == puts[0]["u"] + 6, puts
    assert puts[2]["side"] == puts[3]["side"] and puts[3]["u"] == puts[2]["u"] + 6, puts
    assert puts[0]["side"] != puts[2]["side"], "the second cluster across the hall"
    # the same four as one together row: 23 columns, no room on an 18-run
    pl, why = place(req(us[:4]))
    assert pl is None and why == "no room", why
    assert P.fits_empty(req(us[:4], [[1, 2], [3, 4]]), G) is True
    assert P.fits_empty(req(us[:4]), G) is False
    assert P.fits_empty(req(us, [[1, 2], [3, 4], [5, 6]]), G) is False
    for bad in ([[1, 2], [2, 3, 4]], [[1, 2]], [[1, 2], [3, 9]], [[], [1, 2, 3, 4]]):
        pl, why = place(req(us[:4], bad))
        assert pl is None and str(why).startswith("bad request"), (bad, why)


# --------------------------------------------------------------------------- the drawing


@test("the drawing: a 4-shop level (with its pile room) on the Merchant city's floor, by draw_level.render")
def _():
    g = dict(PRESETS["Merchant city"], elevs=[ROCK_Z])
    F.start(kind="bedrooms", rooms=4, room_size=3, floor=dict(g, tag="homes"))
    r = F.start(kind="workshops", shops=list(FOUR), floor=dict(g))
    assert r.ok and r.floor is not None, r.not_on_floor
    clusters_ok(r, what="drawing")
    text = F.draw(ROCK_Z, title="F3: bedrooms, then a 4-shop workshops level (Masons with its stone pile), "
                                "Merchant city grammar, z63")
    for key in ("wm", "wc", "wr"):
        assert key in text, (key, text)
    out = os.environ.get("DFAI_F3_DRAW")
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    finish()

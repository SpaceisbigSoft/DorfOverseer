"""(0.105.112 item2) E's killers held: a citizen who killed a citizen is held,
never let out "no longer needed" while in a tantrum, miserable or very
unhappy, or within killer_hold_days of the killing; a chronic tantrum case
who attacked a citizen is held until no longer miserable; chronic_convict
refused "no solved case" waits for a new tantrum.

Live E, 24 Nov: Muterazor (17912) was celled at 20:29 and let out "no
longer needed" at 20:35 (year 270 tick 65088): his killings of year 267
(tick 61328, a tame dog; 62769, a woodcrafter) passed WINDOW_TICKS (3 game
years, ~7 real hours in E). He strangled Thikut at 21:31 (one killing:
"weak", a note only). Diamondlenses (Melbil, 16:35) and Dentconstruct
(Medtob, 22:16): one killing each, "weak", never held. chronic_convict was
refused 41 times in 12 hours, the back-off begun again after each conviction.

    python tests/test_r112_killers_hold.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

from planner import Memory, PLANNER_CONFIG as cfg  # noqa: E402
from planner_core import TICKS_PER_DAY, Proposal  # noqa: E402
from planner_core_refusals import note_refusal  # noqa: E402
import planner_killers as PK  # noqa: E402
import planner_tantrums as PT  # noqa: E402

YEAR, TICK = 270, 65088
NOW = YEAR * 403200 + TICK
DENT, DIAM, MUTE, CALM = 19508, 16784, 17912, 30


def state(killers=None, cells=None, tantrums=None, fights=None):
    s = {"date": {"year": YEAR, "tick": TICK}, "killers": {"list": killers or [], "cells": cells or [], "rooms": 5}}
    if tantrums is not None:
        s["tantrums"] = {"dwarves": tantrums, "loose": sum(1 for t in tantrums if t.get("now"))}
    if fights is not None:
        s["fights"] = {"armed": True, "log": fights}
    return s


def krow(uid, name, people=1, ago=2000, stress=0, conf="weak", **kw):
    return {"id": uid, "name": name, "kind": "killer", "confidence": conf, "citizen": True, "kills": 1,
            "people": people, "last_ago": ago, "stress": stress, "seen_ticks": 5000, "victims": ["Medtob"], **kw}


def trow(uid, name, year=3, stress="miserable", now=False, ticks=None):
    return {"id": uid, "name": name, "year": year, "stress": stress, "now": now or None,
            "ticks": ticks or [NOW - 300 * (i + 1) for i in range(year)], "unmet": [], "posts": []}


def run(s, memory=None):
    props, notes = [], []
    PK._killer_rule(s, cfg, props, notes, memory)
    cells = [p for p in props if p.rule == "killer" and p.action.get("type") == "killer_cell"]
    return cells, notes


@test("one killing of a citizen (a tantrum's, 'weak'): held in a cell, and the other rules keep off them")
def _():
    s = state([krow(DENT, "Dentconstruct"), krow(DIAM, "Diamondlenses", ago=50000)])
    cells, notes = run(s, Memory())
    assert cells and sorted(cells[0].action["units"]) == sorted([DENT, DIAM]), cells
    assert "lock them in a cell" in cells[0].reason, cells[0].reason
    assert {DENT, DIAM} <= PK.held_killer_ids(s)
    # a brawler with no person killed (an animal, or an older bridge without `people`): a note only
    s2 = state([krow(40, "Brawler", people=0), {**krow(41, "Old"), "people": None}])
    cells, notes = run(s2, Memory())
    assert not cells and any("watched" in n for n in notes), notes
    assert not (PK.held_killer_ids(s2) & {40, 41})
    # the law and children as before
    s3 = state([krow(42, "Child", child=True), krow(43, "Sheriff", law=True, law_kills=1, law_codes=["SHERIFF"])])
    cells, notes = run(s3, Memory())
    assert not cells, cells


@test("Muterazor: the killing aged out of the report, but miserable, in a tantrum or within the hold days: kept")
def _():
    m = Memory()
    # first seen with his killing: booked
    run(state([krow(MUTE, "Muterazor", ago=1000, stress=2)], cells=[{"unit_id": MUTE, "locked": True}]), m)
    assert str(MUTE) in m.killer_book["kills"]
    # the report has forgotten it (the window): still within the hold days -> kept
    cells, notes = run(state([], cells=[{"unit_id": MUTE, "locked": True}]), m)
    assert cells == [] or MUTE in cells[0].action["units"], cells
    assert not any("no longer needed" in p.reason for p in cells), cells
    assert any("Muterazor killed a citizen and did so" in n for n in notes), notes
    # past the hold days, calm, no tantrum: let out
    m.killer_book["kills"][str(MUTE)]["last"] = NOW - (cfg["killer_hold_days"] + 1) * TICKS_PER_DAY
    cells, notes = run(state([], cells=[{"unit_id": MUTE, "locked": True}]), m)
    assert cells and "no longer needed" in cells[0].reason and MUTE not in cells[0].action["units"], cells
    # ...but miserable (the tantrum ledger), or very unhappy, or in a tantrum: kept
    for t in (trow(MUTE, "Muterazor", year=1), trow(MUTE, "Muterazor", year=1, stress="very_unhappy"),
              trow(MUTE, "Muterazor", year=1, stress="fine", now=True)):
        cells, notes = run(state([], cells=[{"unit_id": MUTE, "locked": True}], tantrums=[t]), m)
        assert not any("no longer needed" in p.reason for p in cells), (t, cells)
    # a killer row still listed but with no person in the window (weak, brawls), miserable: kept too
    row = {**krow(MUTE, "Muterazor", people=0, stress=0)}
    cells, notes = run(state([row], cells=[{"unit_id": MUTE, "locked": True}]), m)
    assert not any("no longer needed" in p.reason for p in cells), cells


@test("a chronic tantrum case who attacked a citizen: held until no longer miserable; one who attacked no one: free")
def _():
    m = Memory()
    fights = [{"kind": "tantrum_ended", "id": DENT, "target": 17988, "tick": NOW - 500},
              {"kind": "attack", "id": DENT, "target": 18239, "tick": NOW - 400},
              {"kind": "capped", "id": 1, "tick": NOW - 100}]
    t = [trow(DENT, "Dentconstruct", year=3), trow(CALM, "Grumpy", year=4)]
    cells, notes = run(state([], tantrums=t, fights=fights), m)
    assert cells and cells[0].action["units"] == [DENT], cells
    assert "chronic tantrum" in cells[0].reason, cells[0].reason
    assert m.killer_book["attacks"][str(DENT)] == [NOW - 500, NOW - 400]
    # the watcher's log lost (a reload): the book remembers; celled, still miserable: kept
    cells, notes = run(state([], cells=[{"unit_id": DENT, "locked": True}], tantrums=t, fights=[]), m)
    assert not cells or DENT in cells[0].action["units"], cells
    assert any("until no longer miserable" in n for n in notes), notes
    # no longer miserable: let out
    t2 = [trow(DENT, "Dentconstruct", year=3, stress="very_unhappy")]
    cells, notes = run(state([], cells=[{"unit_id": DENT, "locked": True}], tantrums=t2, fights=[]), m)
    assert cells and "no longer needed" in cells[0].reason, cells
    # two tantrums only: not a chronic case
    cells, notes = run(state([], tantrums=[trow(DENT, "Dentconstruct", year=2)], fights=fights), Memory())
    assert not cells, cells


@test("chronic_convict refused 'no solved case': not asked again until a new tantrum of theirs (and a day), or 28 days")
def _():
    r = trow(MUTE, "Muterazor", year=6, ticks=[NOW - 40 * TICKS_PER_DAY - i for i in range(6)])
    p = Proposal("chronic_convict", {"type": "convict", "max": 1, "unit_id": MUTE, "disorderly": True}, "x", 4)
    s = state()
    m = Memory()
    assert PT._convict_backoff(m, p, r, s, cfg) is None                       # never refused: asked
    note_refusal(m, p, {"ok": False, "error": "no solved case of that culprit waits for a trial (disorderly "
                                              "behaviour only)"}, NOW - 2 * TICKS_PER_DAY)
    assert PT._convict_backoff(m, p, r, s, cfg)                               # no tantrum since: waits
    r2 = dict(r, ticks=r["ticks"] + [NOW - TICKS_PER_DAY])
    assert PT._convict_backoff(m, p, r2, s, cfg) is None                      # a new tantrum: asked
    r3 = dict(r, ticks=r["ticks"] + [NOW - 10])
    m.refusals[next(iter(m.refusals))]["at"] = NOW - 100
    assert PT._convict_backoff(m, p, r3, s, cfg)                              # a new one, but not a day yet
    m.refusals[next(iter(m.refusals))]["at"] = NOW - 29 * TICKS_PER_DAY
    assert PT._convict_backoff(m, p, r, s, cfg) is None                       # 28 days: asked anyway
    # another refusal reason: the old back-off only
    m2 = Memory()
    note_refusal(m2, p, {"ok": False, "error": "no free jail chain"}, NOW - 2 * TICKS_PER_DAY)
    assert PT._convict_backoff(m2, p, r, s, cfg) is None


@test("config: the new keys")
def _():
    assert cfg["killer_hold_days"] == 56 and cfg["chronic_hold_attack_days"] == 336
    assert cfg["chronic_convict_refused_days"] == 1


@test("bridge: the killers report gives people, last_ago and stress; ai-killers.lua under the limit")
def _():
    from lua_modules_util import split_src
    src = split_src("ai-killers.lua")
    assert "row.people, row.last_ago = k.people, k.last and t - k.last" in src
    assert "not is(dfhack.units.isAnimal, v)" in src and "getStressCategory" in src
    assert len((ROOT / "lua" / "ai-killers.lua").read_bytes().replace(b"\r", b"")) < 60 * 1024


finish()

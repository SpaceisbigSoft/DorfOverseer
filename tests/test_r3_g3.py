"""(r3 g3) Hallway floors: placement sense and the record.

(a) the holy levels (worship, crypt: temple, tombs ...) never on the floors
    nearest the surface or with soil, and an elevation a floor was refused at
    for soil or roots ("not natural rock (ROOT)") remembered and not offered
    again for a while (brain/floor_soil.py, masterplan_floors.hint,
    masterplan.note_result);
(b) the floor hint actually sent journaled with the start_project
    (`floor_hint` on the decision line; planner_floors.journal_hint);
(c) the FLOORS digest line counts the classic placements by reason
    (lua/ai-builder-floorstore.lua floor_fallback's `why_n`,
    planner_floor_notes.floors_line).

    python tests/test_r3_g3.py
"""

from __future__ import annotations

import copy
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import finish, have_lua, make_test, skip  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import masterplan  # noqa: E402
import masterplan_floors as MF  # noqa: E402
import overseer  # noqa: E402
import planner_floor_notes as PFN  # noqa: E402
import planner_floors as PF  # noqa: E402
from planner import Memory  # noqa: E402
from planner_config import PLANNER_CONFIG  # noqa: E402
import test_overseer as T  # noqa: E402   (its fakes and its reset; its tests don't run here)

REAL_MF = MF
CFG = PLANNER_CONFIG
DAY = 1200
SITE = {"stairs": [{"x": 100, "y": 100, "z_top": 160, "z_bottom": 130, "elev_top": 60, "elev_bottom": 30,
                    "count": 8}],
        "citizen_elevation": 50, "soil": [58, 59], "elevation_offset": -100}
STATE = {"date": {"year": 150, "tick": 0, "day": 1, "month": "Granite"}, "dwarves": {"total": 40}}
TRAITS = {"verticality": 0, "spacing": 0, "grandeur": 0, "fortification": 0, "craftsmanship": 0}
PROFILE = {"layout": "grid", "palette": "dark", "temple": "shrine", "entry_doors": True}
ROOT_WHY = ("floor 3: refused: not natural rock (ROOT) at x107 y177 z39; floor 1: no room; "
            "z35: no hall: north 0, east 0, south 0, west 0")
_RECORD = overseer.record


def _before():
    T._before()
    sys.modules["masterplan_floors"] = REAL_MF
    overseer.record = _RECORD
    PF.LAST_SENT.clear()
    CFG["r3g3_journal_floor_hint"] = True
    CFG["r3g3_floor_reasons"] = True
    CFG["r3g3_soil_skip"] = True


test = make_test(before=_before)


def fort_memory(halls=None, soil=(58, 59)) -> Memory:
    """A plan drawn on the B11 test site (surface 60), its table made; the
    halls district moved to `halls` (lo, hi, target) when given."""
    m = Memory()
    m.culture = {"seed": "Test#1", "eras": [{"year": 150, "title": "Plain era"}]}
    m.atlas = {"survey": {"elevation_offset": -100, "tick": 1,
                          "layers": [{"name": "Cavern1", "z_top": 120, "z_bottom": 115, "discovered": True}],
                          "site": {"soil": list(soil)}},
               "entrances": {}}
    assert masterplan.draw(STATE, m, SITE, TRAITS, PROFILE) is not None
    if halls:
        for d in m.atlas["plan"]["districts"]:
            if d["kind"] == "halls":
                d["lo"], d["hi"], d["target"] = halls
    MF.ensure(m, TRAITS, PROFILE)
    return m


def at(day: int) -> dict:
    return {"date": {"year": 150, "tick": day * DAY, "day": 1, "month": "Granite"}}


def start(kind, **kw):
    return {"type": "start_project", "kind": kind, **kw}


def elevs(m, kind, s, cfg=CFG):
    h = MF.hint(m, start(kind), s, TRAITS, cfg)
    return h["elevs"] if isinstance(h, dict) else h


# --- (a) soil and roots -------------------------------------------------------------------

@test("(a) the builder's reasons read: the elevation each floor was refused at for soil or roots")
def _():
    import floor_soil as FS
    assert FS.soil_refusals(ROOT_WHY) == [(39, "x107 y177")]
    floors = {"list": [{"id": 4, "elevation": 41}, {"id": 3, "elevation": 39}]}
    assert FS.soil_refusals("floor 4: refused: not natural rock (SOIL)", floors) == [(41, "")]
    assert FS.soil_refusals("z37: refused: not natural rock (GRASS_DARK) at x9 y8 z37; floor 9: no room") == [(37, "x9 y8")]
    for why in ("floor 3: no room", "floor 2: refused: not natural rock (CONSTRUCTION) at x1 y1 z30",
                "floor 5: refused: the stair's hub", "z35: no hall: north 0", "", None, 7):
        assert FS.soil_refusals(why, floors) == [], why
    assert FS.soil_refusals("floor 8: refused: not natural rock (ROOT)", floors) == []   # no elevation known


@test("(a) masterplan.note_result keeps an elevation refused for roots in memory (not on a dry run)")
def _():
    m = fort_memory()
    s = dict(at(10), floors={"list": [{"id": 3, "elevation": 39}]})
    r = {"ok": True, "project_id": 9, "elevation": 30, "not_on_floor": ROOT_WHY}
    masterplan.note_result(m, start("storage"), r, s)
    book = m.atlas.get("floor_soil")
    assert isinstance(book, dict) and book.get("39", {}).get("tick") == 150 * 403200 + 10 * DAY, book
    assert book["39"]["n"] == 1 and book["39"]["at"] == "x107 y177"
    masterplan.note_result(m, start("storage"), r, at(11))
    assert book["39"]["n"] == 2
    m2 = fort_memory()
    masterplan.note_result(m2, start("storage", dry_run=True), r, s)
    assert "floor_soil" not in m2.atlas
    CFG["r3g3_soil_skip"] = False
    masterplan.note_result(m2, start("storage"), r, s)
    assert "floor_soil" not in m2.atlas


@test("(a) an elevation refused for roots is not offered again for r3g3_soil_days (any kind)")
def _():
    m = fort_memory()
    assert elevs(m, "bedrooms", at(1)) == [51, 49, 50]
    masterplan.note_result(m, start("bedrooms"), {"ok": True, "not_on_floor": "z51: refused: not natural rock (ROOT) at x1 y2 z51"}, at(1))
    assert elevs(m, "bedrooms", at(2)) == [49, 50]
    assert elevs(m, "bedrooms", at(1 + CFG["r3g3_soil_days"] + 1)) == [51, 49, 50]      # offered again later
    # nothing else left: the list as it was (never no floor at all for an ordinary level)
    for e in (49, 50):
        masterplan.note_result(m, start("bedrooms"), {"ok": True, "not_on_floor": f"z{e}: refused: not natural rock (SOIL)"}, at(3))
    assert elevs(m, "bedrooms", at(4)) == [51, 49, 50]
    # the switch off, or a bare config (the layout-B tests'): offered as before
    CFG["r3g3_soil_skip"] = False
    assert elevs(m, "bedrooms", at(2)) == [51, 49, 50]
    CFG["r3g3_soil_skip"] = True
    assert elevs(m, "bedrooms", at(2), {}) == [51, 49, 50]


@test("(a) temple and tombs: never near the surface or on soil; the floors taken out made up from under the band")
def _():
    m = fort_memory(halls=(56, 58, 57))          # the halls grown up under the surface (60), soil on 58-59
    assert m.atlas["plan"]["floors"]["roles"]["worship"]["elevs"] == [57, 58, 56]
    assert MF.hint(m, start("temple"), at(1), TRAITS, {})["elevs"] == [57, 58, 56]      # before: as the plan says
    assert elevs(m, "temple", at(1)) == [57, 56, 55]          # 58: soil, and within 3 of the surface
    assert m.atlas["plan"]["floors"]["roles"]["crypt"]["elevs"] == [58, 56, 57]
    assert elevs(m, "tombs", at(1)) == [56, 57, 55]
    assert elevs(m, "memorial", at(1)) == [57, 56, 55]
    # an ordinary kind on the same floors keeps them
    h = MF.hint(m, start("barracks"), at(1), TRAITS, CFG)
    assert 58 in h["elevs"], h
    # roots met on 57 a while ago: no holy level there for a year, though others may go again
    masterplan.note_result(m, start("storage"), {"ok": True, "not_on_floor": "z57: refused: not natural rock (ROOT) at x5 y5 z57"}, at(1))
    assert elevs(m, "temple", at(40)) == [56, 55, 54]
    assert 57 in MF.hint(m, start("barracks"), at(40), TRAITS, CFG)["elevs"]
    assert elevs(m, "temple", at(1 + 337)) == [57, 56, 55]


@test("(a) a holy level with only soil and the surface to go to: placed the classic way (False), not near the top")
def _():
    m = fort_memory(halls=(58, 59, 58), soil=(55, 56, 57, 58, 59))
    CFG_ = dict(CFG, r3g3_sacred_deeper=2)
    h = MF.hint(m, start("temple"), at(1), TRAITS, CFG_)
    assert h is False, h
    h = MF.hint(m, start("bedrooms"), at(1), TRAITS, CFG_)
    assert isinstance(h, dict), h


# --- (b) the hint journaled --------------------------------------------------------------

HINT = {"elevs": [12, 11, 13], "tag": "homes", "zone": "near", "spine": {"x": 96, "y": 101}, "gap": 1}


def stand_in(answer):
    mod = types.ModuleType("masterplan_floors")
    mod.hint = lambda memory, action, s, traits, cfg: answer
    sys.modules["masterplan_floors"] = mod


class FloorBridge(T.FakeBridge):
    def act(self, action):
        r = super().act(action)
        if action["type"] == "start_project":
            return {"ok": True, "project_id": 57, "kind": action["kind"], "elevation": 12,
                    "not_on_floor": "floor 3: no room"}
        return r


def young(**settings):
    b = FloorBridge()
    st = b._state
    st["mandates"] = []
    st["buildings"]["other"]["Bed"] = 20
    st["settings"]["mode"] = "autopilot"
    st["settings"].update(settings)
    return b


def cycle(b):
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    sent = [a for a in b.acted if a["type"] == "start_project"]
    journal = [e for e in T.entries("decision") if e["action"]["type"] == "start_project"]
    return sent, journal


@test("(b) the level's journal line carries the floor hint it was sent with; its action stays the proposal's")
def _():
    stand_in(HINT)
    sent, journal = cycle(young())
    assert len(sent) == 1 and sent[0]["floor"] == HINT, sent
    assert len(journal) == 1 and journal[0].get("floor_hint") == HINT, journal
    assert "floor" not in journal[0]["action"]
    others = [e for e in T.entries("decision") if e["action"]["type"] != "start_project"]
    assert all("floor_hint" not in e for e in others), others
    # False (classic on purpose) is journaled too
    _before()
    stand_in(False)
    sent, journal = cycle(young())
    assert sent[0]["floor"] is False and journal[0].get("floor_hint") is False, journal


@test("(b) no hint sent (None, the fort at classic, the switch off): no floor_hint on the line")
def _():
    for setup, settings in ((lambda: stand_in(None), {}), (lambda: stand_in(HINT), {"floor_layout": "classic"}),
                            (lambda: (stand_in(HINT), CFG.update(r3g3_journal_floor_hint=False)), {})):
        _before()
        setup()
        sent, journal = cycle(young(**settings))
        assert len(journal) == 1 and "floor_hint" not in journal[0], (settings, journal)
    # journal_hint takes the hint once; another action gets none
    _before()
    stand_in(HINT)
    a = start("bedrooms", rooms=4)
    PF.floor_action(a, {"settings": {}}, None)
    assert PF.journal_hint({"type": "work_order"}) == {}
    PF.floor_action(a, {"settings": {}}, None)
    assert PF.journal_hint(a) == {"floor_hint": HINT} and PF.journal_hint(a) == {}


# --- (c) the reasons counted --------------------------------------------------------------

LUA = B = W = TB = None
if have_lua():
    import test_builder as TB  # noqa: E402
    LUA, B, W = TB.LUA, TB.B, TB.W
    _env = LUA.execute(r"""
local src = ...
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-floorplan', 't', env))()
local real = R3G3_REAL_REQ or reqscript
R3G3_REAL_REQ = real
reqscript = function(name)
  if name == 'ai-floorplan' then return env end
  return real(name)
end
return env
""", (ROOT / "lua" / "ai-floorplan.lua").read_text(encoding="utf-8"))


@test("(c) floor_fallback tallies each classic placement's reasons; floors_report gives them as why_n")
def _():
    if TB is None:
        skip("needs the lupa package (pip install lupa)")
    TB._reset(False)
    B.util_module().report_end()
    B.now_tick = LUA.eval("function() return 5000 end")
    whys = ["floor 1: no room; floor 2: no room; z35: no hall: north 0, east 0, south 0, west 0",
            "floor 1: no room (too big for a run); floor 3: refused: the stair's hub",
            ROOT_WHY,
            "floor 2: full for homes; floor 4: refused: open to the sky"]
    for w in whys:
        B.floor_fallback("tombs", w, 40, LUA.table())
    rep = B.floors_report()
    n = {k: v for k, v in rep.why_n.items()}
    assert rep.fallbacks == 4, rep.fallbacks
    assert n == {"no_room": 2, "no_hall": 2, "too_big": 1, "hub": 1, "soil": 1, "full": 1, "other": 1}, n


@test("(c) the FLOORS line counts the classic placements by reason")
def _():
    s = {"floors": {"v": 1, "mode": "hallway", "count": 3, "rooms": 62, "hall_tiles": 648, "fallbacks": 54,
                    "why_n": {"no_room": 35, "no_hall": 31, "hub": 10, "soil": 23, "too_big": 2, "bogus": 3},
                    "list": [{"id": 1, "elevation": 40}, {"id": 2, "elevation": 41}, {"id": 3, "elevation": 39}]}}
    line = PFN.floors_line(s)
    assert ("classic placements 54 (no room 35, too big for a run 2, no hall 31, the stair's hub 10, "
            "soil or roots 23)") in line, line
    CFG["r3g3_floor_reasons"] = False
    assert "classic placements 54 |" in PFN.floors_line(s) + " |" and "(no room" not in PFN.floors_line(s)
    CFG["r3g3_floor_reasons"] = True
    s2 = copy.deepcopy(s)
    del s2["floors"]["why_n"]                              # an older record: as before
    assert PFN.floors_line(s2).endswith("classic placements 54"), PFN.floors_line(s2)


if __name__ == "__main__":
    finish()

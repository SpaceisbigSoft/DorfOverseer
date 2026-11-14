"""(0.105.46, plan item I5) Scorecard measurement: levers counted (every
built one and the AI's own), legendary by craft skills only, per-100-dwarves
lines where the forts' sizes differ (a collapsed fort marked), the SameBooze
count kept past the top 15 stresses, and lines flat at 0 explained.

    python tests/test_r1_scorecard_measure.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402

import scorecard  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def jc(ok=None, peak=None):
    j = scorecard.journal_counts([], {"year": 1, "tick": 0})
    if ok:
        j["ok"] = Counter(ok)
    j["peak_pop"] = peak
    return j


def state(**kw):
    s = copy.deepcopy(BASE)
    for k, v in kw.items():
        s[k] = v
    return s


# ------------------------------------------------------------------ levers and traps

@test("levers: the bridge's trap_kinds (a lever is a Trap building): every lever and the AI's own; traps leave levers out")
def _():
    s = state(buildings={"other": {"Trap": 9}, "zones": {},
                         "trap_kinds": {"Lever": 4, "CageTrap": 3, "TrackStop": 1, "PressurePlate": 1},
                         "ai_levers": 3})
    m = scorecard.measures(s, jc())
    assert (m["levers"], m["ai_levers"], m["traps"]) == (4, 3, 3), (m["levers"], m["ai_levers"], m["traps"])
    # a fort with no trap at all: Lua's empty table reaches Python as a list: still 0, not "no data"
    s["buildings"]["trap_kinds"], s["buildings"]["ai_levers"] = [], 0
    m = scorecard.measures(s, jc())
    assert (m["levers"], m["ai_levers"]) == (0, 0), (m["levers"], m["ai_levers"])


@test("levers: an older report (no trap_kinds) counts the levers the ways in are linked to (a lower bound)")
def _():
    ents = {"entrances": [
        {"id": 1, "equipment": [{"id": 50, "lever_driven": True,
                                 "levers": [{"id": 7, "name": "AI gate lever"}, {"id": 8, "name": "AI gate"}]},
                                {"id": 51, "levers": [{"id": 7, "name": "AI gate lever"}]}]},
        {"id": 2, "equipment": [{"id": 52, "levers": [{"id": 9, "name": ""}]}]}]}
    s = state(buildings={"other": {"Trap": 3}, "zones": {}}, entrances=ents)
    m = scorecard.measures(s, jc())
    assert (m["levers"], m["ai_levers"]) == (3, 1), (m["levers"], m["ai_levers"])   # "AI gate" is the player's
    assert m["lever_gates"] == 1, m["lever_gates"]
    s.pop("entrances")
    m = scorecard.measures(s, jc())
    assert m["levers"] is None and m["ai_levers"] is None, (m["levers"], m["ai_levers"])


@test("levers: the AI's lever names (AI gate lever, AI lure lever, AI moat, AI pump), never the player's 'AI gate'")
def _():
    for n in ("AI gate lever", "AI lure lever", "AI moat", "ai pump", "AI irrigation"):
        assert scorecard.ai_lever_name(n), n
    for n in ("AI gate", "ai gate", "", None, "Moat lever", "AIgate"):
        assert not scorecard.ai_lever_name(n), n


# ------------------------------------------------------------------ legendary

@test("legendary: craft skills only (the bridge's legendary_craft); no field is no data, not the old any-skill count")
def _():
    dw = dict(BASE["dwarves"], adults=40, legendary=30, legendary_craft=6)
    m = scorecard.measures(state(dwarves=dw), jc())
    assert m["legendary_pct"] == 15.0, m["legendary_pct"]
    dw.pop("legendary_craft")
    m = scorecard.measures(state(dwarves=dw), jc())
    assert m["legendary_pct"] is None, m["legendary_pct"]


# ------------------------------------------------------------------ the same booze

def booze(**sc):
    return state(needs=dict(BASE.get("needs") or {}, stress_causes=sc))


@test("same booze: the bridge's own count first; in the top list; not listed with a short list is 0; past a full list no data")
def _():
    m = scorecard.measures(booze(citizens=20, same_booze=5, causes=[]), jc())
    assert m["same_booze_pct"] == 25.0, m["same_booze_pct"]
    m = scorecard.measures(booze(citizens=20, causes=[{"thought": "SameBooze", "citizens": 2}]), jc())
    assert m["same_booze_pct"] == 10.0, m["same_booze_pct"]
    m = scorecard.measures(booze(citizens=20, causes=[{"thought": "Rain", "citizens": 2}]), jc())
    assert m["same_booze_pct"] == 0.0, m["same_booze_pct"]
    full = [{"thought": f"T{i}", "citizens": 1} for i in range(scorecard.STRESS_TOP)]
    m = scorecard.measures(booze(citizens=20, causes=full), jc())
    assert m["same_booze_pct"] is None, m["same_booze_pct"]


# ------------------------------------------------------------------ soil floors from the journal

@test("soil floors (journal): floor_rooms' `floors` is the tiles placed, not `tiles` (the bare soil counted)")
def _():
    e = {"kind": "decision", "date": {"year": 1, "tick": 10},
         "action": {"type": "floor_rooms", "project_id": 3},
         "result": {"ok": True, "floors": 12, "tiles": 40, "left": 28}}
    j = scorecard.journal_counts([e], {"year": 2, "tick": 0})
    assert j["soil_floored"] == 12, j["soil_floored"]


# ------------------------------------------------------------------ the fort's size

@test("peak: the most citizens of this run up to the date (the timeline), never under today's; rows after the date left out")
def _():
    e = {"kind": "decision", "date": {"year": 1, "tick": 0}, "action": {"type": "x"}, "result": {"ok": True}}
    tl = [(330, 90), (336, 100), (400, 1), (500, 28), (1000, 300)]     # day 1000: after the date
    j = scorecard.journal_counts([e], {"year": 2, "tick": 300 * 1200}, tl)
    assert j["peak_pop"] == 100, j["peak_pop"]                          # day 330 is before this run began
    m = scorecard.measures(state(dwarves=dict(BASE["dwarves"], total=28)), j)
    assert m["peak"] == 100 and scorecard.collapsed(m), (m["peak"], m["pop"])
    assert m["statues_pk"] == round(100.0 * m["statues"] / 100, 1)
    m = scorecard.measures(state(dwarves=dict(BASE["dwarves"], total=28)), jc())
    assert m["peak"] == 28 and not scorecard.collapsed(m)


@test("sizes: forts of near the same size get no per-peak lines; a peak twice another's or a collapse does")
def _():
    a, b = {"peak": 100, "pop": 95}, {"peak": 80, "pop": 70}
    assert not scorecard.sizes_differ([a, b])
    assert scorecard.sizes_differ([a, {"peak": 40, "pop": 40}])
    assert scorecard.sizes_differ([a, {"peak": 100, "pop": 28}])
    assert not scorecard.collapsed({"peak": 6, "pop": 1})          # a tiny fort is not a collapse
    keys = {k for _, _, k, _, _ in scorecard.PEAK_LINES}
    assert keys == {k + "_pk" for k in scorecard.PER_PEAK}, keys
    assert not keys & {k for _, _, k, _, _ in scorecard.LINES}


# ------------------------------------------------------------------ the report

def fort_dir(root: Path, label: str, preset: str, s: dict, timeline=None, journal=()) -> Path:
    d = root / label
    fd = d / "logs" / "forts" / "region1-1"
    (fd / "states").mkdir(parents=True)
    s = copy.deepcopy(s)
    s["settings"] = dict(s.get("settings") or {}, preset=preset)
    s["date"] = {"year": 252, "tick": 0, "season": "spring"}
    (fd / "states" / "252-spring.json").write_text(json.dumps(s), encoding="utf-8")
    if timeline:
        (fd / "timeline.csv").write_text("day,pop\n" + "".join(f"{a},{b}\n" for a, b in timeline), encoding="utf-8")
    (fd / "journal.jsonl").write_text("".join(json.dumps(e) + "\n" for e in journal), encoding="utf-8")
    return d


def report(forts):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fs = [scorecard.Fort(lb, fort_dir(root, lb, p, s, tl, jn)) for lb, p, s, tl, jn in forts]
        md, rows = scorecard.score(fs, None, True)
    return md, rows


def built(pop, statues):
    s = copy.deepcopy(BASE)
    s["dwarves"] = dict(s["dwarves"], total=pop, adults=pop)
    s["buildings"] = dict(s.get("buildings") or {}, other={"Statue": statues}, zones={},
                          trap_kinds={"Lever": 2}, ai_levers=1)
    return s


@test("report: a collapsed fort is marked and the per-100 lines appear; the levers line no longer reads 0 beside lever gates")
def _():
    start = {"kind": "decision", "date": {"year": 250, "tick": 0}, "action": {"type": "x"}, "result": {"ok": True}}
    md, rows = report([("A", "Monastery", built(100, 20), [(250 * 336, 100)], [start]),
                       ("B", "War-hold", built(28, 20), [(250 * 336, 100), (251 * 336, 1)], [start])])
    assert "B War (collapsed)" in md and "Fort B collapsed: 28 citizens now, 100 at the most" in md, md[:1500]
    st = next(r for r in rows if r["line"] == "statues per 100 dwarves (peak)")
    assert st["values"] == {"A": 20.0, "B": 20.0}, st
    lv = next(r for r in rows if r["line"] == "levers")
    assert lv["values"] == {"A": 2, "B": 2}, lv
    ai = next(r for r in rows if r["line"] == "the AI's levers")
    assert ai["values"] == {"A": 1, "B": 1}, ai
    # two forts of a size: no per-peak lines, no mark
    md, rows = report([("A", "Monastery", built(100, 20), None, []), ("B", "War-hold", built(90, 3), None, [])])
    assert "collapsed" not in md and not any(r["key"].endswith("_pk") for r in rows)
    assert len(rows) == len(scorecard.LINES)


@test("report: a line flat at 0 says whether the AI never did it or did it and the measure missed it")
def _():
    s = built(50, 1)
    s["constructions"] = {"total": 40, "surface": {"total": 0}, "roofed_surface_tiles": 0,
                          "by_item": {"blocks": 10}, "ai": {"gate_pieces": 0, "wings": 0, "cavern_walls": 0,
                                                            "soil_floors": 0}}
    wings = {"kind": "decision", "date": {"year": 251, "tick": 0}, "action": {"type": "build_wings"},
             "result": {"ok": True}}
    md, rows = report([("A", "War-hold", s, None, [wings]), ("B", "Hermit hold", s, None, []),
                       ("C", "Garden fort", s, None, [])])
    gw = next(r for r in rows if r["line"] == "gate walls and wings")
    assert gw["result"] == "flat", gw
    assert "Lines flat at 0 in every fort:" in md
    line = next(x for x in md.splitlines() if x.startswith("- Fortification, gate walls and wings"))
    assert "the measure misses it" in line and "A 1, B 0, C 0" in line, line
    cav = next(x for x in md.splitlines() if x.startswith("- Fortification, cavern openings walled"))
    assert "no fort's AI did it" in cav, cav
    assert any(x.startswith("- Agriculture, halls and kitchens by the fields") and "FIELD_TOP" in x
               for x in md.splitlines())


# ------------------------------------------------------------------ deaths (the combat-deaths investigation)

Y = 259 * 403200


def dec(t):
    return {"kind": "decision", "date": {"year": t // 403200, "tick": t % 403200},
            "action": {"type": "x"}, "result": {"ok": True}}


def death(uid, cause, t, **kw):
    ev = dict({"kind": "death", "own_civ": True, "unit_id": uid, "cause": cause,
               "year": t // 403200, "tick": t % 403200}, **kw)
    return {"kind": "event", "event": ev}


@test("deaths (C, 13 Nov): a reload's undone deaths dropped, each dwarf once, ghosts laid to rest skipped: "
      "STRUCK_DOWN 16 (not 18), COLLISION 0, DROWN 1")
def _():
    jn = [dec(Y + 100), death(200, "DROWN", Y + 150)]
    for i in range(14):                                         # 14 fallen in the fights before
        jn += [dec(Y + 1000 + 100 * i), death(i + 1, "STRUCK_DOWN", Y + 1050 + 100 * i)]
    jn += [dec(Y + 10000), death(101, "STRUCK_DOWN", Y + 10100), death(102, "STRUCK_DOWN", Y + 10200),
           death(103, "COLLISION", Y + 10300), dec(Y + 10400),
           dec(Y + 9000),                                       # the keeper's reload: back before the three
           dec(Y + 12000), death(101, "STRUCK_DOWN", Y + 12100),
           dec(Y + 13000), death(102, "STRUCK_DOWN", Y + 13100),
           dec(Y + 20000), death(200, "DROWN", Y + 20100, ghost=True),     # Bomrek's ghost put to rest
           death(200, "DROWN", Y + 20200),                      # told again after a restart (DEATHS_TOLD lost)
           death(300, "BLEED", Y + 20300, again=True, old_death=True)]
    j = scorecard.journal_counts(jn, {"year": 260, "tick": 0})
    d = dict(j["deaths"])
    assert d == {"STRUCK_DOWN": 16, "DROWN": 1}, d
    assert d.get("COLLISION", 0) == 0


@test("deaths: decisions in order (no reload) keep every death; a unit with no id is still counted each time")
def _():
    jn = [dec(Y), death(1, "BLEED", Y + 10), dec(Y + 20), death(None, "BLEED", Y + 30),
          death(None, "BLEED", Y + 40), dec(Y + 25)]                     # 5 ticks back: no reload
    d = dict(scorecard.journal_counts(jn, {"year": 260, "tick": 0})["deaths"])
    assert d == {"BLEED": 3}, d


# ------------------------------------------------------------------ the bridge (lupa)

if LuaRuntime is not None:
    HARNESS = re.search(r'HARNESS = r"""(.*?)"""',
                        (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8"), re.S).group(1)
    LUA = LuaRuntime(unpack_returned_tuples=True)
    H = LUA.execute(HARNESS, (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8"), str(LUA_DIR))

    DWARVES = r"""
    local env, H = ...
    local df = H.df
    local saved_js = df.job_skill
    df.job_skill = {[0] = 'MINING', [1] = 'STONECRAFT', [2] = 'AXE', [3] = 'DETAILSTONE', [4] = 'COOK'}
    local function unit(child, skills)
      local list = {}
      for i, s in ipairs(skills) do list[i] = {id = s[1], rating = s[2]} end
      return {job = {current_job = {}}, military = {squad_id = -1}, health = nil, child = child,
              social_activities = {}, status = {current_soul = {skills = list}}}
    end
    local list = {unit(false, {{0, 20}}), unit(false, {{1, 15}, {0, 20}}), unit(false, {{2, 18}, {4, 16}}),
                  unit(false, {{3, 15}}), unit(true, {{1, 15}}), unit(false, {{1, 14}})}
    local d = H.dfhack
    local saved = d.units
    d.units = {getCitizens = function() return list end, isChild = function(u) return u.child end,
               isBaby = function() return false end, getStressCategory = function() return 3 end,
               getProfessionName = function() return 'Miner' end}
    d.df2utf = function(s) return s end
    local s = env.get_dwarves(false)
    d.units = saved
    df.job_skill = saved_js
    return s.adults, s.legendary, s.legendary_craft
    """

    @test("bridge: get_dwarves counts adults legendary at a craft (stonecraft, engraving), not mining, axe or cooking")
    def _():
        r = LUA.execute(DWARVES, H.module(), H)
        # legendary at any skill: 4 adults and the child (5); at a craft: the stonecrafter and the engraver
        assert tuple(r) == (5, 5, 2), tuple(r)

    BUILDINGS = r"""
    local env, H = ...
    local df = H.df
    local saved = {bt = df.building_type, tt = df.trap_type, bs = df.global.world.buildings}
    df.building_type = {Trap = 1, Bridge = 2, Civzone = 3, Stockpile = 4, Workshop = 5, Furnace = 6,
                        [1] = 'Trap', [2] = 'Bridge'}
    df.trap_type = {Lever = 0, CageTrap = 1, [0] = 'Lever', [1] = 'CageTrap'}
    local function b(t, trap, name, stage)
      return {getType = function() return t end, trap_type = trap, name = name, jobs = {},
              getBuildStage = function() return stage or 1 end, getMaxBuildStage = function() return 1 end}
    end
    df.global.world.buildings = {}
    df.global.world.buildings.all = {b(1, 0, 'AI gate lever'), b(1, 0, 'AI gate'), b(1, 0, ''),
                                     b(1, 0, 'AI moat', 0), b(1, 1, ''), b(2, nil, '')}
    local r = env.get_buildings()
    df.building_type, df.trap_type, df.global.world.buildings = saved.bt, saved.tt, saved.bs
    return r.other.Trap, r.trap_kinds.Lever, r.trap_kinds.CageTrap, r.ai_levers, r.other.Bridge, r.under_construction
    """

    @test("bridge: get_buildings counts traps by kind and the AI's built levers (not the player's 'AI gate', not unbuilt)")
    def _():
        r = LUA.execute(BUILDINGS, H.module(), H)
        assert tuple(r) == (4, 3, 1, 1, 1, 1), tuple(r)

    from lua_modules_util import module_src  # noqa: E402
    FAKE = re.search(r'FAKE = r"""(.*?)"""', (ROOT / "tests" / "test_society.py").read_text(encoding="utf-8"),
                     re.S).group(1)

    @test("bridge: the stress census keeps the same-booze count when it falls off the top-15 list")
    def _():
        env, *_ = LuaRuntime(unpack_returned_tuples=True).execute(FAKE, module_src("ai-society.lua"))
        snippet = """
          local env = ...
          env.df.global.cur_year, env.df.global.cur_year_tick = 92, 200000
          local names = {[1] = 'SameBooze'}
          for i = 2, 20 do names[i] = 'T' .. i end
          env.df.unit_thought_type = names
          env.df.emotion_type = {[10] = 'HORROR', attrs = {[10] = {divider = 1}}}
          local function em(th, str) return {thought = th, type = 10, strength = str, year = 92, year_tick = 199000} end
          local function soul(list) return {status = {current_soul = {personality = {emotions = list}}}} end
          local big = {}
          for i = 2, 20 do big[#big + 1] = em(i, 100) end
          STRESS_UNITS = {soul(big), soul({em(1, 1)}), soul({em(1, 1)})}
        """
        env["load"](snippet, "t", "t", env)(env)
        c = env.stress_census(env.STRESS_UNITS)
        names = [x.thought for x in c.causes.values()]
        assert "SameBooze" not in names and len(names) == 15, names
        assert c.same_booze == 2 and c.citizens == 3, (c.same_booze, c.citizens)


if __name__ == "__main__":
    finish()

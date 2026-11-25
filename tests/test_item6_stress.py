"""(item6) Fort B's stress: why the needs most dwarves miss stay unmet.

Fort B "Monastery", 24 Nov 22:20-22:30 (live reads and probes i6-needs,
i6-idle, i6-stress): 36 citizens, 15 unhappy or worse; BeWithFriends badly
missed by 30 while Socialize only by 2 (they talk, seldom to a friend);
15 locations (3 taverns, 5 temples, 2 guildhalls, a library, 4 hospitals);
the idle dwarves' idle areas spread over 12 of them and the mayor's office;
the recreation burrow's 7 members idled in 7 different ones (the burrow held
every location and meeting hall). Its one fruit zone kept 125 GatherPlants
jobs waiting at 403 food a dwarf (gather_trim: "nothing to cancel" every
cycle), and its 2-3 gatherers, the tavern keeper among them, were never idle
(TakeItEasy 11,000-23,000 below).

1. The recreation burrow holds one tavern (a keeper, goblets and
   instruments first) and one temple (to all gods first), so its members
   meet one another (lua/ai-society-burrows.lua rec_gathering).
2. The AI's fruit zones paused while food is plentiful and gathering jobs
   pile up, set going again when food runs low (planner_provisions
   _fruit_pause_rule; the Lua in tests/test_provisions.py).

    python tests/test_item6_stress.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src, split_src  # noqa: E402

from planner import Memory, PLANNER_CONFIG as CFG  # noqa: E402
from planner_core import Proposal  # noqa: E402
import planner_provisions as PP  # noqa: E402
import planner_guards  # noqa: E402
import overseer_words  # noqa: E402
import hold_classes  # noqa: E402
import digest  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def lua_env(name):
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    env = L.execute("""
local src = ...
local env = setmetatable({df = {global = {world = {buildings = {all = {}}}}},
  dfhack = {onStateChange = {}, burrows = {}},
  xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end,
  reqscript = function(n) return {} end}, {__index = _G})
assert(load(src, 'mod', 't', env))()
return env
""", module_src(name))
    return L, env


# ---- 1. the recreation burrow's one tavern and one temple -----------------------------------

# B's locations (state.json locations.list, 24 Nov 22:22): taverns 1 (no keeper; goblets,
# instruments), 6 (keeper; nothing) and 10 (keeper, 10 goblets, 5 instruments); temples 0 and
# 2 to all gods (values 1254, 7853), 5, 8 and 11 to one god each (8187, 9697, 7758)
B_LOCS = [
    {"id": 0, "kind": "TEMPLE", "value": 1254, "any_deity": True},
    {"id": 1, "kind": "INN_TAVERN", "value": 910, "goblets": 10, "instruments": 5},
    {"id": 2, "kind": "TEMPLE", "value": 7853, "any_deity": True},
    {"id": 3, "kind": "HOSPITAL", "value": 236},
    {"id": 4, "kind": "LIBRARY", "value": 22},
    {"id": 5, "kind": "TEMPLE", "value": 8187},
    {"id": 6, "kind": "INN_TAVERN", "value": 683, "keeper": True},
    {"id": 7, "kind": "GUILDHALL", "value": 12681},
    {"id": 8, "kind": "TEMPLE", "value": 9697},
    {"id": 10, "kind": "INN_TAVERN", "value": 553, "keeper": True, "goblets": 10, "instruments": 5},
    {"id": 11, "kind": "TEMPLE", "value": 7758},
]


@test("1: rec_gathering picks B's tavern 10 (keeper, goblets, instruments) and its best temple to all gods (2)")
def _():
    need_lua()
    L, env = lua_env("ai-society-burrows.lua")
    t = lambda v: L.table_from([L.table_from(e) for e in v])  # noqa: E731
    tav, tem = env.rec_gathering(t(B_LOCS))
    assert (tav, tem) == (10, 2), (tav, tem)
    # no temple to all gods: the most valuable one
    tav, tem = env.rec_gathering(t([e for e in B_LOCS if not e.get("any_deity")]))
    assert (tav, tem) == (10, 8), (tav, tem)
    # equal taverns: the more valuable, then the lower id
    two = [{"id": 4, "kind": "INN_TAVERN", "value": 5}, {"id": 3, "kind": "INN_TAVERN", "value": 5},
           {"id": 9, "kind": "INN_TAVERN", "value": 1}]
    assert env.rec_gathering(t(two))[0] == 3
    # no tavern: nil (the burrow keeps every location, as before)
    tav, tem = env.rec_gathering(t([e for e in B_LOCS if e["kind"] != "INN_TAVERN"]))
    assert tav is None and tem == 2, (tav, tem)
    assert env.rec_gathering(L.table_from([]))[0] is None


@test("1: fill_recreation keeps the chosen tavern's and temple's zones (and the hospital's out), plain meeting "
      "halls only without a tavern; a burrow filled by the older rule is filled again; the status says where")
def _():
    src = split_src("ai-society-burrows.lua")
    body = src[src.index("function fill_recreation(burrow)"):]
    body = body[:body.index("\nend\n")]
    assert "rec_gathering(locs)" in body, body
    assert "e.kind == 'HOSPITAL' or not tav or e.id == tav or e.id == tem" in body
    assert "(kind ~= 'MeetingHall' or not tav)" in body
    assert "tav and {tavern = tav, temple = tem} or nil" in body
    tick = src[src.index("function recreation_tick("):]
    assert "d.fill_v ~= REC_FILL_V" in tick and "d.fill_v, d.gathering = REC_FILL_V, place" in tick
    status = src[src.index("function recreation_status("):]
    status = status[:status.index("\nend\n")]
    assert "out.gathering = d.gathering" in status


# ---- 2. the fruit zones paused while food is plentiful --------------------------------------

def fort(fruit=None, gather_jobs=125, citizens=30, meals=None) -> dict:
    s = copy.deepcopy(BASE)
    s["provisions"] = {"fruit": {"zones": 1, "ai_zones": 1, "trees": 108, "paused": 0, **(fruit or {})}}
    s["dwarves"]["total"] = citizens
    s["jobs"] = {"by_type": {"GatherPlants": gather_jobs}, "total": gather_jobs + 10}
    s["labor"] = {"jobs": {"gathering": {"doing": 0, "candidates": 5, "mode": "OnlySelectedDoesThis"}}}
    if meals is not None:
        for k in ("prepared_meals", "meat", "plants", "fish", "raw_fish"):
            s["stocks"][k] = 0
        s["stocks"]["prepared_meals"] = meals
    return digest.normalize(s)


def run(s):
    props, notes = [], []
    PP._provisions_rules(s, CFG, int(s["dwarves"]["total"]), props, notes, Memory())
    return props


def rules(props):
    return {p.rule: p for p in props}


@test("2: food to spare and 125 fruit-zone jobs waiting: the AI's zone paused (not a picker put on it)")
def _():
    r = rules(run(fort()))
    assert "fruit_pause" in r and r["fruit_pause"].action == {"type": "fruit_zone", "pause": True}, r
    assert "fruit_pickers" not in r and "fruit_resume" not in r
    assert "125 plant-gathering jobs" in r["fruit_pause"].reason


@test("2: no pause with few jobs waiting, food under the line, drink short, or no zone of the AI's")
def _():
    assert "fruit_pause" not in rules(run(fort(gather_jobs=CFG["gather_jobs_max"])))
    assert "fruit_pause" not in rules(run(fort(meals=30 * (CFG["fruit_pause_food_pd"] - 1))))
    s = fort()
    s["stocks"]["drink"] = 0
    s.setdefault("supplies", {}).update({"brewable_plants": 0, "brewable_growths": 0})
    assert "fruit_pause" not in rules(run(s))
    assert "fruit_pause" not in rules(run(fort(fruit={"ai_zones": 0})))


@test("2: paused: set going again under the resume line or when drink runs short; else left (no picker)")
def _():
    r = rules(run(fort(fruit={"paused": 1}, meals=30 * (CFG["fruit_resume_food_pd"] - 1))))
    assert "fruit_resume" in r and r["fruit_resume"].action == {"type": "fruit_zone", "pause": False}, r
    r = rules(run(fort(fruit={"paused": 1})))
    assert not ({"fruit_resume", "fruit_pause", "fruit_pickers"} & set(r)), r
    s = fort(fruit={"paused": 1})
    s["stocks"]["drink"] = 0
    s.setdefault("supplies", {}).update({"brewable_plants": 0, "brewable_growths": 0})
    assert "fruit_resume" in rules(run(s))


@test("2: pausing is no outdoor work (never held for danger); resuming is; words, classes and config")
def _():
    pause = Proposal("fruit_pause", {"type": "fruit_zone", "pause": True}, "", 5)
    resume = Proposal("fruit_resume", {"type": "fruit_zone", "pause": False}, "", 4)
    assert not planner_guards.is_outdoor(pause) and planner_guards.is_outdoor(resume)
    assert "pause" in overseer_words.short(pause.action) and "again" in overseer_words.short(resume.action)
    assert overseer_words.short({"type": "fruit_zone", "min_trees": 3}).startswith("mark the fruit trees")
    for rule in ("fruit_pause", "fruit_resume"):
        assert hold_classes.rule_class(rule) == hold_classes.SURVIVAL, rule
        assert f"{rule}_cooldown_ticks" in CFG
    assert CFG["fruit_resume_food_pd"] < CFG["fruit_pause_food_pd"]


finish()

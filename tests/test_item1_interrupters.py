"""(item1, 14 Nov) The thirst trap: B lost 66 citizens to thirst on 13 Nov
(17:05-17:45, y259 Obsidian - y260 Slate) with 845 drinks in store. DF's
gamelog: "X cancels Drink: Interrupted by a human spearman." ~4900 times;
the spearman (a visitor beaten in the squad's fight with a thief) was no
invader and not isDanger, so the AI saw no threat and sent nobody.

Tested here: lua/ai-threats.lua reads the job cancellations and names the
unit (pure parts and over a fake game), ai-military's kill_target_ok takes
it as a target, and the planner (brain/planner_threats.py _interrupters)
sends a squad, never at a merchant or diplomat, keeps it on (no "no more
threats" recall), and says why Drink jobs were dropped when dwarves are
parched.

    python tests/test_item1_interrupters.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from lua_modules_util import module_src  # noqa: E402
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

from planner import Memory, plan  # noqa: E402
from planner_core import NEEDS_YOU  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))

SPEARMAN = {"id": 9001, "name": "Om Konlihiñer \"Oilbaked\", Human Spearman", "who": "human spearman",
            "cancels": 120, "drink": 100, "eat": 15, "sleep": 5, "dwarves": 40, "near": 110,
            "pos": {"x": 115, "y": 150, "z": 142}, "inside": True, "can_reach_dwarves": True,
            "visitor": True, "kill_ok": True}


def fort(inter: dict, squads=None, parched=0) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["threats"] = {"interrupters": inter}
    s.setdefault("society", {})["parched"] = parched
    s["military"]["squads"] = squads if squads is not None else [{"id": 3, "members": 6, "name": "Axes"}]
    return s


def kills(props):
    return [p for p in props if p.rule == "squad_attack" and p.action.get("type") == "squad_orders"]


@test("planner: a unit keeping the dwarves from drink gets the squad (B, 13 Nov: the human spearman)")
def _():
    s = fort({"list": [dict(SPEARMAN)], "window_days": 2})
    props, notes = plan(s, Memory())
    k = [p for p in kills(props) if 9001 in p.action.get("kill", [])]
    assert k and k[0].action["squad_id"] == 3, (k, notes)
    assert "drink" in k[0].reason and "Om Konlihi" in k[0].reason, k[0].reason


@test("planner: a merchant or diplomat is never attacked, a caged one never; said instead")
def _():
    for flag in ("merchant", "diplomat"):
        row = dict(SPEARMAN, **{flag: True})
        props, notes = plan(fort({"list": [row]}), Memory())
        assert not [p for p in kills(props) if 9001 in p.action.get("kill", [])], props
        assert any("not attacked" in n for n in notes), notes
    props, notes = plan(fort({"list": [dict(SPEARMAN, caged=True)]}), Memory())
    assert not [p for p in kills(props) if 9001 in p.action.get("kill", [])]
    assert any("caged or chained" in n for n in notes), notes
    # the bridge's own check refused it (kill_ok false): no order the game would refuse
    props, _ = plan(fort({"list": [dict(SPEARMAN, kill_ok=False)]}), Memory())
    assert not [p for p in kills(props) if 9001 in p.action.get("kill", [])]


@test("planner: a squad already on it stays on it (no 'no more threats' recall); none at all: Needs you")
def _():
    sq = [{"id": 3, "members": 6, "name": "Axes", "ai_orders": True, "kill_ids": [9001]}]
    props, notes = plan(fort({"list": [dict(SPEARMAN)]}, squads=sq), Memory())
    assert not [p for p in props if p.rule == "squad_recall" and p.action.get("squad_id") == 3], props
    assert any("is after them" in n for n in notes), notes
    props, notes = plan(fort({"list": [dict(SPEARMAN)]}, squads=[]), Memory())
    assert any(n.startswith(NEEDS_YOU) and "no squad" in n for n in notes), notes


@test("planner: parched dwarves: why their Drink jobs were dropped is said")
def _():
    inter = {"list": [], "window_days": 2,
             "reasons": {"drink": [{"why": "Interrupted by a human spearman", "n": 300}],
                         "eat": [{"why": "Interrupted by a human spearman", "n": 40}]}}
    _, notes = plan(fort(inter, parched=14), Memory())
    assert any("14 parched" in n and "Drink jobs dropped: Interrupted by a human spearman x300" in n
               for n in notes), notes
    _, notes = plan(fort(inter, parched=0), Memory())
    assert not any("Drink jobs dropped" in n for n in notes)


try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

if LuaRuntime:
    LUA = LuaRuntime(unpack_returned_tuples=True)
    SRC = module_src("ai-threats.lua")

    GAME = r"""
local src = ...
local G = {units = {}, reports = {}}
local e = setmetatable({G = G}, {__index = _G})
local function vec(t) return setmetatable(t, {__len = function(v) local n = 0
    while rawget(v, n) ~= nil do n = n + 1 end return n end}) end
G.reports = vec({})
G.active = {}
e.ipairs = function(t)
    if getmetatable(t) then return function(v, i) i = i + 1; if rawget(v, i) ~= nil then return i, v[i] end end, t, -1 end
    return ipairs(t)
end
e.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
e.df = {global = {cur_year = 260, cur_year_tick = 5000,
                  world = {status = {reports = G.reports}, units = {active = G.active},
                           raws = {creatures = {all = {[1] = {name = {[0] = 'human'}}, [2] = {name = {[0] = 'dwarf'}}}}}}},
        unit = {find = function(id) return G.units[id] end}}
local function has(k) return function(u) return u[k] == true end end
e.dfhack = {persistent = {getSiteData = function(k, d) return d end, saveSiteData = function() end},
            units = {isActive = function() return true end, isDead = function() return false end,
                     isCitizen = has('citizen'), isHidden = function() return false end,
                     isVisitor = has('visitor'), isMerchant = has('merchant'), isDiplomat = has('diplomat'),
                     isInvader = has('invader'), isDanger = has('danger'),
                     getReadableName = function(u) return u.name end,
                     getProfessionName = function(u) return u.prof end,
                     getCitizens = function() local l = {} for _, u in ipairs(G.active) do
                         if u.citizen then l[#l + 1] = u end end return l end},
            maps = {getTileFlags = function() return {outside = false} end,
                    getWalkableGroup = function() return 1 end}}
e.reqscript = function(name) error('no ' .. name) end
assert(load(src, 'ai-threats', 't', e))()
function e.add_unit(u) G.units[u.id] = u; G.active[#G.active + 1] = u end
function e.add_report(text, tick, x, y, z, rep, cont)
    local n = #G.reports
    G.reports[n] = {text = text, year = 260, time = tick, flags = {continuation = cont == true},
                    pos = {x = x or -30000, y = y or 0, z = z or 0}, repeat_count = rep or 0}
end
return e
"""

    @test("lua: a cancellation parsed; the interrupter's phrase; a unit's phrases")
    def _():
        E = LUA.execute("local src = ...; local e = setmetatable({}, {__index = _G}); "
                        "assert(load(src, 'ai-threats', 't', e))(); return e", SRC)
        who, job, why = E.parse_cancel("Mûthkat Arzesthob, Surgeon cancels Drink: Interrupted by a human spearman.")
        assert (job, why) == ("Drink", "Interrupted by a human spearman") and who.endswith("Surgeon"), (who, job, why)
        assert E.parse_cancel("Make cheese (1) has been completed.") is None
        assert E.interrupter_of("Interrupted by a human spearman") == "human spearman"
        assert E.interrupter_of("Interrupted by an elf") == "elf"
        assert E.interrupter_of("Interrupted by combat") is None
        assert E.interrupter_of("Needs orthoclase") is None
        ph = list(E.unit_phrases("Human", "Spearman").values())
        assert ph == ["spearman", "human spearman", "human"], ph

    @test("lua: the tally and the blocking unit: of two human spearmen, the one by the dwarves (B, 13 Nov)")
    def _():
        E = LUA.execute("local src = ...; local e = setmetatable({}, {__index = _G}); "
                        "assert(load(src, 'ai-threats', 't', e))(); return e", SRC)
        rows = LUA.table_from([LUA.table_from({"text": f"Dwarf{i % 5}, Stonecrafter cancels "
                                                       f"{'Drink' if i % 3 else 'Eat'}: Interrupted by a human spearman.",
                                               "tick": 1000 + i, "x": 114 + i % 3, "y": 149, "z": 142, "n": 1})
                               for i in range(12)]
                              + [LUA.table_from({"text": "Urist, Miner cancels Dig: Needs pick.", "tick": 1000,
                                                 "n": 1}),
                                 LUA.table_from({"text": "Old, Miner cancels Drink: Interrupted by a human spearman.",
                                                 "tick": 1, "x": 114, "y": 149, "z": 142})])
        tl = E.tally_cancels(rows, 1100, 1000)
        w = tl.by_who["human spearman"]
        assert w.n == 12 and w.drink == 8 and w.eat == 4 and w.dwarves == 5, (w.n, w.drink, w.eat, w.dwarves)
        assert tl.reasons.Drink["Interrupted by a human spearman"] == 8
        cands = LUA.table_from([
            LUA.table_from({"id": 1, "x": 115, "y": 150, "z": 142, "phrases": E.unit_phrases("human", "Spearman")}),
            LUA.table_from({"id": 2, "x": 20, "y": 20, "z": 170, "phrases": E.unit_phrases("human", "Spearman")}),
            LUA.table_from({"id": 3, "x": 115, "y": 150, "z": 142, "phrases": E.unit_phrases("human", "Poet")})])
        b = E.blocking_units(tl, cands, None)
        assert b[1] is not None and b[2] is None and b[3] is None, [k for k in b.keys()]
        assert b[1].drink == 8 and b[1].who == "human spearman"
        # reports without places: the spearman with the dwarves about him, not the one far off
        nopos = LUA.table_from([LUA.table_from({"text": f"Dwarf{i % 5}, Stonecrafter cancels Drink: "
                                                        "Interrupted by a human spearman.", "tick": 1000 + i})
                                for i in range(12)])
        tn = E.tally_cancels(nopos, 1100, 1000)
        cit = LUA.table_from([LUA.table_from({"x": 114 + i, "y": 149, "z": 142}) for i in range(4)])
        b = E.blocking_units(tn, cands, None, cit)
        assert b[1] is not None and b[2] is None, [k for k in b.keys()]
        assert len(list(E.blocking_units(tn, cands, None, LUA.table_from([])).keys())) == 0   # two alike, nobody by
        # a few cancellations only: nobody is blocked
        few = E.tally_cancels(LUA.table_from(list(rows.values())[:3]), 1100, 1000)
        assert len(list(E.blocking_units(few, cands, None).keys())) == 0

    @test("lua: over a fake game: the report names the spearman, interrupting() says so, old reports drop out")
    def _():
        E = LUA.execute(GAME, SRC)
        E.add_unit(LUA.table_from({"id": 10, "name": "Urist", "citizen": True, "race": 2, "prof": "Stonecrafter",
                                   "pos": LUA.table_from({"x": 116, "y": 149, "z": 142}),
                                   "flags1": LUA.table_from({})}))
        E.add_unit(LUA.table_from({"id": 9001, "name": "Om", "visitor": True, "race": 1, "prof": "Spearman",
                                   "pos": LUA.table_from({"x": 115, "y": 150, "z": 142}),
                                   "flags1": LUA.table_from({})}))
        E.add_unit(LUA.table_from({"id": 9002, "name": "Uthra", "visitor": True, "race": 1, "prof": "Spearman",
                                   "pos": LUA.table_from({"x": 30, "y": 30, "z": 170}),
                                   "flags1": LUA.table_from({})}))
        for i in range(10):
            E.add_report(f"Dwarf{i % 4}, Stonecrafter cancels Drink: Interrupted by a human spearman.",
                         4000 + i * 10, 113 + i % 5, 149, 142, 0)
        E.add_report("Dwarf9, Miner cancels Dig: Needs pick.", 4990)
        # a long line split in two reports (flags.continuation): put together
        E.add_report("Mûthkat Arzesthob, Surgeon cancels Drink: Interrupted by", 4995, 115, 149, 142, 0)
        E.add_report("a human spearman.", 4995, 115, 149, 142, 0, True)
        r = E.interrupters_report(LUA.table_from([]), LUA.table_from({}), None)
        ids = [r.list[i].id for i in range(1, len(r.list) + 1)]
        assert ids == [9001], ids
        assert r.list[1].drink == 11 and r.list[1].visitor is True and r.list[1].kill_ok is None   # no ai-military here
        assert r.reasons.drink[1].why == "Interrupted by a human spearman" and r.reasons.drink[1].n == 11
        assert E.interrupting(E.G.units[9001]) is True and E.interrupting(E.G.units[9002]) is False
        # old reports (outside the window) don't count: the game a month on
        LUA.execute("local E = ...; E.df.global.cur_year_tick = 5000 + 30 * 1200", E)
        r = E.interrupters_report(LUA.table_from([]), LUA.table_from({}), None)
        assert len(r.list) == 0 and E.interrupting(E.G.units[9001]) is False

    @test("lua: ai-military's kill_target_ok takes a unit ai-threats names as interrupting, never a merchant")
    def _():
        M = LUA.execute(r"""
        local src = ...
        local env = setmetatable({}, {__index = _G})
        env.BLOCK = {}
        env.reqscript = function(name)
            if name == 'ai-threats' then return {interrupting = function(u) return env.BLOCK[u.id] == true end} end
            error('no ' .. name)
        end
        assert(load(src, 'ai-military', 't', env))()
        env.df = {mood_type = {Berserk = 7}}
        local function has(k) return function(u) return u[k] == true end end
        env.dfhack = {units = {isMerchant = has('merchant'), isDiplomat = has('diplomat'), isTame = has('tame'),
            isCitizen = has('citizen'), isDanger = has('danger'), isInvader = has('invader')}}
        return env
        """, module_src("ai-military.lua"))
        ok = M.kill_target_ok
        t = lambda **kw: LUA.table_from(kw)
        assert not ok(t(id=5))                      # a peaceful visitor
        LUA.execute("local M = ...; M.BLOCK[5] = true; M.BLOCK[6] = true; M.BLOCK[7] = true", M)
        assert ok(t(id=5))                          # the visitor keeping them from drink
        assert not ok(t(id=6, merchant=True)) and not ok(t(id=7, citizen=True))

    @test("lua: the threats survey carries the interrupters part")
    def _():
        src = (ROOT / "lua" / "ai-threats.lua").read_text(encoding="utf-8")
        assert "part('interrupters', interrupters_report, cit, groups, txt)" in src


if __name__ == "__main__":
    finish()

"""0.105.48 K1 part b: squad orders (audits A6 #1, #5, #6, #7, #8; A9 #2).

- the station (move) order is made with DF 53.17's own fields (pos and
  point_id; squad_order_movest has no title) and known as the AI's by its
  site mark and tile: run in a fake fort whose move order refuses any other
  field, as DFHack does;
- one order per squad per cycle in select(): the highest priority wins, kill
  orders on one squad merge, a squad list loses the squads taken;
- the defence's "no more threats" recall leaves a hunting squad and a squad
  sent at a vampire alone;
- `attack_policy = all` still calls a fight off on its losses;
- squad_recall is outside the per-cycle action limit.

    python tests/test_k48_squad_orders.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

from planner import Memory, PLANNER_CONFIG, plan, select  # noqa: E402
from planner_core import LIMIT_EXEMPT, Proposal, abs_tick  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime  # noqa: F401
except ImportError:
    LuaRuntime = None

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
DAY = 1200


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    return s


def by_rule(props, rule):
    return [p for p in props if p.rule == rule]


# --- 1. the station order in a fake DF (lua/ai-military.lua station) ------------------------------

STRICT_MOVE = r"""local env = ...
    env.fort_squad = function(id) return env.df.squad.find(id) end
    -- DF 53.17's squad_order_movest: the base order's fields, pos and point_id.
    -- Like DFHack, reading or writing any other field raises (the fakes'
    -- own markers, '_'..., read as nil)
    local FIELDS = {pos = true, point_id = true, year = true, year_tick = true, issuer_hf = true,
                    recipient_hf = true, origin_army_controller = true, flags = true}
    env.MADE = 0
    local function movest(x, y, z)
        local o = {pos = {x = x or 0, y = y or 0, z = z or 0}, point_id = 0}
        local proxy = {}
        return setmetatable(proxy, {
            __index = function(_, k)
                if k == 'delete' then return function() end end
                if k == '_move' then return true end
                if type(k) == 'string' and k:sub(1, 1) == '_' then return nil end
                if FIELDS[k] then return o[k] end
                error('Cannot read field squad_order_movest.' .. tostring(k) .. ': not found.')
            end,
            __newindex = function(_, k, v)
                if FIELDS[k] then o[k] = v; return end
                error('Cannot write field squad_order_movest.' .. tostring(k) .. ': not found.')
            end})
    end
    env.MOVEST = movest
    env.df.squad_order_movest = {new = function() env.MADE = env.MADE + 1; return movest() end,
                                 is_instance = function(_, o) return type(o) == 'table' and o._move == true end}
    env.df.global.cur_year = 260
    env.df.global.cur_year_tick = 1000
    env.df.tiletype = {attrs = setmetatable({}, {__index = function() return {shape = 1} end})}
    env.df.tiletype_shape = {[1] = 'FLOOR'}
    env.dfhack.maps.getTileType = function() return 5 end
    env.dfhack.maps.getWalkableGroup = function() return 3 end
"""


def station_env():
    import test_military as TM
    lua, n, env, eq, sq7, sq8 = TM.army()
    lua.execute(STRICT_MOVE, env)
    return lua, n, env, sq7


@test("station: the move order is made with DF's own fields only (pos, point_id -1), no title, and is the AI's")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    lua, n, env, sq7 = station_env()
    r = env.station(7, 10, 20, 100, False)
    assert r.ok, dict(r)                       # before: 'could not make a station order: ... title'
    assert n(sq7.orders) == 1
    o = sq7.orders[0]
    assert (o.pos.x, o.pos.y, o.pos.z, o.point_id) == (10, 20, 100, -1)
    assert o.year == 260 and o.year_tick == 1000
    st = env.station_of(o, 7)
    assert st is not None and (st.x, st.y, st.z) == (10, 20, 100)
    assert env.ai_order(o, 7) is True          # known as the AI's by its mark and tile
    assert env.order_sig(o) == "move:10,20,100"
    again = env.station(7, 10, 20, 100, False)
    assert not again.ok and "stands there already" in again.error, dict(again)
    # moved elsewhere: the AI's own station order is replaced, not called the player's
    moved = env.station(7, 11, 20, 100, False)
    assert moved.ok and moved.replaced == 1 and n(sq7.orders) == 1, dict(moved)
    assert env.MADE == 2                       # the refused repeat made nothing


@test("station: a dry run makes nothing; the recall clears the order and its mark; a player's move order is theirs")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    lua, n, env, sq7 = station_env()
    d = env.station(7, 10, 20, 100, True)
    assert d.ok and d.dry_run and n(sq7.orders) == 0 and env.MADE == 0, dict(d)
    assert env.station(7, 10, 20, 100, False).ok
    c = env.orders(7, None, True)
    assert c.ok and c.cleared == 1 and n(sq7.orders) == 0, dict(c)
    assert lua.eval("function(env) return env.station_marks()['7'] end")(env) is None
    # the player's own move order (no mark, or another tile): never the AI's
    lua.execute("local env = ...; env.df.squad.find(7).orders:insert('#', env.MOVEST(10, 20, 100))", env)
    assert env.ai_order(sq7.orders[0], 7) is False
    r = env.station(7, 12, 20, 100, False)
    assert not r.ok and "on your orders" in r.error, dict(r)
    assert n(sq7.orders) == 1


@test("station: the military report shows the stationed squad as the AI's (sheltering, stationed)")
def _():
    src = (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8")
    body = src[src.index("function station(squad_id"):src.index("-- --- the gear")]
    assert "title" not in body.split("local made")[1].split("sq.orders:insert")[0], "a title on the move order"
    sof = src[src.index("function station_of(o, squad_id)"):src.index("function station(squad_id")]
    assert "o.title" not in sof


# --- 2. one order per squad per cycle (select) --------------------------------------------------

def kill(rule, sq, ids, pri):
    return Proposal(rule, {"type": "squad_orders", "squad_id": sq, "kill": ids}, f"{rule} at {ids}", pri)


@test("select: four rules at one squad and no other free -> one order, the highest priority's, with every "
      "target merged into it")
def _():
    s = fort()
    s["military"]["squads"] = []          # (0.105.48, K16) no other squad free
    props = [kill("killer", 185, [5004], 1), kill("squad_attack", 185, [5001], 0),
             kill("squad_attack", 185, [5002], 0), Proposal("killer", {"type": "squad_orders", "squad_id": 185,
                                                                       "kill": [5003]}, "x", 2)]
    allowed, held = select(props, s, Memory())
    sq = [p for p in allowed if p.action.get("squad_id") == 185]
    assert len(sq) == 1, [(p.rule, p.action) for p in allowed]
    assert sq[0].action["kill"][0] == 5001 and set(sq[0].action["kill"]) == {5001, 5002, 5003, 5004}, sq[0].action
    assert sum("already has an order this cycle" in h for h in held) == 3, held


@test("select: a kill order and a station on one squad: the higher priority goes, the other waits; other squads untouched")
def _():
    s = fort()
    station = Proposal("intruder_guard", {"type": "squad_station", "squad_id": 11, "x": 1, "y": 2, "z": 3}, "post", 1)
    props = [station, kill("squad_attack", 11, [900], 0), kill("squad_attack", 12, [900], 0)]
    allowed, held = select(props, s, Memory())
    assert [(p.rule, p.action.get("squad_id")) for p in allowed] == [("squad_attack", 11), ("squad_attack", 12)]
    assert any(h.startswith("intruder_guard: squad 11 already has an order this cycle") for h in held), held
    # a recall and a kill order on one squad: the first by priority only
    props = [Proposal("squad_recall", {"type": "squad_orders", "squad_id": 11, "clear": True}, "back", 1),
             kill("squad_attack", 11, [900], 0)]
    allowed, held = select(props, s, Memory())
    assert [p.rule for p in allowed] == ["squad_attack"], [(p.rule, p.action) for p in allowed]


@test("select: a squad list loses the squads already ordered; a hunting party is held whole")
def _():
    s = fort()
    props = [kill("squad_attack", 11, [900], 0),
             Proposal("shelter_squads", {"type": "shelter_squads", "squads": [11, 12]}, "hide", 0)]
    allowed, held = select(props, s, Memory())
    sh = by_rule(allowed, "shelter_squads")
    assert sh and sh[0].action["squads"] == [12], [(p.rule, p.action) for p in allowed]
    props = [kill("squad_attack", 11, [900], 0),
             Proposal("hunt", {"type": "hunt_send", "squad_ids": [11, 12], "target_id": 7}, "hunt", 3)]
    allowed, held = select(props, s, Memory())
    assert not by_rule(allowed, "hunt") and any(h.startswith("hunt: squad 11") for h in held), held
    # different squads, different rules: all go as before
    props = [kill("squad_attack", 11, [900], 0), kill("killer", 12, [5], 1)]
    allowed, _ = select(props, s, Memory())
    assert len(allowed) == 2 and allowed[1].action == {"type": "squad_orders", "squad_id": 12, "kill": [5]}


# --- 3. squad_recall outside the action limit (A9 #2) ---------------------------------------------

@test("limit: six recalls and a drink order all go; other rules still meet the limit")
def _():
    assert "squad_recall" in LIMIT_EXEMPT
    s = fort()
    props = [Proposal("squad_recall", {"type": "squad_orders", "squad_id": 100 + i, "clear": True}, "back", 0)
             for i in range(6)]
    props.append(Proposal("drink", {"type": "work_order", "recipe": "brew_drink", "amount": 10}, "drink", 1,
                          is_order=True))
    allowed, held = select(props, s, Memory())
    assert len(by_rule(allowed, "squad_recall")) == 6 and by_rule(allowed, "drink"), held
    assert not any("action limit" in h for h in held), held
    lim = PLANNER_CONFIG["max_actions_per_cycle"]
    many = [Proposal(f"rule{i}", {"type": "noop", "n": i}, "x", 5) for i in range(lim + 2)]
    allowed, held = select(props[:1] + many, s, Memory())
    assert len([p for p in allowed if p.rule.startswith("rule")]) == lim


# --- 4. recalls respect who sent the squad (A6 #7, #8) ----------------------------------------------

def busy_fort(**extra) -> dict:
    s = fort()
    s["military"]["squads"][0].update(ai_orders=1, orders=1, kill_ids=[700])
    s["military"]["squads"][1].update(ai_orders=1, orders=1, kill_ids=[800])
    s.update(extra)
    return s


@test("recall: a squad on a hunt is the hunt's (no 'no more threats' recall); the other is called back")
def _():
    s = busy_fort(hunt={"targets": [{"id": 700, "name": "a beast"}],
                        "squads": [{"id": 11, "hunting": 700}, {"id": 12, "hunting": None}],
                        "hunts": [{"squad_id": 11, "target_id": 700, "since_tick": 0}], "history": []})
    s["hunt"]["hunts"][0]["since_tick"] = abs_tick(s) - 1500
    rec = [p for p in by_rule(plan(s, Memory())[0], "squad_recall") if "no more threats" in p.reason]
    ids = {p.action.get("squad_id") for p in rec}
    assert 11 not in ids and 12 in ids, ids


@test("recall: a squad sent at a vampire still here is the killers rule's; gone, it is called back")
def _():
    v = {"id": 800, "name": "Vamp", "kind": "vampire", "confidence": "certain", "resident": True,
         "seen_ticks": 9 * DAY}
    s = busy_fort(killers={"list": [v], "cells": [], "rooms": 1})
    m = Memory()
    m.kill_sent, m.kill_sent_at = {"12": [800]}, {"12": abs_tick(s) - 60}
    rec = [p for p in by_rule(plan(s, m)[0], "squad_recall") if "no more threats" in p.reason]
    ids = {p.action.get("squad_id") for p in rec}
    assert 12 not in ids and 11 in ids, ids
    s["killers"]["list"] = []                  # dead or gone: the squad comes home
    rec = [p for p in by_rule(plan(s, Memory())[0], "squad_recall") if "no more threats" in p.reason]
    assert 12 in {p.action.get("squad_id") for p in rec}


# --- 5. attack everything still calls a fight off (A6 #6) -----------------------------------------

def titan_fort(policy: str) -> dict:
    s = fort()
    s["others_on_map"]["threats"] = [{"id": 900, "name": "Ume, Swamp Titan", "great_danger": True,
                                      "can_reach_dwarves": True, "kinds": ["Titan"], "size": 2_500_000}]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    for q in s["military"]["squads"]:
        q["power"] = {"power": 10, "armored": 10, "skill": 10}
    s["military"]["soldiers"] = 20
    s["civ_alert_ready"] = True
    s["settings"]["attack_policy"] = policy
    return s


@test("attack everything: the fight is booked, and a third of the soldiers lost calls it off (recall, no new order)")
def _():
    s = titan_fort("all")
    m = Memory()
    props, _ = plan(s, m)
    assert by_rule(props, "squad_attack"), "attack everything sends the squads"
    assert isinstance(m.fight, dict) and m.fight.get("soldiers") == 20, m.fight     # before: never booked
    # the squads went at it; 8 of the 20 are dead
    s2 = titan_fort("all")
    s2["military"]["soldiers"] = 12
    for q in s2["military"]["squads"]:
        q.update(ai_orders=1, orders=1, kill_ids=[900])
    props, notes = plan(s2, m)
    att = [p for p in by_rule(props, "squad_attack") if 900 in (p.action.get("kill") or [])]
    rec = [p for p in by_rule(props, "squad_recall") if "called off" in p.reason]
    assert not att, [(p.rule, p.action) for p in att]
    assert {p.action["squad_id"] for p in rec} == {11, 12}, [(p.rule, p.action, p.reason) for p in props]
    assert "900" in m.called_off
    # 'ordinary' as before: the same losses call it off too
    s3 = titan_fort("ordinary")
    s3["military"]["soldiers"] = 12
    for q in s3["military"]["squads"]:
        q.update(ai_orders=1, orders=1, kill_ids=[900], power={"power": 100, "armored": 10, "skill": 10})
    m3 = Memory()
    m3.fight = {"tick": abs_tick(s3) - 100, "keys": ["titan"], "soldiers": 20}
    props, _ = plan(s3, m3)
    assert {p.action["squad_id"] for p in by_rule(props, "squad_recall") if "called off" in p.reason} == {11, 12}


if __name__ == "__main__":
    finish()

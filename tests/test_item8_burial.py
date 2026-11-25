"""(0.105.112 item8) Fort B, 24 Nov: the AI's stone coffin order in the fort's
bauxite stone (order 2498, placed in 264) "made no job in 2,349 days": all
six bauxite boulders lay on the flooded level z136 the dwarves can't reach.
The stuck rule kept the last coffin order while the dead waited, and the
coffins rule benched coffins every few minutes. And Dodok (dead raving, of
thirst) lay 165 days free on a meeting hall floor beside 10 open tombs.

  * order_remake: an AI one-time stone order in one named stone, no job for
    order_remake_days: cancelled (no stuck hold) and made again in any stone
    (wood where stone is short), before the stuck rule (which skips its id);
  * burial_assign: the fort's own dead lying free in reach with open tombs
    for burial_assign_days: entomb_dead (a free tomb assigned to each);
  * the wiring (catalog, dry run, cache, words, rule classes, config).

    python tests/test_item8_burial.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402
from planner import Memory  # noqa: E402
import planner_orders as PO  # noqa: E402
import planner_welfare as PW  # noqa: E402
from planner_core import TICKS_PER_DAY, abs_tick  # noqa: E402
from planner_config import PLANNER_CONFIG as CFG  # noqa: E402

LUA = ROOT / "lua"


def b_orders(material="INORGANIC:BAUXITE", jobs=None, usable=100, **extra):
    o = {"id": 2498, "by_ai": True, "active": True, "validated": True, "repeats": False, "recipe": "stone_coffin",
         "job": "ConstructCoffin", "material": material, "amount_left": 1, "amount_total": 1}
    if jobs:
        o["jobs"] = jobs
    o.update(extra)
    return {"date": {"year": 271, "tick": 230593}, "bridge_version": "0.105.111", "orders": [o], "_errors": {},
            "stone_use": {"usable": usable}, "stocks": {"wood": 40},
            "buildings": {"workshops": {"Masons": 5, "Carpenters": 1}},
            "dead": {"unburied": 9, "ghosts": 0}, "projects": {"open": []}}


def watched(s, days):
    m = Memory()
    m.order_watch["2498"] = {"left": 1, "since": abs_tick(s) - days * TICKS_PER_DAY, "by_ai": True,
                             "what": "stone_coffin"}
    return m


@test("order_remake (B): the bauxite coffin order with no job in 2,349 days: cancelled, then made in any stone")
def _():
    s = b_orders()
    props = []
    PO._order_remake_rule(s, watched(s, 2349), CFG, props)
    assert [p.rule for p in props] == ["order_remake", "order_remake"], props
    assert props[0].action == {"type": "cancel_work_order", "order_id": 2498}, props[0]   # no stuck hold
    assert props[1].action == {"type": "work_order", "recipe": "stone_coffin", "amount": 1}, props[1]
    assert "material" not in props[1].action and props[1].is_order
    assert "bauxite" in props[0].reason and "2349 days" in props[0].reason


@test("order_remake: not before order_remake_days, not with a job, not in any stone, not the player's")
def _():
    s = b_orders()
    props = []
    PO._order_remake_rule(s, watched(s, CFG["order_remake_days"] - 1), CFG, props)
    assert not props
    for s in (b_orders(jobs={"n": 1}), b_orders(material="INORGANIC"), b_orders(by_ai=False),
              b_orders(repeats=True)):
        props = []
        PO._order_remake_rule(s, watched(s, 30), CFG, props)
        assert not props, (s["orders"], props)


@test("order_remake: stone short and a carpenter's: made again in wood; no wood either: left to the quarry")
def _():
    s = b_orders(usable=0)
    props = []
    PO._order_remake_rule(s, watched(s, 30), CFG, props)
    assert props[1].action == {"type": "work_order", "recipe": "wooden_coffin", "amount": 1}, props
    s["stocks"]["wood"] = 0
    props = []
    PO._order_remake_rule(s, watched(s, 30), CFG, props)
    assert not props


@test("order_remake runs before the stuck rule (which then leaves that order alone); both may act in one cycle")
def _():
    src = (ROOT / "brain" / "planner.py").read_text(encoding="utf-8")
    assert src.index("_guard(_order_remake_rule,") < src.index("_guard(_stuck_orders_rule,")
    from planner_core_base import MULTI_PER_CYCLE
    assert "order_remake" in MULTI_PER_CYCLE


def b_dead(free=1, tombs=10, **dead):
    d = {"unburied": 9, "free_tombs": tombs, "ghosts": 0,
         "why": {"free": free, "forbidden": 2, "unreachable": 6, "not_ours": 2, "not_ours_loose": 0}}
    d.update(dead)
    return {"date": {"year": 271, "tick": 230593}, "dead": d, "_errors": {}}


@test("burial_assign (B): Dodok free in reach beside 10 open tombs: watched, then a tomb given after the wait")
def _():
    m = Memory()
    s = b_dead()
    props = []
    PW._burial_assign_rule(s, CFG, props, m)
    assert not props and isinstance(m.burial_watch.get("since"), int)
    s["date"]["tick"] += CFG["burial_assign_days"] * TICKS_PER_DAY
    PW._burial_assign_rule(s, CFG, props, m)
    assert len(props) == 1 and props[0].rule == "burial_assign", props
    assert props[0].action == {"type": "entomb_dead", "max": 1}, props[0]


@test("burial_assign: none free, or no open tomb (closed to citizens, out of reach): nothing, the watch reset")
def _():
    for s in (b_dead(free=0), b_dead(tombs=0), b_dead(free_tombs_no_citizens=10),
              b_dead(free_tombs_unreachable=10)):
        m = Memory()
        m.burial_watch = {"since": 0, "n": 1}
        props = []
        PW._burial_assign_rule(s, CFG, props, m)
        assert not props and m.burial_watch == {}, (s["dead"], props, m.burial_watch)


@test("burial_watch survives a save (Memory field)")
def _():
    m = Memory()
    m.burial_watch = {"since": 5, "n": 1}
    assert Memory.from_dict(m.to_dict()).burial_watch == {"since": 5, "n": 1}


@test("the wiring: entomb_dead action, dry run, cache, words, rule classes, config")
def _():
    cat = (LUA / "ai-bridge-catalog.lua").read_text(encoding="utf-8")
    assert "return reqscript('ai-welfare').entomb_dead(n, a.dry_run == true)" in cat
    assert "'entomb_dead'," in cat[cat.index("DRY_OK = {}"):]
    assert "CACHE_INVALIDATES.entomb_dead = {'dead'}" in (LUA / "ai-bridge-sections.lua").read_text(encoding="utf-8")
    wel = (LUA / "ai-welfare.lua").read_text(encoding="utf-8")
    i = wel.index("function entomb_dead(max, dry_run)")
    body = wel[i:wel.index("\nend\n", i)]
    assert "dfhack.buildings.setOwner" in body and "if not dry_run then" in body
    assert "U.corpse_side(it, 'CORPSE', ctx) ~= 'own'" in body and "f.forbid" in body
    assert len(wel.encode()) + 0 < 60000
    import overseer_words as OW
    assert "entomb_dead" in OW.SHORT_WORDS
    hc = (ROOT / "brain" / "hold_classes.py").read_text(encoding="utf-8")
    assert '"burial_assign"' in hc and '"entomb_dead"' in hc and '"order_remake"' in hc
    for k in ("burial_assign_days", "burial_assign_cooldown_ticks", "order_remake_days"):
        assert k in CFG, k


finish()

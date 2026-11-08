"""Tests for lua/ai-reports.lua (announcements -> events), in a real Lua
engine (pip install lupa).

    python tests/test_reports.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

LUA = LuaRuntime(unpack_returned_tuples=True)
R = LUA.execute(r"""
local src = ...
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-reports', 't', env))()
return env
""", (ROOT / "lua" / "ai-reports.lua").read_text(encoding="utf-8"))


CASES = [
    ("STRANGE_MOOD", "Urist McMiner withdraws from society...", "mood"),
    ("UNKNOWN_99", "Urist McMiner is taken by a fey mood!", "mood"),
    ("MOOD_BUILDING_CLAIMED", "Urist McMiner has claimed a Craftsdwarf's Workshop.", "mood_claimed"),
    ("ARTIFACT_BEGUN", "Urist McMiner has begun a mysterious construction!", "mood_working"),
    ("MADE_ARTIFACT", "Urist McMiner has created Gemfire, a granite amulet!", "artifact_made"),
    ("X", "Urist McMiner has gone stark raving mad!", "insanity"),
    ("BERSERK_CITIZEN", "Urist McMiner has gone berserk!", "insanity"),
    ("X", "Urist McMiner is throwing a tantrum!", "tantrum"),
    ("X", "The ghost of Urist McMiner has risen and is haunting the fortress!", "ghost"),
    ("X", "A vile force of darkness has arrived!", "siege"),
    # (0.105.15) a lone sneak is a thief, not a siege; an ambush still is one
    ("AMBUSH", "The Speardwarf Bembul was spotted sneaking around! \"You will not stand between me and Killstakes!\"", "thief"),
    ("X", "The Human Hammerman Otu was spotted sneaking around! \"I'll live to fight another day!\"", "thief"),
    ("AMBUSH", "An ambush! Curse them!", "siege"),
    ("X", "Urist has been bitten by a weremole!", "curse"),
    ("X", "A crime has been committed.", "crime"),
    ("X", "Some migrants have arrived.", "migrants"),
    ("CARAVAN_ARRIVAL", "Merchants from Nish have arrived.", "caravan"),
    ("BIRTH_CITIZEN", "Urist has given birth to a boy.", "birth"),
    ("X", "Mining cancelled: damp stone located.", "dig_cancelled"),
]


@test("announcements are sorted into topics, by type name or by their words")
def _():
    bad = [(t, x, R.classify(t, x), want) for t, x, want in CASES if R.classify(t, x) != want]
    assert not bad, bad


@test("ordinary chatter, combat and animal births are not events")
def _():
    assert R.classify("X", "Urist McMiner has become a Legendary Miner.") is None
    assert R.classify("X", "Goden Unibnunok has become a Siege Operator.") is None        # (0.104.38)
    assert R.classify("X", "Tirist, Siege Engineer has been found dead, contorted in fear!") != "siege"
    assert R.classify("COMBAT_STRIKE", "The goblin collapses in pain!") is None
    assert R.classify("BIRTH_ANIMAL", "A cow has given birth.") is None
    assert R.classify("X", "Urist McMiner has created a masterpiece!") is None
    assert R.classify("X", "Etur cancels Clean: Throwing tantrum.") is None      # job dropped, not news
    assert R.classify("X", "Etur cancels Dig: Damp stone located.") == "dig_cancelled"
    assert R.classify("X", "They were happy.") is None        # "were" is not a werebeast


def reports(*items):
    lst = LUA.table()
    for i, item in enumerate(items):
        rid, typ, text, cont, year, tick = item[:6]
        r = {"id": rid, "type": typ, "text": text, "year": year, "time": tick,
             "flags": LUA.table_from({"continuation": cont})}
        if len(item) > 6:
            r["pos"] = LUA.table_from(dict(zip("xyz", item[6])))
        lst[i] = LUA.table_from(r)
    return lst, len(items)


IDENT = LUA.eval("function(x) return x end")


@test("continuation lines join their announcement; only new ones become events")
def _():
    lst, n = reports((5, "X", "Urist McMiner is taken", False, 148, 1000),
                     (6, "X", "by a fey mood!", True, 148, 1000),
                     (7, "X", "Urist McMiner has become a Legendary Miner.", False, 148, 1100))
    merged = R.merge(lst, n, IDENT, IDENT)
    assert len(merged) == 2 and merged[1].text == "Urist McMiner is taken by a fey mood!"
    ev, newest = R.new_events(merged, 4, 148, 1200)
    assert len(ev) == 1 and ev[1].topic == "mood" and ev[1].kind == "report" and newest == 7
    ev, newest = R.new_events(merged, 7, 148, 1300)
    assert len(ev) == 0 and newest == 7


@test("first look: only the last day's announcements, not the whole backlog")
def _():
    lst, n = reports((1, "X", "Some migrants have arrived.", False, 147, 5000),
                     (2, "X", "Urist is throwing a tantrum!", False, 148, 9000))
    merged = R.merge(lst, n, IDENT, IDENT)
    ev, newest = R.new_events(merged, None, 148, 9500)
    assert [e.topic for e in ev.values()] == ["tantrum"] and newest == 2


@test("an announcement's map position travels onto the event; 'nowhere' (-30000) or none gives no x/y/z")
def _():
    lst, n = reports((1, "X", "Urist is throwing a tantrum!", False, 148, 100, (10, 20, 30)),
                     (2, "X", "Some migrants have arrived.", False, 148, 100, (-30000, -30000, -30000)),
                     (3, "X", "A crime has been committed.", False, 148, 100))
    merged = R.merge(lst, n, IDENT, IDENT)
    assert (merged[1].x, merged[1].y, merged[1].z) == (10, 20, 30)
    ev, _ = R.new_events(merged, 0, 148, 200)
    assert (ev[1].x, ev[1].y, ev[1].z) == (10, 20, 30), (ev[1].x, ev[1].y, ev[1].z)
    for e in (ev[2], ev[3]):
        assert e.x is None and e.y is None and e.z is None, e.topic


FAKE_ALERTS = r"""
local env, open, hover_i = ...
local TYPES = {[0] = 'GENERAL', 'ERA_CHANGE', 'UNDERGROUND', 'MIGRANT'}
local att = {}
for i, n in pairs(TYPES) do att[i] = n; att[n] = i end
att[21] = 'DEATH'; att.DEATH = 21
local function vec(items)
  local v = {n = #items}
  for i, x in ipairs(items) do v[i - 1] = x end
  v.erase = function(self, i)
    for k = i, self.n - 2 do self[k] = self[k + 1] end
    self[self.n - 1] = nil; self.n = self.n - 1
  end
  return setmetatable(v, {__len = function(self) return self.n end})
end
local function ids(t) local v = vec(t) return v end
local freed = {}
local function alert(t, rid) return {type = t, announcement_id = ids({rid}), report_unid = ids({}),
                                      delete = function(self) table.insert(freed, self.type) end} end
local reports = {[1] = {year = 100, time = 1000}, [2] = {year = 100, time = 9000}, [3] = {year = 99, time = 0}}
local list = vec({alert(0, 1), alert(3, 2), alert(21, 3)})
local hover = hover_i and list[hover_i] or nil
env.df = {global = {cur_year = 100, cur_year_tick = 10000, world = {status = {announcement_alert = list}},
                    game = {main_interface = {announcement_alert = {open = open}, current_hover_alert = hover}}},
          report = {find = function(id) return reports[id] end}, announcement_alert_type = att}
local _ipairs = ipairs
env.ipairs = function(t)
  if type(t) == 'table' and t.n ~= nil then
    return function(_, i) i = i + 1; if i < t.n then return i, t[i] end end, t, -1
  end
  return _ipairs(t)
end
return {list = list, freed = freed}
"""


@test("alert icons (0.88): the report by type with the newest report's age; dismissed by age, dangers kept")
def _():
    f = LUA.execute(FAKE_ALERTS, R, False, None)
    rep = R.alerts_report()
    assert rep.total == 3 and rep.by_type.GENERAL.age == 9000 and rep.by_type.MIGRANT.age == 1000, rep
    ages = LUA.eval("{default = 1200, DEATH = false}")
    d = R.dismiss_alerts(ages, 10, True)
    assert d.ok and d.dismissed == 1 and len(f["freed"]) == 0, d               # a dry run frees nothing
    r = R.dismiss_alerts(ages, 10, False)
    assert r.ok and r.dismissed == 1 and r.by_type.GENERAL == 1 and r.left == 2, r
    assert len(f["freed"]) == 0 and f["list"].n == 2 and f["list"][0].type == 3   # taken out, not freed
    r = R.dismiss_alerts(LUA.eval("{default = 0, DEATH = false}"), 1, False)   # max 1
    assert r.dismissed == 1 and r.by_type.MIGRANT == 1 and f["list"].n == 1, r
    assert not R.dismiss_alerts(ages, 10, False).ok                              # DEATH is kept


@test("alert icons (0.88): never while the alert window is open, nor the one under the mouse")
def _():
    LUA.execute(FAKE_ALERTS, R, True, None)
    r = R.dismiss_alerts(LUA.eval("{default = 0}"), 10, False)
    assert not r.ok and r.waiting, r
    f = LUA.execute(FAKE_ALERTS, R, False, 0)
    r = R.dismiss_alerts(LUA.eval("{default = 0}"), 10, False)
    assert r.dismissed == 2 and f["list"].n == 1 and f["list"][0].type == 0, r


if __name__ == "__main__":
    finish()

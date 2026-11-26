"""(0.105.113 item9) Fort B's social scatter: the taverns and temples drawn
together when the fort has more than its size needs.

Fort B "Monastery", 24 Nov 23:30-23:40 (state.json, probe i9-rec): 35
citizens (94 a season before), 3 taverns, 5 temples, 2 guildhalls, a
library, 4 hospitals, every zone active; 11 idle dwarves in 6 locations and
the barracks (3 at most in one); BeWithFriends badly 26 (8 soldiers),
DrinkAlcohol badly 0.

1. brain/planner_social_places.py: one tavern and one temple for every 40
   citizens open; the AI's retired ones back when the fort grows.
2. lua/ai-society-burrows.lua social_keep / social_consolidate: the best kept
   (the recreation burrow's ranking), the others' zones inactive, the
   player's never touched; rec_gathering skips an inactive location.
3. the bridge's action, the report's `inactive`, the supply rules skip a
   retired location.

    python tests/test_item9_social.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src, split_src  # noqa: E402

from planner import PLANNER_CONFIG as CFG  # noqa: E402
import planner_social_places as SP  # noqa: E402
import planner_core_fort  # noqa: E402


def loc(i, kind, zone, **kw):
    return {"id": i, "type": kind, "zones": [zone], **kw}


# B's locations, 24 Nov 23:32 (state.json locations.list, cut to what matters)
B_LOCS = [loc(0, "TEMPLE", 21, any_deity=True, value=1279), loc(1, "INN_TAVERN", 184, value=844),
          loc(2, "TEMPLE", 306, any_deity=True, value=7829), loc(3, "HOSPITAL", 333),
          loc(4, "LIBRARY", 403), loc(5, "TEMPLE", 409, deity_hf=537, value=8187),
          loc(6, "INN_TAVERN", 494, value=683), loc(7, "GUILDHALL", 705), loc(8, "TEMPLE", 748, deity_hf=537),
          loc(9, "GUILDHALL", 783), loc(10, "INN_TAVERN", 913, value=553), loc(11, "TEMPLE", 1098, deity_hf=538),
          loc(12, "HOSPITAL", 1342), loc(13, "HOSPITAL", 1643), loc(14, "HOSPITAL", 1760)]


def fort(citizens=35, locs=None, retired=None, badly=26):
    s = {"_errors": {}, "dwarves": {"total": citizens},
         "locations": {"list": copy.deepcopy(B_LOCS if locs is None else locs)},
         "society": {"recreation": {"members": 2, **({"retired": retired} if retired else {})}},
         "needs": {"needs": {"BeWithFriends": {"badly": badly, "badly_soldiers": 8}}}}
    return s


def retire(s, ids):
    for e in s["locations"]["list"]:
        if e["id"] in ids:
            e["inactive"] = True


# ---- 1. the brain ---------------------------------------------------------------------------

@test("1: B (35 citizens, 3 taverns and 5 temples open): keep 1 and 1, the reason with the numbers")
def _():
    p = SP.social_places_plan(fort(), CFG)
    assert p and (p["taverns"], p["temples"]) == (1, 1), p
    assert (p["open_taverns"], p["open_temples"]) == (3, 5), p
    props = []
    SP._social_places_rule(fort(), CFG, props)
    assert len(props) == 1 and props[0].rule == "social_places", props
    assert props[0].action == {"type": "social_places", "taverns": 1, "temples": 1}, props[0].action
    assert "3 tavern(s) and 5 temple(s) open for 35 citizens" in props[0].reason, props[0].reason
    assert "26 badly miss friends" in props[0].reason


@test("1: by the fort's size: 90 citizens keep 3 of each; the halls' cap holds; one at least")
def _():
    assert SP.social_places_keep(90, CFG) == 3
    assert SP.social_places_keep(40, CFG) == 1 and SP.social_places_keep(41, CFG) == 2
    assert SP.social_places_keep(1000, CFG) == CFG["social_halls_max"]
    assert SP.social_places_keep(0, CFG) == 1
    p = SP.social_places_plan(fort(citizens=90), CFG)
    assert (p["taverns"], p["temples"]) == (3, 3), p


@test("1: once retired nothing more is asked; back when the fort grows past a quarter more (no flapping)")
def _():
    s = fort(retired=[0, 1, 5, 6, 8, 11])
    retire(s, {0, 1, 5, 6, 8, 11})
    assert SP.social_places_plan(s, CFG) is None
    for n in (41, 45, 50):                       # 1 open serves 40; back only past 50
        s["dwarves"]["total"] = n
        assert SP.social_places_plan(s, CFG) is None, n
    s["dwarves"]["total"] = 51
    p = SP.social_places_plan(s, CFG)
    assert p and (p["taverns"], p["temples"]) == (2, 2), p
    props = []
    SP._social_places_rule(s, CFG, props)
    assert "grown to 51" in props[0].reason, props[0].reason


@test("1: one the player made inactive (not in the AI's retired) is never counted to bring back")
def _():
    s = fort(citizens=120)
    retire(s, {1, 6})                             # the player's: no `retired`
    p = SP.social_places_plan(s, CFG)
    assert p["retired_taverns"] == 0 and p["taverns"] == 1, p     # 1 open, 3 wanted, none to bring back


@test("1: one the player opened again after the AI retired it is kept besides, not counted")
def _():
    s = fort(retired=[0, 1, 5, 8, 11])
    retire(s, {0, 1, 5, 8, 11})
    s["society"]["recreation"]["player_kept"] = [6]
    assert SP.social_places_plan(s, CFG) is None            # 10 and 6 open, 6 the player's


@test("1: temples only while an open one serves all gods; none in a fort without; unreadable: nothing")
def _():
    locs = [e for e in B_LOCS if not e.get("any_deity")]
    p = SP.social_places_plan(fort(locs=locs), CFG)
    assert p["temples"] == p["open_temples"] == 3 and p["taverns"] == 1, p
    s = fort()
    s["_errors"] = {"locations": "boom"}
    assert SP.social_places_plan(s, CFG) is None
    s = fort()
    s["society"]["recreation"] = {"error": "boom"}
    assert SP.social_places_plan(s, CFG) is None
    one = [loc(1, "INN_TAVERN", 1), loc(2, "TEMPLE", 2, any_deity=True)]
    assert SP.social_places_plan(fort(locs=one), CFG) is None
    props = []
    SP._social_places_rule(fort(), {**CFG, "social_places_on": False}, props)
    assert props == []


@test("1: wired: planner_society calls the rule; a label; classed with the mind's rules and kinds")
def _():
    src = (ROOT / "brain" / "planner_society.py").read_text(encoding="utf-8")
    assert "_social_places_rule(s, cfg, proposals)" in src
    words = (ROOT / "brain" / "overseer_words.py").read_text(encoding="utf-8")
    assert '"social_places":' in words
    hc = (ROOT / "brain" / "hold_classes.py").read_text(encoding="utf-8")
    assert hc.count('"social_places"') == 2


# ---- 3. the supply rules skip a retired location -----------------------------------------------

@test("3: _location gives the first open one; instruments and paired chairs never for a retired one")
def _():
    s = fort()
    retire(s, {1})
    assert planner_core_fort._location(s, "INN_TAVERN")["id"] == 6
    retire(s, {6, 10})
    assert planner_core_fort._location(s, "INN_TAVERN")["id"] == 1        # all retired: the first
    src = (ROOT / "brain" / "planner_locations.py").read_text(encoding="utf-8")
    assert src.count('not e.get("inactive")') >= 3


@test("3: the bridge: social_places in ACTIONS and DRY_OK, taverns/temples 1-6; the report's inactive")
def _():
    cat = (ROOT / "lua" / "ai-bridge-catalog.lua").read_text(encoding="utf-8")
    assert "social_places = act_social_places," in cat and "'social_places'," in cat
    works = (ROOT / "lua" / "ai-bridge-actions-works.lua").read_text(encoding="utf-8")
    body = works[works.index("function act_social_places(a)"):]
    body = body[:body.index("\nend\n")]
    assert "int_in(a.taverns or 1, 1, 6), int_in(a.temples or 1, 1, 6)" in body
    assert "social_consolidate(nt, ne, a.dry_run == true)" in body
    rep = split_src("ai-bridge-report.lua")   # (0.105.119) get_locations in ai-bridge-report-civic
    assert "if off > 0 and off == #c.building_ids then e.inactive = true end" in rep
    burrows = split_src("ai-society-burrows.lua")
    st = burrows[burrows.index("function recreation_status("):]
    assert "out.retired = r" in st[:st.index("\nend\n")]
    assert "out.player_kept = held" in st[:st.index("\nend\n")]


# ---- 2. the Lua -------------------------------------------------------------------------------

def lua_env(zones_active=None, store=None):
    """ai-society-burrows loaded with B's 15 locations (DF types by name)."""
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    env = L.execute("""
local src, rows, active, store = ...
local types = {}
local bld = {}
local zones = {}
for i = 1, #rows do
  local r = rows[i]
  types[r.id] = r.kind
  local z = {id = r.zone, spec_sub_flag = {active = active[r.zone] ~= false}}
  zones[r.zone] = z
  table.insert(bld, {id = r.id, flags = {}, deity_type = r.any and 0 or 1,
    occupations = r.keeper and {{type = 'TAVERN_KEEPER', histfig_id = 5}} or {},
    getType = function(self) return self.id end,
    getContents = function(self) return {building_ids = {r.zone}, location_value = r.value or 0,
                                         count_goblets = r.goblets or 0, count_instruments = r.instruments or 0} end})
end
local occ = setmetatable({}, {__index = function(t, k) return k end})
local env = setmetatable({
  df = {global = {world = {buildings = {all = {}}}},
        abstract_building_type = types,
        occupation_type = occ,
        religious_practice_type = {[0] = 'NONE', [1] = 'WORSHIP_HFID'},
        building = {find = function(id) return zones[id] end}},
  dfhack = {onStateChange = {}, burrows = {},
            world = {getCurrentSite = function() return {buildings = bld} end},
            persistent = {getSiteData = function(k, d) return store[k] or d end,
                          saveSiteData = function(k, v) store[k] = v end}},
  xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end,
  reqscript = function(n) return {} end,
  ZONES = zones}, {__index = _G})
assert(load(src, 'mod', 't', env))()
return env
""", module_src("ai-society-burrows.lua"), L.table_from([L.table_from(r) for r in B_ROWS]),
        L.table_from(zones_active or {}), store if store is not None else L.table_from({}))
    return L, env


# B's taverns and temples as DF holds them (keeper, goblets, instruments as state.json)
B_ROWS = [{"id": 0, "kind": "TEMPLE", "zone": 21, "value": 1279, "any": True, "instruments": 5},
          {"id": 1, "kind": "INN_TAVERN", "zone": 184, "value": 844, "goblets": 10, "instruments": 5},
          {"id": 2, "kind": "TEMPLE", "zone": 306, "value": 7829, "any": True, "instruments": 5},
          {"id": 3, "kind": "HOSPITAL", "zone": 333, "value": 236},
          {"id": 5, "kind": "TEMPLE", "zone": 409, "value": 8187, "instruments": 5},
          {"id": 6, "kind": "INN_TAVERN", "zone": 494, "value": 683, "keeper": True},
          {"id": 7, "kind": "GUILDHALL", "zone": 705, "value": 12681},
          {"id": 8, "kind": "TEMPLE", "zone": 748, "value": 9697, "instruments": 5},
          {"id": 10, "kind": "INN_TAVERN", "zone": 913, "value": 553, "keeper": True, "goblets": 10, "instruments": 5},
          {"id": 11, "kind": "TEMPLE", "zone": 1098, "value": 7758, "instruments": 5}]


def keys(t):
    return sorted(k for k in t.keys())


@test("2: social_keep: B keeps tavern 10 and temple 2 (the recreation burrow's); 2 and 2; the player's besides")
def _():
    need_lua()
    L, env = lua_env()
    rows = L.table_from([L.table_from({"id": r["id"], "kind": r["kind"], "value": r.get("value"),
                                       "keeper": r.get("keeper"), "goblets": r.get("goblets"),
                                       "instruments": r.get("instruments"), "any_deity": r.get("any")})
                         for r in B_ROWS])
    assert keys(env.social_keep(rows, 1, 1)) == [2, 10]
    assert keys(env.social_keep(rows, 2, 2)) == [0, 1, 2, 10]
    assert keys(env.social_keep(rows, 1, 1, L.table_from({"6": True}))) == [2, 6, 10]
    assert keys(env.social_keep(rows, 0, 0)) == [2, 10]          # one of each at least


@test("2: social_consolidate: B's other 2 taverns and 4 temples made inactive, remembered; the guildhall "
      "and hospital untouched; rec_gathering then still picks 10 and 2; asked again: already so")
def _():
    need_lua()
    L, env = lua_env()
    dry = env.social_consolidate(1, 1, True)
    assert dry.ok and dry.dry_run and len(list(dry.retired.values())) == 6, dict(dry)
    assert all(z.spec_sub_flag.active for z in env.ZONES.values())        # the dry run switched nothing
    r = env.social_consolidate(1, 1, False)
    assert r.ok and sorted(r.retired.values()) == sorted(
        ["tavern #1", "tavern #6", "temple #0", "temple #5", "temple #8", "temple #11"]), list(r.retired.values())
    off = sorted(z.id for z in env.ZONES.values() if not z.spec_sub_flag.active)
    assert off == [21, 184, 409, 494, 748, 1098], off
    assert sorted(env.social_retired().values()) == [0, 1, 5, 6, 8, 11]
    again = env.social_consolidate(1, 1, False)
    assert again.rejected, dict(again)


@test("2: grown: the AI's retired set going again, the best first; one the player turned on is the player's")
def _():
    need_lua()
    L, env = lua_env()
    env.social_consolidate(1, 1, False)
    env.ZONES[494].spec_sub_flag.active = True       # the player opens tavern 6 again
    r = env.social_consolidate(2, 2, False)
    # tavern 6 now the player's (kept besides): tavern 1 back as the second best; temple 0 (to all gods)
    assert sorted(r.restored.values()) == ["tavern #1", "temple #0"], list(r.restored.values())
    assert env.ZONES[21].spec_sub_flag.active and env.ZONES[184].spec_sub_flag.active
    r = env.social_consolidate(1, 1, False)          # shrunk again: 6 is the player's, never retired
    assert env.ZONES[494].spec_sub_flag.active and env.ZONES[913].spec_sub_flag.active
    assert sorted(r.retired.values()) == ["tavern #1", "temple #0"], list(r.retired.values())


@test("2: rec_gathering passes over a location whose zones are all inactive")
def _():
    need_lua()
    L, env = lua_env()
    t = lambda v: L.table_from([L.table_from(e) for e in v])  # noqa: E731
    rows = [{"id": 10, "kind": "INN_TAVERN", "keeper": True, "goblets": 10, "inactive": True},
            {"id": 6, "kind": "INN_TAVERN", "keeper": True},
            {"id": 2, "kind": "TEMPLE", "any_deity": True, "inactive": True}, {"id": 5, "kind": "TEMPLE"}]
    assert env.rec_gathering(t(rows)) == (6, 5)


if __name__ == "__main__":
    finish()

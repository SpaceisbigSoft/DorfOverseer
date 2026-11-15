"""(layout B, group B4) lua/ai-builder-floorstore.lua: the Rules switch as the
builder reads it (floor_mode), the fort's saved floor record (load_floors,
save_floors), what a placed, a refused and a cancelled level write into it
(floor_commit, floor_fallback, floor_release) and the report's `floors`
section (floors_report).

On test_builder's fake fort in a real Lua engine. The record's own logic is
the pure module ai-floorplan (group B1), which this part only calls: here a
stand-in keeps the contract's shapes (migrate, find_floor, new_floor, commit,
release, mark_full, summary) and logs every call. The real module first meets
this part in the end-to-end tests after the merge.

    python tests/test_b4_floorstore.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import finish, have_lua, make_test, skip  # noqa: E402

LUA = B = W = TB = None
if have_lua():
    import test_builder as TB  # noqa: E402  (its fake fort; its tests run only when it is run itself)
    LUA, B, W = TB.LUA, TB.B, TB.W

KEY = "ai-overseer/floors"
PKEY = "ai-overseer/projects"

# The stand-in ai-floorplan and the reqscript that answers it. STAND.mods[name]
# is a module, or the text 'raise' (reqscript raises), or nil (the fake fort's
# own reqscript: ai-layouts and quickfort only).
SETUP = r"""
local real = reqscript
STAND = {mods = {}, calls = {}, asked = {}}
reqscript = function(name)
  table.insert(STAND.asked, name)
  local m = STAND.mods[name]
  if m == 'raise' then error('no such script: ' .. name) end
  if m ~= nil then return m end
  return real(name)
end

local function log(name, ...) table.insert(STAND.calls, {name = name, args = {...}}) end

function STAND.floorplan()
  local FP = {VERSION = 1}
  function FP.new_store() return {v = 1, next = 1, fallbacks = 0, floors = {}} end
  function FP.migrate(store)
    log('migrate', store)
    if type(store) ~= 'table' or store.v == nil then return FP.new_store(), true end
    if type(store.v) ~= 'number' then return FP.new_store(), true end
    if store.v > FP.VERSION then return store, false, 'newer' end
    return store, false
  end
  function FP.find_floor(store, z, sx, sy)
    for _, f in ipairs(store.floors) do
      if type(f) == 'table' and f.z == z and type(f.stair) == 'table' and f.stair.x == sx and f.stair.y == sy then return f end
    end
  end
  function FP.new_floor(store, z, sx, sy, tick)
    log('new_floor', z, sx, sy, tick)
    return {id = store.next, z = z, stair = {x = sx, y = sy}, made = tick, hub = 'dug', runs = {}, slots = {}, full = {}}
  end
  local function insert(store, floor)
    for _, f in ipairs(store.floors) do if f == floor then return end end
    table.insert(store.floors, floor)
    store.next = math.max(store.next or 1, floor.id + 1)
  end
  function FP.commit(store, floor, placement, pid, tick)
    log('commit', store, floor, placement, pid, tick)
    insert(store, floor)
    for _, r in ipairs(placement.runs or {}) do table.insert(floor.runs, r) end
    for _, s in ipairs(placement.slots or {}) do s.pid = pid; table.insert(floor.slots, s) end
    floor.full = {}
    return floor
  end
  function FP.release(store, pid)
    log('release', store, pid)
    local n = 0
    for _, f in ipairs(store.floors) do
      for _, s in ipairs(type(f) == 'table' and type(f.slots) == 'table' and f.slots or {}) do
        if s.pid == pid and not s.dead then s.dead = true; n = n + 1 end
      end
    end
    return n
  end
  function FP.mark_full(store, floor, tag, tick, free)
    log('mark_full', store, floor, tag, tick, free)
    insert(store, floor)
    floor.full = floor.full or {}
    floor.full[tag] = tick
    if free then floor.free = free end
  end
  function FP.summary(store, ez, now, retry_days)
    log('summary', store, ez, now, retry_days)
    if STAND.rows then return STAND.rows(store, ez, now, retry_days) end
    local rows = {}
    for _, f in ipairs(store.floors) do
      local rooms = 0
      for _, s in ipairs(f.slots or {}) do if not s.dead then rooms = rooms + 1 end end
      local hall, arms = 0, {}
      for _, r in ipairs(f.runs or {}) do
        hall = hall + r.len * 3
        table.insert(arms, {dir = 'east', len = r.len, runs = 1, tag = r.tag, slots = rooms})
      end
      table.insert(rows, {id = f.id, elevation = ez(f.z), z = f.z, stair = f.stair, hub = f.hub,
                          no_hall = (f.full or {})['*'] ~= nil, width = 3, rooms = rooms, hall = hall,
                          tags = {}, kinds = {}, full = {}, free = f.free, arms = arms})
    end
    return rows
  end
  return FP
end

function STAND.settings(layout)
  return {load_settings = function()
    if layout == '!raise' then error('the settings cannot be read') end
    return {floor_layout = layout}
  end}
end

-- a saved record with two floors: floor 1 (z 70, stair 60,60: one run of 12, two slots of project 5)
-- and floor 2 (z 72, no run: marked '*')
function STAND.record()
  return {v = 1, next = 3, fallbacks = 2,
          last = {tick = 900, ok = false, kind = 'dining', elevation = 70, why = 'floor 1: no room'},
          floors = {
            {id = 1, z = 70, stair = {x = 60, y = 60}, made = 100, hub = 'dug',
             runs = {{id = 1, parent = 0, ox = 0, oy = 0, dx = 1, dy = 0, len = 12, walked = 0, tag = 'homes', node = 3}},
             slots = {{run = 1, side = -1, u = 4, w = 3, d = 3, pid = 5, kind = 'bedrooms', tag = 'homes', role = 'room'},
                      {run = 1, side = 1, u = 4, w = 3, d = 3, pid = 5, kind = 'bedrooms', tag = 'homes', role = 'room'}},
             full = {}, free = {north = 0, east = 20, south = 0, west = 9, tick = 100}},
            {id = 2, z = 72, stair = {x = 60, y = 60}, made = 200, hub = 'found', runs = {}, slots = {},
             full = {['*'] = 200}}}}
end

-- a value written out with its keys in order: two equal saves give the same text
function STAND.dump(v, seen)
  if type(v) ~= 'table' then return type(v) .. ':' .. tostring(v) end
  seen = seen or {}
  if seen[v] then return '<again>' end
  seen[v] = true
  local keys = {}
  for k in pairs(v) do table.insert(keys, k) end
  table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
  local out = {}
  for _, k in ipairs(keys) do table.insert(out, tostring(k) .. '=' .. STAND.dump(v[k], seen)) end
  seen[v] = nil
  return '{' .. table.concat(out, ',') .. '}'
end
"""

REAL_TILE_INFO = None
if TB is not None:
    LUA.execute(SETUP)
    REAL_TILE_INFO = B.tile_info
S = LUA.globals().STAND if TB is not None else None


def ev(code):
    return LUA.eval(code)


def _reset():
    if TB is None:
        return
    TB._reset(False)
    B.tile_info = REAL_TILE_INFO
    B.util_module().report_end()
    B.now_tick = ev("function() return 5000 end")
    LUA.execute("STAND.mods = {['ai-floorplan'] = STAND.floorplan()}; STAND.calls = {}; STAND.asked = {}; STAND.rows = nil")


test = make_test(before=_reset)


def need():
    if TB is None:
        skip("needs the lupa package (pip install lupa)")


def calls(name=None):
    out = [S.calls[i] for i in range(1, len(S.calls) + 1)]
    return [c for c in out if name is None or c.name == name]


def same(a, b):
    return LUA.globals().rawequal(a, b)


def lst(t):
    return [t[i] for i in range(1, len(t) + 1)] if t is not None else []


def dump(v):
    return S.dump(v)


def settings(layout):
    S.mods["ai-overseer-settings"] = S.settings(layout)


def put_record(code="STAND.record()"):
    W.persist[KEY] = ev(code)


def put_projects(code):
    W.persist[PKEY] = ev(code)


def new_site(store_code="{v = 1, next = 1, fallbacks = 0, floors = {}}"):
    """A site as floor_site hands it over: a new floor's first placement."""
    return ev("""function(store)
        local floor = {id = store.next, z = 70, stair = {x = 60, y = 60}, made = 5000, hub = 'dug', runs = {}, slots = {}, full = {}}
        return {z = 70, floor = {id = floor.id, slots = 1, hall = 9},
                floor_result = {id = floor.id, elevation = 70},
                _commit = {store = store, floor = floor,
                           placement = {runs = {{id = 1, parent = 0, dx = 1, dy = 0, len = 9, tag = 'homes'}},
                                        slots = {{run = 1, side = -1, u = 3, w = 3, d = 3, kind = 'bedrooms', tag = 'homes', role = 'room'}}},
                           free = {north = 0, east = 31, south = 4, west = 0, tick = 5000},
                           marks = {{z = 72, sx = 60, sy = 60, tag = '*', free = {north = 0, east = 0, south = 0, west = 0, tick = 5000}}}}}
    end""")(ev(store_code))


# --- 1. the part loads, and asks for no script while it does -------------------

@test("the builder boots with the part in PARTS, its version marked")
def _():
    need()
    assert "floorstore" in lst(B.PARTS)
    assert B.PART_VERSIONS["ai-builder-floorstore"] == B.PART_VERSIONS["ai-builder"]   # (bumped together)
    assert B.FLOORS_KEY == KEY
    for name in ("floor_mode", "load_floors", "save_floors", "floor_commit", "floor_fallback",
                 "floor_release", "floors_report"):
        assert B[name] is not None, name


@test("no reqscript for ai-floorplan or the settings while the builder loads")
def _():
    need()
    line = "_G.reqscript = function(name)\n"
    assert line in TB.HARNESS
    harness = TB.HARNESS.replace(line, line + "  ASKED = ASKED or {}; table.insert(ASKED, name)\n")
    lua = TB.LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(ROOT / "lua")
    b, _w = lua.execute(harness, (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8"),
                        (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8"))
    asked = lua.globals().ASKED
    asked = [asked[i] for i in range(1, len(asked) + 1)] if asked is not None else []
    assert "ai-floorplan" not in asked and "ai-overseer-settings" not in asked, asked
    assert b.floor_mode() == "classic"                 # the bare fake: no settings module
    src = (ROOT / "lua" / "ai-builder-floorstore.lua").read_text(encoding="utf-8")
    for ln in src.splitlines():                        # every reqscript sits inside a function
        if "reqscript" in ln and not ln.lstrip().startswith("--"):
            assert ln.startswith(" "), ln


# --- 2. the switch -------------------------------------------------------------

@test("floor_mode: classic on the bare fake fort (no settings module)")
def _():
    need()
    assert B.floor_mode() == "classic"
    assert "ai-overseer-settings" in lst(S.asked)


@test("floor_mode: hallway only when the settings say hallway")
def _():
    need()
    settings("hallway")
    assert B.floor_mode() == "hallway"
    settings("classic")
    assert B.floor_mode() == "classic"
    for junk in ("'Hallway'", "'halls'", "7", "true", "{}", "nil"):
        S.mods["ai-overseer-settings"] = ev("{load_settings = function() return {floor_layout = %s} end}" % junk)
        assert B.floor_mode() == "classic", junk


@test("floor_mode: classic when load_settings raises, answers junk, or the module is junk")
def _():
    need()
    settings("!raise")
    assert B.floor_mode() == "classic"
    S.mods["ai-overseer-settings"] = ev("{load_settings = function() return 'hallway' end}")
    assert B.floor_mode() == "classic"
    S.mods["ai-overseer-settings"] = ev("{load_settings = function() return nil end}")
    assert B.floor_mode() == "classic"
    S.mods["ai-overseer-settings"] = ev("{}")
    assert B.floor_mode() == "classic"
    S.mods["ai-overseer-settings"] = "raise"
    assert B.floor_mode() == "classic"


# --- 3. the saved record -------------------------------------------------------

@test("load_floors: an empty save gives a new store, writable, and saves nothing")
def _():
    need()
    store, writable = B.load_floors()[:2]
    assert writable is True
    assert store.v == 1 and len(store.floors) == 0 and store.fallbacks == 0
    assert W.persist[KEY] is None
    assert len(calls("migrate")) == 1


@test("load_floors: a v1 record comes back as saved, writable")
def _():
    need()
    put_record()
    store, writable = B.load_floors()[:2]
    assert writable is True
    assert store.v == 1 and store.next == 3 and store.fallbacks == 2
    assert [f.id for f in lst(store.floors)] == [1, 2]
    assert store.floors[1].runs[1].len == 12 and store.last.why == "floor 1: no room"


@test("load_floors: a record of v 99 is handed out untouched, not writable")
def _():
    need()
    put_record("{v = 99, next = 8, floors = 'another shape', extra = {1, 2}}")
    before = dump(W.persist[KEY])
    store, writable, why = B.load_floors()
    assert writable is False and why == "newer"
    assert store.v == 99 and store.floors == "another shape"
    assert dump(W.persist[KEY]) == before


@test("load_floors: v 99 is not writable even when migrate gives no 'newer'")
def _():
    need()
    put_record("{v = 99, floors = {}}")
    S.mods["ai-floorplan"].migrate = ev("function(s) return s, false end")
    _store, writable = B.load_floors()[:2]
    assert writable is False


@test("load_floors: without ai-floorplan nil, false and why")
def _():
    need()
    put_record()
    S.mods["ai-floorplan"] = "raise"
    store, writable, why = B.load_floors()
    assert store is None and writable is False and "ai-floorplan" in why


@test("save_floors: round trip through the save")
def _():
    need()
    store = B.load_floors()[0]
    store.fallbacks = 4
    store.floors[1] = ev("{id = 1, z = 71, stair = {x = 60, y = 60}, runs = {}, slots = {}}")
    ok = B.save_floors(store)
    assert ok is True or ok == (True,) or (isinstance(ok, tuple) and ok[0] is True)
    assert W.persist[KEY].fallbacks == 4
    again, writable = B.load_floors()[:2]
    assert writable and again.fallbacks == 4 and again.floors[1].z == 71


@test("save_floors: no table, or a save that fails: false and why, nothing raised")
def _():
    need()
    ok, err = B.save_floors(None)
    assert ok is False and err
    ok, err = B.save_floors("junk")
    assert ok is False and err
    real = B.site_put
    try:
        B.site_put = ev("function() return false, 'disk full' end")
        ok, err = B.save_floors(ev("{v = 1, floors = {}}"))
        assert ok is False and err == "disk full"
        B.site_put = ev("function() error('boom') end")
        ok, err = B.save_floors(ev("{v = 1, floors = {}}"))
        assert ok is False and "boom" in err
    finally:
        B.site_put = real
    assert W.persist[KEY] is None


@test("load_floors inside a report: decoded once, each caller its own copy; a save drops it")
def _():
    need()
    put_record()
    U = B.util_module()
    U.report_begin()
    try:
        a = B.load_floors()[0]
        b, writable = B.load_floors()[:2]
        assert len(calls("migrate")) == 1, "decoded more than once inside a report"
        assert writable is True
        a.fallbacks = 77
        a.floors[1].runs[1].len = 99
        assert b.fallbacks == 2 and b.floors[1].runs[1].len == 12
        assert W.persist[KEY].fallbacks == 2 and W.persist[KEY].floors[1].runs[1].len == 12
        B.save_floors(a)
        c = B.load_floors()[0]
        assert c.fallbacks == 77 and len(calls("migrate")) == 2
    finally:
        U.report_end()
    B.load_floors()
    B.load_floors()
    assert len(calls("migrate")) == 4, "outside a report every call decodes"


# --- 4. floor_commit -----------------------------------------------------------

@test("floor_commit: marks applied, commit with the project id and now_tick, free kept, saved")
def _():
    need()
    put_projects("{next_id = 42, list = {{id = 41, kind = 'bedrooms', phase = 'dig', z = 70, floor = {id = 1}}}}")
    site = new_site()
    ok = B.floor_commit(site, 41)
    assert (ok[0] if isinstance(ok, tuple) else ok) is True, ok
    order = [c.name for c in calls() if c.name in ("mark_full", "commit")]
    # the placement first: the new floor keeps the id floor_site gave it (the project's p.floor.id),
    # and the marked level with no record gets the next one
    assert order == ["commit", "mark_full"], order
    c = calls("commit")[0]
    assert same(c.args[1], site._commit.store) and same(c.args[2], site._commit.floor)
    assert same(c.args[3], site._commit.placement) and c.args[4] == 41 and c.args[5] == 5000
    m = calls("mark_full")[0]
    assert m.args[3] == "*" and m.args[4] == 5000 and m.args[2].z == 72 and m.args[5].east == 0
    saved = W.persist[KEY]
    assert saved is not None and saved.v == 1
    by_z = {f.z: f for f in lst(saved.floors)}
    assert set(by_z) == {70, 72}
    assert by_z[70].free.east == 31 and by_z[70].free.south == 4
    assert by_z[70].runs[1].len == 9 and by_z[70].slots[1].pid == 41
    assert by_z[72].full["*"] == 5000
    assert by_z[70].id == 1 == site.floor.id and by_z[72].id == 2 and saved.next == 3
    last = saved.last
    assert last.ok is True and last.tick == 5000 and last.kind == "bedrooms" and last.elevation == 70
    assert last.why is None


@test("floor_commit: a mark on the placed floor itself is passed over; junk marks too")
def _():
    need()
    site = new_site()
    site._commit.marks = ev("""{{z = 70, sx = 60, sy = 60, tag = 'homes'}, 'junk', {z = 71}, {z = 73, sx = 60, sy = 60, tag = 'homes'}}""")
    ok = B.floor_commit(site, 41)
    assert (ok[0] if isinstance(ok, tuple) else ok) is True
    saved = W.persist[KEY]
    by_z = {f.z: f for f in lst(saved.floors)}
    assert set(by_z) == {70, 73} and len(calls("mark_full")) == 1
    assert by_z[70].full.homes is None and by_z[73].full.homes == 5000
    assert sorted(f.id for f in lst(saved.floors)) == [1, 2]


@test("floor_commit: onto a floor already in the record")
def _():
    need()
    put_record()
    store = B.load_floors()[0]
    site = ev("""function(store)
        return {z = 70, floor = {id = 1}, _commit = {store = store, floor = store.floors[1],
                placement = {runs = {}, slots = {{run = 1, side = -1, u = 9, w = 5, d = 5, kind = 'workshops', role = 'shop'}}},
                free = {north = 0, east = 14, south = 0, west = 9, tick = 5000}}}
    end""")(store)
    ok = B.floor_commit(site, 57)
    assert (ok[0] if isinstance(ok, tuple) else ok) is True
    saved = W.persist[KEY]
    assert len(saved.floors) == 2 and len(saved.floors[1].slots) == 3 and saved.floors[1].slots[3].pid == 57
    assert saved.floors[1].free.east == 14
    assert saved.fallbacks == 2                         # a commit is no fallback
    assert saved.last.ok is True and saved.last.elevation == 70 and saved.last.kind is None


@test("floor_commit: a store that is not writable saves nothing")
def _():
    need()
    put_record("{v = 99, floors = {}}")                 # the saved record is newer
    before = dump(W.persist[KEY])
    ok, why = B.floor_commit(new_site(), 41)
    assert ok is False and "newer" in why
    assert dump(W.persist[KEY]) == before and not calls("commit") and not calls("mark_full")
    _reset()                                            # the site's own store is newer
    ok, why = B.floor_commit(new_site("{v = 99, next = 1, floors = {}}"), 41)
    assert ok is False and "newer" in why
    assert W.persist[KEY] is None and not calls("commit")


@test("floor_commit: ai-floorplan missing, no _commit, or commit raising: false and why, nothing saved")
def _():
    need()
    S.mods["ai-floorplan"] = "raise"
    ok, why = B.floor_commit(new_site(), 41)
    assert ok is False and "ai-floorplan" in why and W.persist[KEY] is None
    _reset()
    for site in (None, "x", ev("{}"), ev("{_commit = 5}"), ev("{_commit = {store = {v = 1}}}")):
        ok, why = B.floor_commit(site, 41)
        assert ok is False and why, site
    S.mods["ai-floorplan"].commit = ev("function() error('bad placement') end")
    ok, why = B.floor_commit(new_site(), 41)
    assert ok is False and "bad placement" in why
    assert W.persist[KEY] is None


# --- 5. floor_fallback, floor_release -------------------------------------------

@test("floor_fallback: counted, last set, marks on floors with and without a record, saved")
def _():
    need()
    put_record()
    marks = ev("""{{z = 70, sx = 60, sy = 60, tag = 'homes', free = {north = 0, east = 2, south = 0, west = 1, tick = 5000}},
                   {z = 75, sx = 60, sy = 60, tag = '*'},
                   'junk', {z = 'a', tag = 'x'}}""")
    B.floor_fallback("dining", "floor 1: no room; floor 3: no hall", 70, marks)
    saved = W.persist[KEY]
    assert saved.fallbacks == 3
    last = saved.last
    assert last.ok is False and last.tick == 5000 and last.kind == "dining" and last.elevation == 70
    assert last.why == "floor 1: no room; floor 3: no hall"
    by_z = {f.z: f for f in lst(saved.floors)}
    assert set(by_z) == {70, 72, 75}
    assert by_z[70].id == 1 and by_z[70].full.homes == 5000 and by_z[70].free.east == 2
    assert by_z[75].id == 3 and by_z[75].full["*"] == 5000 and by_z[75].stair.x == 60
    assert saved.next == 4
    assert len(calls("mark_full")) == 2 and len(calls("new_floor")) == 1


@test("floor_fallback: on an empty save, with no marks; why cut to 300 characters")
def _():
    need()
    B.floor_fallback("workshops", "x" * 1000, 12, None)
    saved = W.persist[KEY]
    assert saved.fallbacks == 1 and len(saved.floors) == 0
    assert len(saved.last.why) == 300 and saved.last.kind == "workshops" and saved.last.elevation == 12
    B.floor_fallback("workshops", None, None, ev("{}"))
    assert W.persist[KEY].fallbacks == 2 and W.persist[KEY].last.why is None


@test("floor_fallback: never raises, and writes nothing to a newer record or without ai-floorplan")
def _():
    need()
    put_record("{v = 99, floors = {}}")
    before = dump(W.persist[KEY])
    B.floor_fallback("dining", "no room", 70, ev("{{z = 70, sx = 60, sy = 60, tag = 'homes'}}"))
    assert dump(W.persist[KEY]) == before
    _reset()
    S.mods["ai-floorplan"] = "raise"
    B.floor_fallback("dining", "no room", 70, None)
    assert W.persist[KEY] is None
    _reset()
    S.mods["ai-floorplan"].mark_full = ev("function() error('bad mark') end")
    B.floor_fallback(ev("{}"), ev("{}"), "high", ev("{{z = 70, sx = 60, sy = 60, tag = 'homes'}}"))
    assert W.persist[KEY].fallbacks == 1                # the level is counted, the bad mark passed over
    B.floor_fallback(None, None, None, "marks")
    assert W.persist[KEY].fallbacks == 2


@test("floor_release: release called with the project's id, the record saved")
def _():
    need()
    put_record()
    n = B.floor_release(ev("{id = 5, kind = 'bedrooms', floor = {id = 1}}"))
    assert n == 2
    c = calls("release")
    assert len(c) == 1 and c[0].args[2] == 5
    saved = W.persist[KEY]
    assert all(s.dead is True for s in lst(saved.floors[1].slots))
    assert B.floor_release(ev("{id = 5}")) == 0         # nothing left to release


@test("floor_release: 0 and nothing written for junk, a newer record, or without ai-floorplan")
def _():
    need()
    for p in (None, "x", ev("{}")):
        assert B.floor_release(p) == 0
    assert W.persist[KEY] is None and not calls("release")
    put_record("{v = 99, floors = {}}")
    before = dump(W.persist[KEY])
    assert B.floor_release(ev("{id = 5}")) == 0
    assert dump(W.persist[KEY]) == before and not calls("release")
    put_record()
    S.mods["ai-floorplan"] = "raise"
    assert B.floor_release(ev("{id = 5}")) == 0
    _reset()
    put_record()
    S.mods["ai-floorplan"].release = ev("function() error('boom') end")
    assert B.floor_release(ev("{id = 5}")) == 0


# --- 6. the report -------------------------------------------------------------

def keys(t):
    return sorted(str(k) for k in t.keys())


@test("floors_report: an empty save is the empty answer")
def _():
    need()
    r = B.floors_report()
    assert keys(r) == ["count", "fallbacks", "hall_tiles", "list", "mode", "rooms", "v"], keys(r)
    assert r.v == 1 and r.mode == "classic" and r.count == 0 and r.rooms == 0 and r.hall_tiles == 0
    assert r.fallbacks == 0 and len(r.list) == 0
    settings("hallway")
    assert B.floors_report().mode == "hallway"


PROJECTS = """{next_id = 90, list = {
    {id = 5,  kind = 'bedrooms',  phase = 'done',      z = 70, floor = {id = 1, slots = 2, hall = 12}},
    {id = 70, kind = 'dining',    phase = 'done',      z = 70},
    {id = 72, kind = 'workshops', phase = 'dig',       z = 70},
    {id = 81, kind = 'storage',   phase = 'cancelled', z = 70},
    {id = 83, kind = 'bedrooms',  phase = 'dig',       z = 70, floor = {id = 9}},
    {id = 60, kind = 'tombs',     phase = 'done',      z = 71},
    {id = 61, kind = 'well',      phase = 'done',      z = 72},
    {id = 62, kind = 'farm',      phase = 'done'},
    'junk'},
  old_areas = {{x1 = 1, y1 = 1, x2 = 9, y2 = 9, z = 70}, {x1 = 20, y1 = 1, x2 = 29, y2 = 9, z = 70},
               {x1 = 1, y1 = 1, x2 = 9, y2 = 9, z = 71}, 'junk', {x1 = 1}}}"""


@test("floors_report: a floor's row gains others and old_boxes; the totals")
def _():
    need()
    settings("hallway")
    put_record()
    put_projects(PROJECTS)
    r = B.floors_report()
    assert r.v == 1 and r.mode == "hallway"
    assert r.count == 1, "only the floor with a run counts"
    assert r.rooms == 2 and r.hall_tiles == 36 and r.fallbacks == 2
    assert r.last.why == "floor 1: no room" and r.last.ok is False
    rows = lst(r.list)
    assert [x.id for x in rows] == [1, 2]
    a, b = rows
    # the floor's own project (5) is left out; projects on another z too; newest first
    assert lst(a.others) == [83, 81, 72, 70], lst(a.others)
    assert a.old_boxes == 2
    assert a.elevation == 70 and a.z == 70 and a.stair.x == 60 and a.hub == "dug" and a.width == 3
    assert a.free.east == 20 and a.arms[1].len == 12
    assert lst(b.others) == [61] and b.old_boxes == 0 and b.no_hall is True and len(b.arms) == 0
    s = calls("summary")[0]
    assert same(s.args[2], B.ez) and s.args[3] == 5000 and s.args[4] == 28


@test("floors_report: others stop at 30, the newest kept; elevations follow the offset")
def _():
    need()
    put_record()
    put_projects("(function() local l = {} for i = 1, 45 do l[i] = {id = 100 + i, kind = 'storage', phase = 'done', z = 70} end "
                 "return {next_id = 200, list = l} end)()")
    real = B.elevation_offset
    try:
        B.OFFSET = 0
        B.elevation_offset = ev("function() return -58 end")
        r = B.floors_report()
        assert B.OFFSET == -58
    finally:
        B.elevation_offset = real
        B.OFFSET = 0
    a = r.list[1]
    assert a.elevation == 12 and a.z == 70
    assert lst(a.others) == list(range(145, 115, -1))


@test("floors_report: a newer record is the empty answer with newer")
def _():
    need()
    put_record("{v = 99, fallbacks = 6, floors = {{id = 1, z = 70}}}")
    r = B.floors_report()
    assert r.newer is True and r.count == 0 and r.rooms == 0 and r.hall_tiles == 0 and r.fallbacks == 0
    assert len(r.list) == 0 and r.v == 1 and r.error is None
    assert not calls("summary")


@test("floors_report: ai-floorplan missing, or its summary raising, is the empty answer with error")
def _():
    need()
    put_record()
    S.mods["ai-floorplan"] = "raise"
    r = B.floors_report()
    assert "ai-floorplan" in r.error and r.count == 0 and len(r.list) == 0 and r.v == 1 and r.mode == "classic"
    _reset()
    put_record()
    S.mods["ai-floorplan"].summary = ev("function() error('bad rows') end")
    r = B.floors_report()
    assert "bad rows" in r.error and r.count == 0 and len(r.list) == 0


@test("floors_report: writes nothing and reads no map tile")
def _():
    need()
    settings("hallway")
    put_record()
    put_projects(PROJECTS)
    reads = [0]
    real = B.tile_info

    def counting(*a):
        reads[0] += 1
        return real(*a)

    B.tile_info = counting
    before = dump(W.persist)
    try:
        for _ in range(2):
            r = B.floors_report()
            assert r.count == 1
        B.util_module().report_begin()                  # and inside a report, as the bridge calls it
        r = B.floors_report()
        assert r.count == 1 and lst(r.list[1].others) == [83, 81, 72, 70]
    finally:
        B.util_module().report_end()
        B.tile_info = real
    assert reads[0] == 0, "the report read %d map tiles" % reads[0]
    assert dump(W.persist) == before, "the report wrote to the save"
    assert sorted(str(k) for k in W.persist.keys()) == sorted([KEY, PKEY])
    assert len(W.calls) == 0                            # no blueprint either


@test("floors_report: on an empty save writes nothing")
def _():
    need()
    B.floors_report()
    assert W.persist[KEY] is None and len(list(W.persist.keys())) == 0


# --- 7. junk in the saved record --------------------------------------------------

JUNK = ["'a string'", "{1, 2, 3}", "{'a', {b = 1}}", "7", "true",
        "{v = 'one', floors = 5}", "{v = 1, floors = 'none', fallbacks = 'many', last = 'never'}",
        "{v = 1, floors = {'junk', 7}, fallbacks = {}}", "{v = 1}"]


@test("every function survives junk in the saved floor record")
def _():
    need()
    for junk in JUNK:
        _reset()
        put_record(junk)
        put_projects(PROJECTS)
        store, writable = B.load_floors()[:2]
        assert store is not None and writable is True, junk
        r = B.floors_report()
        assert r.count == 0 and r.mode == "classic", junk
        assert B.floor_release(ev("{id = 5}")) == 0, junk
        B.floor_fallback("dining", "no room", 70, ev("{{z = 70, sx = 60, sy = 60, tag = 'homes'}}"))
        assert W.persist[KEY].fallbacks == 1, junk
        ok = B.floor_commit(new_site(), 41)
        assert (ok[0] if isinstance(ok, tuple) else ok) is True, junk
        r = B.floors_report()
        assert r.count == 1 and r.rooms == 1 and r.hall_tiles == 27, junk
        B.save_floors(B.load_floors()[0])


@test("the report survives junk in the saved projects and junk rows from the summary")
def _():
    need()
    put_record()
    for junk in ("'a string'", "{1, 2}", "{list = 'none', old_areas = 4}", "{list = {{id = 'x', z = 70}, {z = 70}, 5}}"):
        put_projects(junk)
        r = B.floors_report()
        assert r.count == 1 and len(r.list) == 2, junk
        assert lst(r.list[1].others) == [] and r.list[1].old_boxes == 0, junk
    LUA.execute("STAND.rows = function() return {'junk', {id = 4, z = 70, rooms = 'two', hall = 9, arms = {{}}}, {}} end")
    r = B.floors_report()
    assert len(r.list) == 2 and r.count == 1 and r.rooms == 0 and r.hall_tiles == 9


if __name__ == "__main__":
    finish()

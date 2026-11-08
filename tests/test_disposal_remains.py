"""(0.105.28, remains) Six fresh forts raised a false Needs you note right
after 0.105.27 started: "335-415 items lie forbidden for no reason the game
gives". All were REMAINS (vermin and small creatures' remains) in the
caverns, forbidden by the "forbid other dead" standing order: the game's,
not the player's.

 1. ai-util forbidden_reason: REMAINS (every dead creature's item type DF 50
    has: CORPSE, CORPSEPIECE, REMAINS) are bodies: another's are other_dead,
    counted under forbidden.corpses, not by_reason; the fort's race's are
    its own and empty_dump never removes them; unforbid_items never touches them;
 2. the census: forbidden.unknown_reachable (unknown, not in the caverns, not
    unreachable) and unknown_where {surface, inside};
 3. the brain: the Needs you note fires on unknown_reachable only (else
    by_reason.unknown), and says where the items lie.

    python tests/test_disposal_remains.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import test_disposal_actions as A      # ai-disposal on a fake fort  # noqa: E402
import test_disposal_brain as BR       # the brain's disposal state  # noqa: E402
import test_disposal_census as C       # ai-census on a fake fort  # noqa: E402

mk, opts, skipped = A.mk, A.opts, A.skipped

# ai-util on a fake game: test_disposal_fixes' UTIL_FAKE, read from its source
# (importing that file would run its tests again here)
_FIXES = (ROOT / "tests" / "test_disposal_fixes.py").read_text(encoding="utf-8")
UTIL_FAKE = re.search(r'^UTIL_FAKE = r"""(.*?)"""', _FIXES, re.S | re.M).group(1)
UTIL = (ROOT / "lua" / "ai-util.lua").read_text(encoding="utf-8")

# The census' fake fort, with REMAINS: 400 of vermin (race 3) in the caverns
# (x >= 70), one of vermin inside, one of the fort's race (1) inside.
REMAINS_FAKE = C.FAKE.replace(
    "local TYPES = {'BOULDER', 'AMMO', 'CORPSE', 'CORPSEPIECE', 'WEAPON', 'PANTS', 'BAR'}",
    "local TYPES = {'BOULDER', 'AMMO', 'CORPSE', 'CORPSEPIECE', 'WEAPON', 'PANTS', 'BAR', 'REMAINS'}",
).replace(
    "local UNITS = ",
    "for i = 1, 400 do table.insert(ITEMS, it('REMAINS', 70 + i % 20, 10 + i // 20, 10, nil, {race = 3})) end\n"
    "table.insert(ITEMS, it('REMAINS', 33, 33, 10, nil, {race = 3}))\n"
    "table.insert(ITEMS, it('REMAINS', 34, 34, 10, nil, {race = 1}))\n"
    "local UNITS = ",
)
assert REMAINS_FAKE.count("REMAINS") >= 4


def remains_census():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(REMAINS_FAKE, C.CENSUS, lua.table_from({}), C.UTIL)
    return env.census()["items"].forbidden


def brain_census(fb_over: dict):
    s, m = BR.state()
    fb = m.census["items"]["forbidden"]
    fb.update(fb_over)
    return BR.run(s, m)


def you(notes):
    return [n for n in notes if n.startswith("[you] ")]


# --- 1. the classifier ---------------------------------------------------------------------------

@test("1. ai-util: REMAINS of another race are other_dead bodies; of the fort's race its own; fort_remains keeps those")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(UTIL_FAKE, UTIL, lua.table_from({}), lua.table_from({}))
    ctx = env.forbid_context()
    rat = env.item("REMAINS", 80, 80, 5, None, lua.table_from({"race": 3}))
    dwarf = env.item("REMAINS", 81, 80, 5, None, lua.table_from({"race": 1}))
    assert tuple(env.forbidden_reason(rat, ctx)) == ("other_dead", "other")
    assert tuple(env.forbidden_reason(dwarf, ctx)) == ("own_dead", "own")
    assert env.fort_remains(dwarf, "REMAINS", ctx) and not env.fort_remains(rat, "REMAINS", ctx)
    assert env.DEAD_KINDS["REMAINS"] and env.DEAD_KINDS["CORPSE"] and env.DEAD_KINDS["CORPSEPIECE"]


@test("1. a dead rat's remains beside a helm don't make the helm another's gear (only bodies and parts do)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(UTIL_FAKE, UTIL, lua.table_from({}), lua.table_from({}))
    env.df["global"]["world"]["items"]["other"]["REMAINS"] = lua.table_from({})
    ctx = env.forbid_context()
    env.item("REMAINS", 20, 20, 5, None, lua.table_from({"race": 3}))
    helm = env.item("HELM", 21, 20, 5)
    assert env.forbidden_reason(helm, ctx)[0] == "unknown"


@test("1. empty_dump removes a vermin's remains in the dump, never the remains of the fort's race")
def _():
    lua, env, w = A.world()
    w.dump(50, 10, 10, 150)
    rat = mk(lua, w, kind="REMAINS", race=3, flags={"forbid": True}, pos=(10, 10, 150))
    dwarf = mk(lua, w, kind="REMAINS", race=1, flags={"forbid": True}, pos=(11, 10, 150))
    r = env.empty_dump(opts(lua), False)
    assert set(w.removed.values()) == {rat.id}, (list(w.removed.values()), skipped(r))
    assert not dwarf.flags.removed and skipped(r).get("own_remains") == 1, skipped(r)


@test("1. unforbid_items and mark_dump leave forbidden REMAINS as they are, as they do bodies")
def _():
    lua, env, w = A.world()
    w.dump(50, 10, 10, 150)
    rats = [mk(lua, w, kind="REMAINS", race=3, flags={"forbid": True}, pos=(30 + i, 30, 150)) for i in range(3)]
    env.unforbid_items(opts(lua, reasons=["other_dead"], player_items=True), False)
    env.mark_dump(opts(lua, reasons=["other_dead", "free"], player_items=True), False)
    for it in rats:
        assert it.flags.forbid and not it.flags.dump and not it.flags.removed, dict(it.flags)


# --- 2. the census ------------------------------------------------------------------------------

@test("2. census: 400 cavern REMAINS and 2 inside count as corpses (403 other: 401 vermin's and the base fort's two; 2 own), none as unknown")
def _():
    fb = remains_census()
    assert dict(fb.corpses) == {"own": 2, "other": 403}, dict(fb.corpses)
    assert fb.by_reason.unknown == 5, dict(fb.by_reason)          # the base fort's five, as before
    assert fb.by_type.REMAINS == 402, dict(fb.by_type)


@test("2. census: unknown_reachable counts the unknown items neither in the caverns nor unreachable, and where")
def _():
    _, env = C.world()
    fb = C.forbidden(env)
    # unknown: pile ammo and the boulder by the invader (inside), the artifact bar (surface),
    # a cavern boulder and an unreachable one (not counted)
    assert fb.unknown_reachable == 3, fb.unknown_reachable
    assert dict(fb.unknown_where) == {"surface": 1, "inside": 2}, dict(fb.unknown_where)
    assert remains_census().unknown_reachable == 3


# --- 3. the brain -------------------------------------------------------------------------------

@test("3. fort D: 415 unknown in the caverns and unreachable (unknown_reachable 0): no Needs you note")
def _():
    got, notes = brain_census({"by_reason": {"own_dead": 0, "used_ammo": 0, "other_dead": 0, "dumped": 0, "ai": 0,
                                             "unknown": 415},
                               "unknown_reachable": 0, "unknown_where": {"surface": 0, "inside": 0}})
    assert not you(notes), notes


@test("3. the fix's census of fort D: 415 cavern REMAINS as corpses: no Needs you note, no action on them")
def _():
    got, notes = brain_census({"total": 415, "by_type": {"REMAINS": 415},
                               "by_reason": {"own_dead": 0, "used_ammo": 0, "other_dead": 0, "dumped": 0, "ai": 0,
                                             "unknown": 0},
                               "by_where": {"surface": 0, "inside": 0, "caverns": 415, "near_danger": 0,
                                            "unreachable": 415},
                               "corpses": {"own": 0, "other": 415}, "metal": 0, "worn": 0, "valuable": 0,
                               "unknown_reachable": 0, "unknown_where": {"surface": 0, "inside": 0}})
    assert not you(notes), notes
    assert "disposal_unforbid" not in got and "disposal_melt" not in got, sorted(got)


@test("3. 300 unknown reachable items past the threshold: the note, saying where they lie")
def _():
    _, notes = brain_census({"by_reason": {"own_dead": 0, "used_ammo": 0, "other_dead": 0, "dumped": 0, "ai": 0,
                                           "unknown": 700},
                             "unknown_reachable": 300, "unknown_where": {"surface": 260, "inside": 40}})
    n = you(notes)
    assert n and "300 items" in n[0] and "on the surface (260) and inside the fort (40)" in n[0], notes
    assert "may be yours" in n[0] and "disposal_player_items" in n[0], n


@test("3. a census without unknown_reachable falls back on by_reason.unknown")
def _():
    _, notes = brain_census({"by_reason": {"own_dead": 0, "used_ammo": 0, "other_dead": 0, "dumped": 0, "ai": 0,
                                           "unknown": 450}})
    n = you(notes)
    assert n and "450 items" in n[0] and "about the map" in n[0], notes
    _, notes = brain_census({"by_reason": {"own_dead": 0, "used_ammo": 0, "other_dead": 0, "dumped": 0, "ai": 0,
                                           "unknown": 150}})
    assert not you(notes), notes


if __name__ == "__main__":
    finish()

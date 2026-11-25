"""(0.105.114 item15) The fight watcher leaves werebeasts' fights alone.

E, 25 Nov 07:38-08:05 (0.105.113): a werepanther outbreak among citizens. A
slain werepanther citizen (civ 300, race NIGHT_CREATURE_55, enemy.normal_race
DWARF) read 'dead' (the fort's own dead) before the transformed test, so its
conflict was the fort's own with died set: capped and the soldiers separated
at once (349 separated, 46 died in 25 minutes). The were test now comes first,
dead or alive; a citizen carrying a were syndrome (class WERECURSE, or a
BODY_TRANSFORMATION effect: E's 367) or a citizen of another race than the
fort's that is a night creature is not the fort's own either. A pet DF reads
as neither tame nor domesticated (an owner, isPet, a training level) is still
a pet.

Uses test_item1_fights.py's fake game (lupa: run on the PC).

    python tests/test_i114_fights.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402
import ast  # noqa: E402


def _const(fname: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / fname).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"no {name} in {fname}")


FAKE = _const("test_item1_fights.py", "FAKE")
P112 = _const("test_i112_fights.py", "PRELUDE")

PRELUDE = P112 + r"""
E.df.global.plotinfo.race_id = 1
E.df.creature_interaction_effect_type = {BODY_TRANSFORMATION = 24, ADD_TAG = 17}
E.df.animal_training_level = {WildUntamed = 9}
local SYN = {
    [367] = {syn_class = W.vec({{value = 'WERECURSE'}}), ce = W.vec({{getType = function() return 24 end}})},
    [368] = {syn_class = W.vec({}), ce = W.vec({{getType = function() return 24 end}})},
    [60] = {syn_class = W.vec({}), ce = W.vec({{getType = function() return 17 end}})},
}
E.df.syndrome = {find = function(id) return SYN[id] end}
function W.syn(u, ids)
    local l = {}
    for _, id in ipairs(ids) do table.insert(l, {type = id, ticks = 10}) end
    u.syndromes = {active = W.vec(l)}
end
"""


def case(name: str, code: str):
    @test("lua: " + name)
    def _():
        need_lua()
        from lupa.lua53 import LuaRuntime
        lua = LuaRuntime(unpack_returned_tuples=True)
        r = lua.execute(FAKE, module_src("ai-fights.lua"), PRELUDE + code)
        assert r == "ok", r
    return _


case("E's slain werepanther citizen: its conflict is not the fort's own, nobody separated or capped", r"""
W.unit{id = 1}; W.unit{id = 2}
W.unit{id = 19508, name = 'Dentconstruct, Werepanther Planter', race = 1301, enemy = {normal_race = 1}, dead = true}
local _, ev = W.conflict(197690, {{units = {19508}, level = 6}, {units = {1, 2}, level = 6}})
E.pass(5000)
local lv = W.levels(ev)
assert(lv[1] == 6 and lv[2] == 6, 'not capped')
assert(#W.removed == 0 and E.state().counts.seen == 0 and E.state().counts.died == 0, 'left alone')
local k, why = E.unit_kind(W.units[19508])
assert(k == nil and why == 'transformed', tostring(why))
""")

case("a living transformed citizen (still isCitizen) and its fight: left alone, the soldiers kept", r"""
W.unit{id = 1}; W.unit{id = 2}; W.unit{id = 3}
W.unit{id = 9, race = 1301, enemy = {normal_race = 1}}   -- citizen = true by default
W.conflict(800, {{units = {9}, level = 5}, {units = {1, 2}, level = 5}})
W.conflict(801, {{units = {2}, level = 3}, {units = {3}, level = 3}})
E.pass(5000)
for _, id in ipairs(W.removed) do assert(id ~= 1 and id ~= 2 and id ~= 9, 'removed ' .. id) end
assert(E.unit_kind(W.units[9]) == nil)
""")

case("a citizen of another race that is a night creature (normal_race unread): transformed", r"""
local u = W.unit{id = 9, race = 1301, night = true}
local k, why = E.unit_kind(u)
assert(k == nil and why == 'transformed', tostring(why))
""")

case("a citizen bitten (were syndrome by class or by body transformation): not the fort's own", r"""
W.unit{id = 1}
local a = W.unit{id = 18451}; W.syn(a, {60, 367})
local b = W.unit{id = 18452}; W.syn(b, {368})
local c = W.unit{id = 20}; W.syn(c, {60})
local ka, wa = E.unit_kind(a); local kb, wb = E.unit_kind(b)
assert(ka == nil and wa == 'were syndrome' and kb == nil and wb == 'were syndrome', tostring(wa) .. tostring(wb))
assert(E.unit_kind(c) == 'citizen', 'drink is no curse')
W.conflict(810, {{units = {1}, level = 5}, {units = {18451}, level = 5}})
E.pass(5000)
assert(#W.removed == 0)
""")

case("a dead plain citizen still makes the fight the fort's own (separated at once)", r"""
W.unit{id = 1}; W.unit{id = 2}; W.unit{id = 3, dead = true}
W.conflict(820, {{units = {1, 2}, level = 3}, {units = {3}, level = 3}})
E.pass(5000)
assert(#W.removed == 2 and E.state().counts.died == 1)
""")

case("a pet DF reads as neither tame nor domesticated: an owner or a training level makes it the fort's", r"""
W.unit{id = 1}; W.unit{id = 2}
local ram = W.unit{id = 20003, name = 'Ram', animal = true, citizen = false, relationship_ids = {PetOwner = 17886}}
local ewe = W.unit{id = 20004, name = 'Ewe', animal = true, citizen = false, training_level = 7}
local wild = W.unit{id = 20005, name = 'Wild', animal = true, citizen = false, civ_id = -1, training_level = 9}
local stray = W.unit{id = 20006, name = 'Stray', animal = true, citizen = false, training_level = 9}
assert(E.unit_kind(ram) == 'pet' and E.unit_kind(ewe) == 'pet', 'owned / trained')
assert(E.unit_kind(wild) == nil and E.unit_kind(stray) == nil, 'wild ones stay wild')
W.conflict(830, {{units = {1}, level = 5}, {units = {20003}, level = 5}})
E.pass(5000)
local got = {}
for _, id in ipairs(W.removed) do got[id] = true end
assert(got[1] and got[20003], 'separated with the ram')
""")


@test("ai-fights.lua under 60,000 bytes without CR")
def _():
    n = len((ROOT / "lua" / "ai-fights.lua").read_bytes().replace(b"\r", b""))
    assert n < 60000, n


if __name__ == "__main__":
    finish()

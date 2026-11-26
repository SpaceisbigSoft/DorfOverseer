"""(0.105.119 item34) The fight watcher and a were-bitten dwarf's strangling hold.

F, 25 Nov 17:27-17:28 (0.105.118): Besmar "Stockadecreed", Tavern Keeper,
turned into a weremole at 17:27:32, killed a dog, turned back into a dwarf at
17:27:59 and at 17:28:10 strangled Tosid "Balancedfenced", Mason (SUFFOCATE),
himself bitten (both in moon_cell's list at 17:27:54). The watcher read both
as 'were syndrome' (never the fort's own) and its citizen scan skipped them:
F's fights counts showed seen 0, chokes 0. Now a dwarf of the fort in dwarf
form (a citizen, or bitten: were syndrome only, not transformed) choking or
suffocating another such dwarf, one of the two bitten, has both taken out of
their conflicts (kind 'cursed_choke', counts cursed_chokes and chokes). A
transformed beast's fights stay the were rules'.

C and D (Edzul "Salvegod" 17:51, Bomrek "Torchtamed" 15:50) were berserkers
after failed moods, struck down by citizens: DF's own (the handoff: berserk
ones stay as DF handles them). The watcher saw those conflicts only once the
berserker was dead; its log rows now say berserk for the dead too.

Uses test_item1_fights.py's fake game (lupa: run on the PC).

    python tests/test_i119_fights_cursed.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402
import planner_tantrums as PT  # noqa: E402
from planner_core import Memory  # noqa: E402


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
E.df.creature_interaction_effect_type = {BODY_TRANSFORMATION = 24}
local SYN = {[367] = {syn_class = W.vec({{value = 'WERECURSE'}}), ce = W.vec({{getType = function() return 24 end}})}}
E.df.syndrome = {find = function(id) return SYN[id] end}
function W.bite(u) u.syndromes = {active = W.vec({{type = 367, ticks = 10}})}; return u end
function W.last(kind)
    for i = #E.state().log, 1, -1 do if E.state().log[i].kind == kind then return E.state().log[i] end end
end
function W.gone(id) for _, x in ipairs(W.removed) do if x == id then return true end end return false end
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


case("F's weremole in dwarf form strangling a bitten mason: both out of their conflicts, logged and counted", r"""
local tosid = W.bite(W.unit{id = 16958, name = 'Tosid, Mason'})
local besmar = W.bite(W.unit{id = 17284, name = 'Besmar, Tavern Keeper'})
W.grapple(besmar, 16958, 1)
W.conflict(900, {{units = {17284}, level = 3}, {units = {16958}, level = 3}})
E.pass(5000)
assert(W.gone(17284) and W.gone(16958), 'both separated')
local e = W.last('cursed_choke')
assert(e and e.id == 17284 and e.target == 16958 and e.grapple == 'Choke' and e.separated == true, 'logged')
assert(E.state().counts.cursed_chokes == 1 and E.state().counts.chokes == 1, 'counted')
assert(E.report().counts.cursed_chokes == 1)
E.pass(5010)
local n = 0
for _, x in ipairs(E.state().log) do if x.kind == 'cursed_choke' then n = n + 1 end end
assert(n == 1, 'logged once a pair a while: ' .. n)
""")

case("a bitten dwarf suffocating a plain citizen, and a citizen choking a bitten one: both taken apart", r"""
W.unit{id = 1, name = 'Plain', suffocation = 2}
local a = W.bite(W.unit{id = 2, name = 'Bitten', attacks = {1}})
E.pass(5000)
assert(W.gone(1) and W.gone(2), 'suffocation')
W.removed = {}
local b = W.bite(W.unit{id = 3, name = 'Bitten too'})
local c = W.unit{id = 4, name = 'Wrestler'}
a.actions = nil
W.grapple(c, 3, 13)
E.pass(6000)
assert(W.gone(3) and W.gone(4), 'a citizen choking a bitten dwarf')
""")

case("left alone: a transformed beast, a bitten dwarf's plain blow, two plain citizens (the conflict rules')", r"""
W.unit{id = 1}
local beast = W.bite(W.unit{id = 9, race = 1301, enemy = {normal_race = 1}})
W.grapple(beast, 1, 1)
local b = W.bite(W.unit{id = 2, attacks = {1}})
E.pass(5000)
assert(#W.removed == 0 and W.last('cursed_choke') == nil, 'nothing for a beast or a plain blow')
assert((E.state().counts.cursed_chokes or 0) == 0)
""")

case("dry run: logged, nobody separated", r"""
W.unit{id = 1}
local b = W.bite(W.unit{id = 2})
W.grapple(b, 1, 1)
E.state().dry = true
E.pass(5000)
local e = W.last('cursed_choke')
assert(#W.removed == 0 and e and e.dry == true and e.separated == false, 'dry')
""")

case("a conflict seen once its berserker is dead: the dead row says berserk", r"""
W.unit{id = 1}; W.unit{id = 2}
W.unit{id = 18149, name = 'Edzul, Miner', dead = true, mood = 7}
W.conflict(31531, {{units = {18149}, level = 6}, {units = {1, 2}, level = 6}})
E.pass(5000)
local e = W.last('seen')
assert(e and e.units[1].id == 18149 and e.units[1].dead == true and e.units[1].berserk == true, 'berserk shown')
""")


@test("journal: a broken strangling hold with a bitten dwarf makes a fight line")
def _():
    m = Memory()
    sec = {"armed": True, "counts": {"capped": 0, "separated": 0, "cursed_chokes": 1}}
    out = PT.fight_journal({"fights": sec}, m)
    assert len(out) == 1 and out[0]["cursed_chokes"] == 1 and "were-bitten" in out[0]["text"], out
    assert PT.fight_journal({"fights": sec}, m) == []
    assert "cursed_chokes" in PT.FIGHT_COUNTS


@test("ai-fights.lua under 60,000 bytes without CR")
def _():
    n = len((ROOT / "lua" / "ai-fights.lua").read_bytes().replace(b"\r", b""))
    assert n < 60000, n


if __name__ == "__main__":
    finish()

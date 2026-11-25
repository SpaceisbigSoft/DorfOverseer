"""(0.105.112 item1) The fight watcher's wider side and strangling holds.

E, 24 Nov: 13 citizens were kept out of a separation, each also in a conflict
with a tame Blue Peahen or a Dog of the fort (`kept_why: "not a citizen"`);
B 15:03 "8 of 10 kept". The fort's own tame animals ('pet') and its guests at
peace ('guest') are now its side: such conflicts are capped and separated,
the animal or guest taken out too. Real enemies still keep the citizens.
A strangling hold (Attack wrestle_info.grapple_attack Choke/FollowStrangle)
or a citizen suffocating under an attack: separated at once, `choke` logged.

Uses test_item1_fights.py's fake game (lupa: run on the PC).

    python tests/test_i112_fights.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402


def _fake() -> str:
    tree = ast.parse((ROOT / "tests" / "test_item1_fights.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "FAKE" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("no FAKE in test_item1_fights.py")


FAKE = _fake()

# the DFHack calls this round reads, over the fake's units
PRELUDE = r"""
local U = E.dfhack.units
U.isTame = function(u) return u.tame == true end
U.isDomesticated = function(u) return false end
U.isResident = function(u) return u.resident == true end
U.isVisiting = function(u) return false end
U.isAgitated = function(u) return u.agitated == true end
U.isForgottenBeast = function(u) return u.fb == true end
U.isNightCreature = function(u) return u.night == true end
U.isGreatDanger = function(u) return u.fb == true end
E.df.wrestle_attack_type = {[-1] = 'NONE', [0] = 'JointLock', [1] = 'Choke', [2] = 'Takedown',
                            [11] = 'FollowLoosen', [13] = 'FollowStrangle'}
-- an Attack action of unit u on target tid with this grapple move
function W.grapple(u, tid, move)
    u.actions = W.vec({{id = 1, type = 1, data = {attack = {target_unit_id = tid, attack_body_part_id = 0,
        timer1 = 2, timer2 = 3, wrestle_info = {wrestle_type = -1, grapple_attack = move, grapple_a_bp = 4,
        grapple_d_bp = 3}}}}})
end
function W.why(id)
    for i = #E.state().log, 1, -1 do
        local e = E.state().log[i]
        for _, k in ipairs(e.kept_why or {}) do if k.id == id then return k.why end end
    end
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


case("E's peahen: a citizen also in a conflict with a pet of the fort is separated, the pet too", r"""
W.unit{id = 1}; W.unit{id = 2}
W.unit{id = 30, name = 'Blue Peahen', animal = true, tame = true, citizen = false}
local _, ev = W.conflict(700, {{units = {1}, level = 3}, {units = {2}, level = 3}})
local _, pev = W.conflict(701, {{units = {1}, level = 5}, {units = {30}, level = 5}})
E.pass(5000)
local lv = W.levels(pev)
assert(lv[1] == 3 and lv[2] == 3, 'the pet conflict capped')
local got = {}
for _, id in ipairs(W.removed) do got[id] = true end
assert(got[1] and got[30], 'citizen and peahen out')
local S = E.state()
assert(S.counts.others_separated == 1, 'the pet counted apart')
for _, e in ipairs(S.log) do assert(e.kept == nil, 'nobody kept') end
local rows = {}
for _, e in ipairs(S.log) do for _, r in ipairs(e.units or {}) do rows[r.id] = r end end
assert(rows[30].kind == 'pet' and rows[1].kind == nil, 'kind shown')
""")

case("a visitor and a resident at peace are the fort's side; a hostile visitor is not", r"""
W.unit{id = 1}; W.unit{id = 2}; W.unit{id = 3}
W.unit{id = 40, visitor = true, citizen = false}
W.unit{id = 41, resident = true, citizen = false}
W.unit{id = 42, visitor = true, citizen = false, flags2 = {visitor_uninvited = true}}
W.conflict(710, {{units = {1}, level = 5}, {units = {40}, level = 5}})
W.conflict(711, {{units = {2}, level = 5}, {units = {41}, level = 5}})
W.conflict(712, {{units = {3}, level = 5}, {units = {42}, level = 5}})
E.pass(5000)
local got = {}
for _, id in ipairs(W.removed) do got[id] = true end
assert(got[1] and got[40] and got[2] and got[41], 'the peaceful ones separated')
assert(not got[3] and not got[42], 'the hostile visitor left alone')
assert(E.unit_kind(W.units[40]) == 'guest' and E.unit_kind(W.units[41]) == 'guest')
local k, why = E.unit_kind(W.units[42])
assert(k == nil and why:find('hostile visitor'), why)
""")

case("real enemies still keep: wild, agitated, another civ's, forgotten beast; kept_why honest", r"""
W.unit{id = 2}
local cases = {
    {id = 50, animal = true, citizen = false, why = 'wild animal'},
    {id = 51, animal = true, tame = true, citizen = false, civ_id = 9, why = "another civ's animal"},
    {id = 52, animal = true, tame = true, citizen = false, agitated = true, why = 'hostile animal'},
    {id = 53, animal = true, citizen = false, fb = true, why = 'forgotten beast'},
    {id = 54, night = true, citizen = false, why = 'night creature'},
    {id = 55, invader = true, citizen = false, why = 'invader'},
}
for i, c in ipairs(cases) do
    local cid = 100 + i
    W.unit{id = cid}
    local o = W.unit{id = c.id, animal = c.animal, tame = c.tame, citizen = false, civ_id = c.civ_id,
                     agitated = c.agitated, fb = c.fb, night = c.night, invader = c.invader}
    W.conflict(720 + i, {{units = {cid}, level = 5}, {units = {c.id}, level = 5}})
    W.conflict(740 + i, {{units = {cid}, level = 5}, {units = {2}, level = 5}})
end
E.pass(5000)
for i, c in ipairs(cases) do
    local cid = 100 + i
    for _, id in ipairs(W.removed) do assert(id ~= cid and id ~= c.id, 'kept ' .. cid) end
    local w = W.why(cid)
    assert(w and w:find(c.why, 1, true), tostring(cid) .. ': ' .. tostring(w))
end
""")

case("pets or guests alone: no citizen in it, left alone", r"""
W.unit{id = 30, animal = true, tame = true, citizen = false}
W.unit{id = 40, visitor = true, citizen = false}
local _, ev = W.conflict(760, {{units = {30}, level = 5}, {units = {40}, level = 5}})
E.pass(5000)
local lv = W.levels(ev)
assert(lv[1] == 5 and #W.removed == 0 and E.state().counts.seen == 0)
""")

case("a dead pet of the fort in the fight: the living separated at once", r"""
W.unit{id = 1}
W.unit{id = 31, animal = true, tame = true, dead = true, citizen = false}
W.conflict(770, {{units = {1}, level = 3}, {units = {31}, level = 3}})
E.pass(5000)
assert(#W.removed == 1 and W.removed[1] == 1 and E.state().counts.died == 1)
""")

case("a strangling hold in a brawl: separated at once, choke logged; a young brawl without one waits", r"""
local a = W.unit{id = 1, name = 'Strangler'}; W.unit{id = 2, name = 'Victim'}
W.unit{id = 3}; W.unit{id = 4}
W.grapple(a, 2, 13)
W.conflict(780, {{units = {1}, level = 3}, {units = {2}, level = 3}})
W.conflict(781, {{units = {3}, level = 3}, {units = {4}, level = 3}})
E.pass(5000)
local got = {}
for _, id in ipairs(W.removed) do got[id] = true end
assert(got[1] and got[2], 'the choke broken up at once')
assert(not got[3] and not got[4], 'the plain young brawl waits')
local S = E.state()
local e = nil
for _, x in ipairs(S.log) do if x.activity_id == 780 then e = x end end
assert(e and e.choke and e.choke.how == 'hold' and e.choke.grapple == 'FollowStrangle', 'choke logged')
assert(e.choke.by == 1 and e.choke.victim == 2 and e.choke.by_name == 'Strangler', 'who')
assert(S.counts.chokes == 1)
""")

case("a Choke hold in sparring (Training) is left alone; a citizen suffocating under an attack is not", r"""
local a = W.unit{id = 1}; W.unit{id = 2}
W.grapple(a, 2, 1)
W.conflict(790, {{units = {1}, level = 2}, {units = {2}, level = 2}})
E.pass(5000)
assert(#W.removed == 0 and E.state().counts.chokes == 0, 'sparring choke')
W.units[2].counters.suffocation = 12
W.grapple(a, 2, 11)
E.pass(5010)
assert(#W.removed == 2, 'suffocating: separated')
local e = E.state().log[#E.state().log]
assert(e.choke.how == 'suffocation' and e.choke.suffocation == 12 and e.choke.grapple == 'FollowLoosen', 'how')
""")

case("the enum unreadable: the move's number still reads as a choke", r"""
E.df.wrestle_attack_type = nil
local a = W.unit{id = 1}; W.unit{id = 2}
W.grapple(a, 2, 1)
W.conflict(795, {{units = {1}, level = 4}, {units = {2}, level = 4}})
E.pass(5000)
local e = E.state().log[#E.state().log]
assert(e.choke and e.choke.grapple == 'Choke' and #W.removed == 2)
""")

case("dry: a choke logged, nothing removed or counted", r"""
local a = W.unit{id = 1}; W.unit{id = 2}
W.grapple(a, 2, 1)
W.conflict(799, {{units = {1}, level = 3}, {units = {2}, level = 3}})
E.pass(5000, {dry = true})
local e = E.state().log[#E.state().log]
assert(#W.removed == 0 and e.dry and e.choke and #e.separated == 2 and E.state().counts.chokes == 0)
""")


@test("ai-fights.lua under 60,000 bytes without CR")
def _():
    n = len((ROOT / "lua" / "ai-fights.lua").read_bytes().replace(b"\r", b""))
    assert n < 60000, n


if __name__ == "__main__":
    finish()

"""(0.105.35, group core) Nothing waits for the player: the core planner's
Needs you lines turned into the AI acting (the shelter tried again, the
first staircase looked for further out, marker-only dig tiles made real, a
stuck-again order cancelled again, a twice-started workshops level started
once more) or into plain notes of what it does; the ones the game truly won't
let the AI do (a barony's holder, the World screen's unrecorded steps) kept,
each saying what the AI does meanwhile. Fake reports, and the builder's fake
map in a real Lua engine (test_builder).

    python tests/test_r35_core.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import make_test, finish, code_has  # noqa: E402

import planner  # noqa: E402
from planner import Memory, plan, select, record, Proposal  # noqa: E402
import planner_world  # noqa: E402
import overseer  # noqa: E402
import test_planner as TPL  # noqa: E402   (fort(): the saved test fort)

test = make_test()
YOU = "[you] "
BRIDGE = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
ACTIONS_SRC = (ROOT / "lua" / "ai-bridge-actions.lua").read_text(encoding="utf-8")


def now_of(s):
    return s["date"]["year"] * 403200 + s["date"]["tick"]


def yous(notes):
    return [n for n in notes if n.startswith(YOU)]


# --- the shelter ---------------------------------------------------------------------

@test("shelter: refused twice, tried again after 3 days while a threat can reach the dwarves (was Needs you for good)")
def _():
    s = TPL.under_attack()
    s["civ_alert_ready"] = False
    m = Memory(shelter_attempts=2, shelter_tick=now_of(s) - 2 * 1200)
    p, notes = plan(s, m)
    assert "shelter" not in TPL.rules(p) and not yous(notes), notes
    assert any("refused the AI shelter" in n and "tried again in 1 day(s)" in n and "meanwhile" in n
               for n in notes), notes
    m.shelter_tick = now_of(s) - 3 * 1200
    p, notes = plan(s, m)
    sh = TPL.by_rule(p, "shelter")
    assert sh and sh[0].priority == 0 and any("setting up a shelter" in n for n in notes), (p, notes)
    record([(sh[0], {"ok": False, "error": "no room inside"})], s, m)
    assert m.shelter_attempts == 3 and m.shelter_tick == now_of(s)


@test("shelter: an old memory (two tries, no tick) tries once more; the player's switch off is kept, said")
def _():
    s = TPL.under_attack()
    s["civ_alert_ready"] = False
    assert TPL.by_rule(plan(s, Memory(shelter_attempts=2))[0], "shelter")
    s["settings"]["alert_shelter"] = False
    p, notes = plan(s, Memory(shelter_attempts=0))
    assert not TPL.by_rule(p, "shelter") and not yous(notes), notes
    assert any("off on the Rules tab" in n and "gates close" in n for n in notes), notes


# --- the first staircase ---------------------------------------------------------------

@test("founding: a refusal near the wagon is tried further out (wide); a wide refusal is Needs you, saying the AI keeps looking")
def _():
    s = TPL.fort()
    s["founding"] = {"stairs": False, "near": "the wagon"}
    m = Memory()
    p = TPL.by_rule(plan(s, m)[0], "found")
    record([(p[0], {"ok": False, "error": "no tile within 10 of the wagon (found: an aquifer below)"})], s, m)
    assert m.found_failure and not m.found_wide_failure
    p, notes = plan(s, m)
    p = TPL.by_rule(p, "found")
    assert p[0].action == {"type": "found_fort", "wide": True} and "further out" in p[0].reason, p
    assert not yous(notes)
    assert overseer.short(p[0].action) == "dig the first staircase, further from the wagon"
    record([(p[0], {"ok": False, "error": "no tile within 20 of the wagon (found: an aquifer below)"})], s, m)
    notes = plan(s, m)[1]
    ask = [n for n in yous(notes) if "can't start the fort" in n]
    assert ask and "looks again" in ask[0] and "yourself" not in ask[0], notes
    p = TPL.by_rule(plan(s, m)[0], "found")[0]
    record([(p, {"ok": True})], s, m)                               # dug: both failures cleared
    assert not m.found_failure and not m.found_wide_failure


@test("founding (Lua): an aquifer all round the dwarves: refused near, found_fort wide finds solid ground further out")
def _():
    import test_builder as TB
    TB._reset(False)
    TB.fresh_embark()
    TB.LUA.execute("""local W = ...
      for x = 38, 66 do for y = 36, 64 do W.set(x, y, 78, {aquifer = true}) end end""", TB.W)
    r = TB.B.found_fort(True)
    assert not r.ok and "aquifer" in r.error, dict(r)
    r = TB.B.found_fort(True, True)
    assert r.ok and r.dry_run and TB.designated_count() == 0, dict(r)
    assert max(abs(r.x - 52), abs(r.y - 50)) > 10, (r.x, r.y)
    r = TB.B.found_fort(False, True)
    assert r.ok and TB.W.get(r.x, r.y, 80).designated, dict(r)
    assert code_has(ACTIONS_SRC, "found_fort(a.dry_run == true, a.wide == true)")


# --- marker-only dig tiles -----------------------------------------------------------

@test("marker-only dig tiles (Lua): unmark_project_dig counts them on a dry run, then makes them real; nothing to do: refused")
def _():
    import test_builder as TB
    TB._reset(False)
    r = TB.start(kind="bedrooms", rooms=4, room_size=3)
    n = 0
    for t in TB.W.tiles.values():
        if t.designated:
            t.designated, t.marked = False, True
            n += 1
    made = []
    TB.LUA.execute("""local B, W, made = ...
      B.make_dig_real = function(x, y, z)
        local t = W.get(x, y, z)
        if not t.marked then return false end
        t.marked, t.designated = false, true
        table.insert(made, x .. ',' .. y .. ',' .. z)
        return true
      end""", TB.B, TB.W, TB.LUA.table())
    pid = TB.B.projects_report().open[1].id
    d = TB.B.unmark_project_dig(pid, True)
    assert d.ok and d.dry_run and d.tiles == n and TB.designated_count() == 0, dict(d)
    d = TB.B.unmark_project_dig(pid, False)
    assert d.ok and d.tiles == n and TB.designated_count() == n, dict(d)
    assert TB.B.projects_report().open[1].dig.marked == 0
    again = TB.B.unmark_project_dig(pid, False)
    assert again.rejected and "marker" in again.error, dict(again)
    assert TB.B.unmark_project_dig(999, True).rejected


@test("marker-only dig tiles: wired as a bridge action whose dry run passes while halted, with words on the panel")
def _():
    assert code_has(BRIDGE, "unmark_project_dig = act_unmark_project_dig,")
    assert code_has(BRIDGE, "'unmark_project_dig', -- (0.105.35)")
    assert code_has(ACTIONS_SRC, "reqscript('ai-builder').unmark_project_dig(id, a.dry_run == true)")
    assert overseer.short({"type": "unmark_project_dig", "project_id": 3}) != "unmark_project_dig"


@test("a level whose tiles are no longer designated: said with when the AI gives it up (was Needs you)")
def _():
    s = TPL.fort()
    s["projects"]["open"] = [{"id": 4, "kind": "storage", "phase": "dig", "started": {"year": s["date"]["year"],
                              "tick": max(0, s["date"]["tick"] - 1200)},
                              "dig": {"total": 50, "dug": 40, "stuck": 10, "marked": 0}}]
    p, notes = plan(s, Memory())
    line = [n for n in notes if "no longer designated" in n]
    assert line and "the AI gives it up in" in line[0] and not line[0].startswith(YOU), notes


# --- stuck again, workshops started twice ------------------------------------------------

@test("workshops level started twice and not seen built: held 56 days, then started once more (was held for good)")
def _():
    s = TPL.fort()
    m = Memory()
    m.shops_started = {"Kiln": 2}
    m.shops_seen = {"Kiln": 99}                  # (no more kilns seen than when it was started)
    prop = lambda: Proposal("industry", {"type": "start_project", "kind": "workshops", "shops": ["Kiln"]}, "x", 4)
    allowed, held = select([prop()], s, m)
    assert not allowed and any("started twice already" in h and "56 day(s)" in h and "Needs you" not in h
                               for h in held), held
    t = copy.deepcopy(s)
    t["date"]["tick"] += 56 * 1200
    allowed, held = select([prop()], t, m)
    assert [a for a in allowed if a.rule == "industry"], held
    assert m.shops_started["Kiln"] == 1 and "Kiln" not in m.shops_held_since


# --- plain notes ------------------------------------------------------------------------

@test("drink, meals and mandates the AI can't meet now: plain notes of what it does, not Needs you")
def _():
    s = TPL.fort()
    s["stocks"]["drink"] = 0
    s["supplies"]["brewable_plants"] = 0
    s["supplies"]["brewable_growths"] = 0
    notes = plan(s, Memory())[1]
    line = [n for n in notes if "no plants or fruit a still can brew" in n]
    assert line and "gathers" in line[0] and not any("still can brew" in n for n in yous(notes)), notes
    for n in yous(notes):
        assert "drink" not in n and "meals" not in n and "mandate" not in n, n
    s = TPL.fort()
    s["stocks"]["prepared_meals"] = 0
    s["supplies"]["food_stacks"] = 0
    s["orders"] = []
    notes = plan(s, Memory())[1]
    line = [n for n in notes if "too little raw food" in n]
    assert line and "fishes" in line[0] and not line[0].startswith(YOU), notes


@test("the deep: a forgotten beast in an open cavern, a werebeast, a kept vampire: said with what the AI does")
def _():
    s = TPL.fort()
    s["deep"] = {"caverns": [{"name": "Cavern1", "discovered": True, "open": True, "z_top": 40, "z_bottom": 30}],
                 "dangers": [{"name": "Ubbul", "kind": "forgotten beast", "layer": "Cavern1"}],
                 "cursed": [{"id": 5, "name": "Bomrek", "kind": "werebeast"}]}
    s["settings"]["seal_caverns"] = False
    s["settings"]["moon_cells"] = False
    notes = plan(s, Memory())[1]
    assert any(n.startswith("Cavern1 is open") and "sealing the caverns is off" in n for n in notes), notes
    assert any(n.startswith("Bomrek carries") and "moon cells are off" in n for n in notes), notes
    assert not [n for n in yous(notes) if "Cavern1" in n or "Bomrek" in n], notes


# --- kept: what the game won't let the AI do ----------------------------------------------

@test("kept: a barony's holder and the unrecorded World-screen steps stay Needs you, each saying what the AI does meanwhile")
def _():
    notes = []
    planner_world._meeting_answer_rule({"world": {"meeting": {"open": True, "land_holder": True}}},
                                       planner.PLANNER_CONFIG, [], notes)
    assert notes and notes[0].startswith(YOU) and "leaves the screen" in notes[0] and "yours" not in notes[0], notes
    src = (ROOT / "brain" / "planner_world.py").read_text(encoding="utf-8")
    assert src.count("stays home") >= 3                          # each Make contact Needs you says it


@test("overseer: an unattended meeting the AI leaves to the player is left soon; no 'yourself' for the trade button")
def _():
    src = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    assert code_has(src, 'or (r.get("pressed") and not r.get("ok")) or r.get("left_to_player"):')
    assert "press Trade yourself" not in src and "refused, left to you" not in src
    assert "left for you to fix" not in src


@test("no 'yourself' or 'by hand' instruction left in the core group's Needs you lines but the kept World screen ones")
def _():
    for name in ("planner.py", "planner_core.py", "planner_building.py"):
        src = (ROOT / "brain" / name).read_text(encoding="utf-8")
        assert "yourself" not in src, name
        assert "ask_player(" not in src or name != "planner_building.py", name


if __name__ == "__main__":
    finish()

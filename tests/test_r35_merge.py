"""(0.105.35 merge) The follow-ups the builders reported, after the six
groups' branches were merged (the player: nothing waits for them):

- the Rules switch "Cavern well into an unfound cavern": off means the AI
  decides (on: always allowed), in the switch, its settings and the
  strategist's Rules line;
- an open cavern with a great beast in it (planner_building's deep notes):
  the AI's cavern seal and doors (planner_threats), said, never a Needs you;
- a gate the AI didn't shut on the player's own lever that works other
  things too: the lever is never pulled (open_entrance refuses it, the
  stranded rows carry it), and the AI digs them a way in instead;
- no ask_player left in brain/ that tells the player to do what the AI could.

    python tests/test_r35_merge.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))

from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

_src = (ROOT / "tests" / "test_r32_gatesplit.py").read_text(encoding="utf-8")
_ns: dict = {"module_src": module_src, "sys": sys}
exec(compile(_src[_src.index("try:\n    from lupa"):_src.index("\ndef lst")], "r32rig", "exec"), _ns)

from planner import Memory, plan  # noqa: E402
import planner_building  # noqa: E402
from strategist import rules_line  # noqa: E402
import test_r33_fix_gates as F  # noqa: E402

LUA = _ns["LUA"]


def needs_you(notes):
    return [n for n in notes if n.startswith(("[you]", "Needs you"))]


def links(E, table):
    """lever_links() stubbed: {target id: [lever ids]}."""
    t = LUA.table_from
    m = t({k: t(v) for k, v in table.items()})
    E.lever_links = LUA.eval("function(m) return function() return m, {} end end")(m)


def player_gate_rig(works):
    """The r32 rig's hatch 7 on the player's lever 137 (not "AI gate"), shut
    by the player (not in GATES.closed); lever 137 works `works`."""
    E, G = _ns["rig"](player=True, closed=True)
    links(E, {w: [137] for w in works})
    G.pulled = LUA.table_from([])
    return E, G


# --- the Rules switch: off means the AI decides -------------------------------------

@test("open_caverns: the switch reads Always / AI decides; the settings and docs say off means the AI decides")
def _():
    gui = (ROOT / "lua" / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
    i = gui.index("view_id = 'open_caverns'")
    block = gui[i:gui.index("})", i)]
    assert "label = 'Always', value = true" in block and "label = 'AI decides', value = false" in block, block
    st = (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    j = st.index("open_caverns = false")
    assert "the AI decides" in st[j - 400:j], st[j - 400:j]
    ctl = (ROOT / "docs" / "controls.md").read_text(encoding="utf-8")
    assert "Off (\"AI decides\", the default), the AI decides" in ctl


@test("open_caverns: the strategist's Rules line says the AI decides, not plain 'off'")
def _():
    from planner import player_rules
    line = rules_line(player_rules({"settings": {}}))
    assert "AI decides: open_caverns" in line, line
    assert "open_caverns" not in line.split("| off: ")[1].split("|")[0], line
    line = rules_line(player_rules({"settings": {"open_caverns": True}}))
    assert "open_caverns" not in line, line


# --- the deep notes: a beast in an open cavern --------------------------------------

def deep_state(kind="forgotten beast", seal=True):
    return {"settings": {"seal_caverns": seal},
            "deep": {"caverns": [{"name": "Cavern 1", "discovered": True, "open": True,
                                  "z_bottom": 100, "z_top": 110, "open_at": {"x": 5, "y": 6, "z": 110}}],
                     "dangers": [{"name": "Ezum", "kind": kind, "layer": "Cavern 1"}]}}


@test("deep notes: a forgotten beast in an open cavern: the AI's seal and doors said, never 'seal the way down' as a Needs you")
def _():
    notes: list = []
    planner_building._deep_notes(deep_state(), notes)
    assert not needs_you(notes), notes
    assert any("the AI locks every way into the caverns" in n for n in notes), notes
    assert not any("seal the way down" in n for n in notes), notes
    # the seal switched off: said as the player's switch, still no Needs you
    notes = []
    planner_building._deep_notes(deep_state(seal=False), notes)
    assert not needs_you(notes) and any("sealing the caverns is off on the Rules tab" in n for n in notes), notes
    # an ordinary cavern creature: the openings walled, squads and gates answer it
    notes = []
    planner_building._deep_notes(deep_state(kind="cave crocodile"), notes)
    assert not needs_you(notes) and any("walls the openings" in n for n in notes), notes


# --- a player's lever that works other things ---------------------------------------

@test("lua: open_entrance never pulls the player's lever that also works something else (dry run too)")
def _():
    E, G = player_gate_rig([7, 99])
    for dry in (True, False):
        r = E.open_entrance(1, dry)
        assert not r.ok and r.rejected and r.shared_lever == 137 and r.works_other == 1, dict(r)
        assert "player's lever 137" in r.error, r.error
    assert len(list(G.pulled.values())) == 0 and G.blds[7].door_flags.closed


@test("lua: the player's lever that works only this entrance's gates is pulled; an AI-shut entrance isn't checked")
def _():
    E, G = player_gate_rig([7])
    r = E.open_entrance(1, False)
    assert r.ok and not G.blds[7].door_flags.closed, dict(r)
    assert list(G.pulled.values()) == [137]
    # the AI's own lockdown shut it: the check is for the player's gates only
    E, G = player_gate_rig([7, 99])
    E.GATES.closed[1] = True
    r = E.open_entrance(1, False)
    assert r.ok and r.shared_lever is None, dict(r)
    # an "AI gate" lever: the AI's own, never refused for it
    E, G = player_gate_rig([7, 99])
    G.blds[137].name = "AI gate lever"
    r = E.open_entrance(1, True)
    assert r.ok and r.dry_run, dict(r)


@test("lua: the stranded row of a gate shut on a shared player's lever carries it (entrance.shared_lever)")
def _():
    E, G = player_gate_rig([7, 99])
    rows = {row.name: row for row in list(E.stranded_citizens().list.values())}
    out = rows["Out"]
    assert out.cause == "gate_shut" and not out.by_ai, (out.cause, out.by_ai)
    assert out.entrance.shared_lever == 137 and out.entrance.works_other == 1
    E, G = player_gate_rig([7])
    rows = {row.name: row for row in list(E.stranded_citizens().list.values())}
    assert rows["Out"].entrance.shared_lever is None


def shared_state(out_ticks=2400):
    s = F.stranded_state({"invader": False, "pos": {"x": 10, "y": 150, "z": 173}})
    s["entrances"]["armed"] = False
    for r in s["entrances"]["stranded"]:
        r.update(cause="gate_shut", by_ai=False, out_ticks=out_ticks, out_days=out_ticks // 1200)
        r["entrance"]["shared_lever"] = 137
        r["entrance"]["works_other"] = 2
    return s


@test("brain: a gate on the player's shared lever: no open_entrance; a stair dug in, said, never a Needs you")
def _():
    s = shared_state()
    props, notes = plan(s, Memory())
    assert not [p for p in props if p.action.get("type") in ("open_entrance", "open_gates")], props
    way = [p.action for p in props if p.rule == "way_in"]
    assert way and way[0]["type"] == "dig_way_in" and (way[0]["x"], way[0]["y"]) == (152, 18), (way, notes)
    said = [n for n in notes if "player's lever 137" in n]
    assert said and "digs them a way in" in said[0] and "works 2 other thing(s)" in said[0], notes
    assert not [n for n in needs_you(notes) if "shut outside" in n], notes
    # without the flag: the entrance opened, as the gates group made it
    for r in s["entrances"]["stranded"]:
        r["entrance"].pop("shared_lever")
    props, _n = plan(s, Memory())
    assert [p.action for p in props if p.rule == "stranded"] == [{"type": "open_entrance", "id": 2}], props


@test("brain: not out long enough for a stair yet: said with when, no Needs you")
def _():
    s = shared_state(out_ticks=600)
    props, notes = plan(s, Memory())
    assert not [p for p in props if p.rule in ("way_in", "stranded")], props
    said = [n for n in notes if "player's lever 137" in n]
    assert said and "digs them a stair in once" in said[0], notes
    assert not needs_you(said), said


# --- no ask_player that hands the AI's work to the player ---------------------------

BANNED = ("yourself", "open it", "allow it", "dig or build them", "the player's call", "put to the player",
          "check they can", "left to you", "seal the way down")


@test("brain: no ask_player text tells the player to do what the AI could")
def _():
    bad = []
    for p in sorted((ROOT / "brain").glob("*.py")):
        src = p.read_text(encoding="utf-8")
        for m in re.finditer(r"ask_player\(notes,", src):
            # the call's text: to the closing parenthesis at the call's depth
            i, depth = m.end(), 1
            while depth and i < len(src):
                depth += {"(": 1, ")": -1}.get(src[i], 0)
                i += 1
            text = src[m.end():i].lower()
            for w in BANNED:
                if w in text:
                    bad.append((p.name, src[:m.start()].count("\n") + 1, w))
    assert not bad, bad


@test("lua: everything compiles under 5.3")
def _():
    L = _ns["LuaRuntime"]()
    chk = L.eval("function(src, n) local f, e = load(src, n, 't', {}); return f ~= nil, e end")
    for p in sorted((ROOT / "lua").glob("*.lua")) + sorted((ROOT / "lua" / "gui").glob("*.lua")):
        ok, err = chk(p.read_text(encoding="utf-8"), p.name)
        assert ok, (p.name, err)


if __name__ == "__main__":
    finish()

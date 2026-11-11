"""(0.105.34) The player: nothing waits for them. Citizens the AI's gates
shut out while a siege is held off elsewhere: the AI opens their entrance
alone (open_entrance; the watcher stays armed), or, with an enemy within the
gates' close distance of it, keeps it shut and says it will open it once the
enemy is farther off. Never open_gates (which would let the siege in), never
a question for the player.

    python tests/test_r34_open_entrance.py
"""

from __future__ import annotations

import json
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

import test_r33_fix_gates as F  # noqa: E402  (its stranded_state and plan helpers)


def lua_rig():
    return _ns["rig"]()


@test("brain: an invader held off far from their gate: open_entrance for that gate, not open_gates, no Needs you")
def _():
    s = F.stranded_state({"invader": True, "pos": {"x": 10, "y": 150, "z": 173}})
    props, notes = F.plan(s, F.Memory())
    acts = [p.action for p in props if p.rule == "stranded"]
    assert acts == [{"type": "open_entrance", "id": 2}], acts
    assert not [n for n in notes if n.startswith("NEEDS YOU") and "shut outside" in n], notes


@test("brain: an enemy 8 tiles from their gate: kept shut with a note, no action, no Needs you")
def _():
    s = F.stranded_state({"invader": True, "pos": {"x": 158, "y": 20, "z": 173}})
    for r in s["entrances"]["stranded"]:
        r["gate_danger"] = 8
        r["danger_near"] = 40
    props, notes = F.plan(s, F.Memory())
    assert not [p for p in props if p.rule == "stranded"], props
    assert not [n for n in notes if n.startswith("NEEDS YOU") and "shut outside" in n], notes


@test("lua: open_entrance opens the entrance's own gate; refused with a danger within 12 tiles; dry run changes nothing")
def _():
    E, G = lua_rig()
    t = _ns["LUA"].table_from
    G.blds[7].door_flags.closed = True
    E.GATES.closed[1] = True
    r = E.open_entrance(1, True)
    assert r.ok and r.dry_run and G.blds[7].door_flags.closed and len(list(G.pulled.values())) == 0
    G.units[1] = t({"id": 99, "danger": True, "flags1": t({"caged": False, "chained": False}), "pos": t({"x": 112, "y": 149, "z": 171})})
    r = E.open_entrance(1)
    assert not r.ok and "tiles from this entrance" in r.error, dict(r)
    G.units[1] = t({"id": 99, "danger": True, "flags1": t({"caged": False, "chained": False}), "pos": t({"x": 140, "y": 149, "z": 171})})
    r = E.open_entrance(1)
    assert r.ok and not G.blds[7].door_flags.closed, dict(r)
    r = E.open_entrance(5)
    assert not r.ok


if __name__ == "__main__":
    finish()

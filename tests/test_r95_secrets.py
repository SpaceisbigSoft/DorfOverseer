"""(0.105.95) The secrets of life and death: the AI decides.

Live 23 Nov: C and F hold the artifact slab "Kuluruxen, Nightsearch" (the
Secrets). A slab can't be read in a fort (kept, said); a book or scroll of
the secret makes a necromancer, whose raised dead are hostile to all life. A
war fort (Militarism 50+, 20+ soldiers) keeps such books; any other forbids
them.

    python tests/test_r95_secrets.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402

from planner import Memory, plan  # noqa: E402
import planner_secrets as PS  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
BOOK = {"id": 901, "name": "The Dead Shall Walk"}


def fort(secrets, militarism=0, soldiers=0):
    s = copy.deepcopy(BASE)
    s.setdefault("settings", {})
    s["settings"] = dict(s["settings"], traits=dict(_traits(s), militarism=militarism))
    s.setdefault("artifacts", {})
    s["artifacts"] = dict(s["artifacts"] or {}, secrets=secrets)
    s.setdefault("military", {})
    s["military"]["squads"] = [{"id": 1, "name": "Q", "members": soldiers, "size": 10, "orders": 0, "ai_orders": 0}] \
        if soldiers else []
    return s


def _traits(s):
    t = (s.get("settings") or {}).get("traits")
    return dict(t) if isinstance(t, dict) else {}


def secrets_props(s):
    props, notes = plan(s, Memory())
    return [p for p in props if p.rule == "secrets"], notes


@test("C/F's Secrets slab alone: kept, said; nothing proposed")
def _():
    props, notes = secrets_props(fort({"slabs": 1, "books": [], "necromancers": []}))
    assert not props, props
    assert any("slab(s) of the secrets of life and death: kept" in n for n in notes), notes


@test("a peaceful or weak fort: a secrets book forbidden; a war fort with 20+ soldiers keeps it")
def _():
    props, _ = secrets_props(fort({"slabs": 0, "books": [BOOK], "necromancers": []}, militarism=0, soldiers=40))
    assert props and props[0].action == {"type": "forbid_secrets", "ids": [901], "on": True}, props
    props, _ = secrets_props(fort({"slabs": 0, "books": [BOOK], "necromancers": []}, militarism=80, soldiers=5))
    assert props and props[0].action["on"] is True, props
    props, notes = secrets_props(fort({"slabs": 0, "books": [BOOK], "necromancers": []}, militarism=80, soldiers=30))
    assert not props, props
    assert any("kept: a war fort" in n for n in notes), notes


@test("a war fort lets go a secrets book the AI forbade before; a forbidden one in a peaceful fort: nothing more")
def _():
    props, _ = secrets_props(fort({"books": [dict(BOOK, forbidden=True)]}, militarism=80, soldiers=30))
    assert props and props[0].action == {"type": "forbid_secrets", "ids": [901], "on": False}, props
    props, _ = secrets_props(fort({"books": [dict(BOOK, forbidden=True)]}, militarism=0, soldiers=0))
    assert not props, props


@test("necromancers on the map are said")
def _():
    _, notes = secrets_props(fort({"necromancers": [{"id": 5, "name": "Urist", "citizen": True}]}))
    assert any("1 necromancer(s) on the map: Urist (a citizen)" in n for n in notes), notes


@test("keeps_secrets: missing or odd traits read as Militarism 0")
def _():
    assert PS.keeps_secrets({"settings": {}})[0] is False
    assert PS.keeps_secrets({"settings": {"traits": {"militarism": True}}})[0] is False


@test("the bridge: forbid_secrets in the catalog and DRY_OK; the artifacts section carries `secrets`; "
      "ai-secrets.lua compiles")
def _():
    cat = (ROOT / "lua" / "ai-bridge-catalog.lua").read_text(encoding="utf-8")
    assert "forbid_secrets = function(a)" in cat and "'forbid_secrets'," in cat
    sec = (ROOT / "lua" / "ai-bridge-sections.lua").read_text(encoding="utf-8")
    assert "reqscript('ai-secrets').report()" in sec
    need_lua()
    from lupa.lua53 import LuaRuntime
    f = LuaRuntime().eval("function(s) local f, e = load(s, 'b', 't', {}) return e end")
    for name in ("ai-secrets.lua", "ai-bridge-catalog.lua", "ai-bridge-sections.lua"):
        src = (ROOT / "lua" / name).read_text(encoding="utf-8")
        assert f(src) is None, (name, f(src))


finish()

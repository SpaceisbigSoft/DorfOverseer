"""(0.105.99) The fort's law killing dwarves: what it was, and the office swap.

Live 24 Nov 00:34, B: "Urdim Zithisgoden, sheriff" STRUCK_DOWN Nish Onoltath
(Mechanic) and "Doren Ushatnelas, captain of the guard" SUFFOCATE Besmar
Dumatabod (Strand Extractor), y263 ticks 38166 and 39011. The probes
(r99i11-law-deaths, -fight, -reports, -sum) found no punishment: no crime on
either incident, no sentence, the punishments queue empty, no jail, the AI
never convicted on B. Both deaths, and the tantruming wrestler Likot's, were
one activity (114300): a tantrum's fist brawl, the two officers punching each
other, a beekeeper, a planter and a manager in it too; the captain's punch to
the head broke the strand extractor's neck.

The bridge now tells a convict's death at the law's hands (a punishment:
`punished`) from the law's other killings (`law_kills`); at two of those the
office goes to a calm free dwarf (`law_swap`: `appoint` replace killer_out),
after which the killer rule treats them as any other. The chronic case
already in the jail is not convicted again (E, 24 Nov: refused every cycle).

    python tests/test_r99_law.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

from planner import PLANNER_CONFIG  # noqa: E402
from planner_core import Proposal, cooldown_key, refusal_key  # noqa: E402
from digest import normalize  # noqa: E402
import planner_killers as PK  # noqa: E402
import planner_tantrums as PT  # noqa: E402
from overseer_words import short as action_words  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

ITEM3 = (ROOT / "tests" / "test_item3_killers.py").read_text(encoding="utf-8")
FAKE = re.search(r'FAKE = r"""(.*?)"""', ITEM3, re.S).group(1)


def state(killers, **extra):
    base = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    base["killers"] = killers
    base.update(extra)
    return normalize(base)


def run(s, cfg=None):
    props, notes = [], []
    PK._killer_rule(s, dict(cfg or PLANNER_CONFIG), props, notes, None)
    return props, notes


def law_row(**kw):
    r = {"id": 17199, "name": "Doren Ushatnelas, captain of the guard", "kind": "killer", "confidence": "strong",
         "citizen": True, "kills": 2, "victims": ["Besmar", "Nish"], "seen_ticks": 2000, "law": True,
         "law_codes": ["CAPTAIN_OF_THE_GUARD"], "law_kills": 2, "law_killer": True}
    r.update(kw)
    return r


# --- the brain ---------------------------------------------------------------------

@test("B's case: one killing each in a brawl (law_kills 1): a note, nothing done, never a cell")
def _():
    r = law_row(confidence="weak", kills=1, law_kills=1, law_killer=None, victims=["Besmar"])
    p, n = run(state({"list": [r], "cells": [], "rooms": 2}))
    assert p == [], p
    assert "1 killing(s) outside a punishment" in n[0] and "calmer dwarf at 2" in n[0], n
    assert 17199 not in PK.held_killer_ids(state({"list": [r], "cells": []}))


@test("two killings outside a punishment: the office to a calm free dwarf (law_swap appoint killer_out)")
def _():
    p, n = run(state({"list": [law_row()], "cells": [], "rooms": 2}))
    assert [(x.rule, x.action) for x in p] == [("law_swap", {"type": "appoint", "office": "CAPTAIN_OF_THE_GUARD",
                                                            "replace": True, "killer_out": True,
                                                            "unit_id": 17199})], p
    assert "outside a punishment" in p[0].reason and "calm free dwarf" in p[0].reason
    # still never held (no cell) while in office
    assert 17199 not in PK.held_killer_ids(state({"list": [law_row()], "cells": []}))


@test("brawls count too (no convict died), the sheriff's office named when only that is held")
def _():
    r = law_row(confidence="weak", kills=0, brawls=2, law_kills=2, law_codes=["SHERIFF"])
    p, _ = run(state({"list": [r], "cells": [], "rooms": 2}))
    assert [x.action["office"] for x in p] == ["SHERIFF"], p


@test("a convict's death by the law is lawful: said apart, not counted")
def _():
    r = law_row(kills=0, law_kills=0, law_killer=None, punished=3, confidence="weak")
    p, n = run(state({"list": [r], "cells": [], "rooms": 2}))
    assert p == [] and "3 convict(s) died of DF's punishment" in n[0], n


@test("first seen, appointing off, or an older bridge (no law_kills): a note only")
def _():
    p, n = run(state({"list": [law_row(seen_ticks=100)], "cells": [], "rooms": 2}))
    assert p == [] and "if it still holds" in n[0], n
    s = state({"list": [law_row()], "cells": [], "rooms": 2})
    s.setdefault("settings", {})["appoint_nobles"] = False
    p, n = run(s)
    assert p == [] and "appointing is off" in n[0], n
    old = law_row()
    for k in ("law_kills", "law_killer", "law_codes"):
        old.pop(k)
    p, n = run(state({"list": [old], "cells": [], "rooms": 2}))
    assert p == [] and "DF's justice judges them" in n[0], n


@test("law_swap: a refusal and a cooldown per office; its words; a month's cooldown")
def _():
    a = Proposal("law_swap", {"type": "appoint", "office": "SHERIFF", "replace": True, "killer_out": True}, "x", 2)
    b = Proposal("law_swap", {"type": "appoint", "office": "CAPTAIN_OF_THE_GUARD", "replace": True,
                              "killer_out": True}, "x", 2)
    assert refusal_key(a) != refusal_key(b)
    assert cooldown_key(a) == "law_swap:SHERIFF"
    assert PLANNER_CONFIG["law_swap_cooldown_ticks"] == 28 * 1200 and PLANNER_CONFIG["law_killer_kills"] == 2
    assert "calm dwarf" in action_words(a.action) and "sheriff" in action_words(a.action)
    src = (ROOT / "brain" / "hold_classes.py").read_text(encoding="utf-8")
    assert '"law_swap"' in src


@test("chronic_convict: a case already in the jail is not convicted again (E, 24 Nov)")
def _():
    s = {"justice": {"prisoners": [{"id": 18369, "name": "Ingiz"}]}, "settings": {}}
    why = PT._convict_blockers(s, dict(PLANNER_CONFIG), {"id": 18369})
    assert "already serving time in the jail" in why, why
    assert "already serving time in the jail" not in PT._convict_blockers(s, dict(PLANNER_CONFIG), {"id": 5})


# --- the bridge (lupa) ---------------------------------------------------------------

def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-killers.lua"))
    return lua, env, w


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


def kill(lua, w, killer, victim, conflict=0):
    w.incidents[len(w.incidents) + 1] = T(lua, {"criminal": killer, "victim": victim, "death_cause": 7,
                                                "conflict_level": conflict, "event_year": 300, "event_time": 0})


@test("bridge: the law's brawl killings are law_kills (law_killer at 2); a sentenced convict's death is punished")
def _():
    need_lua()
    lua, env, w = world()
    w.unit(T(lua, {"id": 5, "name": "Sheriff", "citizen": True, "positions": [{"position": {"code": "SHERIFF"}}]}))
    for v in (20, 21, 22):
        w.unit(T(lua, {"id": v, "name": f"V{v}", "is_dead": True}))
    w.crimes[1] = T(lua, {"mode": 5, "criminal": 22, "flags": {"sentenced": True}})
    kill(lua, w, 5, 20)                   # B: a fist fight, conflict None
    kill(lua, w, 5, 22, conflict=5)       # a beating of a convict: lawful
    rows = {x["id"]: x for x in [dict(r) for r in env.report()["list"].values()]}
    r = rows[5]
    assert (r.get("law"), r.get("law_kills"), r.get("punished"), r.get("kills")) == (True, 1, 1, 1), r
    assert r.get("law_killer") is None, r
    assert list(r["law_codes"].values()) == ["SHERIFF"]
    kill(lua, w, 5, 21, conflict=4)       # a second, a brawl
    r = {x["id"]: dict(x) for x in env.report()["list"].values()}[5]
    assert r.get("law_kills") == 2 and r.get("law_killer") is True, r
    assert env.law_killer(5) is True and env.law_killer(6) is False
    # never held while in office
    assert not env.held_ids()[5]


@test("bridge files: the swap takes killer_out for the law offices only; the dispatcher passes it; sizes")
def _():
    swap = (ROOT / "lua" / "ai-nobles-swap.lua").read_text(encoding="utf-8")
    assert "LAW_OFFICES = {SHERIFF = true, CAPTAIN_OF_THE_GUARD = true}" in swap
    assert "law_killer(old.id)" in swap and "calm_pick(code, old.id)" in swap
    works = (ROOT / "lua" / "ai-bridge-actions-works.lua").read_text(encoding="utf-8")
    assert "killer_out = a.killer_out == true" in works
    for f in ("ai-killers.lua", "ai-nobles-swap.lua", "ai-bridge-actions-works.lua"):
        assert len((ROOT / "lua" / f).read_bytes()) < 60 * 1024, f


if __name__ == "__main__":
    finish()

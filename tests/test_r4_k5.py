"""Round 4, group k5: audit item B10 (the prompt and the section list brought up
to today's report) and the strategist's advice-only ("shadow") mode, plus the
rewritten handoff-ai.md. Offline: every model is a fake.

    python tests/test_r4_k5.py
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
from lua_modules_util import bridge_hub_src  # noqa: E402  (r8) the hub's text with its catalog and sections
sys.path.insert(0, str(ROOT / "brain"))

from backends import Reply  # noqa: E402
from digest import digest  # noqa: E402
from planner import Memory, plan  # noqa: E402
import strategist  # noqa: E402
from strategist import INSTRUCTIONS, check_answer, review_message  # noqa: E402
from tokens import TokenBank  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
REAL = json.loads((ROOT / "tests" / "fixtures" / "real" / "enxah-0.104.52-y73-winter.json").read_text(encoding="utf-8"))
HUB = bridge_hub_src()
LAYOUTS = (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8")
KINDS = re.findall(r"'(\w+)'", re.search(r"\nKINDS = \{(.*?)\}", LAYOUTS, re.S).group(1))
RECIPES, TOOLS = {"brew_drink", "stone_blocks"}, {"autochop"}
BUILD = {"level_kinds": KINDS, "stockpiles": ["food"], "workshops": ["Still"]}


def bridge_sections() -> list[str]:
    """The report's section names, read from the bridge's SECTIONS table."""
    body = HUB[HUB.index("\nSECTIONS = {"):HUB.index("\nPULSE_SECTIONS = {")]
    body = body[:re.search(r"\n\}", body).start()]
    return re.findall(r"^    ([a-z_0-9]+) = ", body, re.M) + ["perf"]


class Fake:
    def __init__(self, text):
        self.text, self.calls = text, []

    def ask(self, instr, msg, important=False, effort=None, **kw):
        self.calls.append((instr, msg, effort))
        return Reply(text=self.text, input_tokens=int((len(instr) + len(msg)) / 2.5), output_tokens=200,
                     model="fake")


class Shadow:
    """DFAI_STRATEGIST_SHADOW set for one block (the harness sets 0)."""
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        self.old = os.environ.get("DFAI_STRATEGIST_SHADOW")
        if self.value is None:
            os.environ.pop("DFAI_STRATEGIST_SHADOW", None)
        else:
            os.environ["DFAI_STRATEGIST_SHADOW"] = self.value

    def __exit__(self, *a):
        if self.old is None:
            os.environ.pop("DFAI_STRATEGIST_SHADOW", None)
        else:
            os.environ["DFAI_STRATEGIST_SHADOW"] = self.old


def _ai(state):
    s = copy.deepcopy(state)
    s.setdefault("settings", {}).update({"ai_frequency": 0, "ai_effort": 0, "real_day_token_cap": 0})
    return s


# --- B10: sections -----------------------------------------------------------------

@test("B10: every section the bridge reports may be asked for (want), but bridge_version and paused")
def _():
    names = bridge_sections()
    assert len(names) > 90 and "floors" in names and "thirst" in names, names
    wantable = set(getattr(strategist, "WANTABLE", strategist.SECTIONS))
    missing = sorted(set(names) - wantable - {"bridge_version", "paused"})
    assert not missing, f"not askable: {missing}"
    assert not wantable - set(names), sorted(wantable - set(names))      # nothing the report lacks
    a = check_answer(json.dumps({"note": "x", "want": ["floors", "shelter_plan", "nonsense"]}), RECIPES, TOOLS, set())
    assert a.want == ["floors", "shelter_plan"] and any("nonsense" in r for r in a.rejected), (a.want, a.rejected)


@test("B10: a section asked for is shown in full next review, cut at SECTION_CHARS as before")
def _():
    s = copy.deepcopy(BASE)
    s["floors"] = {"floors": [{"id": i, "hall": "main", "slots": list(range(40))} for i in range(30)]}
    s["thirst"] = {"parched": 2}
    msg = review_message(s, "routine", [], [], {}, [], wants=["floors", "thirst"])
    line = next(x for x in msg.splitlines() if x.startswith("SECTION floors"))
    assert "cut" in line and len(line) < strategist.SECTION_CHARS + 80, len(line)
    assert 'SECTION thirst (as you asked) {"parched":2}' in msg, msg[-300:]


@test("B10: the prompt names the newer sections worth reading (floors, thirst, siege...) within its size")
def _():
    text = strategist.instructions(sorted(RECIPES), sorted(TOOLS), BUILD)
    for sec in ("floors", "thirst", "hunt", "siege", "herd", "welfare", "waterworks", "shelter_plan"):
        assert sec in text, sec
    assert "another report section" in text


# --- B10: project kinds and the floor wording --------------------------------------

@test("B10: INSTRUCTIONS lists every level kind the bridge builds, and no longer says 'by the main staircase'")
def _():
    assert len(KINDS) == 15, KINDS
    block = INSTRUCTIONS[INSTRUCTIONS.index('"type":"start_project"'):INSTRUCTIONS.index('"type":"cancel_project"')]
    for k in KINDS:
        assert f'"{k}" ' in block, k
    assert set(strategist.PROJECT_KINDS) == set(KINDS)
    assert "main staircase" not in INSTRUCTIONS
    assert "main hall" in INSTRUCTIONS


@test("B10: suites, jail, archery and garden are checked with their sizes; a kind with no check is refused")
def _():
    def one(act, build=BUILD):
        return check_answer(json.dumps({"note": "x", "actions": [dict(act, type="start_project")]}),
                            RECIPES, TOOLS, set(), build)
    good = [({"kind": "suites", "suites": 3}, {"suites": 3}),
            ({"kind": "jail", "cells": 4}, {"cells": 4}),
            ({"kind": "archery", "lanes": 2}, {"lanes": 2, "length": 12}),
            ({"kind": "archery", "lanes": 3, "length": 16}, {"lanes": 3, "length": 16}),
            ({"kind": "garden", "name": "The  Quiet Stones"}, {"name": "The Quiet Stones"})]
    for act, want in good:
        a = one(act)
        assert a.actions == [{"type": "start_project", "kind": act["kind"], **want}], (act, a.actions, a.rejected)
    bad = [{"kind": "suites"}, {"kind": "suites", "suites": 9}, {"kind": "jail"}, {"kind": "jail", "cells": 0},
           {"kind": "archery"}, {"kind": "archery", "lanes": 2, "length": 30}, {"kind": "garden"},
           {"kind": "garden", "name": "x{y}"}, {"kind": "garden", "name": "A" * 41}]
    for act in bad:
        a = one(act)
        assert not a.actions and a.rejected, (act, a.actions)
    # a kind the bridge has that the strategist's list doesn't (a new one): refused, never sent bare
    a = one({"kind": "observatory"}, dict(BUILD, level_kinds=KINDS + ["observatory"]))
    assert not a.actions and "not one the strategist may start" in a.rejected[0], a.rejected


# --- B10: squad names ----------------------------------------------------------------

@test("B10: a squad nobody named reads 'squad <id>' in the digest, not '?'")
def _():
    s = copy.deepcopy(BASE)
    s["military"] = {"soldiers": 6, "squads": [{"id": 7, "name": "", "members": 4, "size": 10, "routine": "train"},
                                               {"id": 8, "name": "The Axes of Dawn", "members": 2, "size": 10}]}
    d = digest(s)
    line = next(x for x in d.splitlines() if x.startswith("MILITARY"))
    assert "squad 7 4/10 train" in line and "The Axes of Dawn 2/10" in line, line
    assert "? 4/10" not in line, line


# --- advice-only (shadow) mode -------------------------------------------------------

@test("shadow: on by default (no config, or config without the key); only config false switches it off")
def _():
    import dfhack
    import review
    real = dfhack.CONFIG_PATH
    with tempfile.TemporaryDirectory() as tmp, Shadow(None):
        try:
            cfg = Path(tmp) / "config.json"
            dfhack.CONFIG_PATH = cfg
            assert review.shadow_on() is True                   # no config.json
            for body, want in (({}, True), ({"strategist_shadow": True}, True), ({"strategist_shadow": 0}, True),
                               ({"strategist_shadow": "false"}, True), ({"strategist_shadow": False}, False)):
                cfg.write_text(json.dumps(body), encoding="utf-8")
                assert review.shadow_on() is want, (body, want)
            cfg.write_text("{not json", encoding="utf-8")
            assert review.shadow_on() is True
        finally:
            dfhack.CONFIG_PATH = real
    with Shadow("1"):
        assert review.shadow_on() is True
    with Shadow("0"):
        assert review.shadow_on() is False
    ex = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    assert ex.get("strategist_shadow") is True and ex.get("strategist_backend") == "subscription"


def _answer(rule):
    return json.dumps({"note": "steady as she goes", "adjust": {"drink_per_dwarf": 12, "min_citizens": 3},
                       "want": ["floors"],
                       "actions": [{"type": "work_order", "recipe": "brew_drink", "amount": 5},
                                   {"type": "start_project", "kind": "jail", "cells": 4},
                                   {"type": "set_style", "hall": "pillared", "reason": "a siege"},
                                   {"type": "hold", "rule": rule, "days": 5, "why": "not now"},
                                   {"type": "tool", "name": "rm -rf", "enabled": True}],
                       "season": {"choice": "focus:drink", "line": "The winter of the mugs.", "why": "thirst"}})


def _review(shadow):
    from review import maybe_review
    s, m = _ai(REAL), Memory()
    props, notes = plan(copy.deepcopy(s), m)
    from planner import STEER_PROTECTED
    from steer_guard import hold_refused          # (r4 merge) a rule k1's guard lets a model hold
    rule = next(p.rule for p in props if p.rule not in STEER_PROTECTED and p.rule != "build"
                and not hold_refused(p.rule))
    style_before = copy.deepcopy(m.culture)
    c = Fake(_answer(rule))
    info = {"recipes": sorted(RECIPES), "tools": sorted(TOOLS), "level_kinds": KINDS, "stockpiles": [],
            "workshops": []}
    with Shadow("1" if shadow else "0"):
        out = maybe_review(s, m, TokenBank(), c, info, notes, proposals=props)
    return s, m, c, out, rule, style_before


@test("shadow: the review runs and is checked, NOTHING is applied, and the journal line holds it all")
def _():
    import season
    s, m, c, out, rule, style_before = _review(True)
    assert len(c.calls) == 1, out.say
    j = out.journal
    assert j["kind"] == "review" and j["shadow"] is True and j["applied"] is False, j
    # what it would do: in full
    assert j["adjust"] == {"drink_per_dwarf": 12}, j["adjust"]
    assert [a["type"] for a in j["actions"]] == ["work_order", "start_project", "set_style"], j["actions"]
    assert j["steer"] == [{"type": "hold", "rule": rule, "days": 5, "why": "not now"}], j["steer"]
    assert j["season"]["choice"] == "focus:drink", j["season"]
    assert any("min_citizens" in r for r in j["rejected"]) and any("more than the allowed" in r for r in j["rejected"]), j["rejected"]
    assert j["verdict"] == {"accepted": 3 + 1 + 1 + 1, "refused": len(j["rejected"])}, j["verdict"]
    assert '"focus:drink"' in j["reply"] and j["tokens"] > 0
    # and nothing applied
    assert out.proposals == [], out.proposals
    assert m.adjust == {} and not (m.steer or {}), (m.adjust, m.steer)
    assert m.culture == style_before or (m.culture or {}).get("season_done") is None, m.culture
    assert (m.culture or {}).get("profile_overrides") == (style_before or {}).get("profile_overrides")
    assert season.due(s, m), "the season's choice is the script's in shadow mode"
    assert not any(x.get("kind") == "season" for x in (m.culture or {}).get("chronicle", []) if isinstance(x, dict))
    said = "\n".join(out.say)
    assert "ADVICE ONLY" in said and "AI would adjust" in said and "AI would steer" in said, said
    assert "AI would do: type=start_project kind=jail cells=4" in said, said
    # asked the season once: a second review this season gets no season menu
    assert (m.culture or {}).get("shadow_season") == season.season_key(s)


@test("shadow off: the same answer is applied as before (proposals, adjust, hold, season)")
def _():
    import season
    import review
    with Shadow("0"):
        assert review.shadow_on() is False          # the switch, as the player's config "false" sets it
    s, m, c, out, rule, _ = _review(False)
    j = out.journal
    assert "shadow" not in j, j
    assert m.adjust.get("drink_per_dwarf") in (12, 15.0) and m.steer.get(rule, {}).get("mode") == "hold"
    assert {p.action["type"] for p in out.proposals} == {"work_order", "start_project"}, out.proposals
    assert not season.due(s, m)


@test("shadow, the overseer's cycle: the script makes the season choice, the review only advises")
def _():
    import test_overseer as T
    import overseer
    T._before()
    c = T.FakeClaude(json.dumps({"note": "drink!", "adjust": {"drink_per_dwarf": 12},
                                 "actions": [{"type": "work_order", "recipe": "brew_drink", "amount": 9}],
                                 "season": {"choice": "focus:drink"}}))
    b = T.FakeBridge()
    with Shadow("1"):
        overseer.one_cycle(b, autopilot=True, backend=c)
    assert len(c.calls) == 1 and "SEASON:" in c.calls[0][0], "the review was asked, with the season menu"
    seasons = T.entries("season")
    assert seasons and seasons[0]["by"] == "script", seasons
    rev = T.entries("review")
    assert rev and rev[0]["shadow"] is True and rev[0]["season"]["choice"] == "focus:drink", rev
    assert not any(a.get("type") == "work_order" and a.get("amount") == 9 for a in b.acted), b.acted
    assert any("ADVICE ONLY" in x for x in T.SAID), T.SAID[-10:]


# --- handoff-ai.md -------------------------------------------------------------------

@test("handoff-ai.md: rewritten to today's code (Step 0, shadow mode, the cap, the bounds), short")
def _():
    text = (ROOT / "handoff-ai.md").read_text(encoding="utf-8")
    for need in ("claude auth status", "pip install claude-agent-sdk", '"strategist_backend": "subscription"',
                 "check_ai.py", "strategist_shadow", "real_day_token_cap", "check_answer", "hold_classes"):
        assert need in text, need
    for stale in ("Code version: 0.105.40", "still uses `max_thinking_tokens`", "about 730 tokens",
                  "/tmp/claude-0", "91 files"):
        assert stale not in text, stale
    assert len(text) < 14000, len(text)


if __name__ == "__main__":
    finish()

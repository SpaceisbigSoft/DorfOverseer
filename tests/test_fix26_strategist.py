"""0.105.26 fix round, strategist group: the --ai review before its first live run.

    python tests/test_fix26_strategist.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

from backends import Reply  # noqa: E402
from digest import digest, normalize  # noqa: E402
from planner import Memory, Proposal, STEER_PROTECTED, TICKS_PER_DAY, abs_tick, plan, steer_of  # noqa: E402
from strategist import SECTIONS, check_answer, cut_json, review_message, rules_line, shown_rules  # noqa: E402
from tokens import TokenBank  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
REAL = json.loads((ROOT / "tests" / "fixtures" / "real" / "enxah-0.104.52-y73-winter.json").read_text(encoding="utf-8"))
RECIPES = {"brew_drink", "stone_blocks"}
TOOLS = {"autochop"}
INFO = {"recipes": sorted(RECIPES), "tools": sorted(TOOLS), "level_kinds": ["bedrooms"], "stockpiles": [],
        "workshops": []}


def _steer(*acts, shown=None):
    return check_answer(json.dumps({"note": "x", "actions": list(acts)}), RECIPES, TOOLS, set(), shown=shown)


class Fake:
    def __init__(self, text):
        self.text, self.calls = text, []

    def ask(self, instr, msg, important=False, effort=None):
        self.calls.append((instr, msg, effort))
        return Reply(text=self.text, input_tokens=int((len(instr) + len(msg)) / 2.5), output_tokens=200, model="fake")


def _ai(state):
    s = copy.deepcopy(state)
    s.setdefault("settings", {}).update({"ai_frequency": 0, "ai_effort": 0, "real_day_token_cap": 0})
    return s


# --- 1. life-saving rules can't be held -------------------------------------------

@test("steer: mood, the infected, the injured, soap, fights and the other life rules can't be held")
def _():
    for rule in ("mood", "infected_rest", "traction_rest", "soap_rush", "break_fights", "hospital", "doctor_post",
                 "stress_care", "well_parts", "gate_lever", "cursed", "location_access", "drink", "shelter",
                 "fire_guard", "threat_alert"):
        assert rule in STEER_PROTECTED, rule
        a = _steer({"type": "hold", "rule": rule, "days": 84, "why": "x"}, shown={rule})
        assert not a.steer and "can't be held" in a.rejected[0], (rule, a.rejected)
        # a raise is still fine
        assert _steer({"type": "raise", "rule": rule, "why": "x"}, shown={rule}).steer, rule
    # and a hold saved earlier (an older version let it through) is ignored
    m = Memory()
    m.steer = {"mood": {"mode": "hold", "until": 10 ** 9, "why": "x"}}
    assert steer_of(m, "mood", 0) is None


# --- 2. the rules a review shows may be steered -----------------------------------

@test("steer: a rule shown in THE PLANNER PROPOSES NOW or RECENT ACTIONS is accepted; others are not")
def _():
    props = [Proposal("homes", {"type": "x"}, "homes for couples", 5),
             Proposal("waterworks_moat", {"type": "x"}, "a moat", 5)]
    recent = [{"rule": "gatehouse", "action": {"type": "build_gatehouse"}}, {"rule": "strategist", "action": {}}]
    shown = shown_rules(props, recent)
    assert shown == {"homes", "waterworks_moat", "gatehouse"}, shown
    a = _steer({"type": "hold", "rule": "homes", "days": 10, "why": "x"},
               {"type": "raise", "rule": "gatehouse", "why": "x"},
               {"type": "hold", "rule": "waterworks_moat", "days": 3, "why": "x"}, shown=shown)
    assert [s["rule"] for s in a.steer] == ["homes", "gatehouse", "waterworks_moat"], a.rejected
    # not shown and not on the fixed list: refused, as before
    a = _steer({"type": "hold", "rule": "homes_dig", "days": 10, "why": "x"}, shown=shown)
    assert not a.steer and "unknown rule" in a.rejected[0]
    # its own actions: nothing to steer
    a = _steer({"type": "hold", "rule": "strategist", "days": 3, "why": "x"}, shown={"strategist"})
    assert not a.steer


@test("steer end to end: a hold of a rule the review showed reaches memory; a protected one doesn't")
def _():
    from review import maybe_review
    s, m = _ai(REAL), Memory()
    props, notes = plan(copy.deepcopy(s), m)
    rule = next(p.rule for p in props if p.rule not in STEER_PROTECTED and p.rule != "build")
    prot = next(p.rule for p in props if p.rule in STEER_PROTECTED)
    c = Fake(json.dumps({"note": "x", "actions": [{"type": "hold", "rule": rule, "days": 5, "why": "a"},
                                                  {"type": "hold", "rule": prot, "days": 5, "why": "b"}]}))
    out = maybe_review(s, m, TokenBank(), c, INFO, notes, proposals=props)
    assert m.steer.get(rule, {}).get("mode") == "hold", out.say
    assert prot not in m.steer and any("can't be held" in x for x in out.say), out.say


# --- 3. missing values: wealth, the date, the map ---------------------------------

@test("digest: a missing, failed or odd wealth is '?' and named, never a crash")
def _():
    for w in ("missing", {"error": "boom"}, None, "lots"):
        s = copy.deepcopy(BASE)
        if w == "missing":
            s.pop("wealth", None)
        else:
            s["wealth"] = w
        d = digest(s)
        assert "| wealth ?" in d, d.splitlines()[0]
        if isinstance(w, dict) or w == "lots":
            assert "wealth" in d.splitlines()[[i for i, x in enumerate(d.splitlines())
                                                if x.startswith("MISSING_SECTIONS")][0]]


@test("digest: a partial section (keys missing) reads as 0, never a KeyError")
def _():
    s = copy.deepcopy(BASE)
    s["dwarves"] = {"total": 5}
    s["buildings"] = {"workshops": {"Still": 1}}
    s["jobs"] = {}
    s["mandates"] = [{"kind": "Make"}]
    s["settings"] = {"traits": {"piety": 50.5, "odd": "x"}}
    d = digest(s)
    assert "DWARVES 5 (0 children)" in d and "piety:+50" in d, d


@test("a failed date: no review on a made-up y0 date, no season, and the memory cache doesn't crash")
def _():
    from review import maybe_review, note_events
    import season
    s = _ai(BASE)
    s["date"] = {"error": "date unreadable"}
    m, bank, c = Memory(), TokenBank(), Fake('{"note":"x"}')
    note_events(s, m, bank, [{"kind": "invasion"}])
    assert not m.pending_kinds and bank.balance == 0
    out = maybe_review(s, m, bank, c, INFO, [])
    assert not c.calls and "date couldn't be read" in out.say[0], out.say
    assert season.season_key(s) is None and not season.due(s, m)
    import overseer
    import memstore
    real = memstore.load
    memstore.load = lambda *a, **k: (Memory(), TokenBank())
    try:
        overseer.MEMORY_CACHE.pop("fix26", None)
        overseer.load("fix26", None, prefer_logs=True, state={"date": {"error": "x"}})
        assert "fix26" not in overseer.MEMORY_CACHE
    finally:
        memstore.load = real


@test("digest: a failed map section is told to the model, not shown as an empty map")
def _():
    s = copy.deepcopy(BASE)
    s["map"] = {"error": "map probe failed"}
    d = digest(s)
    assert "MAP unknown: the map section failed (map probe failed)" in d, d
    assert "map" in normalize(s)["_errors"]


# --- 4. what the strategist sees ---------------------------------------------------

@test("want: moods, threats, world, missions, infection, homes, petitions and meetings may be asked for")
def _():
    want = ["moods", "threats", "world", "missions", "infection", "homes", "petitions", "meetings"]
    assert set(want) <= set(SECTIONS)
    a = check_answer(json.dumps({"note": "x", "want": want[:3]}), RECIPES, TOOLS, set())
    assert a.want == want[:3] and not a.rejected


@test("digest: threats, war and sieges, and infection get a short line each (none when calm)")
def _():
    s = copy.deepcopy(BASE)
    calm = digest(s)
    assert "THREATS" not in calm and "WORLD" not in calm and "INFECTION" not in calm
    s["threats"] = {"fire": {"fires": 3}, "undead": {"undead": 2, "clouds": 1, "cloud_near": 9},
                    "thieves": {"now": 1}, "were": {"list": [{"id": 1}]}, "rescue": {"down": 2, "holders": 0}}
    s["world"] = {"civs": [{"id": 1, "name": "The Red Hand", "race": "GOBLIN", "hostile": True},
                           {"id": 2, "name": "Kin", "race": "DWARF"}],
                  "sieges": [{"id": 1, "n": 3, "last_year": 72, "active": True, "name": "The Red Hand"}],
                  "visitors_from_hostile": 2}
    s["infection"] = {"infected": 4, "untreated": 3, "bleeding": 1, "cleaners": 0}
    d = digest(s)
    assert "THREATS fire:3 tiles undead:2 evil_clouds:1 (nearest 9 tiles) thieves_on_map:1 werebeast_citizens:1" in d, d
    assert "wounded_down:2 (rescuers 0)" in d
    assert "WORLD at war with The Red Hand (GOBLIN) | SIEGE NOW by The Red Hand | sieges on record 3 (last y72)" in d, d
    assert "visitors from a civ at war on the map: 2" in d
    assert "INFECTION 4 citizens with infected wounds, untreated 3, bleeding from it 1, nobody can clean wounds" in d


@test("review: the visitor lockout after a heist is told")
def _():
    from review import maybe_review
    s, m, c = _ai(BASE), Memory(), Fake('{"note":"x"}')
    m.heists = [[abs_tick(normalize(s)) - 3 * TICKS_PER_DAY, "a thief"]]
    maybe_review(s, m, TokenBank(), c, INFO, [])
    assert "VISITORS KEPT OUT after a heist" in c.calls[0][1] and "last 3 days ago" in c.calls[0][1], c.calls[0][1]


@test("a section asked for in full is cut on a whole item, stays JSON, and says (cut)")
def _():
    big = {"list": [{"id": i, "name": f"dwarf {i}", "why": "x" * 40} for i in range(200)], "n": 200}
    text, cut = cut_json(big, 2500)
    assert cut and len(text) <= 2500
    back = json.loads(text)
    assert back["list"] and all(set(x) == {"id", "name", "why"} for x in back["list"])
    small, cut = cut_json({"a": 1}, 2500)
    assert small == '{"a":1}' and not cut
    s = copy.deepcopy(BASE)
    s["moods"] = big
    msg = review_message(s, "routine", [], [], {}, [], wants=["moods"])
    line = next(x for x in msg.splitlines() if x.startswith("SECTION moods"))
    assert line.endswith(" (cut)"), line[-40:]
    json.loads(line[len("SECTION moods (as you asked, cut) "):-len(" (cut)")])


# --- 5. the Rules tab line ---------------------------------------------------------

@test("RULES TAB: off by default is 'off'; only a switch the player turned off is 'switched off by the player'")
def _():
    from planner import player_rules
    line = rules_line(player_rules({"settings": {}}))
    assert "switched off by the player" not in line and "off: open_caverns, send_messenger" in line, line
    line = rules_line(player_rules({"settings": {"fill_squads": False}}))
    assert "switched off by the player: fill_squads" in line and "open_caverns" not in line.split("player:")[1].split("|")[0]


# --- 6. the season and the call itself ---------------------------------------------

@test("API: models from 4.6 on get adaptive thinking and an effort, never the manual budget they refuse")
def _():
    from backends import thinking_params
    for model in ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-4-6"):
        body, most = thinking_params(model, 2000, 1200)
        assert body == {"thinking": {"type": "adaptive"}, "output_config": {"effort": "medium"}}, body
        assert most > 1200 + 2000 - 1
        body, most = thinking_params(model, 0, 1200)
        assert "thinking" not in body and body["output_config"]["effort"] == "low" and most > 1200, body
    body, most = thinking_params("claude-3-5-haiku-20241022", 2000, 1200)
    assert body == {"thinking": {"type": "enabled", "budget_tokens": 2000}} and most == 3200
    assert thinking_params("claude-sonnet-4-5", 0, 1200) == ({}, 1200)


@test("API backend: the request carries the thinking it should (fake client)")
def _():
    import backends

    class Resp:
        content = [type("B", (), {"type": "text", "text": '{"note":"x"}'})()]
        usage = type("U", (), {"input_tokens": 10, "output_tokens": 5})()

    sent = {}

    class Client:
        class messages:
            @staticmethod
            def create(**kw):
                sent.update(kw)
                return Resp()
    b = backends.ApiBackend.__new__(backends.ApiBackend)
    b.client, b.model, b.model_events, b.model_top = Client, "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"
    r = b.ask("i", "m", effort={"model": "large", "thinking": 3000, "answer_tokens": 1200})
    assert r.text == '{"note":"x"}' and "thinking" not in sent, sent
    assert sent["extra_body"]["thinking"] == {"type": "adaptive"} and sent["model"] == "claude-sonnet-5-5"


@test("season: the AI raising a hall the Rules tab refuses keeps the fort to its ways")
def _():
    import season
    s = copy.deepcopy(BASE)
    s["settings"] = {"traits": {}, "levels": {"tavern": False}}
    m = Memory()
    said = season.apply({"choice": "raise:tavern"}, s, m, m.adjust)
    assert m.culture["season_choice"]["choice"] == "keep" and "can't come first" in said[0], said
    assert season.raised(m, abs_tick(normalize(s))) is None


@test("token bank: a new fort's first (season) review is affordable at every slider setting")
def _():
    from review import maybe_review
    recipes = [f"recipe_number_{i}" for i in range(120)]       # a real bridge's recipe list
    for f in (-200, 0, 200):
        for e in (-200, 0, 100, 200):
            s = copy.deepcopy(REAL)
            s["settings"].update(ai_frequency=f, ai_effort=e, real_day_token_cap=0)
            c = Fake('{"note":"x"}')
            out = maybe_review(s, Memory(), TokenBank(), c, {"recipes": recipes, "tools": ["autochop"] * 20}, [])
            assert c.calls, (f, e, out.say)


@test("end to end on a real fort: review, answer, check, actions, steer, want, then the section shown")
def _():
    from review import maybe_review
    s, m, bank = _ai(REAL), Memory(), TokenBank()
    props, notes = plan(copy.deepcopy(s), m)
    shown = next(p.rule for p in props if p.rule not in STEER_PROTECTED and p.rule != "build")
    c = Fake(json.dumps({"note": "steady", "adjust": {}, "want": ["needs", "infection"],
                         "actions": [{"type": "work_order", "recipe": "brew_drink", "amount": 5},
                                     {"type": "raise", "rule": shown, "why": "now"},
                                     {"type": "hold", "rule": "mood", "days": 84, "why": "no"}],
                         "season": {"choice": "focus:drink", "line": "The winter of the mugs."}}))
    out = maybe_review(s, m, bank, c, INFO, notes, proposals=props)
    assert len(c.calls) == 1, out.say
    instr, msg, _ = c.calls[0]
    assert "CHARACTER DECISION" in instr and "THE PLANNER PROPOSES NOW" in msg
    assert [p.action for p in out.proposals] == [{"type": "work_order", "recipe": "brew_drink", "amount": 5}]
    assert m.steer[shown]["mode"] == "raise" and "mood" not in m.steer
    assert m.strategist_wants == ["needs", "infection"]
    assert m.culture["season_choice"]["choice"] == "focus:drink"
    assert out.journal["kind"] == "review" and out.journal["tokens"] > 0
    # the next review shows what it asked for
    s2 = copy.deepcopy(s)
    s2["date"]["tick"] += 20 * TICKS_PER_DAY
    c2 = Fake('{"note":"ok"}')
    maybe_review(s2, m, bank, c2, INFO, notes, proposals=props)
    assert c2.calls and "SECTION needs (as you asked" in c2.calls[0][1], [x[:30] for x in c2.calls[0][1].splitlines()]


if __name__ == "__main__":
    finish()

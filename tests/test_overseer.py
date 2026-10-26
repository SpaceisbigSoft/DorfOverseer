"""End-to-end tests of the overseer loop with a fake game and a fake Claude.
Nothing real is called and no tokens are spent.

    python tests/test_overseer.py
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

import overseer  # noqa: E402

overseer.THROTTLE_MEMORY_SAVE = False      # every write seen (the throttle has its own test)
# (0.95) These tests are about the loop, not style: the test fort's close calls
# and its own and site leanings are switched off, so it keeps the default style
# (no gate traps to ask about). Style variety has its own tests (test_weights).
overseer.leanings.OWN_MAX = 0
overseer.leanings.site_leanings = lambda state: []
import weights  # noqa: E402
weights.data()["settings"]["near"] = 0.0
from backends import Reply  # noqa: E402
from dfhack import DFHackError  # noqa: E402
from tokens import TICKS_PER_DAY  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
RESULTS = []
TMP = Path(tempfile.mkdtemp())
overseer.memstore.FORTS_DIR = TMP / "forts"
overseer.memstore.LEGACY_FILE = TMP / "memory.json"      # the one-file memory from before 0.31
MEMORY_FILE = overseer.memstore.LEGACY_FILE
FORT_MEMORY = overseer.memstore.fort_dir("AI Test Run#1234") / "memory.json"
overseer.JOURNAL = TMP / "decisions.jsonl"
overseer.STOP_FILE = TMP / "STOP"
overseer.learning.PLAYER_FILE = TMP / "player-memory.json"
overseer.say = lambda msg: SAID.append(msg)
SAID: list[str] = []


def test(name):
    def wrap(fn):
        for f in (MEMORY_FILE, overseer.JOURNAL, overseer.STOP_FILE, overseer.learning.PLAYER_FILE):
            f.unlink(missing_ok=True)
        shutil.rmtree(overseer.memstore.FORTS_DIR, ignore_errors=True)
        overseer.PRINTED.clear()
        overseer.LAST_FULL.clear()
        SAID.clear()
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            import traceback
            RESULTS.append((name, False, traceback.format_exc()))
        return fn
    return wrap


class FakeBridge:
    version = {"recipes": ["brew_drink", "stone_blocks", "prepare_fine_meal"],
               "tools": ["autochop", "seedwatch", "suspendmanager"]}

    def __init__(self, state=None, events=None, act_error=None):
        self._state = state or copy.deepcopy(BASE)
        self._events = events or []
        self.acted: list[dict] = []
        self.reports: list[dict] = []          # report_status (display only) kept apart
        self.act_error = act_error
        self.halted = False
        self.decisions: dict = {}
        self.commands: list[str] = []
        outer = self

        class _DF:
            def run(self, *args):
                outer.commands.append(" ".join(args))
                return ""
        self.df = _DF()

    def status(self):
        return {"ok": True, "in_fort": True, "halted": self.halted, "decisions": dict(self.decisions)}

    def state(self, include_units=True):
        return copy.deepcopy(self._state)

    def events(self):
        ev, self._events = self._events, []
        return ev

    def act(self, action):
        if action["type"] == "report_status":
            self.reports.append(action["status"])
            for pid in action["status"].get("ack", []):
                self.decisions.pop(pid, None)
            return {"ok": True}
        if self.act_error:
            raise self.act_error
        self.acted.append(action)
        if action["type"] == "tool":
            return {"ok": True, "name": action["name"], "enabled": True}
        return {"ok": True, "order_id": 900 + len(self.acted)}

    def advance(self, days):
        self._state["date"]["tick"] += days * TICKS_PER_DAY


class FakeClaude:
    name = "subscription"

    def __init__(self, answer='{"note":"all fine","actions":[]}', error=None):
        self.answer, self.error = answer, error
        self.calls: list[tuple[str, str, bool]] = []

    def ask(self, instructions, message, important=False, effort=None):
        self.calls.append((instructions, message, important))
        self.efforts = getattr(self, "efforts", []) + [effort]
        if self.error:
            raise self.error
        return Reply(text=self.answer, input_tokens=2000, output_tokens=150, model="fake-haiku")


def entries(kind=None):
    if not overseer.JOURNAL.exists():
        return []
    rows = [json.loads(x) for x in overseer.JOURNAL.read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if kind is None or r.get("kind") == kind]


def saved():
    """The memory as kept in logs/ ({"memory": ..., "bank": ...})."""
    return overseer.memstore.read_logged("AI Test Run#1234")


# --- planner only -----------------------------------------------------------------

@test("season (0.104.3): without the AI the script makes the season's choice once, says it, journals it; not in a dry run")
def _():
    b = FakeBridge()
    overseer.one_cycle(b, autopilot=False)
    assert not entries("season")
    overseer.one_cycle(b, autopilot=True)
    e = entries("season")
    assert len(e) == 1 and e[0]["by"] == "script" and e[0]["choice"]["choice"], e
    assert any("Season (script):" in x for x in SAID), SAID
    assert saved()["memory"]["culture"]["season_done"]
    overseer.one_cycle(b, autopilot=True)
    assert len(entries("season")) == 1                        # once a season


@test("dry run: proposes, logs, changes nothing in the game")
def _():
    b = FakeBridge()
    b._state["stocks"]["drink"] = 10
    overseer.one_cycle(b, autopilot=False)
    assert b.acted == []
    d = entries("decision")
    assert d and all(x["mode"] == "dry-run" for x in d) and any(x["rule"] == "drink" for x in d)


@test("autopilot: acts, then the cooldown stops a repeat the next day")
def _():
    b = FakeBridge()
    b._state["stocks"]["drink"] = 10
    overseer.one_cycle(b, autopilot=True)
    assert any(a.get("recipe") == "brew_drink" for a in b.acted), b.acted
    n = len(b.acted)
    b.advance(1)
    overseer.one_cycle(b, autopilot=True)
    assert not any(a.get("recipe") == "brew_drink" for a in b.acted[n:])


@test("STOP file: nothing is done")
def _():
    overseer.STOP_FILE.write_text("")
    b = FakeBridge()
    b._state["stocks"]["drink"] = 10
    overseer.one_cycle(b, autopilot=True)
    assert b.acted == []


@test("game timeout mid-action: memory still saved, action not repeated next cycle")
def _():
    b = FakeBridge(act_error=DFHackError("dfhack-run timed out"))
    b._state["stocks"]["drink"] = 10
    overseer.one_cycle(b, autopilot=True)
    assert "drink" in saved()["memory"]["last_fired"]
    b.act_error = None
    overseer.one_cycle(b, autopilot=True)
    assert not any(a.get("recipe") == "brew_drink" for a in b.acted)


@test("a crash inside the cycle still saves memory")
def _():
    b = FakeBridge()
    b._state["stocks"]["drink"] = 10
    b.act = lambda a: (_ for _ in ()).throw(KeyError("boom"))
    try:
        overseer.one_cycle(b, autopilot=True)
    except KeyError:
        pass
    assert FORT_MEMORY.exists()


@test("unknown fort (fort section failed): skips the cycle, saves nothing")
def _():
    b = FakeBridge()
    b._state["fort"] = {"error": "boom"}
    b._state["stocks"]["drink"] = 10
    overseer.one_cycle(b, autopilot=True)
    assert b.acted == [] and not FORT_MEMORY.exists()


@test("memory file from the previous version still loads")
def _():
    MEMORY_FILE.write_text(json.dumps({"AI Test Run#1234": {"last_fired": {"drink": 5}}}))
    m, bank = overseer.load("AI Test Run#1234")
    assert m.last_fired == {"drink": 5} and bank.balance == 0


# --- with the AI strategist -----------------------------------------------------------

@test("AI: first cycle runs a routine review, spends from the bank, logs it")
def _():
    c = FakeClaude()
    overseer.one_cycle(FakeBridge(), autopilot=True, backend=c)
    assert len(c.calls) == 1 and c.calls[0][2] is False
    r = entries("review")[0]
    assert r["tokens"] == 2150 and r["note"] == "all fine"
    assert saved()["bank"]["balance"] == 50000 - 2150


@test("AI: no second review until the routine interval passes (14 days at 50%)")
def _():
    c, b = FakeClaude(), FakeBridge()
    overseer.one_cycle(b, autopilot=True, backend=c)
    b.advance(13)
    overseer.one_cycle(b, autopilot=True, backend=c)
    assert len(c.calls) == 1
    b.advance(1)
    overseer.one_cycle(b, autopilot=True, backend=c)
    assert len(c.calls) == 2


@test("AI: its actions and adjustments go through the same limits")
def _():
    c = FakeClaude('{"note":"brew ahead","adjust":{"drink_per_dwarf":25},'
                   '"actions":[{"type":"work_order","recipe":"brew_drink","amount":40},'
                   '{"type":"tool","name":"autochop","enabled":true}]}')
    b = FakeBridge()
    overseer.one_cycle(b, autopilot=True, backend=c)
    assert {"type": "work_order", "recipe": "brew_drink", "amount": 40} in b.acted, b.acted
    assert saved()["memory"]["adjust"] == {"drink_per_dwarf": 25}
    assert len([a for a in b.acted if a["type"] not in ("set_culture", "set_learned", "ledger_set")]) <= 3


@test("AI: hostile answer does nothing; what was thrown out is logged")
def _():
    c = FakeClaude('{"actions":[{"type":"work_order","recipe":"Sleep","amount":5},'
                   '{"type":"run_lua","code":"os.exit()"},{"type":"cancel_work_order","order_id":500}]}')
    b = FakeBridge()
    overseer.one_cycle(b, autopilot=True, backend=c)
    assert not [x for x in entries("decision") if x["rule"] == "strategist"]
    assert len(entries("review")[0]["rejected"]) == 3


@test("AI: can't lower an alert the player raised")
def _():
    c = FakeClaude('{"actions":[{"type":"civ_alert","on":false}]}')
    b = FakeBridge()
    b._state["civ_alert"] = True
    overseer.one_cycle(b, autopilot=True, backend=c)
    assert b.acted == [] or {"type": "civ_alert", "on": False} not in b.acted
    assert any("player raised" in r for r in entries("review")[0]["rejected"])


@test("AI: connection failure -> planner carries on, retries in a day (not every cycle)")
def _():
    c, b = FakeClaude(error=RuntimeError("not signed in")), FakeBridge()
    b._state["stocks"]["drink"] = 10
    overseer.one_cycle(b, autopilot=True, backend=c)
    assert any(a.get("recipe") == "brew_drink" for a in b.acted) and entries("review_failed")
    b._state["date"]["tick"] += 600
    overseer.one_cycle(b, autopilot=True, backend=c)
    assert len(c.calls) == 1
    b.advance(1)
    overseer.one_cycle(b, autopilot=True, backend=c)
    assert len(c.calls) == 2


@test("AI: a siege tops up the bank and triggers an event review with the stronger model")
def _():
    c, b = FakeClaude(), FakeBridge()
    overseer.one_cycle(b, autopilot=True, backend=c)       # routine review first
    b.advance(1)
    b._events = [{"kind": "invasion"}]
    overseer.one_cycle(b, autopilot=True, backend=c)
    assert len(c.calls) == 2 and c.calls[1][2] is True, [x[2] for x in c.calls]
    assert "siege" in c.calls[1][1] and "invasion" in c.calls[1][1]
    assert saved()["bank"]["last_topup"].get("siege") is not None


@test("AI: an empty bank skips the routine review (and says why)")
def _():
    c, b = FakeClaude(), FakeBridge()
    MEMORY_FILE.write_text(json.dumps({"AI Test Run#1234": {
        "memory": {}, "bank": {"balance": 1000, "last_tick": 148 * 403200 + 332256}}}))
    overseer.one_cycle(b, autopilot=True, backend=c)
    assert c.calls == [] and entries("review_skipped") and any("skipped" in s for s in SAID)


@test("AI: the review message names no dwarves and stays compact")
def _():
    c = FakeClaude()
    overseer.one_cycle(FakeBridge(), autopilot=False, backend=c)
    instr, msg, _ = c.calls[0]
    assert "Zas Oslantarmid" not in msg
    # (0.103.20) the first review of a season carries the season's menu (4 a year)
    # (0.104.89) and the wider view of 14a (steering the planner's rules, the
    # Rules tab, what the planner proposes): about 3.6k tokens, in line with
    # what 14.0's audit measured a real call to cost
    assert (len(instr) + len(msg)) / 2.5 < 3700, len(instr) + len(msg)


@test("AI (0.104.89): a review's raise and hold reach the planner's memory, are said, and the token ratio is learned")
def _():
    c = FakeClaude(answer=json.dumps({"note": "raise the garden, hold the dairy", "actions": [
        {"type": "raise", "rule": "grandeur", "why": "good times"},
        {"type": "hold", "rule": "dairy", "days": 20, "why": "the herd is for war"}], "want": ["trade"]}))
    overseer.one_cycle(FakeBridge(), autopilot=False, backend=c)
    m = saved()["memory"]
    assert m["steer"]["grandeur"]["mode"] == "raise" and m["steer"]["dairy"]["mode"] == "hold", m.get("steer")
    assert m["strategist_wants"] == ["trade"] and m["token_ratio"] != 1.0, (m.get("strategist_wants"), m.get("token_ratio"))
    assert any("AI steers: hold dairy for 20 day(s)" in x for x in SAID), SAID[-12:]


# --- culture ----------------------------------------------------------------------------

@test("culture: a slain forgotten beast is remembered, and a memorial is planned for a young fort")
def _():
    b = FakeBridge(events=[{"kind": "death", "hostile": True,
                            "name": 'Shulmik Soshoshritas "Jackalowls", Forgotten Beast'}])
    overseer.one_cycle(b, autopilot=False)
    m = saved()["memory"]["culture"]
    assert m["beasts_slain"] == ["Shulmik the Jackalowls"], m
    assert any("Jackalowls" in x for x in SAID)


@test("culture: the first cycle starts an era; it is copied into the save once, not every cycle")
def _():
    b = FakeBridge()
    overseer.one_cycle(b, autopilot=True)
    pushes = [a for a in b.acted if a["type"] == "set_culture"]
    assert len(pushes) == 1 and pushes[0]["culture"]["eras"], pushes
    assert any("new era" in x for x in SAID)
    b.advance(1)
    overseer.one_cycle(b, autopilot=True)
    assert len([a for a in b.acted if a["type"] == "set_culture"]) == 1


@test("culture: dry run never writes the culture into the save")
def _():
    b = FakeBridge()
    overseer.one_cycle(b, autopilot=False)
    assert not [a for a in b.acted if a["type"] == "set_culture"]


@test("culture: changing the sliders starts a new era and updates the save")
def _():
    b = FakeBridge()
    overseer.one_cycle(b, autopilot=True)
    b._state["settings"]["traits"] = {"grandeur": 150}
    b.advance(1)
    overseer.one_cycle(b, autopilot=True)
    pushes = [a for a in b.acted if a["type"] == "set_culture"]
    assert len(pushes) == 2 and pushes[-1]["culture"]["profile"]["hall"] == "pillared"
    assert len(saved()["memory"]["culture"]["eras"]) == 2


@test("AI: set_style changes the fort's style and guide, nothing else")
def _():
    c = FakeClaude('{"note":"darker","actions":[{"type":"set_style","palette":"dark","hall":"rounded",'
                   '"guide":"Low dark halls carved with the deeds of the fort."}]}')
    b = FakeBridge()
    b._state["mandates"] = []
    overseer.one_cycle(b, autopilot=True, backend=c)
    cul = saved()["memory"]["culture"]
    assert {k: v["value"] for k, v in cul["overrides"].items()} == {"palette": "dark", "hall": "rounded"}
    assert cul["guide"].startswith("Low dark")
    pushes = [a for a in b.acted if a["type"] == "set_culture"]
    assert pushes and pushes[-1]["culture"]["guide"].startswith("Low dark")
    assert not [a for a in b.acted if a["type"] not in ("set_culture", "set_learned", "tool", "ledger_set")]



# --- Phase 5: in-game controls ------------------------------------------------------------

def young(mode="autopilot", **settings):
    """A fort with too few beds (so a new level is wanted), in the given mode."""
    b = FakeBridge()
    st = b._state
    st["mandates"] = []                  # keep the action slots for what's being tested
    st["buildings"]["other"]["Bed"] = 20
    st["settings"]["mode"] = mode
    st["settings"].update(settings)
    return b


def kinds(b):
    return [a["type"] for a in b.acted if a["type"] not in ("set_culture", "set_learned")]


@test("halted in the game: nothing is changed, the panel says so")
def _():
    b = young()
    b._state["stocks"]["drink"] = 10
    b.halted = True
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    assert kinds(b) == [] and b.reports and b.reports[-1]["acting"] == "halted in the game"


@test("advisor mode: only suggests; the panel lists what it would do")
def _():
    b = young("advisor")
    b._state["stocks"]["drink"] = 10
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    assert kinds(b) == []
    assert any(x.startswith("would ") for x in b.reports[-1]["last"]), b.reports[-1]["last"]


@test("co-pilot: routine work goes ahead; a new level waits for your Yes")
def _():
    b = young("copilot")
    b._state["stocks"]["drink"] = 10
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    assert "work_order" in kinds(b) and "start_project" not in kinds(b), kinds(b)
    ask = b.reports[-1]["pending"]
    assert ask and "bedrooms" in ask[0]["text"], ask
    b.decisions[ask[0]["id"]] = "yes"
    b.advance(1)
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    assert "start_project" in kinds(b), kinds(b)
    assert b.decisions == {}                       # the answer was acknowledged


@test("co-pilot: a No is respected for 7 in-game days, then it may ask again")
def _():
    b = young("copilot")
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    pid = b.reports[-1]["pending"][0]["id"]
    b.decisions[pid] = "no"
    b.advance(1)
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    assert "start_project" not in kinds(b) and b.reports[-1]["pending"] == []
    b.advance(5)
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    assert b.reports[-1]["pending"] == []
    b.advance(2)
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    assert b.reports[-1]["pending"] and b.reports[-1]["pending"][0]["id"] == pid


def devout(mode="copilot"):
    """An established fort that only lacks a temple (Piety 60)."""
    b = FakeBridge()
    st = b._state
    st["mandates"] = []
    st["settings"].update({"mode": mode, "traits": {"piety": 60}})
    st["locations"] = {"count": {"HOSPITAL": 1, "INN_TAVERN": 1, "LIBRARY": 1}, "total": 3}
    return b


@test("learning: a No holds temples back 4 weeks; a second No makes a lesson; the panel shows it")
def _():
    b = devout()
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    pid = b.reports[-1]["pending"][0]["id"]
    assert "temple" in b.reports[-1]["pending"][0]["text"]
    b.decisions[pid] = "no"
    b.advance(1)
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    assert any("you declined" in x for x in SAID)
    b.advance(10)                         # past the 7-day No, but the AI learned: it still waits
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    assert b.reports[-1]["pending"] == [] and any("holding back on temples" in n
                                                  for n in saved()["memory"]["notes"])
    b.advance(20)
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    pid = b.reports[-1]["pending"][0]["id"]
    b.decisions[pid] = "no"
    b.advance(1)
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    assert any("lesson: you don't want temples" in x for x in SAID), SAID
    b.advance(100)
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    assert b.reports[-1]["pending"] == []
    pushes = [a for a in b.acted if a["type"] == "set_learned"]
    assert pushes and pushes[-1]["learned"]["prefs"][0]["lesson"] is True
    assert pushes[-1]["learned"]["prefs"][0]["effect"] == "left to you"
    assert [e for e in entries("learned")]
    lesson = json.loads(overseer.learning.PLAYER_FILE.read_text(encoding="utf-8"))["lessons"]
    assert "level:temple" in lesson


@test("outcome log: an autopilot brewing order opens an entry; it's judged 2 weeks later and logged")
def _():
    b = FakeBridge()
    b._state["stocks"]["drink"] = 10
    b._state["date"]["tick"] = 0
    overseer.one_cycle(b, autopilot=True)
    assert saved()["memory"]["outcomes"]["open"][0]["kind"] == "drink_order"
    b._state["stocks"]["drink"] = 3000
    b.advance(15)
    overseer.one_cycle(b, autopilot=True)
    e = entries("outcome")
    assert e and e[0]["verdict"] == "helped", e
    pushes = [a for a in b.acted if a["type"] == "set_learned"]
    assert pushes and pushes[-1]["learned"]["verdicts"]


@test("learning: a dry run learns nothing into the save and pushes nothing")
def _():
    b = devout("autopilot")
    overseer.one_cycle(b, autopilot=False)
    assert not [a for a in b.acted if a["type"] == "set_learned"]


@test("save before new levels: the game is saved first, the level starts next cycle")
def _():
    b = young("autopilot", save_before_projects=True)
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    assert b.commands == ["quicksave"] and "start_project" not in kinds(b)
    b.advance(1)
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    assert "start_project" in kinds(b) and b.commands == ["quicksave"]


@test("the panel shows the last actions with their reasons")
def _():
    b = young()
    b._state["stocks"]["drink"] = 10
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    r = b.reports[-1]
    assert r["mode"] == "Autopilot" and r["acting"] == "acting"
    assert any("brew drink" in x and "below the target" in x for x in r["last"]), r["last"]



@test("review 5: co-pilot + save first: one Yes is enough (save, then build)")
def _():
    b = young("copilot", save_before_projects=True)
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    pid = b.reports[-1]["pending"][0]["id"]
    b.decisions[pid] = "yes"
    b.advance(1)
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    assert b.commands == ["quicksave"] and "start_project" not in kinds(b)
    b.advance(1)
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    assert "start_project" in kinds(b) and b.reports[-1]["pending"] == [], b.reports[-1]["pending"]


@test("review 5: a No still holds when the fort's size changes the request")
def _():
    b = young("copilot")
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    b.decisions[b.reports[-1]["pending"][0]["id"]] = "no"
    b.advance(1)
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    b._state["dwarves"]["total"] += 7               # migrants: more rooms wanted now
    b.advance(1)
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    assert b.reports[-1]["pending"] == [] and "start_project" not in kinds(b)



@test("needs you: what only the player can set up goes to the panel apart from the notes")
def _():
    b = FakeBridge()
    b._state["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    b._state["civ_alert_ready"] = False
    b._state["settings"]["alert_shelter"] = False        # so the AI can't set it up itself
    overseer.one_cycle(b, autopilot=True)
    st = b.reports[-1]
    assert any("civilian-alert" in t for t in st["todo"]), st
    assert not any("civilian-alert" in n for n in st["notes"]) and not any(t.startswith("[you]") for t in st["todo"])
    assert any(m.startswith("  NEEDS YOU:") for m in SAID), SAID


# --- memory kept in the save ---------------------------------------------------------

class SaveBridge(FakeBridge):
    """A fake game whose save can hold the overseer's memory, one key per kind
    (as lua/ai-bridge.lua keeps it). saved_memory is what the save holds:
    {"kinds": {kind: {"fort", "text"}}, "legacy": {...}} (a test may also put
    an old one-blob memory there)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.saved_memory = None
        self.writes: list[dict] = []

    def load_memory(self):
        return copy.deepcopy(self.saved_memory)

    def save_memory(self, data):
        data = json.loads(json.dumps(data))
        self.writes.append(data)
        sm = self.saved_memory if isinstance(self.saved_memory, dict) and "kinds" in self.saved_memory else {
            "kinds": {}, **({"legacy": self.saved_memory} if self.saved_memory else {})}
        for k, text in data["kinds"].items():
            assert isinstance(text, str), "each kind travels as text"
            sm["kinds"][k] = {"fort": data["fort"], "text": text}
        if data.get("drop_legacy"):
            sm.pop("legacy", None)
        self.saved_memory = sm
        return True

    def memory(self) -> dict:
        """The memory in the save, joined back up: {"fort", "memory", "bank"}."""
        kinds = (self.saved_memory or {}).get("kinds") or {}
        datas = {k: overseer.memstore.decode(k, v["text"]) for k, v in kinds.items()}
        m, bank = overseer.memstore.join(datas)
        forts = {v["fort"] for v in kinds.values()}
        return {"fort": forts.pop() if len(forts) == 1 else None, "memory": m.to_dict(), "bank": bank.to_dict()}


@test("memory: autopilot writes it into the save; a dry run doesn't")
def _():
    b = SaveBridge()
    b._state["stocks"]["drink"] = 10
    overseer.one_cycle(b, autopilot=False, controls=b.status())
    assert b.saved_memory is None
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    assert b.memory()["fort"] == "AI Test Run#1234" and "drink" in b.memory()["memory"]["last_fired"]


@test("memory: reloading an older save brings back what the AI knew then")
def _():
    b = SaveBridge()
    b._state["stocks"]["drink"] = 10
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    older = copy.deepcopy(b.saved_memory)                 # the player saves here
    b.advance(3)
    b._state["buildings"]["other"]["Bed"] = 20
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    assert "build" in saved()["memory"]["last_fired"]       # later: a level was started
    b.saved_memory = older                                 # ...and the player reloads the older save
    m, _ = overseer.load("AI Test Run#1234", b)
    assert "build" not in m.last_fired and "drink" in m.last_fired


@test("memory: another fort's memory in the save is ignored")
def _():
    b = SaveBridge()
    b.saved_memory = {"fort": "Other#9", "memory": {"last_fired": {"drink": 5}}, "bank": {}}
    m, _ = overseer.load("AI Test Run#1234", b)
    assert m.last_fired == {}


@test("memory: still kept while halted (it's bookkeeping, not a change to the fort)")
def _():
    b = SaveBridge()
    b.halted = True
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    assert b.saved_memory is not None and kinds(b) == []


@test("farm plots: short label; co-pilot asks only when a farm level would be dug")
def _():
    a = {"type": "farm_plots", "tiles": 40, "dig": True}
    assert overseer.short(a) == "lay out 40 farm tiles (or dig a farm level)", overseer.short(a)
    assert overseer.is_big(a)
    a["dig"] = False
    assert overseer.short(a) == "lay out 40 farm tiles" and not overseer.is_big(a)
    assert overseer.short({"type": "make_pasture", "tiles": 75}) == "make a 75-tile pasture"
    assert not overseer.is_big({"type": "make_pasture", "tiles": 75})
    w = {"type": "place_well"}
    assert overseer.short(w) == "dig a well over water" and overseer.is_big(w)


@test("kitchen ban (0.100): short labels; routine work, not asked about in co-pilot")
def _():
    a = {"type": "kitchen_brewables", "ban": True}
    assert overseer.short(a) == "stop the kitchen cooking brewable plants" and not overseer.is_big(a)
    assert overseer.short({"type": "kitchen_brewables", "ban": False}) == "let the kitchen cook brewable plants again"


@test("the memory goes into the game's save once a game week, and daily in a season's last 3 days")
def _():
    overseer.THROTTLE_MEMORY_SAVE = True
    try:
        overseer.LAST_MEMORY_SAVE.clear()
        st = {"date": {"year": 50, "tick": 1200 * 10}}
        assert overseer.memory_save_due("f", st)
        overseer.LAST_MEMORY_SAVE["f"] = overseer.abs_tick(st)
        st2 = {"date": {"year": 50, "tick": 1200 * 12}}
        assert not overseer.memory_save_due("f", st2)
        assert overseer.memory_save_due("f", {"date": {"year": 50, "tick": 1200 * 17}})        # a week on
        assert overseer.memory_save_due("f", {"date": {"year": 50, "tick": 1200 * 82}})        # season's end
        assert overseer.memory_save_due("f", {"date": {"year": 49, "tick": 0}})                # an older save
    finally:
        overseer.THROTTLE_MEMORY_SAVE = False

@test("the memory is read from the save once, then kept while the game's clock runs on; read again after a reload")
def _():
    calls = []
    real = overseer.memstore.load
    overseer.memstore.load = lambda key, bridge, prefer: calls.append(key) or (overseer.Memory(), object())
    overseer.THROTTLE_MEMORY_SAVE = True
    try:
        overseer.MEMORY_CACHE.clear()
        st = lambda t: {"date": {"year": 50, "tick": t}}
        m1, _b = overseer.load("f", None, False, st(1200))
        m2, _b = overseer.load("f", None, False, st(2400))
        assert m1 is m2 and calls == ["f"], calls
        overseer.load("f", None, False, st(600))                     # the clock went back: an older save
        assert calls == ["f", "f"], calls
        overseer.load("f", None, False, st(600 + 31 * 1200))         # jumped far ahead
        assert len(calls) == 3
        # (0.104.45) a save that couldn't be read isn't kept: read again next cycle
        def unread(key, bridge, prefer):
            calls.append(key)
            m = overseer.Memory()
            m._texts = {"save_unread": True}
            return m, object()
        overseer.memstore.load = unread
        overseer.load("f", None, False, st(100))                      # back: read, unreadable
        overseer.load("f", None, False, st(200))                      # not kept: read again
        assert len(calls) == 5, calls
    finally:
        overseer.memstore.load = real
        overseer.THROTTLE_MEMORY_SAVE = False
        overseer.MEMORY_CACHE.clear()


@test("strategist adjustments last a season, then the planner's own values return (0.97.1, B7)")
def _():
    from planner import Memory as M
    m = M()
    m.adjust = {"drink_per_dwarf": 30}
    st = {"date": {"year": 100, "tick": 0}}
    assert overseer.expire_adjustments(m, st) == [] and m.adjust_at == {"drink_per_dwarf": 100 * 403200}
    st = {"date": {"year": 100, "tick": overseer.ADJUST_LASTS_TICKS - 1}}
    assert overseer.expire_adjustments(m, st) == [] and m.adjust
    st = {"date": {"year": 100, "tick": overseer.ADJUST_LASTS_TICKS}}
    assert overseer.expire_adjustments(m, st) == ["drink_per_dwarf"] and m.adjust == {} and m.adjust_at == {}


@test("camera (0.104.90): the keeper sends the camera the plan's district names and its newest work's reasons")
def _():
    m = overseer.Memory()
    m.atlas = {"plan": {"districts": [{"name": "the Pale Hearths", "lo": 120, "hi": 125, "kind": "homes"},
                                      {"name": "bad", "lo": "x", "hi": 3}]}}
    m.recent_actions = [{"action": {"type": "build", "kind": "temple"}, "reason": "the gods are wanted"},
                        {"action": {"type": "tool", "name": "autofarm", "enabled": True}, "reason": ""}]
    feed = overseer.camera_feed(m)
    assert feed["districts"] == [{"name": "the Pale Hearths", "lo": 120, "hi": 125}], feed
    assert feed["news"][0] == "autofarm on" and "the gods are wanted" in feed["news"][1], feed["news"]
    assert len(json.dumps(feed)) < 2000


@test("camera (0.104.91): the feed skips routine actions and puts a level's reason first")
def _():
    overseer._CAMERA_LEVELS.clear()
    m = overseer.Memory()
    m.recent_actions = [{"action": {"type": "start_project", "kind": "hospital"}, "reason": "no hospital for 39 dwarves"},
                        {"action": {"type": "dismiss_alerts"}, "reason": "old icons"}]
    overseer.camera_feed(m)
    # ten cycles later the hospital is out of memory's 10, but its reason stays
    m.recent_actions = ([{"action": {"type": "dismiss_alerts"}, "reason": "old icons"}] * 8
                        + [{"action": {"type": "work_order", "recipe": "wooden_barrel", "amount": 3}, "reason": "barrels"},
                           {"action": {"type": "finish_project", "project_id": 29}, "reason": "storage level #29 is fully built"}])
    news = overseer.camera_feed(m)["news"]
    assert news[0] == "dig a new hospital level: no hospital for 39 dwarves", news
    assert not any("old icons" in n for n in news) and len(news) == 3, news
    overseer._CAMERA_LEVELS.clear()


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

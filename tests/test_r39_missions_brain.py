"""(0.105.39, phase 13b offence) The missions brain (brain/planner_missions.py)
on the real test fort: the reserve, the guard, a threat near, one mission at
a time, the Rules switch's levels, raids only against the hostile and only
at 'all', the retry after a stopped run, a mission followed to its return,
game text quoted and cut short, and the plan without `missions.targets`
the same as main's.

    python tests/test_r39_missions_brain.py
"""

from __future__ import annotations

import atexit
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

from planner import Memory, PLANNER_CONFIG, TICKS_PER_YEAR, abs_tick, note_cycle, plan, player_rules  # noqa: E402
import planner_missions as PM  # noqa: E402
import digest  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = PLANNER_CONFIG


def target(goal="rescue", site_id=101, dist=5, **kw) -> dict:
    t = {"goal": goal, "site_id": site_id, "site": f"Site{site_id}", "dist": dist, "civ_id": 7, "civ": "The Goblins",
         "why": "held there", "hostile": False, "at_war": False}
    if goal == "rescue":
        t.update(hf_id=900 + site_id, hf="Urist McHeld")
    if goal == "recover_artifact":
        t.update(artifact_id=500 + site_id, artifact="The Gem of Ages")
    t.update(kw)
    return t


def fort(targets=None, militarism=0, send=None, **rules) -> dict:
    s = copy.deepcopy(BASE)
    s["settings"]["traits"] = {"militarism": militarism}
    s["settings"].update(rules)
    for q in s["military"]["squads"]:
        q["power"] = {"power": 10.0, "armed": q["members"], "armored": 0}
    s["missions"] = {"controllers": [], "reports": {"n": 0, "unviewed": 0}, "spoils": {"n": 0}, "sites": {},
                     "unknown": [], "squads": [{"id": q["id"], "name": q["name"], "members": q["members"], "away": 0}
                                               for q in s["military"]["squads"]],
                     "targets": [target()] if targets is None else targets}
    if send is not None:
        s["missions"]["send"] = send
    return s


def button(*goals, last=None) -> dict:
    d = {"on": True, "buttons": ["World", "Diplomacy"], "goals": {g: {"button": True, "recorded": "confirm"} for g in goals}}
    if last is not None:
        d["last"] = last
    return d


def rule(s, memory=None):
    props, notes = [], []
    from digest import normalize
    s = normalize(s)
    PM._mission_rule(s, CFG, props, notes, memory)
    return props, notes


def needs(notes):
    return [n for n in notes if n.startswith("[you] ")]


# --- the reserve and the guard ---------------------------------------------------------

@test("the reserve follows Militarism: three quarters home at -100, half at 0, a quarter at +100, never under 3")
def _():
    s = fort()
    assert PM.mission_reserve(s) == 10
    assert PM.mission_reserve(fort(militarism=-100)) == 15
    assert PM.mission_reserve(fort(militarism=100)) == 5
    assert PM.mission_reserve(fort(militarism=200)) == 5          # Extreme counts as 100
    assert PM.mission_reserve(fort(militarism=-50)) == 13         # 0.625 x 20 = 12.5 -> 13
    s["military"]["soldiers"] = 4
    assert PM.mission_reserve(s) == 3                             # the guard, whatever the share
    # -100: 20 soldiers, 15 stay: one squad of 10 would leave 10 home -> nothing sendable
    sq, sent, res = PM.sendable_squads(fort(militarism=-100))
    assert sq == [] and res == 15
    # 0: one squad goes, the other stays (10 home = the reserve)
    sq, sent, res = PM.sendable_squads(fort())
    assert len(sq) == 1 and sent == 10 and res == 10
    # +100: still one squad: both would leave nobody home
    sq, sent, _ = PM.sendable_squads(fort(militarism=100))
    assert len(sq) == 1 and sent == 10


@test("the guard rule holds after sending: a small army keeps 3 home, and too few free soldiers send nobody")
def _():
    s = fort(militarism=100)
    s["military"]["squads"] = [{"id": 1, "name": "A", "members": 3, "orders": 0, "power": {"armed": 3}},
                               {"id": 2, "name": "B", "members": 2, "orders": 0, "power": {"armed": 2}}]
    s["military"]["soldiers"] = 5
    s["missions"]["squads"] = [{"id": 1, "members": 3, "away": 0}, {"id": 2, "members": 2, "away": 0}]
    sq, sent, res = PM.sendable_squads(s)
    assert res == 3 and [q["id"] for q in sq] == [2] and sent == 2      # 3 home after: the guard holds
    s["military"]["squads"][1]["members"] = 1
    s["military"]["soldiers"] = 4
    sq, sent, res = PM.sendable_squads(s)
    assert sq == [], sq                                                 # 1 sendable < 2: no mission
    p, notes = rule(s)
    assert not p and any("too few soldiers are free" in n for n in notes), notes


@test("squads on orders, hiding, in a fight, away or not all armed don't go")
def _():
    for change, why in [({"orders": 1}, "on duty"), ({"sheltering": True}, "hiding"), ({"kill_ids": [5]}, "in a fight"),
                        ({"power": {"armed": 9}}, "not all armed"), ({"power": None}, "not all armed")]:
        s = fort(militarism=100)
        s["military"]["squads"][0].update(change)
        s["military"]["squads"][1].update(change)
        assert PM.sendable_squads(s)[0] == [], why
    s = fort(militarism=100)
    s["missions"]["squads"][0]["away"] = 2
    sq = PM.sendable_squads(s)[0]
    assert [q["id"] for q in sq] == [12], sq


# --- when and what ---------------------------------------------------------------------

@test("a threat near, a siege or the alarm: no mission, said in a note")
def _():
    s = fort(send=button("rescue"), send_missions=True)
    s["others_on_map"]["threats"][0]["can_reach_dwarves"] = True
    p, notes = rule(s)
    assert not p and any("not while a threat is near" in n for n in notes), notes
    s = fort(send=button("rescue"), send_missions=True)
    s["world"] = {"sieges": [{"id": 3, "active": True}]}
    assert not rule(s)[0]
    s = fort(send=button("rescue"), send_missions=True)
    s["civ_alert"] = True
    assert not rule(s)[0]


@test("one at a time: a mission out, or the World screen being driven, or the messenger sent this cycle")
def _():
    s = fort(send=button("rescue"), send_missions=True)
    p, _ = rule(s)
    assert p and p[0].action["type"] == "send_mission" and p[0].action["goal"] == "rescue"
    assert p[0].action["squad_ids"] == [11] and p[0].action["hf_id"] == 1001 and p[0].action["site_id"] == 101
    s = fort(send=button("rescue"), send_missions=True)
    s["missions"]["controllers"] = [{"id": 55, "goal": "RESCUE", "site_id": 9, "site": "Far", "squads": [12], "away": 10}]
    p, notes = rule(s)
    assert not p and any("one mission at a time" in n for n in notes), notes
    # the messenger's mission out (DIPLOMACY) doesn't count
    s["missions"]["controllers"] = [{"id": 56, "goal": "DIPLOMACY", "site_id": 9, "squads": [], "away": 0}]
    assert rule(s)[0]
    s = fort(send=dict(button("rescue"), running={"step": "site"}), send_missions=True)
    assert not rule(s)[0]
    from planner import Proposal
    props, notes = [Proposal("contact", {"type": "send_mission", "goal": "make_contact", "site_id": 3}, "x", 7)], []
    PM._mission_rule(digest.normalize(fort(send=button("rescue"), send_missions=True)), CFG, props, notes)
    assert len(props) == 1


@test("the switch's levels filter the goals, in the goal order, nearest first on a tie")
def _():
    ts = [target("explore", 1, dist=1), target("recover_artifact", 2, dist=9), target("rescue", 3, dist=20),
          target("rescue", 4, dist=12), target("raid", 5, dist=1, hostile=True)]
    send = button(*PM.MISSION_GOALS)

    def pick(level):
        p, _ = rule(fort(ts, send=send, send_missions=True, missions=level))
        return (p[0].action["goal"], p[0].action["site_id"]) if p else None
    assert pick("rescue") == ("rescue", 4)
    assert pick("explore") == ("rescue", 4)
    assert pick("all") == ("rescue", 4)
    assert pick("off") is None
    only = [t for t in ts if t["goal"] in ("explore", "raid")]
    p, _ = rule(fort(only, send=send, send_missions=True, missions="rescue"))
    assert not p
    p, _ = rule(fort(only, send=send, send_missions=True, missions="explore"))
    assert p[0].action["goal"] == "explore"
    assert player_rules({"settings": {}})["missions"] == "rescue" and player_rules({"settings": {}})["send_missions"] is False
    assert player_rules({"settings": {"missions": "bogus"}})["missions"] == "rescue"


@test("raids only against a hostile or at-war civ, and only at 'all'; a target DF's screen refused is passed over")
def _():
    send = button(*PM.MISSION_GOALS)
    for level in ("rescue", "explore"):
        assert not rule(fort([target("raid", 5, hostile=True)], send=send, send_missions=True, missions=level))[0]
    assert not rule(fort([target("raid", 5), target("pillage", 6), target("tribute", 7)], send=send,
                         send_missions=True, missions="all"))[0]
    p, _ = rule(fort([target("raid", 5), target("pillage", 6, at_war=True)], send=send, send_missions=True, missions="all"))
    assert p and p[0].action["goal"] == "pillage"
    p, _ = rule(fort([target("tribute", 8, hostile=True), target("raid", 5, hostile=True)], send=send,
                     send_missions=True, missions="all"))
    assert p[0].action["goal"] == "tribute"                       # goal order: tribute before raid
    p, _ = rule(fort([target("rescue", 3, ready="too far"), target("rescue", 4, dist=30)], send=send, send_missions=True))
    assert p[0].action["site_id"] == 4


@test("send_missions off or the goal's buttons unshown: a note names target and squads, and one Needs you")
def _():
    p, notes = rule(fort())
    assert not p
    named = [n for n in notes if "rescue Urist McHeld from Site101" in n]
    assert named and "The Axes of Iron" in named[0] and "send missions" in named[0], notes
    nd = needs(notes)
    assert len(nd) == 1 and "probe_missions.py --watch" in nd[0] and "meanwhile" in nd[0], nd
    p, notes = rule(fort(send=button("explore"), send_missions=True))
    assert not p and len(needs(notes)) == 1 and any("hasn't been shown" in n for n in notes), notes
    # the same words every cycle (the Needs you list shows a change only)
    assert needs(rule(fort())[1]) == needs(rule(fort(militarism=100))[1])
    # no targets: nothing at all
    assert rule(fort([]))[0] == [] and rule(fort([]))[1] == []


@test("a stopped run is not tried again for a year for that goal; another goal may go")
def _():
    now = abs_tick(BASE)
    last = {"goal": "rescue", "result": "stopped", "step": "messenger", "tick": now - 100}
    s = fort([target("rescue", 3), target("recover_artifact", 4)], send=button("rescue", "recover_artifact", last=last),
             send_missions=True)
    p, _ = rule(s)
    assert p and p[0].action["goal"] == "recover_artifact", p
    p, notes = rule(fort([target("rescue", 3)], send=button("rescue", last=last), send_missions=True))
    assert not p and any("tried again in a year" in n for n in notes), notes
    last["tick"] = now - TICKS_PER_YEAR - 1
    assert rule(fort([target("rescue", 3)], send=button("rescue", last=last), send_missions=True))[0]
    # sent lately: not proposed again while its controller is still to show
    sent = {"goal": "rescue", "result": "sent", "tick": now - 1000, "site_id": 3}
    assert not rule(fort([target("rescue", 3)], send=button("rescue", last=sent), send_missions=True))[0]
    # a mission's stopped run doesn't read as the messenger's (planner_world _contact_rule)
    from planner_world import _contact_rule
    s = digest.normalize(fort(send=dict(button("rescue", last=last), buttons=["World", "Diplomacy"]),
                              send_messenger=True))
    s["offices"] = {"offices": {"MESSENGER": {"held": ["Mafol"]}}}
    s["missions"]["sites"] = {"nearest": [{"id": 77, "name": "Near", "dist": 3, "relation": "NoContact"}]}
    props, notes = [], []
    _contact_rule(s, CFG, props, notes, Memory())
    assert props and props[0].action["goal"] == "make_contact", notes


@test("through plan(): the mission proposed with the other rules, its label, and the strategist can't raise it")
def _():
    props, _ = plan(fort(send=button("rescue"), send_missions=True), Memory())
    m = [p for p in props if p.rule == "mission"]
    assert m and m[0].action["goal"] == "rescue", [p.rule for p in props]
    from overseer import short as describe
    assert describe(m[0].action).startswith("send 1 squad to rescue at site 101")
    assert describe({"type": "send_mission", "goal": "make_contact", "site_id": 4}) == \
        "send the messenger to make contact with site 4 (World screen)"
    assert describe({"type": "send_mission", "site_id": 4}) == "send the messenger to make contact with site 4 (World screen)"
    import strategist
    act, why = strategist._check_steer({"type": "raise", "rule": "mission", "why": "go"}, {"mission"})
    assert act is None and "can't be raised" in why


@test("the review's Rules line names the missions keys only once the player changes them")
def _():
    import strategist
    line = strategist.rules_line(player_rules({"settings": {}}))
    assert "missions" not in line, line
    line = strategist.rules_line(player_rules({"settings": {"missions": "all", "send_missions": True}}))
    assert "missions=all" in line and "send_missions" not in line.split("off:")[-1], line


# --- following a mission home ----------------------------------------------------------

@test("note_missions follows a mission out and back: journal, chronicle and the counts in memory")
def _():
    m = Memory()
    s = fort([target("rescue", 3)])
    s["missions"]["send"] = {"last": {"goal": "rescue", "result": "sent", "site_id": 3, "tick": abs_tick(s)}}
    s["missions"]["controllers"] = [{"id": 70, "goal": "RESCUE_HF", "site_id": 3, "site": "Site3", "squads": [11],
                                     "away": 10}]
    s["missions"]["squads"][0].update(away=10, controller=70)
    s["missions"]["reports"] = {"n": 2, "unviewed": 0}
    notes = note_cycle(copy.deepcopy(s), m)
    assert any("a mission went out: rescue Site3" in n for n in notes), notes
    assert m.missions_seen["missions_sent"] == 1 and m.missions_seen["out"]["70"]["hf_id"] == 903
    j = PM.mission_journal(m)
    assert j and j[0]["event"] == "out" and j[0]["goal"] == "rescue" and PM.mission_journal(m) == []
    # still out next cycle: nothing new
    assert not [n for n in note_cycle(copy.deepcopy(s), m) if "mission" in n]
    assert m.missions_seen["missions_sent"] == 1
    # back: the controller gone, a report and spoils came, the citizen no longer a target
    s2 = copy.deepcopy(s)
    s2["date"]["tick"] += 20 * 1200
    s2["missions"]["controllers"] = []
    s2["missions"]["squads"][0].update(away=0, controller=None)
    s2["missions"]["targets"] = []
    s2["missions"]["reports"] = {"n": 3, "last": {"title": 'The rescue of "Urist" [at] {Site3} ' + "x" * 80, "year": 148}}
    s2["missions"]["spoils"] = {"n": 1, "last": {"kind": "spoils", "items": 4}}
    notes = note_cycle(s2, m)
    back = [n for n in notes if "came back" in n]
    assert back and "the citizen is no longer held there" in back[0] and "spoils: 4 item(s)" in back[0], notes
    ms = m.missions_seen
    assert (ms["missions_back"], ms["rescued"], ms["artifacts_recovered"]) == (1, 1, 0) and ms["out"] == {}
    e = PM.mission_journal(m)[0]
    assert e["event"] == "back" and e["outcome"] == "rescued" and e["days"] == 20 and e["spoils"]["items"] == 4
    # game text: one line, no brackets or braces, cut short, and quoted in the chronicle line
    assert len(e["report"]) <= 60 and not set("[]{}") & set(e["report"]) and e["report"].endswith("…"), e["report"]
    assert f'its report: "{e["report"]}"' in back[0]
    ch = [x for x in m.chronicle["entries"] if x["k"] == "mission"]
    assert ch and "came back" in ch[0]["t"]
    # not counted twice if DF keeps the controller listed a while
    s3 = copy.deepcopy(s)
    note_cycle(s3, m)
    assert m.missions_seen["missions_sent"] == 1


@test("note_missions: squads home under a lingering controller count as back; an artifact recovered; others' armies ignored")
def _():
    m = Memory()
    s = fort([target("recover_artifact", 4)])
    s["missions"]["controllers"] = [{"id": 80, "goal": "RECOVER_ARTIFACT", "site_id": 4, "squads": [12], "away": 10},
                                    {"id": 81, "goal": "SITE_INVASION", "site_id": 99, "squads": [], "away": 0}]
    s["missions"]["squads"][1].update(away=10, controller=80)
    note_cycle(copy.deepcopy(s), m)
    assert list(m.missions_seen["out"]) == ["80"] and m.missions_seen["out"]["80"]["goal"] == "recover_artifact"
    s["missions"]["controllers"][0].update(away=0, returning=True)
    s["missions"]["squads"][1].update(away=0)
    s["missions"]["targets"] = []
    notes = note_cycle(copy.deepcopy(s), m)
    assert any("came back" in n and "artifact is no longer held" in n for n in notes), notes
    assert m.missions_seen["artifacts_recovered"] == 1 and m.missions_seen["missions_back"] == 1


# --- the digest -------------------------------------------------------------------------

@test("the digest's MISSIONS line: targets and missions out, no coordinates; none without either")
def _():
    s = fort([target("rescue", 3, pos={"x": 10, "y": 20}), target("raid", 5, hostile=True)])
    s["missions"]["controllers"] = [{"id": 70, "goal": "RAID", "site": "Site9", "squads": [11], "away": 10}]
    s["missions"]["squads"][0]["away"] = 10
    line = [ln for ln in digest.digest(s).splitlines() if ln.startswith("MISSIONS")]
    assert line and "rescue Site3 (The Goblins) d5" in line[0] and "raid Site5" in line[0] and "hostile" in line[0], line
    assert "out 1: raid to Site9" in line[0]
    assert "10" not in line[0] and "20" not in line[0]
    assert not [ln for ln in digest.digest(fort([])).splitlines() if ln.startswith("MISSIONS")]
    s = copy.deepcopy(BASE)
    s["missions"] = {"controllers": []}
    assert digest.normalize(s)["missions"]["targets"] == []


# --- scripts identity: without targets, plan() is main's -----------------------------------

PROBE = r'''
import copy, json, sys
from pathlib import Path
brain = Path(sys.argv[1]); sys.path.insert(0, str(brain))
fixtures = Path(sys.argv[2])
from digest import normalize
from planner import Memory, plan, record, select, note_cycle, TICKS_PER_DAY
out = {}
for path in [fixtures / "test_fort.json"] + sorted((fixtures / "real").glob("*.json")):
    base = json.loads(path.read_text(encoding="utf-8"))
    for variant in ("none", "section"):
        s = copy.deepcopy(base)
        if variant == "section":
            sq = [q for q in (s.get("military") or {}).get("squads") or [] if isinstance(q, dict)]
            s["missions"] = {"controllers": [], "reports": {"n": 0, "unviewed": 0}, "spoils": {"n": 0},
                             "squads": [{"id": q.get("id"), "members": q.get("members"), "away": 0} for q in sq],
                             "sites": {"nearest": []}, "unknown": []}
            s.setdefault("settings", {})["missions"] = "all"
            s["settings"]["send_missions"] = True
        s = normalize(s)
        m = Memory()
        cycles = []
        for _ in range(3):
            n = note_cycle(copy.deepcopy(s), m)
            props, notes = plan(copy.deepcopy(s), m)
            cycles.append({"props": [[p.rule, json.dumps(p.action, sort_keys=True, default=str), p.reason,
                                      p.priority] for p in props], "notes": notes, "cycle": n})
            allowed, _ = select(props, s, m)
            record([(p, {"ok": False, "error": "refused (test)"}) for p in allowed], s, m)
            s["date"]["tick"] = s["date"].get("tick", 0) + TICKS_PER_DAY
        out[f"{path.name}:{variant}"] = cycles
print(json.dumps(out, sort_keys=True))
'''

_MAIN = {}


def main_brain() -> Path | None:
    if "dir" not in _MAIN:
        tmp = tempfile.mkdtemp(prefix="r39-main-")
        arch = subprocess.run(["git", "-C", str(ROOT), "archive", "main", "brain"], capture_output=True)
        if arch.returncode != 0:
            _MAIN["dir"] = None
        else:
            subprocess.run(["tar", "-x", "-C", tmp], input=arch.stdout, check=True)
            _MAIN["dir"] = Path(tmp) / "brain"
            atexit.register(shutil.rmtree, tmp, True)
    return _MAIN["dir"]


def probe(brain: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "probe.py"
        p.write_text(PROBE, encoding="utf-8")
        r = subprocess.run([sys.executable, "-I", str(p), str(brain), str(ROOT / "tests" / "fixtures")],
                           capture_output=True, text=True, env=dict(os.environ, DFAI_LOG_DIR=tmp), cwd=tmp)
    assert r.returncode == 0, r.stderr[-1500:]
    return r.stdout.strip().splitlines()[-1]


@test("no missions.targets in the report: plan() and note_cycle() are main's, byte for byte (7 fixtures, with and "
      "without a missions section, 3 cycles)")
def _():
    main = main_brain()
    assert main is not None, "no main branch to compare with"
    a, b = probe(main), probe(ROOT / "brain")
    if a != b:
        ja, jb = json.loads(a), json.loads(b)
        bad = [k for k in ja if ja[k] != jb.get(k)]
        raise AssertionError(f"differs from main at {bad[:3]}")


finish()

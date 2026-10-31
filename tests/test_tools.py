"""Smoke tests for brain/selftest.py and brain/replay.py with a fake game.

    python tests/test_tools.py
"""

from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

import replay  # noqa: E402
import selftest  # noqa: E402
from bridge import BridgeError  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
RESULTS = []
TMP = Path(tempfile.mkdtemp())


def test(name):
    def wrap(fn):
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return wrap


class FakeGame:
    def __init__(self, halted=False, accept_bad=False):
        self.halted, self.accept_bad, self.acted = halted, accept_bad, []
        self.version = None

    def handshake(self):
        self.version = {"protocol": 1, "bridge_version": selftest.expected_bridge_version(),
                        "recipes": ["brew_drink"], "df_version": "53.16"}
        return self.version

    def status(self):
        return {"ok": True, "in_fort": True, "paused": True, "halted": self.halted, "fps": 50,
                "date": BASE["date"]}

    def state(self, include_units=True, tier=None):
        s = copy.deepcopy(BASE)
        s["_meta"] = {"build_ms": 40}
        s["registry"] = [{"id": 1, "kind": "bedrooms", "phase": "done", "z": 150,
                          "bounds": {"x1": 1, "y1": 2, "x2": 9, "y2": 6, "z": 150}}]
        if tier == "pulse":
            s = {k: s[k] for k in ("date", "fort", "stocks", "orders", "_meta")}
            s["_meta"] = {"build_ms": 6}
        s["tier"] = tier or "daily"
        return s

    def survey(self):
        return {"ok": True, "stairs": [{"x": 40, "y": 41, "elev_top": 64, "elev_bottom": 30}],
                "citizen_elevation": 44, "soil": [58]}

    def load_memory(self):
        return {"kinds": {"working": {"fort": "AI Test Run#1234", "text": "x" * 4100}},
                "legacy": {"fort": "AI Test Run#1234", "memory": {}}}

    def map_info(self):
        return {"ok": True, "size": [192, 192, 200], "layers": []}

    def _call(self, cmd, *args, timeout=None):
        if cmd == "probe_defence":
            self.probe_args = args
            return {"ok": True, "probe": {
                "job_types": {"LinkBuildingToTrigger": True}, "ref_types": {"BUILDING_TRIGGER": True},
                "levers": [{"id": 67938, "name": "AI gate", "targets": [], "mechanisms": 0}],
                "tiles": [{"x": 35, "y": 120, "z": 112, "building": "Bridge", "id": 51799, "linked": False}]}}
        if cmd == "reports":
            return {"ok": True, "reports": [{"type": "X", "topic": "mood", "text": "fey"},
                                            {"type": "Y", "topic": False, "text": "chatter"}]}
        return {"ok": True, "present": cmd == "memory", "watching": True}

    def act(self, a):
        self.acted.append(a)
        if self.halted and not a.get("dry_run"):
            return {"ok": False, "rejected": True, "halted": True, "error": "halted"}
        if a.get("dry_run") and a.get("kind") == "bedrooms":
            return {"ok": True, "dry_run": True, "elevation": -20}
        if a.get("dry_run") and a.get("type") == "make_pasture":
            return {"ok": True, "dry_run": True, "tiles": 42,
                    "zones": [{"x": 90, "y": 40, "elevation": 64, "w": 7, "h": 6}]}
        if a.get("dry_run") and a.get("type") == "place_well":
            return {"ok": True, "dry_run": True, "x": 70, "y": 58, "elevation": 30, "drop": 2, "in_hall": True}
        if a.get("dry_run") and a.get("type") == "found_fort":
            return {"ok": False, "rejected": True, "error": "the fort already has a staircase"}
        if a.get("dry_run") and a.get("type") == "quiet_announcements":
            return {"ok": True, "dry_run": True, "pausing": 30, "boxes": 12}
        if a.get("dry_run") and a.get("type") == "save_game":
            return {"ok": True, "dry_run": True}
        if a.get("dry_run") and a.get("type") == "link_lever":
            return {"ok": True, "dry_run": True, "target": "Bridge", "mechanisms": 2}
        if a.get("dry_run") and a.get("type") == "farm_plots" and a.get("tiles", 0) >= 4:
            return {"ok": True, "dry_run": True, "tiles": 12,
                    "placed": [{"x": 40, "y": 50, "elevation": 45, "w": 4, "h": 3}],
                    "level": {"ok": True, "dry_run": True, "elevation": 44}}
        if self.accept_bad:
            return {"ok": True}
        return {"ok": False, "rejected": True, "error": "no"}


def run_selftest(game):
    selftest.Bridge = lambda: game
    selftest.RESULTS.clear()
    out = io.StringIO()
    with redirect_stdout(out):
        rc = selftest.main()
    return rc, out.getvalue()


@test("self-test passes on a healthy game and only sends refused or dry-run actions")
def _():
    g = FakeGame()
    rc, out = run_selftest(g)
    assert rc == 0, out
    assert "FAIL" not in out and "would fit at elevation -20" in out, out
    assert "2 recent, 1 recognised (mood)" in out, out
    assert "[PASS] farm plots" in out and "18 plots, 216 tiles" in out, out
    assert "12 tiles on existing floor (4x3 at x40 y50 elevation 45); a farm level would fit at " \
        "elevation 44" in out, out
    assert "[PASS] silly farm request refused" in out, out
    assert "working 4 KB; the old one-piece memory (moved over" in out, out
    assert "1 main stair(s), the first at x40 y41 from elevation 30 to 64; the dwarves mostly at 44; soil at 58" \
        in out, out
    assert "[PASS] defence probe (for milestone 5)" in out and "x35 y120: Bridge" in out, out
    assert "[PASS] unattended run (keeper)" in out, out
    assert "30 kinds pause the game, 12 open a box" in out, out
    assert "[PASS] founding (a fresh embark)" in out, out
    assert "[PASS] lever link dry run" in out and "lever 67938 could be linked to the bridge at x35 y120" in out, out
    assert "[PASS] registry of AI projects" in out and "1 projects, 1 with their bounds" in out, out
    assert "[PASS] pulse report (between days)" in out and "built in 6 ms in game" in out, out
    assert "42 tiles of grass in 1 pasture(s), the first 7x6 at x90 y40 elevation 64" in out, out
    assert "a well would go at x70 y58 elevation 30, 2 level(s) above the water, in a dining" in out, out
    assert all(a.get("dry_run") or a["type"] in ("self_destruct", "tool", "work_order") for a in g.acted)


@test("self-test fails if the game accepts a bad action")
def _():
    rc, out = run_selftest(FakeGame(accept_bad=True))
    assert rc == 1 and "[FAIL] unknown action refused" in out, out


@test("self-test while halted: refusals still pass, and the dry run still runs (it changes nothing)")
def _():
    g = FakeGame(halted=True)
    rc, out = run_selftest(g)
    assert rc == 0 and "would fit at elevation -20" in out, out


@test("self-test spots an out-of-date bridge in the game")
def _():
    g = FakeGame()
    real = g.handshake
    g.handshake = lambda: {**real(), "bridge_version": "0.1.0"}
    rc, out = run_selftest(g)
    assert rc == 1 and "copy lua" in out, out


@test("self-test probes the remembered open entrances when the game hasn't mapped them this session")
def _():
    g = FakeGame()
    real_state = g.state
    g.state = lambda include_units=True, tier=None: {**real_state(include_units, tier), "entrances": {"entrances": []}}
    fort = BASE.get("fort") or {}
    key = f"{fort.get('save_dir')}#{fort.get('site_id')}"
    atlas = {"data": {"atlas": {"entrances": {
        "35,120,112": {"sealed": False}, "16,136,112": {"sealed": True}, "5,66,127": {"sealed": False}}}}}
    g.load_memory = lambda: {"kinds": {"atlas": {"fort": key, "text": json.dumps(atlas)}}}
    rc, out = run_selftest(g)
    assert rc == 0, out
    assert g.probe_args == ("5", "66", "127", "35", "120", "112"), g.probe_args
    assert "open entrances (as remembered): x35 y120: Bridge" in out, out
    assert "('AI gate' id 67938: 0 target(s))" in out


def write_run(d: Path):
    d.mkdir(parents=True)
    days = [{"day": 1, "row": {"date": "1 Granite 149", "population": 10, "fps": 50},
             "events": [{"kind": "death", "name": "Urist", "own_civ": True}],
             "decisions": [{"kind": "decision", "rule": "drink", "reason": "low drink",
                            "action": {"type": "work_order", "recipe": "brew_drink", "amount": 10},
                            "result": {"ok": True}, "mode": "autopilot"},
                           {"kind": "decision", "rule": "status", "action": {"type": "report_status"},
                            "result": {"ok": True}}]},
            {"day": 2, "row": {"date": "2 Granite 149", "population": 10}, "events": [], "decisions": []}]
    (d / "days.jsonl").write_text("\n".join(json.dumps(x) for x in days) + "\n", encoding="utf-8")


@test("replay shows events and real decisions, hides panel updates, marks quiet days")
def _():
    run = TMP / "runs" / "20261020-120000-planner-a"
    write_run(run)
    days = replay.load_run(run)
    one, two = replay.show_day(days[0], 2), replay.show_day(days[1], 2)
    assert "died: Urist (citizen)" in one and "brew_drink" in one and "[done]" in one, one
    assert "report_status" not in one
    assert "(quiet day)" in two
    replay.RUNS_DIR = TMP / "runs"
    assert replay.find_run("planner") == run and replay.find_run(None) == run


@test("replay of the normal journal groups entries by in-game day")
def _():
    j = TMP / "decisions.jsonl"
    d1 = {"year": 149, "tick": 100, "day": 1, "month": "Granite"}
    d2 = {"year": 149, "tick": 1300, "day": 2, "month": "Granite"}
    lines = [{"kind": "event", "event": {"kind": "arrival", "name": "Goblin", "hostile": True}},
             {"kind": "decision", "date": d1, "rule": "alert", "action": {"type": "civ_alert"}, "result": {"ok": True}},
             {"kind": "decision", "date": d1, "rule": "x", "action": {"type": "tool"}, "result": {"ok": False, "error": "e"}},
             {"kind": "decision", "date": d2, "rule": "y", "action": {"type": "tool"}, "mode": "dry-run"}]
    j.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n", encoding="utf-8")
    days = replay.load_journal(j)
    assert len(days) == 2 and len(days[0]["decisions"]) == 2 and len(days[0]["events"]) == 1
    txt = replay.show_day(days[0], 2)
    assert "arrived: Goblin (hostile)" in txt and "refused: e" in txt, txt
    assert "would do" in replay.show_day(days[1], 2)



@test("probe_justice (0.104.129): a watch prints only what changed, the screen's fields in one level")
def _():
    import probe_justice
    a = {"focus": "dwarfmode/Default", "info": {"open": False}, "justice": {"cases": {"n": 3}}, "sentenced": 1}
    b = {"focus": "dwarfmode/Info/JUSTICE", "info": {"open": True}, "justice": {"cases": {"n": 2}}, "sentenced": 2}
    d = probe_justice.changes(a, b)
    assert set(d) == {"focus", "info.open", "justice.cases", "sentenced"}, d
    assert probe_justice.changes(b, b) == {}

if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

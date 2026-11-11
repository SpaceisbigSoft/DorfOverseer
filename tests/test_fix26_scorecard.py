"""0.105.26 fix round, group scorecard: runs kept apart, ties count half, the
new signature lines, the health table, the series.

    python tests/test_fix26_scorecard.py
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import memstore  # noqa: E402
import overseer  # noqa: E402
import scorecard  # noqa: E402

REAL = json.loads((ROOT / "tests" / "fixtures" / "real" / "enxah-0.104.52-y73-winter.json").read_text(encoding="utf-8"))
PRESETS = ["War-hold", "Monastery", "Merchant city", "Hermit hold", "Deep mine", "Garden fort"]


def real_state(preset: str, year: int, season: str, **extra) -> dict:
    s = copy.deepcopy(REAL)
    s.setdefault("settings", {})["preset"] = preset
    s["date"] = {**s.get("date", {}), "year": year, "season": season, "tick": 10}
    for k, v in extra.items():
        s[k] = v
    return s


def fake_fort(root: Path, name: str, preset: str, states: dict, run: str | None = None,
              journal: list | None = None, dirname: str = "region4-1430", keeper_key: str = "region4#1430") -> Path:
    """A DF-AI folder: logs/forts/<dirname>/states/<season>.json (each written
    as {"_run": ...} first when its value carries one), the journal, and
    keeper-preset.json."""
    folder = root / name
    d = folder / "logs" / "forts" / dirname
    (d / "states").mkdir(parents=True, exist_ok=True)
    for season, (st, srun) in states.items():
        body = {"_run": srun} if srun else {}
        body.update(st)
        (d / "states" / f"{season}.json").write_text(json.dumps(body), encoding="utf-8")
    if journal:
        (d / "journal.jsonl").write_text("\n".join(json.dumps(x) for x in journal), encoding="utf-8")
    if run is not None:
        (folder / "logs" / "keeper-preset.json").write_text(
            json.dumps({keeper_key: {"name": preset, "at": run, "run": run}}), encoding="utf-8")
    return folder


# ------------------------------------------------------------- 1. runs

def _point_overseer(tmp: Path):
    old = (memstore.FORTS_DIR, overseer.PRESET_FILE, dict(memstore.ALIASES))
    memstore.FORTS_DIR = tmp / "forts"
    overseer.PRESET_FILE = tmp / "keeper-preset.json"
    memstore.ALIASES.clear()
    return old


def _restore(old):
    memstore.FORTS_DIR, overseer.PRESET_FILE = old[0], old[1]
    memstore.ALIASES.clear()
    memstore.ALIASES.update(old[2])


@test("keep_state: an older run's season state is replaced; this run's first one kept")
def _():
    tmp = Path(tempfile.mkdtemp())
    old = _point_overseer(tmp)
    try:
        key = "region4#1430"
        st = {"date": {"year": 250, "season": "spring", "tick": 1}, "wealth": 1}
        overseer.keep_state(st, key)                       # no run yet: kept as before
        f = memstore.fort_dir(key) / "states" / "250-spring.json"
        assert json.loads(f.read_text())["wealth"] == 1 and overseer.state_run(f) is None
        overseer.keep_state({**st, "wealth": 2}, key)       # no run: the first stays (old behaviour)
        assert json.loads(f.read_text())["wealth"] == 1
        overseer.note_preset(key, "War-hold")               # a fresh start: the site had no entry
        run = overseer.fort_run(key)
        assert run, overseer.PRESET_FILE.read_text()
        overseer.keep_state({**st, "wealth": 3}, key)       # the old run's file: replaced
        assert json.loads(f.read_text())["wealth"] == 3 and overseer.state_run(f) == run
        assert f.read_text().startswith('{"_run": ')
        overseer.keep_state({**st, "wealth": 4}, key)       # this run's: kept
        assert json.loads(f.read_text())["wealth"] == 3
    finally:
        _restore(old)


@test("note_preset: the run stamp is kept over restarts and autosave keys; cleared = a new run")
def _():
    tmp = Path(tempfile.mkdtemp())
    old = _point_overseer(tmp)
    try:
        overseer.note_preset("region4#1430", "Deep mine")
        run = overseer.fort_run("region4#1430")
        time.sleep(1.1)
        overseer.note_preset("region4#1430", "Deep mine")          # a restart
        overseer.note_preset("autosave 1#1430", "Deep mine")       # an autosave's key
        assert overseer.fort_run("region4#1430") == run == overseer.fort_run("autosave 1#1430")
        # an entry from before runs were marked: no run, and none made up
        overseer.PRESET_FILE.write_text(json.dumps({"region2#99": {"name": "Monastery", "at": "2026-01-01T00:00:00"}}))
        overseer.note_preset("region2#99", "Monastery")
        assert overseer.fort_run("region2#99") is None
        # the checklist clears the site: a new run
        overseer.PRESET_FILE.write_text("{}")
        overseer.note_preset("region4#1430", "Deep mine")
        assert overseer.fort_run("region4#1430") > run
    finally:
        _restore(old)


@test("scorecard: an older run's states and journal lines are left out, and said so")
def _():
    root = Path(tempfile.mkdtemp())
    new_run, old_run = "2026-11-07T10:00:00", "2026-10-01T10:00:00"
    st = real_state("War-hold", 250, "spring")
    journal = [{"time": "2026-10-02T00:00:00", "kind": "decision", "date": {"year": 249, "tick": 1},
                "action": {"type": "bring_goods"}, "result": {"ok": True, "value": 500}},       # old run
               {"time": "2026-11-07T11:00:00", "kind": "decision", "date": {"year": 249, "tick": 2},
                "action": {"type": "bring_goods"}, "result": {"ok": True, "value": 7}}]
    folder = fake_fort(root, "DF-AI", "War-hold",
                       {"250-spring": (st, new_run), "252-winter": (real_state("War-hold", 252, "winter"), old_run)},
                       run=new_run, journal=journal)
    # a legacy state (no "_run") written before this run began
    legacy = folder / "logs" / "forts" / "region4-1430" / "states" / "251-summer.json"
    legacy.write_text(json.dumps(real_state("War-hold", 251, "summer")))
    os.utime(legacy, (1_700_000_000, 1_700_000_000))
    f = scorecard.Fort("A", folder)
    assert set(f.states) == {(250, 0)}, f.states
    assert f.refused == [(251, 1), (252, 3)], f.refused
    m = scorecard.measures(f.state_at((250, 0)), scorecard.journal_counts(f.journal(), {"year": 250, "tick": 10}))
    assert m["trade_value"] == 7, m["trade_value"]
    b = scorecard.Fort("B", fake_fort(root, "DF-AI-B", "Monastery", {"250-spring": (real_state("Monastery", 250, "spring"), new_run)},
                                      run=new_run))
    md, _ = scorecard.score([f, b], None, False)
    assert "all at 250-spring" in md and "2 season state(s) of an older run left out" in md, md[:600]
    # the site cleared, the new run not begun yet: every stamped state is refused
    (folder / "logs" / "keeper-preset.json").write_text("{}")
    f2 = scorecard.Fort("A", folder)
    assert (250, 0) not in f2.states and (250, 0) in f2.refused
    md2, _ = scorecard.score([f2], None, False)
    assert "no season state of its current run yet" in md2, md2


@test("scorecard: a fort folder moved aside inside logs/forts isn't picked")
def _():
    root = Path(tempfile.mkdtemp())
    run = "2026-11-07T10:00:00"
    folder = fake_fort(root, "DF-AI", "War-hold", {"250-spring": (real_state("War-hold", 250, "spring"), run)}, run=run)
    # the old run moved aside under another name, newer files than the new run's
    fake_fort(root, "DF-AI", "War-hold", {"255-winter": (real_state("War-hold", 255, "winter"), None)},
              dirname="region4-1430-old")
    f = scorecard.Fort("A", folder)
    assert f.fort_dir.name == "region4-1430", f.fort_dir
    # only the moved-aside folder has states (the new run hasn't kept one): none graded
    root2 = Path(tempfile.mkdtemp())
    folder2 = fake_fort(root2, "DF-AI", "War-hold", {"255-winter": (real_state("War-hold", 255, "winter"), None)},
                        dirname="region4-1430-old")
    os.utime(next((folder2 / "logs" / "forts" / "region4-1430-old" / "states").glob("*.json")), (1_700_000_000,) * 2)
    (folder2 / "logs" / "keeper-preset.json").write_text(json.dumps({"region4#1430": {"name": "War-hold", "run": run}}))
    f2 = scorecard.Fort("A", folder2)
    assert not f2.states and f2.refused == [(255, 3)], (f2.states, f2.refused)


# ------------------------------------------------------------- 2. ties

@test("judge: a best or worst shared with a fort outside the group counts half")
def _():
    j = scorecard.judge
    assert j({"a": 3, "b": 1, "c": 2}, {"a"}, set()) == "pass"
    assert j({"a": 3, "b": 1, "c": 3}, {"a"}, set()) == "half"          # tied with c
    assert j({"a": 3, "d": 3, "b": 1}, {"a", "d"}, set()) == "pass"     # tied inside the group
    assert j({"a": 3, "b": 1, "c": 1}, {"a"}, {"b"}) == "half"          # low tied with c
    assert j({"a": 3, "b": 1, "c": 2}, {"a"}, {"b"}) == "pass"
    assert j({"a": 1, "b": 3, "c": 2}, {"a"}, {"b"}) == "fail"


# ------------------------------------------------------------- 3. new lines

def six_forts(root: Path, tweak) -> list:
    out = []
    for i, p in enumerate(PRESETS):
        s = real_state(p, 250, "spring")
        jr = tweak(p, s) or []
        out.append(scorecard.Fort(f"F{i + 1}", fake_fort(root, f"DF-AI-F{i + 1}", p, {"250-spring": (s, None)},
                                                        journal=jr)))
    return out


def row(rows, line):
    return next(r for r in rows if r["line"] == line)


@test("the new signature lines read today's report fields and the journal")
def _():
    root = Path(tempfile.mkdtemp())

    def tweak(p, s):
        b = s.setdefault("buildings", {})
        ents = [{"id": 1, "gatehouse": "standing" if p == "Hermit hold" else "none",
                 "equipment": [{"id": 9, "lever_driven": p in ("War-hold", "Deep mine"), "drive_lever": 4}]}]
        s["entrances"] = {"entrances": ents}
        if p == "Deep mine":
            b["deep_depot"] = {"stage": "placed", "depot": "built"}
        locs = s["locations"]["list"]
        for x in locs:
            x["flags"] = ["VISITORS_ALLOWED"] if p == "Merchant city" or x["type"] == "TEMPLE" else []
            if x["type"] == "TEMPLE":
                x["tier"] = 2 if p == "Monastery" else 1
                x["deity_hf"] = 213 if p == "Monastery" else None
        s["needs"] = {"worship": {"Emuth": 5, "Tobul": 3, "Nish": 0}, "deity_ids": {"Emuth": 213, "Tobul": 212},
                      "stress_causes": {"citizens": 100, "causes": [{"thought": "SameBooze",
                                                                      "citizens": 5 if p in ("Monastery", "Garden fort") else 40}]}}
        s["supplies"]["drink_kinds"] = 6 if p in ("Monastery", "Garden fort") else 2
        if p == "War-hold":
            return [{"kind": "decision", "date": {"year": 249, "tick": 0}, "action": {"type": "build_gatehouse"},
                     "result": {"ok": True}},
                    {"kind": "decision", "date": {"year": 249, "tick": 0},
                     "action": {"type": "location_access", "ids": [1, 2], "visitors": False},
                     "result": {"ok": True, "changed": [1, 2], "visitors": False}},
                    {"kind": "decision", "date": {"year": 249, "tick": 12000},
                     "action": {"type": "location_access", "ids": [1], "visitors": True},
                     "result": {"ok": True, "changed": [1], "visitors": True}},
                    {"kind": "decision", "date": {"year": 249, "tick": 24000},
                     "action": {"type": "location_access", "ids": [2], "visitors": True},
                     "result": {"ok": True, "changed": [2], "visitors": True}}]
        if p == "Hermit hold":
            return [{"kind": "decision", "date": {"year": 249, "tick": 0},
                     "action": {"type": "location_access", "ids": [5], "visitors": False},
                     "result": {"ok": True, "changed": [5], "visitors": False}}]
        return []

    forts = six_forts(root, tweak)
    md, rows = scorecard.score(forts, None, False)
    r = row(rows, "gatehouses built")
    assert r["values"]["F1"] == 1 and r["values"]["F4"] == 1 and r["result"] == "pass", r
    assert row(rows, "lever-driven gates")["result"] == "pass"
    assert row(rows, "underground depot built")["values"]["F5"] == 1
    assert row(rows, "underground depot built")["result"] == "pass"
    g = row(rows, "worshipped gods with a temple, %")
    assert g["values"]["F2"] == 50.0 and g["values"]["F1"] == 0 and g["result"] == "pass", g
    assert row(rows, "grand temples (tier 2+)")["result"] == "pass"
    v = row(rows, "locations open to visitors, %")
    assert v["values"]["F3"] == 100.0 and v["result"] == "half", v     # Hermit and War tie with the others at the bottom
    sd = row(rows, "days shut to visitors")
    assert sd["values"]["F1"] == 20.0 and sd["values"]["F3"] == 0, sd   # 2 ids shut, last opened 20 days on
    assert sd["values"]["F4"] > 300, sd                                  # still shut at the date
    assert row(rows, "drink kinds")["result"] == "pass"
    sb = row(rows, "upset by the same booze, % (lowest wins)")
    assert sb["values"]["F2"] == 5.0 and sb["result"] == "pass", sb
    assert not any(r["line"] == "visitors on the map" for r in rows)


# ------------------------------------------------------------- 4. health

@test("health table: failed moods, thirst deaths, unhappy and idle bars, deaths by cause")
def _():
    root = Path(tempfile.mkdtemp())

    def tweak(p, s):
        s["dwarves"]["total"], s["dwarves"]["adults"] = 100, 100
        s["dwarves"]["stress"] = {"unhappy": 20 if p == "War-hold" else 1}
        s["dwarves"]["idle_adults"] = 50 if p == "Deep mine" else 10
        # (0.105.33) the bar reads the bridge's idle_free, of the adults not in squads
        s["dwarves"]["idle_free"], s["dwarves"]["in_squads"] = s["dwarves"]["idle_adults"], 0
        s["dead"] = {}
        s["moods"] = {"list": [{"mood": "Fey", "craft": True}]} if p == "Monastery" else {"list": []}
        if p == "Monastery":
            ev = lambda **e: {"kind": "event", "event": {"year": 249, "tick": 5, **e}}   # noqa: E731
            return [ev(kind="report", topic="mood"), ev(kind="report", topic="mood"), ev(kind="report", topic="mood"),
                    ev(kind="report", topic="artifact_made"),
                    ev(kind="death", own_civ=True, cause="THIRST"), ev(kind="death", own_civ=True, cause="THIRST"),
                    ev(kind="death", own_civ=True, cause="THIRST", again=True),
                    ev(kind="death", own_civ=True, animal=True, cause="THIRST"),
                    ev(kind="death", own_civ=True, cause="DROWN")]
        return []

    md, _ = scorecard.score(six_forts(root, tweak), None, False)
    assert "## Health" in md
    lines = {ln.split(" |")[0].lstrip("| "): ln for ln in md.splitlines() if ln.startswith("| ")}
    fm = lines["failed moods <= 0"]
    assert "| 1 **over** |" in fm, fm                       # 3 moods, 1 artifact, 1 still working
    assert "| 2 **over** |" in lines["deaths by thirst <= 0"]
    assert "20 **over**" in lines["unhappy, % < 10"]
    assert "50 **over**" in lines["idle adults not in squads, % (Phase 12's exit) < 40"]
    assert lines["THIRST"].startswith("| THIRST | 0 | 2 |") and lines["DROWN"].startswith("| DROWN | 0 | 1 |")


# ------------------------------------------------------------- 5. series

@test("a series: one file a season, every N, and a summary across seasons")
def _():
    root = Path(tempfile.mkdtemp())
    folders = []
    for i, p in enumerate(PRESETS[:3]):
        sts = {f"{y}-{se}": (real_state(p, y, se), None) for y in (250, 251, 252) for se in scorecard.SEASONS}
        folders.append(fake_fort(root, f"DF-AI-{i}", p, sts))
    forts = [scorecard.Fort(str(i), f) for i, f in enumerate(folders)]
    assert scorecard.every_step("2y") == 8 and scorecard.every_step("3") == 3
    keys = scorecard.series_keys(forts, 8)
    assert keys == [(250, 3), (252, 3)], keys
    out = root / "out"
    args = sum((["--fort", f"{i}={f}"] for i, f in enumerate(folders)), [])
    scorecard.main(args + ["--every", "4", "--out", str(out / "sc.md"), "--dir", str(out / "series")])
    names = sorted(p.name for p in (out / "series").glob("*.md"))
    assert names == ["250-winter.md", "251-winter.md", "252-winter.md", "summary.md"], names
    summ = (out / "series" / "summary.md").read_text()
    assert summ.count("-winter |") == 3, summ
    assert "all at 252-winter" in (out / "sc.md").read_text()
    # a single run later adds its season to the summary, the others stay
    scorecard.main(args + ["--at", "251-spring", "--out", str(out / "sc.md"), "--dir", str(out / "series")])
    summ = (out / "series" / "summary.md").read_text()
    assert "| 251-spring |" in summ and "| 250-winter |" in summ, summ


if __name__ == "__main__":
    finish()

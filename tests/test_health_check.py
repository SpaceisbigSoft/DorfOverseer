"""Tests for the unattended run's check (brain/health_check.py) and the
keeper starting it after each copy of the save.

    python tests/test_health_check.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp())
os.environ["DFAI_LOG_DIR"] = str(TMP / "logs")
sys.path.insert(0, str(ROOT / "brain"))

import backup  # noqa: E402
import health_check as hc  # noqa: E402
import keeper  # noqa: E402

backup.BACKUP_DIR = TMP / "backups"
backup.STATE = TMP / "backups" / "last.json"
keeper.LOG_DIR = TMP / "keeper"
keeper.LOG = TMP / "keeper" / "unattended.log"
RESULTS = []


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


def dec(rule, action, ok=True, error=None, year=56, tick=0, reason="", fort="F#1"):
    return {"kind": "decision", "mode": "autopilot", "fort": fort, "rule": rule, "action": action,
            "reason": reason, "date": {"year": year, "tick": tick},
            "result": {"ok": ok, **({"error": error} if error else {})}}


@test("journals: a loop by game year, a repeating refusal, order churn and squad churn")
def _():
    es = []
    # 30 meal orders over a quarter of a game year: a loop
    es += [dec("food", {"type": "work_order", "recipe": "prepare_lavish_meal"}, tick=i * 3000) for i in range(30)]
    # 15 alerts dismissed: by design, never a loop
    es += [dec("alerts", {"type": "dismiss_alerts"}, tick=i * 100) for i in range(15)]
    # the same refusal 6 times, numbers differing
    es += [dec("fortify", {"type": "fortify_entrance"}, ok=False, tick=i,
               error=f"the way in at x{30 + i} y187 is a branch") for i in range(6)]
    # metal helms ordered and cancelled in turn
    es += [dec("arms", {"type": "work_order", "recipe": "metal_helm"}, tick=i) for i in range(4)]
    es += [dec("stuck_order", {"type": "cancel_work_order", "order_id": i}, tick=i,
               reason="4 of the AI's metal_helm orders and this one hasn't moved in 14 days") for i in range(3)]
    es += [dec("squad_fill", {"type": "squad_fill"}, tick=i) for i in range(3)]
    es += [dec("stress_care", {"type": "squad_release"}, tick=i) for i in range(3)]
    flags, lines = hc.journal_flags(es)
    text = "\n".join(flags)
    assert "possible loop: food: work_order prepare_lavish_meal x30" in text, text
    assert "dismiss_alerts" not in text, text
    assert "the same refusal repeating: fortify: fortify_entrance x6" in text, text
    assert "churn: metal_helm ordered 4 times and cancelled as stuck 3 times" in text, text
    assert "churn: soldiers drafted 3 times and released 3 times" in text, text
    # spread over 5 game years, 30 orders aren't a loop (6 a year)
    es2 = [dec("food", {"type": "work_order", "recipe": "prepare_lavish_meal"}, year=50 + i // 6, tick=i)
           for i in range(30)]
    assert not hc.journal_flags(es2)[0], hc.journal_flags(es2)[0]


@test("standing lines: first and last seen kept, cleared lines dropped, old ones flagged")
def _():
    path = TMP / "standing.json"
    hc._STANDING_CACHE.update(data=None)
    t0 = 1_000_000.0
    hc.track_standing("F#1", ["8 dwarves are miserable"], ["rule _x failed (KeyError: 'a')", "plain note"],
                      tick=0, now=t0, path=path)
    d = json.loads(path.read_text(encoding="utf-8"))["F#1"]
    assert len(d) == 2 and {e["kind"] for e in d.values()} == {"needs_you", "failed"}, d
    # 13 hours on, the count changed (same shape), the failure gone
    hc.track_standing("F#1", ["9 dwarves are miserable"], [], tick=5 * 1200, now=t0 + 13 * 3600, path=path)
    d = json.loads(path.read_text(encoding="utf-8"))
    assert len(d["F#1"]) == 1, d
    e = next(iter(d["F#1"].values()))
    assert e["first"] == t0 and e["text"] == "9 dwarves are miserable", e
    flags = hc.standing_flags(d, now=t0 + 13 * 3600 + 60)
    assert len(flags) == 1 and "Needs you that never clears" in flags[0] and "13 h" in flags[0], flags
    # a fort not run for hours: history, not flagged
    assert not hc.standing_flags(d, now=t0 + 20 * 3600)
    # 30 game days in 2 real hours: flagged by game time
    hc._STANDING_CACHE.update(data=None)
    p2 = TMP / "standing2.json"
    hc.track_standing("F#2", ["no well"], [], tick=0, now=t0, path=p2)
    hc.track_standing("F#2", ["no well"], [], tick=30 * 1200, now=t0 + 7200, path=p2)
    flags = hc.standing_flags(json.loads(p2.read_text(encoding="utf-8")), now=t0 + 7300)
    assert flags and "30 game days" in flags[0], flags


@test("keeper log and speed: restarts and tracebacks flagged; FPS falling; a slow report section")
def _():
    lines = ["[2026-10-24 10:00:00] Restarting the overseer in 30 s (restart 1)."] * 3
    lines += ["[2026-10-24 10:00:00]   Traceback (most recent call last):"]
    flags, _ = hc.log_flags(lines)
    assert any("restarted" in f for f in flags) and any("Traceback" in f for f in flags), flags
    rows = [{"in_fort": True, "paused": False, "fort": "F#1", "fps": 100, "pop": 50,
             "report_timing": {"industry": 280, "labor": 20}} for _ in range(6)]
    rows += [{"in_fort": True, "paused": False, "fort": "F#1", "fps": 55, "pop": 90,
              "report_timing": {"industry": 300, "labor": 25}} for _ in range(6)]
    flags, plain = hc.fps_flags(rows)
    assert any("slowing down in F#1: FPS median 100 -> 55" in f for f in flags), flags
    assert any("'industry' is slow" in f for f in flags) and not any("'labor'" in f for f in flags), flags
    rows = [dict(r, fps=30) for r in rows]
    assert any("runs slowly in F#1" in f for f in hc.fps_flags(rows)[0])


@test("self-test: its FAIL lines are flags; a game not running is no flag; a hang is")
def _():
    class P:
        def __init__(self, out):
            self.stdout = out
    out = "[PASS] bridge answers\n[FAIL] installed bridge is current\n        old\n\n9 passed, 2 warnings, 1 failed\n"
    flags, plain = hc.run_selftest(lambda *a, **k: P(out))
    assert flags == ["self-test failed: installed bridge is current (old)"] and "9 passed" in plain[0], (flags, plain)
    flags, plain = hc.run_selftest(lambda *a, **k: P("Dwarf Fortress isn't running (or DFHack isn't loaded).\n"))
    assert not flags and "isn't running" in plain[0]

    def hang(*a, **k):
        raise subprocess.TimeoutExpired("x", 300)
    assert "didn't finish" in hc.run_selftest(hang)[0][0]


@test("housekeeping: old test saves listed, never deleted; other forts' old backups thinned to the newest")
def _():
    now = time.time()
    saves = TMP / "save"
    for name in ("AI Run War-hold", "region2", "autosave 1"):
        (saves / name).mkdir(parents=True, exist_ok=True)
        (saves / name / "world.sav").write_bytes(b"x" * 1000)
    old = now - 20 * 86400
    os.utime(saves / "AI Run War-hold", (old, old))
    os.utime(saves / "region2", (old, old))
    bk = TMP / "bk"
    for save, stamps in (("region2", ["2026-10-01 1000", "2026-10-02 1000", "2026-10-03 1000"]),
                         ("autosave 1", ["2026-10-01 1000", "2026-10-02 1000"])):
        for st in stamps:
            (bk / save / st).mkdir(parents=True, exist_ok=True)
            os.utime(bk / save / st, (old, old))
    flags, plain = hc.housekeeping([saves], "autosave 1", bk, now=now)
    assert len(flags) == 1 and "AI Run War-hold" in flags[0] and "region2" not in flags[0], flags
    assert (saves / "AI Run War-hold").exists()                         # listed only
    assert sorted(p.name for p in (bk / "region2").iterdir()) == ["2026-10-03 1000"]
    assert len(list((bk / "autosave 1").iterdir())) == 2                 # the fort being played: untouched
    assert "2 old copies" in plain[0], plain


@test("the whole check: every part runs, a part that fails says so, both files written")
def _():
    logs = TMP / "logs"
    (logs / "forts" / "F-1").mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    with (logs / "forts" / "F-1" / "journal.jsonl").open("w", encoding="utf-8") as f:
        for i in range(6):
            e = dec("feeder", {"type": "feeder_pile"}, ok=False, error="no free floor beside the Masons", tick=i)
            e["time"] = (now - timedelta(minutes=5)).isoformat(timespec="seconds")
            f.write(json.dumps(e) + "\n")
    hc.LOG_DIR, hc.REPORT, hc.FLAGS, hc.STANDING = logs, logs / "health-check.txt", logs / "health-check.json", \
        logs / "standing.json"
    flags, page = hc.check(24, selftest=False, now=now)
    assert any("feeder: feeder_pile x6" in f for f in flags), flags
    assert (logs / "health-check.txt").exists() and json.loads((logs / "health-check.json").read_text())["flags"] == flags
    for title in ("what the AI did:", "standing lines:", "the keeper:", "speed:", "housekeeping:"):
        assert title in page, (title, page)
    assert hc.summary([])[0].startswith("Check: nothing flagged")
    assert hc.summary(flags)[0].startswith("Check: 1 thing(s) flagged")


@test("keeper: the check starts after a new copy of the save, not for the copy found at the start; daily anyway")
def _():
    backup.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup.STATE.write_text(json.dumps({"at": 1, "copy": "C:/b/old"}), encoding="utf-8")
    keeper.EXTRAS.update(check_copy=None, last_check=None, check_thread=None, copy_seen_at=0.0)
    started = []
    t = 1_000_000.0
    assert not keeper.maybe_check(t, start=started.append)              # the old copy: remembered, not new
    assert not keeper.maybe_check(t + 30, start=started.append)
    backup.STATE.write_text(json.dumps({"at": 2, "copy": "C:/b/new"}), encoding="utf-8")
    assert not keeper.maybe_check(t + 30, start=started.append)         # looked at once a minute
    assert keeper.maybe_check(t + 61, start=started.append)
    assert started == ["after the day's copy of the save"], started
    assert not keeper.maybe_check(t + 200, start=started.append)
    assert keeper.maybe_check(t + 61 + keeper.CHECK_EVERY_S, start=started.append)
    assert started[-1] == "a day since the last check"
    # a fresh keeper with no copy ever made: the first check an hour in
    keeper.EXTRAS.update(check_copy=None, last_check=None, copy_seen_at=0.0)
    backup.STATE.unlink()
    assert not keeper.maybe_check(t, start=started.append)
    assert keeper.maybe_check(t + keeper.CHECK_FIRST_S + 1, start=started.append)


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f"\n    {msg}"))
    fails = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - fails} passed, {fails} failed")
    sys.exit(1 if fails else 0)

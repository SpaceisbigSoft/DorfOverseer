"""Tests for the unattended run: brain/keeper.py (restarts), the overseer's
FPS guard, and the season report (brain/report.py).

    python tests/test_keeper.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import backup  # noqa: E402
import keeper  # noqa: E402
import memstore  # noqa: E402
import overseer  # noqa: E402

overseer.THROTTLE_MEMORY_SAVE = False      # each cycle reads and writes the memory (the throttle has its own test)
import report  # noqa: E402
from planner import Memory, plan  # noqa: E402

TMP = Path(tempfile.mkdtemp())
keeper.LOG_DIR = TMP
keeper.LOG = TMP / "unattended.log"
keeper.STATUS = TMP / "status.txt"
keeper.HEARTBEAT = TMP / "heartbeat"
memstore.FORTS_DIR = TMP / "forts"
overseer.HEARTBEAT = TMP / "overseer-heartbeat"
backup.BACKUP_DIR = TMP / "backups"
backup.STATE = TMP / "backups" / "last.json"


class FakeProc:
    def __init__(self, code=1, lines=("hello",), hang=False):
        self.stdout = iter([x + "\n" for x in lines])     # (no readline: the keeper uses next())
        self.code, self.hang, self.killed = code, hang, False

    def poll(self):
        return None if self.hang and not self.killed else self.code

    def kill(self):
        self.killed = True


@test("keeper: runs the overseer unattended without the AI, logs its lines, restarts it with a growing wait")
def _():
    started = []

    def popen(cmd, **kw):
        started.append(cmd)
        return FakeProc(code=1, lines=("Connected: bridge 0.36.0",))
    waits = []
    keeper.main([], popen=popen, sleep=waits.append, max_runs=3)
    assert started and started[0][3:] == ["--autopilot", "--unattended"], started[0]
    assert waits == [30, 60, 120], waits
    text = keeper.LOG.read_text(encoding="utf-8")
    assert "Connected: bridge 0.36.0" in text and "exit code 1" in text and "restart 3" in text, text
    keeper.main(["--ai"], popen=popen, sleep=lambda s: None, max_runs=1)
    assert started[-1][-1] == "--ai"


@test("(0.105.4) keeper --preset: passed to every overseer it starts, and said in the log")
def _():
    started = []

    def popen(cmd, **kw):
        started.append(cmd)
        return FakeProc(code=1, lines=())
    keeper.main(["--preset", "Merchant city"], popen=popen, sleep=lambda s: None, max_runs=2)
    assert len(started) == 2 and all(c[3:] == ["--autopilot", "--unattended", "--preset", "Merchant city"]
                                      for c in started), started
    assert "Preset: Merchant city asked for" in keeper.LOG.read_text(encoding="utf-8")
    keeper.main(["--ai", "--preset", "Deep mine"], popen=popen, sleep=lambda s: None, max_runs=1)
    assert started[-1][3:] == ["--autopilot", "--unattended", "--ai", "--preset", "Deep mine"], started[-1]
    keeper.main([], popen=popen, sleep=lambda s: None, max_runs=1)
    assert "--preset" not in started[-1]


class PresetGame:
    """The bridge's apply_preset, as far as the overseer sees it."""
    def __init__(self, fort_preset=None):
        self.fort_preset, self.acts = fort_preset, []

    def act(self, a):
        self.acts.append(a)
        if a.get("name") not in ("War-hold", "Monastery"):
            return {"ok": False, "rejected": True, "error": "unknown preset: x (known: Monastery, War-hold)"}
        prev = self.fort_preset
        if not a.get("dry_run"):
            self.fort_preset = a["name"]
        return {"ok": True, "preset": a["name"], "previous": prev, "traits": {"militarism": 150, "caution": 60},
                "rules": {"attack_policy": "all", "levels": {"garden": False}},
                "settings": {"traits": {"militarism": 150}, "preset": self.fort_preset}}

    def state(self):
        return {"settings": {"traits": {}, "preset": self.fort_preset}}


def preset_cycle(game, name, key="region1#7", autopilot=True, new_process=True):
    said = []
    real = overseer.say
    overseer.say = said.append
    overseer.PRESET = name
    if new_process:
        overseer.PRESET_DONE.clear()          # a restart or a revive: a new overseer
    try:
        st = game.state()
        overseer.apply_preset(game, st, key, autopilot)
        return said, st
    finally:
        overseer.say, overseer.PRESET = real, None


@test("(0.105.4) overseer --preset: applied once per fort; a restart or revive never applies it over later changes")
def _():
    overseer.PRESET_FILE = TMP / "keeper-preset.json"
    overseer.PRESET_FILE.unlink(missing_ok=True)
    g = PresetGame()
    said, st = preset_cycle(g, "War-hold")
    assert [a["type"] for a in g.acts] == ["apply_preset"] and g.acts[0]["name"] == "War-hold", g.acts
    assert said and said[0].startswith("Preset: War-hold applied (first time for this fort; was none)"), said
    assert "militarism:+150" in said[0] and "attack_policy=all" in said[0] and "garden:off" in said[0], said
    assert st["settings"]["preset"] == "War-hold"                       # this cycle plans with it
    assert '"War-hold"' in overseer.PRESET_FILE.read_text(encoding="utf-8")
    preset_cycle(g, "War-hold", new_process=False)                        # the next cycle: not asked again
    assert len(g.acts) == 1
    g.fort_preset = "Monastery"                                           # the player chose another in the window
    said, _ = preset_cycle(g, "War-hold")                                 # the keeper restarts the overseer
    assert len(g.acts) == 1 and "already applied" in said[0], said
    g.fort_preset = None                                                  # an older save loaded: no preset in it
    said, _ = preset_cycle(g, "War-hold")
    assert len(g.acts) == 2 and "the save shows no preset" in said[0], said
    said, _ = preset_cycle(g, "Monastery")                                # another preset asked: applied
    assert len(g.acts) == 3 and g.fort_preset == "Monastery", g.acts
    g2 = PresetGame()
    preset_cycle(g2, "War-hold", key="region2#9")                         # another fort: its own record
    assert len(g2.acts) == 1


@test("(0.105.4) overseer --preset: an unknown name is said and not retried; a dry run changes and records nothing")
def _():
    overseer.PRESET_FILE = TMP / "keeper-preset2.json"
    overseer.PRESET_FILE.unlink(missing_ok=True)
    g = PresetGame()
    said, _ = preset_cycle(g, "Fortress of Doom")
    assert "not applied: unknown preset" in said[0] and "War-hold" in said[0], said
    preset_cycle(g, "Fortress of Doom", new_process=False)
    assert len(g.acts) == 1
    said, _ = preset_cycle(g, "Monastery", autopilot=False)
    assert g.acts[-1]["dry_run"] is True and "would be applied" in said[0] and g.fort_preset is None, said
    assert not overseer.PRESET_FILE.exists()


@test("keeper: a stuck overseer (no heartbeat) is stopped and restarted")
def _():
    # (13c) a fresh heartbeat keeps it running; only a stale one stops it
    # (with STALE_S = 0 the old test passed whatever the heartbeat said)
    saved = keeper.STALE_S, keeper.heartbeat_age
    keeper.STALE_S = 600
    ages = iter([5.0, 590.0, 601.0])
    procs, sleeps = [], []

    def popen(cmd, **kw):
        procs.append(FakeProc(hang=True, lines=()))
        return procs[-1]
    orig_sleep = time.sleep
    keeper.time.sleep = sleeps.append
    keeper.heartbeat_age = lambda: next(ages)
    try:
        code, why = keeper.run_once(False, popen)
    finally:
        keeper.STALE_S, keeper.heartbeat_age = saved
        keeper.time.sleep = orig_sleep
    assert code is None and procs[0].killed and "stopped answering for 10 minutes" in why, why
    assert len(sleeps) == 2, sleeps                  # two fresh readings watched, killed on the stale one


@test("FPS guard: low only after a minute of samples under 20, and clears above 30 (no flicker)")
def _():
    now = 1000.0
    low = [(now + i, 12) for i in range(40)]
    assert overseer.fps_state(low[:10], None) is None             # too few samples yet
    assert overseer.fps_state(low, None) == 12
    mid = [(now + i, 25) for i in range(40)]
    assert overseer.fps_state(mid, 12) == 25                       # still low: not yet above 30
    assert overseer.fps_state([(now + i, 60) for i in range(40)], 25) is None
    # (0.104.106) a game that runs at 100 is held from 35, and let go above 45
    pk = {"fps": 0}
    fast = [(now + i, 100) for i in range(40)]
    assert overseer.fps_state(fast, None, pk) is None and pk["fps"] == 100
    assert overseer.fps_state([(now + i, 30) for i in range(40)], None, pk) == 30
    assert overseer.fps_state([(now + i, 42) for i in range(40)], 30, pk) == 42     # not yet above 45
    assert overseer.fps_state([(now + i, 50) for i in range(40)], 42, pk) is None


def fort():
    import json
    return json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


@test("FPS guard in the planner: no newcomers and no new luxury levels while slow")
def _():
    s = fort()
    s["society"].update(pop_cap=250, strict_pop_cap=270)   # (13c) the fixture has no cap: the rule never ran
    s["fps_low"] = 14
    props, notes = plan(s, Memory())
    caps = [p for p in props if p.rule == "pop_cap"]
    assert caps and "runs slowly" in caps[0].reason and caps[0].action["strict"] == 110, [p.action for p in caps]
    lux = [p for p in props if p.action.get("type") == "start_project"
           and p.action.get("kind") not in ("bedrooms", "dining", "storage", "workshops", "tombs", "hospital")]
    assert not lux, [p.action for p in lux]


@test("season report: none on the first look, then a few lines each new season, in the fort's folder")
def _():
    s = fort()
    m = Memory()
    key = "Test Fort#99"
    assert report.maybe_write(s, m, key, []) is None and m.report_season       # first look: just noted
    assert report.maybe_write(s, m, key, []) is None                           # same season: nothing
    s["date"]["year"] += 1
    s["date"]["season"] = "spring"                                  # a new season
    line = report.maybe_write(s, m, key, ["appoint a broker"], 87)
    assert line and "report.md" in line, line
    text = (memstore.fort_dir(key) / "report.md").read_text(encoding="utf-8")
    assert text.startswith("# Report: Test Fort") and "87 FPS" in text and "appoint a broker" in text, text
    assert "**Phase:**" in text
    # an older save loaded (the season goes back): noted, no report written
    s["date"]["year"] -= 1
    s["date"]["season"] = "winter"
    assert report.maybe_write(s, m, key, []) is None and m.report_season.endswith("winter")
    assert (memstore.fort_dir(key) / "report.md").read_text(encoding="utf-8") == text


@test("FPS guard: the cap is held at the fort's size when it first ran slowly; deaths don't lower it")
def _():
    from planner import record
    s = fort()
    s["fps_low"] = 14
    s["society"]["pop_cap"], s["society"]["strict_pop_cap"] = 250, 270
    m = Memory()
    p = [x for x in plan(s, m)[0] if x.rule == "pop_cap"]
    assert p and "runs slowly" in p[0].reason, [x.rule for x in plan(s, m)[0]]
    first = p[0].action["cap"]
    assert p[0].action["strict"] == first + 10
    record([(p[0], {"ok": True})], s, m)
    assert m.fps_cap == first
    s["society"]["pop_cap"], s["society"]["strict_pop_cap"] = first, first + 10
    s["dwarves"]["total"] = first - 5                                  # some died
    again = [x for x in plan(s, m)[0] if x.rule == "pop_cap"]
    assert not again or again[0].action["cap"] == first, [x.action for x in again]


class PausedGame:
    """A game that stays paused (an announcement paused it)."""
    def __init__(self, halted=False):
        self.acts, self.halted = [], halted
        self.version = None

    def handshake(self):
        return {"bridge_version": "0.36.0", "dfhack_version": "53.16-r3"}

    def status(self):
        return {"in_fort": True, "paused": True, "halted": self.halted, "fps": 0,
                "date": {"year": 150, "tick": 100, "day": 1, "month": "Granite", "season": "spring"}}

    def act(self, a):
        self.acts.append(a)
        return {"ok": True}


def run_loop(game, args, ticks=40, step=2.0):
    """Run the overseer's main loop against a fake game for a while."""
    clock = [0.0]
    calls = [0]
    real = (overseer.Bridge, overseer.time.monotonic, overseer.time.sleep, sys.argv)
    overseer.Bridge = lambda: game
    overseer.time.monotonic = lambda: clock[0]

    def fake_sleep(s):
        calls[0] += 1
        clock[0] += step
        if calls[0] >= ticks:
            raise KeyboardInterrupt
    overseer.time.sleep = fake_sleep
    sys.argv = ["overseer.py"] + args
    try:
        overseer.main()
    finally:
        overseer.Bridge, overseer.time.monotonic, overseer.time.sleep, sys.argv = real


@test("unattended: a game that paused itself is unpaused after 30 s; never while halted, or without the flag")
def _():
    g = PausedGame()
    run_loop(g, ["--autopilot", "--unattended"])
    unp = [a for a in g.acts if a.get("type") == "unpause"]
    assert 2 <= len(unp) <= 3, g.acts            # 80 s of a game that keeps pausing: every 30 s
    assert [a.get("type") for a in g.acts].count("quiet_announcements") == 1, g.acts
    g = PausedGame(halted=True)
    run_loop(g, ["--autopilot", "--unattended"])
    assert not g.acts                                   # (halted: not even the announcements)
    g = PausedGame()
    run_loop(g, ["--autopilot"])
    assert not g.acts


@test("keeper: a second keeper for the same folder refuses to start")
def _():
    lock = keeper.single_instance()
    assert lock is not None
    try:
        assert keeper.main([], popen=lambda *a, **k: FakeProc(), sleep=lambda s: None, max_runs=1) == 1
        assert "Another keeper is already running" in keeper.LOG.read_text(encoding="utf-8")
    finally:
        lock.close()


@test("unattended: running but the date stands still (a popup): popups taken off at once, retried 1, 2... 10 minutes later")
def _():
    g = PausedGame()
    g.status = lambda: {"in_fort": True, "paused": False, "halted": False, "fps": 100,
                        "date": {"year": 150, "tick": 100, "day": 1, "month": "Granite", "season": "spring"}}
    orig = overseer.one_cycle
    overseer.one_cycle = lambda *a, **k: None
    try:
        run_loop(g, ["--autopilot", "--unattended"], ticks=75)
    finally:
        overseer.one_cycle = orig
    unst = [a for a in g.acts if a.get("type") == "unpause" and a.get("unstick")]
    assert len(unst) == 2, g.acts                       # at 60 s, and 60 s later (it didn't help)
    assert [a for a in g.acts if a.get("type") == "quiet_announcements"], g.acts


@test("backups: the newest of the save and DF's autosaves, once a day, kept by age (0.105.46: a day's for a week); never mid-save")
def _():
    import os
    root = TMP / "save"
    for name, age in (("region1", 5000), ("autosave 1", 3000), ("autosave 2", 9000)):
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "world.sav").write_text(name)
        t = time.time() - age
        os.utime(d / "world.sav", (t, t))
        os.utime(d, (t, t))
    now = time.time()
    line = backup.maybe(root, "region1", now=now)
    assert line and "autosave 1" in line, line
    copies = list((backup.BACKUP_DIR / "region1").iterdir())
    assert len(copies) == 1 and (copies[0] / "world.sav").read_text() == "autosave 1"
    assert backup.maybe(root, "region1", now=now + 60) is None              # not again the same day
    for i in range(1, 5):
        assert backup.maybe(root, "region1", now=now + i * 86400 + 1)
    # (0.105.46, I6) kept by age: five copies a day apart are all inside the week
    assert len(list((backup.BACKUP_DIR / "region1").iterdir())) == 5
    (root / "autosave 2" / "world.sav").write_text("fresh")                   # being written now
    assert backup.maybe(root, "region1", now=time.time(), force=True) is None


@test("trouble: starving dwarves, no food and no farm, too little drink, or no one left are named plainly")
def _():
    s = fort()
    assert report.trouble(s, Memory()) == [], report.trouble(s, Memory())
    s["society"]["starving"] = 3
    s["stocks"].update(prepared_meals=0, meat=0, fish=0, plants=0, plant_growths=0, cheese=0, eggs=0, raw_fish=0,
                       drink=5)
    s["buildings"]["other"].pop("FarmPlot", None)
    s["farms"] = {"plots": 0, "tiles": 0, "built": 0}
    bad = report.trouble(s, Memory())
    assert "3 starving" in bad[0] and any("no farm" in b for b in bad) and any("drink" in b for b in bad), bad
    s["dwarves"]["total"] = 0
    assert "fallen" in report.trouble(s, Memory())[0]


@test("backups (0.100 security): only a plain save folder name; a cut-off copy never counts; only dated copies cleared")
def _():
    root = TMP / "save2"
    (root / "region9").mkdir(parents=True, exist_ok=True)
    (root / "region9" / "world.sav").write_text("x")
    old = time.time() - 5000
    import os
    os.utime(root / "region9" / "world.sav", (old, old))
    os.utime(root / "region9", (old, old))
    for bad in ("..", "../x", "C:", "a\\b", "CON", "x "):
        line = backup.maybe(root, bad, force=True)
        assert line and "plain folder name" in line, (bad, line)
    assert not (backup.BACKUP_DIR / "..").resolve().joinpath("save2-copy").exists()
    keepme = backup.BACKUP_DIR / "region9" / "my notes"
    keepme.mkdir(parents=True, exist_ok=True)
    stale = backup.BACKUP_DIR / "region9" / "2020-01-01 0000.partial"
    stale.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for i in range(5):
        assert backup.maybe(root, "region9", now=now + i * 86400, force=True)
    names = sorted(p.name for p in (backup.BACKUP_DIR / "region9").iterdir())
    assert "my notes" in names, names                                   # not one of ours: left alone
    assert len([n for n in names if backup.COPY_NAME.match(n)]) == 5, names    # (0.105.46) a day's for a week
    assert not any(n.endswith(".partial") and n != stale.name for n in names), names

@test("backups (0.104.81): a long copy beats the overseer's heartbeat now and then, and a failing beat never breaks it")
def _():
    src = TMP / "beat-src"
    src.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (src / f"f{i}.dat").write_text("x")
    beats = []
    def beat():
        beats.append(1)
        raise OSError("disk full")
    old = backup.on_progress
    backup.on_progress, backup._last_beat[0] = beat, 0.0
    try:
        import shutil
        dst = TMP / "beat-dst"
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst, copy_function=backup._copy_beating)
    finally:
        backup.on_progress = old
    assert len(beats) == 1, beats                     # at most one beat each 30 seconds
    assert sorted(p.name for p in dst.iterdir()) == ["f0.dat", "f1.dat", "f2.dat"]


@test("(0.105.4) overseer.py takes --preset (the keeper passes it)")
def _():
    g = PausedGame()
    run_loop(g, ["--autopilot", "--preset", "Garden fort"], ticks=2)
    assert overseer.PRESET == "Garden fort"
    overseer.PRESET = None


if __name__ == "__main__":
    finish()

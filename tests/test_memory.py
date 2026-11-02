"""Tests for memory, part two: the memory store (brain/memstore.py), the
timeline, the atlas and the chronicle. No game needed.

    python tests/test_memory.py
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

import atlas  # noqa: E402
import chronicle  # noqa: E402
import memstore  # noqa: E402
import outcomes  # noqa: E402
import overseer  # noqa: E402

overseer.THROTTLE_MEMORY_SAVE = False      # each cycle reads and writes the memory (the throttle has its own test)
import timeline  # noqa: E402
from planner import PLANNER_CONFIG, Memory  # noqa: E402
from tokens import TokenBank  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
KEY = "AI Test Run#1234"
TMP = Path(tempfile.mkdtemp())
memstore.FORTS_DIR = TMP / "forts"
memstore.LEGACY_FILE = TMP / "overseer-memory.json"
overseer.say = lambda m: None
RESULTS = []
DAY = 1200
YEAR = 403200


def test(name):
    def wrap(fn):
        shutil.rmtree(memstore.FORTS_DIR, ignore_errors=True)
        memstore.LEGACY_FILE.unlink(missing_ok=True)
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception:  # noqa: BLE001
            import traceback
            RESULTS.append((name, False, traceback.format_exc()))
        return fn
    return wrap


def state_at(day: int, **changes) -> dict:
    """The fixture fort on an absolute game day."""
    s = copy.deepcopy(BASE)
    s["date"] = {"year": day // 336, "tick": (day % 336) * DAY, "day": 1, "month": "Granite", "season": "spring"}
    for k, v in changes.items():
        s[k] = v
    return s


class Save:
    """The game's save, holding each kind as text (as lua/ai-bridge.lua does)."""

    def __init__(self, legacy=None):
        self.kinds, self.legacy, self.writes = {}, legacy, []

    def load_memory(self):
        out = {}
        if self.kinds:
            out["kinds"] = copy.deepcopy(self.kinds)
        if self.legacy:
            out["legacy"] = copy.deepcopy(self.legacy)
        return out or None

    def save_memory(self, data):
        data = json.loads(json.dumps(data))
        self.writes.append(data)
        for k, t in data["kinds"].items():
            assert isinstance(t, str)
            self.kinds[k] = {"fort": data["fort"], "text": t}
        if data.get("drop_legacy"):
            self.legacy = None
        return True


# --- the store -------------------------------------------------------------------------

@test("store: each kind travels as text, and an empty {} comes back as a map")
def _():
    m = Memory()
    m.gates_fortified = {}
    m.calibration = {"values": {}, "windows": {}}
    m.atlas = {"registry": {}}
    texts = memstore.texts_of(m, TokenBank(), KEY)
    assert set(texts) == set(memstore.KINDS)
    m2, _ = memstore.join({k: memstore.decode(k, t) for k, t in texts.items()})
    assert m2.calibration["values"] == {} and isinstance(m2.calibration["windows"], dict)
    assert m2.atlas["registry"] == {} and m2.gates_fortified == {}
    assert all(t.isascii() for t in texts.values())


@test("store: the fields are split by kind; the token bank is working state")
def _():
    m = Memory()
    m.learning = {"prefs": {"x": 1}}
    m.culture = {"sieges": 2}
    m.last_fired = {"drink": 5}
    m.timeline = {"days": [[1]]}
    parts = memstore.split(m, TokenBank(balance=500))
    assert parts["knowledge"]["learning"] == {"prefs": {"x": 1}}
    assert parts["chronicle"]["culture"] == {"sieges": 2}
    assert parts["working"]["last_fired"] == {"drink": 5} and parts["working"]["bank"]["balance"] == 500
    assert parts["timeline"]["timeline"] == {"days": [[1]]} and "timeline" not in parts["working"]


@test("store: schema versions upgrade step by step; an unknown version isn't guessed at")
def _():
    text = memstore.encode("atlas", {"atlas": {"old_name": 1}}, KEY)
    saved_schema, saved_mig = dict(memstore.SCHEMA), copy.deepcopy(memstore.MIGRATIONS)
    try:
        memstore.SCHEMA["atlas"] = 2
        memstore.MIGRATIONS["atlas"][1] = lambda d: {"atlas": {"new_name": d["atlas"]["old_name"]}}
        assert memstore.decode("atlas", text) == {"atlas": {"new_name": 1}}
        memstore.SCHEMA["atlas"] = 3                      # no step from 2 to 3
        assert memstore.decode("atlas", text) is None
    finally:
        memstore.SCHEMA.update(saved_schema)
        memstore.MIGRATIONS.clear()
        memstore.MIGRATIONS.update(saved_mig)
    assert memstore.decode("atlas", "not json") is None


@test("store: fields from a newer brain are kept, not dropped")
def _():
    datas = {"working": {"last_fired": {"a": 1}, "from_the_future": [1, 2]}}
    m, bank = memstore.join(datas)
    assert m.last_fired == {"a": 1}
    again = memstore.split(m, bank)
    assert again["working"]["from_the_future"] == [1, 2]


@test("store: only the kinds that changed are written into the save")
def _():
    save = Save()
    m, bank = memstore.load(KEY, save)
    memstore.save(KEY, m, bank, save)
    assert set(save.writes[0]["kinds"]) == set(memstore.KINDS)
    m, bank = memstore.load(KEY, save)
    memstore.save(KEY, m, bank, save)
    assert len(save.writes) == 1, "nothing changed: nothing written"
    m, bank = memstore.load(KEY, save)
    m.last_fired["drink"] = 9
    m.chronicle = {"entries": [{"t": "x"}]}
    memstore.save(KEY, m, bank, save)
    assert set(save.writes[-1]["kinds"]) == {"working", "chronicle"}, save.writes[-1]["kinds"].keys()


@test("store: an old one-piece memory in the save is moved over, then dropped once every kind is saved")
def _():
    save = Save(legacy={"fort": KEY, "memory": {"last_fired": {"drink": 5}, "culture": {"sieges": 3}},
                        "bank": {"balance": 700}})
    m, bank = memstore.load(KEY, save)
    assert m.last_fired == {"drink": 5} and m.culture["sieges"] == 3 and bank.balance == 700
    memstore.save(KEY, m, bank, save)
    w = save.writes[0]
    assert w.get("drop_legacy") is True and set(w["kinds"]) == set(memstore.KINDS)
    assert save.legacy is None
    m, bank = memstore.load(KEY, save)
    assert m.culture["sieges"] == 3 and bank.balance == 700


@test("store: another fort's memory is ignored; the old logs file is migrated")
def _():
    save = Save(legacy={"fort": "Other#9", "memory": {"last_fired": {"drink": 5}}})
    m, _ = memstore.load(KEY, save)
    assert m.last_fired == {}
    memstore.LEGACY_FILE.write_text(json.dumps({KEY: {"memory": {"last_fired": {"x": 1}}, "bank": {}}}))
    m, _ = memstore.load(KEY)
    assert m.last_fired == {"x": 1} and m._texts["source"] == "logs (migrated)"
    memstore.save(KEY, m, TokenBank())
    assert (memstore.fort_dir(KEY) / "memory.json").exists()
    m, _ = memstore.load(KEY)
    assert m._texts["source"] == "logs" and m.last_fired == {"x": 1}


@test("store: the save comes first; a kind it lacks is filled in from logs")
def _():
    save = Save()
    m = Memory()
    m.last_fired = {"logs": 1}
    m.atlas = {"survey": {"tick": 1}}
    memstore.save(KEY, m, TokenBank())                        # logs only
    m2 = Memory()
    m2.last_fired = {"save": 1}
    save.kinds["working"] = {"fort": KEY, "text": memstore.encode("working", memstore.split(m2, TokenBank())["working"], KEY)}
    m3, _ = memstore.load(KEY, save)
    assert m3.last_fired == {"save": 1}, "the save wins"
    assert m3.atlas == {"survey": {"tick": 1}}, "the atlas the save lacks comes from logs"


@test("store: fort folders and journal rotation")
def _():
    assert memstore.fort_dir("My Fort: 1#77").name == "My_Fort_1-77"
    p = TMP / "j" / "journal.jsonl"
    saved = memstore.JOURNAL_MAX_BYTES
    memstore.JOURNAL_MAX_BYTES = 200
    try:
        for i in range(40 + 5 * memstore.JOURNAL_KEEP):
            memstore.append_journal(p, {"i": i, "pad": "x" * 30})
    finally:
        memstore.JOURNAL_MAX_BYTES = saved
    files = sorted(x.name for x in p.parent.iterdir())
    want = sorted([f"journal.{i}.jsonl" for i in range(1, memstore.JOURNAL_KEEP + 1)] + ["journal.jsonl"])
    assert files == want, files
    last = json.loads(p.read_text().splitlines()[-1])
    assert last["i"] == 39 + 5 * memstore.JOURNAL_KEEP


@test("store: the timeline log keeps TIMELINE_LOG_DAYS of days and drops a future that was reloaded away")
def _():
    f = timeline.FIELDS
    for d in range(1000, 1010):
        memstore.log_day(KEY, {"day": d, "pop": d}, f)
    memstore.log_day(KEY, {"day": 1005, "pop": 1}, f)        # an older save was loaded
    rows = (memstore.fort_dir(KEY) / "timeline.csv").read_text().splitlines()
    assert rows[0].startswith("day,") and rows[-1].startswith("1005,1,") and len(rows) == 1 + 6, rows
    memstore.log_day(KEY, {"day": 1005 + memstore.TIMELINE_LOG_DAYS + 30, "pop": 3}, f)
    rows = (memstore.fort_dir(KEY) / "timeline.csv").read_text().splitlines()
    assert len(rows) == 2, "days older than TIMELINE_LOG_DAYS leave the file"
    memstore.log_seasons(KEY, [{"season": 4, "n": 80, "avg": {"pop": 30}}], timeline.season_name)
    memstore.log_seasons(KEY, [{"season": 4, "n": 80}, {"season": 5, "n": 3}], timeline.season_name)
    srows = (memstore.fort_dir(KEY) / "seasons.csv").read_text().splitlines()
    assert len(srows) == 3 and srows[1].startswith("4,spring 1,80"), srows
    memstore.log_seasons(KEY, [{"season": 4, "n": 81}], timeline.season_name)     # an older save
    srows = (memstore.fort_dir(KEY) / "seasons.csv").read_text().splitlines()
    assert len(srows) == 2 and srows[1].startswith("4,spring 1,81"), srows


@test("store: a dry run carries on from its own copy in logs, so its memory grows")
def _():
    save = Save()
    m, bank = memstore.load(KEY, save)
    memstore.save(KEY, m, bank, save)                         # the save holds a copy
    for d in range(5):
        m, bank = memstore.load(KEY, save, prefer_logs=True)
        timeline.record(state_at(2000 + d), m, [], PLANNER_CONFIG)
        memstore.save(KEY, m, bank)                           # a dry run: logs only
    m, _ = memstore.load(KEY, save, prefer_logs=True)
    assert len(timeline.days(m)) == 5


@test("store: an unreadable kind in the save is taken from logs, or left untouched (never overwritten)")
def _():
    save = Save()
    m, bank = memstore.load(KEY, save)
    m.last_fired = {"drink": 5}
    bank.total_used = 777
    memstore.save(KEY, m, bank, save)
    good = save.kinds["working"]["text"]
    save.kinds["working"]["text"] = good[:40]              # damaged in the save
    m, bank = memstore.load(KEY, save)
    assert m.last_fired == {"drink": 5} and bank.total_used == 777, "the copy in logs/ was used"
    # damaged in both places: left exactly as it is
    (memstore.fort_dir(KEY) / "memory.json").unlink()
    m, bank = memstore.load(KEY, save)
    assert "working" in m._texts["frozen"] and m.last_fired == {}
    m.last_fired = {"other": 1}
    memstore.save(KEY, m, bank, save)
    assert save.kinds["working"]["text"] == good[:40], "the damaged kind was not written over"
    logged = json.loads((memstore.fort_dir(KEY) / "memory.json").read_text())["kinds"]["working"]
    assert logged == good[:40]


@test("store: a kind from a newer brain is read but never written back as an older version")
def _():
    save = Save()
    save.kinds["atlas"] = {"fort": KEY, "text": json.dumps({"v": 9, "kind": "atlas", "fort": KEY,
                                                               "data": {"atlas": {"survey": {"x": 1}}}})}
    m, bank = memstore.load(KEY, save)
    assert m.atlas == {"survey": {"x": 1}} and "atlas" in m._texts["frozen"]
    m.atlas["survey"]["x"] = 2
    memstore.save(KEY, m, bank, save)
    assert '"v": 9' in save.kinds["atlas"]["text"]


@test("store: when the save can't be read, nothing is written into it that cycle")
def _():
    save = Save()
    m, bank = memstore.load(KEY, save)
    memstore.save(KEY, m, bank, save)
    n = len(save.writes)

    class Broken(Save):
        def load_memory(self):
            raise OSError("file vanished")
    broken = Broken()
    broken.kinds, broken.writes = save.kinds, save.writes
    m, bank = memstore.load(KEY, broken)
    assert m._texts["save_unread"]
    m.last_fired = {"x": 1}
    memstore.save(KEY, m, bank, broken)
    assert len(save.writes) == n


@test("store: an autosave or renamed folder of the same fort keeps the save's memory")
def _():
    save = Save()
    m, bank = memstore.load("Run C#1428", save)
    m.last_fired = {"drink": 5}
    memstore.save("Run C#1428", m, bank, save)
    m, _ = memstore.load("autosave 1#1428", save)
    assert m.last_fired == {"drink": 5}
    m, _ = memstore.load("autosave 1#99", save)
    assert m.last_fired == {}, "another site is another fort"


@test("store: a bridge from before 0.31 gets the one-piece memory it understands")
def _():
    save = Save()
    save.version = {"bridge_version": "0.30.0"}
    m, bank = memstore.load(KEY, save)
    m.last_fired = {"drink": 5}
    sent = []
    save.save_memory = lambda d: sent.append(d) or True
    memstore.save(KEY, m, bank, save)
    assert sent and sent[0]["memory"]["last_fired"] == {"drink": 5} and "kinds" not in sent[0]


@test("store (0.104.0): one kind a call never starves the others, however often a small one changes")
def _():
    save = Save()
    m, bank = memstore.load(KEY, save)
    m.learning = {"prefs": {"x": "y" * 3000}}               # a big kind, changed once
    m.atlas = {"registry": {"a": "z" * 2000}}
    for i in range(8):
        m.quiet_cycles = i                                   # working changes every call
        memstore.save(KEY, m, bank, save, limit=1)
    written = [k for w in save.writes for k in w["kinds"]]
    for k in memstore.KINDS:
        assert k in written, (k, written)


@test("store: optional ticks (None until set) survive a reload")
def _():
    m = Memory()
    m.last_expel_tick, m.maintain_pop = 12345, 80
    m2, _ = memstore.join({k: memstore.decode(k, t) for k, t in memstore.texts_of(m, TokenBank(), KEY).items()})
    assert m2.last_expel_tick == 12345 and m2.maintain_pop == 80


@test("store: the old one-piece copy is dropped once every kind is in the save, even over several cycles")
def _():
    save = Save(legacy={"fort": KEY, "memory": {"last_fired": {"drink": 5}}})
    for k in ("working", "atlas"):                       # an earlier cycle got only some in
        save.kinds[k] = {"fort": KEY, "text": memstore.encode(k, memstore.split(Memory(), TokenBank())[k], KEY)}
    m, bank = memstore.load(KEY, save)
    memstore.save(KEY, m, bank, save)
    assert save.legacy is not None or set(save.kinds) == set(memstore.KINDS)
    m, bank = memstore.load(KEY, save)
    memstore.save(KEY, m, bank, save)
    assert save.legacy is None and set(save.kinds) == set(memstore.KINDS)


# --- the timeline ------------------------------------------------------------------------

@test("timeline: a row a day; an event cycle updates the day and adds up its deaths")
def _():
    m = Memory()
    timeline.record(state_at(5000), m, [], PLANNER_CONFIG)
    timeline.record(state_at(5000), m, [{"kind": "death", "own_civ": True}], PLANNER_CONFIG)
    timeline.record(state_at(5000), m, [{"kind": "death", "own_civ": True}], PLANNER_CONFIG)
    finished = timeline.record(state_at(5001), m, [], PLANNER_CONFIG)
    rows = timeline.days(m)
    assert [r["day"] for r in rows] == [5000, 5001]
    assert rows[0]["deaths"] == 2 and finished["day"] == 5000
    assert rows[0]["pop"] == BASE["dwarves"]["total"] and rows[0]["drink_ratio"] is not None


@test("timeline: seasons and years roll up; days are kept for two seasons")
def _():
    m = Memory()
    start = 336 * 150                        # spring of year 150
    for d in range(start, start + 336 * 2 + 10):
        s = state_at(d)
        s["stocks"]["drink"] = 100 + 20 * (d - start)  # drink rises all along
        timeline.record(s, m, [], PLANNER_CONFIG)
    t = m.timeline
    assert len(t["days"]) == timeline.DAYS_KEPT
    assert [s["season"] for s in t["seasons"]][:2] == [600, 601] and len(t["seasons"]) == 8
    assert [y["year"] for y in t["years"]] == [150, 151]
    assert t["years"][1]["avg"]["drink_pd"] > t["years"][0]["avg"]["drink_pd"]
    assert t["seasons"][0]["n"] == 84
    lines = timeline.trend_lines(m)
    assert any(l.startswith("drink per dwarf") and "rising" in l for l in lines), lines


@test("timeline: an older save rewinds the days, seasons and years after it")
def _():
    m = Memory()
    for d in range(336 * 10, 336 * 10 + 200):
        timeline.record(state_at(d), m, [], PLANNER_CONFIG)
    assert len(m.timeline["seasons"]) == 2
    timeline.record(state_at(336 * 10 + 50), m, [], PLANNER_CONFIG)
    assert timeline.days(m)[-1]["day"] == 336 * 10 + 50 and len(m.timeline["seasons"]) == 0


@test("timeline: averages and shares over a span")
def _():
    m = Memory()
    for i, d in enumerate(range(100, 110)):
        s = state_at(d)
        s["stocks"]["drink"] = BASE["dwarves"]["total"] * (2 if i < 5 else 20)
        timeline.record(s, m, [], PLANNER_CONFIG)
    v, n = timeline.avg(m, "drink_pd", 100, 104)
    assert v == 2.0 and n == 5
    sh, n = timeline.share(m, "drink_ratio", lambda r: r < 1.0, 10, 109)
    assert sh == 0.5 and n == 10
    assert timeline.avg(m, "drink_pd", 200, 210) == (None, 0)


# --- outcomes judged on averages ------------------------------------------------------------

@test("outcomes: a one-day spike no longer decides the verdict; the week's average does")
def _():
    m = Memory()
    pop = BASE["dwarves"]["total"]
    day = 336 * 150
    for d in range(day - 6, day + 1):                  # a week at 4 per dwarf
        s = state_at(d)
        s["stocks"]["drink"] = pop * 4
        timeline.record(s, m, [], PLANNER_CONFIG)
    s = state_at(day)
    s["stocks"]["drink"] = pop * 9                     # the order is placed on a lucky day
    timeline.record(s, m, [], PLANNER_CONFIG)
    e = outcomes.open_entry(s, m, "drink_order", "brew", "planner")
    assert e["before"] < 5 and e["before_days"] == 7, e
    for d in range(day + 1, day + 15):                 # two weeks later: steady at 6 per dwarf
        s = state_at(d)
        s["stocks"]["drink"] = pop * 6
        timeline.record(s, m, [], PLANNER_CONFIG)
    done = outcomes.judge(s, m)
    assert done and done[0]["verdict"] == "helped", done
    assert "averages over 7 and 7 days" in done[0]["why"], done[0]["why"]


@test("outcomes: without a timeline, single days are compared as before")
def _():
    m = Memory()
    s = state_at(336 * 150)
    e = outcomes.open_entry(s, m, "drink_order", "brew", "planner")
    assert e["before_days"] == 1


# --- the atlas -------------------------------------------------------------------------------

def with_entrance(s, x=31, y=140, z=173, sealed=True, doors=1, scanned_tick=0):
    s["entrances"] = {"scanned": True, "scanned_tick": scanned_tick, "entrances": [
        {"id": 1, "kind": "surface", "x": x, "y": y, "z": z, "width": 3, "sealed": sealed,
         "equipment": [{"id": 500, "kind": "door"}] * doors, "door_spots": 0, "closed": False}]}
    return s


@test("atlas: the survey keeps the layers; a cavern found later is news")
def _():
    m = Memory()
    s = with_entrance(state_at(336 * 150))
    s["map"]["layers"][0]["discovered"] = False
    s["map"]["elevation_offset"] = -100
    assert atlas.survey_due(s, m)
    assert atlas.survey(s, m) == []                      # the first look finds nothing "new"
    assert not atlas.survey_due(s, m)
    sv = m.atlas["survey"]
    assert sv["layers"][0]["found"] is None and sv["layers"][1]["found"]
    assert "31,140,173" in m.atlas["entrances"]
    s2 = with_entrance(state_at(336 * 150 + 3))
    s2["map"]["elevation_offset"] = -100
    assert atlas.survey_due(s2, m), "a layer was discovered"
    found = atlas.survey(s2, m)
    assert found == ["the first cavern was found at elevation 27"], found
    assert atlas.survey_due(state_at(336 * 150 + 90), m), "a new season"


@test("atlas: the registry follows the AI's projects; a finished level dropping off the list stays built")
def _():
    m = Memory()
    reg = [{"id": 3, "kind": "bedrooms", "phase": "dig", "z": 150, "elevation": 50,
            "bounds": {"x1": 10, "y1": 10, "x2": 20, "y2": 14, "z": 150},
            "style": {"hall": "pillared", "smooth": 3, "statues": 2, "entry_door": True}},
           {"id": 4, "kind": "dining", "phase": "furnish", "z": 151}]
    s = state_at(1000, registry=reg)
    s["projects"] = {"open": [], "decorating": [], "finished": 0}
    atlas.note_registry(s, m)
    r = m.atlas["registry"]["project:3"]
    assert r["status"] == "digging" and r["variant"] == "pillared, engraved, 2 statues, entry door"
    assert atlas.bounds(r) == {"x1": 10, "y1": 10, "x2": 20, "y2": 14, "z": 150}
    reg[0]["phase"] = "done"
    s = state_at(1001, registry=copy.deepcopy(reg))
    s["projects"] = {"open": [], "decorating": [], "finished": 1}
    out = atlas.note_registry(s, m)
    assert out == ["a bedroom level was finished at elevation 50"], out
    s = state_at(1002, registry=[])                      # the game trimmed its list
    s["projects"] = {"open": [], "decorating": [], "finished": 1}
    atlas.note_registry(s, m)
    assert m.atlas["registry"]["project:3"]["status"] == "built"
    assert m.atlas["registry"]["project:4"]["status"] == "gone", "an unfinished one that vanished"


@test("atlas: a report without a registry loses nothing that is still open")
def _():
    m = Memory()
    m.atlas = {"registry": {"project:7": {"kind": "tavern", "status": "digging"}}}
    s = state_at(1000)
    s.pop("registry", None)
    s["projects"] = {"open": [{"id": 7, "phase": "dig"}], "decorating": [], "finished": 0}
    atlas.note_registry(s, m)
    assert m.atlas["registry"]["project:7"]["status"] == "digging"


@test("atlas: a walled gate goes in the registry and the entrance's history; open again is noticed")
def _():
    from planner import Proposal
    m = Memory()
    s = with_entrance(state_at(1000), sealed=False, doors=0)
    atlas.note_entrances(s, m)
    p = Proposal("fortify", {"type": "fortify_entrance", "entrance_id": 1, "style": "gatehouse"}, "wall it", 5)
    out = atlas.note_actions([(p, {"ok": True})], s, m)
    assert out and "walled to a gatehouse gate" in out[0], out
    g = m.atlas["registry"]["gate:31,140,173"]
    assert g["kind"] == "gate" and g["variant"] == "gatehouse" and g["status"] == "built"
    assert m.atlas["entrances"]["31,140,173"]["gates"][-1]["style"] == "gatehouse"
    # the next cycle still has the scan from before the walling: not news
    assert atlas.note_entrances(with_entrance(state_at(1001), sealed=False, doors=0), m) == []
    assert g["status"] == "built"
    # a scan made after it was built still finds it wide open: someone took it down
    s2 = with_entrance(state_at(1100), sealed=False, doors=0, scanned_tick=1050 * DAY)
    lines = atlas.note_entrances(s2, m)
    assert lines and "stands open again" in lines[0], lines
    assert g["status"] == "open again"


@test("atlas: deaths and threats are placed by the gate they happened at, once per creature")
def _():
    m = Memory()
    s = with_entrance(state_at(1000))
    atlas.note_entrances(s, m)
    s["others_on_map"]["threats"] = [{"id": 77, "pos": {"x": 35, "y": 141, "z": 173}, "name": "goblin"},
                                     {"id": 78, "pos": {"x": 120, "y": 20, "z": 50}, "great_danger": True,
                                      "name": "Nol \"the Abyssal\", Forgotten Beast"}]
    ev = [{"kind": "death", "own_civ": True, "x": 30, "y": 139, "z": 174, "name": "Urist"},
          {"kind": "death", "own_civ": True, "name": "nowhere"},        # no position: not placed
          {"kind": "report", "topic": "flood", "text": "flood!", "x": 5, "y": 5, "z": 10},
          {"kind": "arrival", "name": 'Edzul "Workedrasped", Ghostly Miner', "hostile": True,
           "x": 34, "y": 176, "z": 22},
          {"kind": "arrival", "name": "Urist, Miner", "own_civ": True, "x": 1, "y": 1, "z": 1}]
    atlas.note_events(s, m, ev)
    atlas.note_events(s, m, [])                          # the same threats next cycle: not again
    kinds = [e["k"] for e in m.atlas["events"]]
    assert sorted(kinds) == ["beast_seen", "death", "flood", "ghost", "threat_at_gate"], kinds
    # the fixture's own threats: two named forgotten beasts, and many demons in the underworld
    m2 = Memory()
    atlas.note_events(state_at(1000), m2, [])
    seen = [e["what"] for e in m2.atlas["events"]]
    assert seen == ["Nol the Dreamedwitches the Abyssal", "Omshit the Fat Fears"], seen
    e = m.atlas["entrances"]["31,140,173"]
    assert e["deaths"] == 1 and e["threats"] == 1
    lines = atlas.notable(m)
    assert lines[0].startswith("the surface entrance x31 y140") and "1 death" in lines[0], lines


@test("atlas: events over a year old become clusters, and the story is kept")
def _():
    m = Memory()
    s = with_entrance(state_at(336 * 150))
    atlas.note_entrances(s, m)
    for i in range(3):
        st = state_at(336 * 150 + i)
        st["others_on_map"]["threats"] = []
        atlas.note_events(st, m, [{"kind": "death", "own_civ": True, "x": 31, "y": 141, "z": 173}])
    n = atlas.consolidate(m, (151 * 336 + 10) * DAY)
    assert n == 3 and m.atlas["events"] == []
    c = m.atlas["clusters"][0]
    assert c["k"] == "death" and c["n"] == 3 and c["place"] == "entrance:31,140,173" and c["y0"] == 150
    assert "3 deaths" in atlas.notable(m)[0]


# --- the chronicle ---------------------------------------------------------------------------

@test("chronicle: entries in order, no repeats; small ones summed up after two years")
def _():
    m = Memory()
    s = state_at(336 * 150)
    chronicle.add(m, s, "siege", "a siege hardened the fort")
    chronicle.add(m, s, "siege", "a siege hardened the fort")
    chronicle.add(m, s, "built", "a bedroom level was finished at elevation 50")
    chronicle.add(m, s, "built", "a dining level was finished at elevation 49")
    assert len(m.chronicle["entries"]) == 3
    chronicle.consolidate(m, 153)
    assert [e["k"] for e in m.chronicle["entries"]] == ["siege"]
    assert chronicle.year_lines(m) == ["year 150: 2 levels finished"]
    chronicle.add(m, state_at(336 * 155), "era", "a new era began")
    chronicle.rewind(m, 152)
    assert [e["k"] for e in m.chronicle["entries"]] == ["siege"]


# --- the whole cycle, tiers and the budget ------------------------------------------------------

@test("overseer: a cycle fills the timeline, the atlas and the chronicle, and the review brief uses them")
def _():
    class B:
        version = {"recipes": [], "tools": []}

        def __init__(self):
            self.s = with_entrance(state_at(336 * 150))
            self.s["registry"] = [{"id": 1, "kind": "bedrooms", "phase": "dig", "z": 150}]

        def state(self, include_units=True, tier=None):
            return copy.deepcopy(self.s)

        def events(self):
            return []

        def act(self, a):
            return {"ok": True}

        def status(self):
            return {"halted": False, "decisions": {}}
    overseer.LAST_FULL.clear()
    overseer.JOURNAL = TMP / "decisions.jsonl"
    b = B()
    for d in range(3):
        overseer.one_cycle(b, autopilot=False)
        b.s["date"]["tick"] += DAY
    m = Memory.from_dict(memstore.read_logged(KEY)["memory"])
    assert len(m.timeline["days"]) == 3
    assert m.atlas["survey"]["layers"] and "project:1" in m.atlas["registry"]
    assert m.chronicle["entries"][0]["k"] == "founded"
    assert (memstore.fort_dir(KEY) / "timeline.csv").exists()


@test("overseer: between days a pulse report fills in from the day's full one")
def _():
    overseer.LAST_FULL.clear()

    class B:
        def __init__(self):
            self.calls = []

        def state(self, include_units=True, tier=None):
            self.calls.append(tier)
            s = state_at(5000)
            if tier == "pulse":
                s = {"tier": "pulse", "fort": s["fort"], "date": dict(s["date"], tick=s["date"]["tick"] + 300),
                     "stocks": {"drink": 1}}
            else:
                s["tier"] = "daily"
            return s
    b = B()
    full = overseer.get_state(b, "daily")
    pulse = overseer.get_state(b, "pulse")
    assert b.calls == [None, "pulse"]
    assert pulse["stocks"] == {"drink": 1} and pulse["buildings"] == full["buildings"] and pulse["tier"] == "pulse"
    overseer.LAST_FULL["state"]["date"]["tick"] -= 2 * DAY       # yesterday's: not good enough
    overseer.get_state(b, "pulse")
    assert b.calls[-1] is None, b.calls


@test("overseer: unchanged lines aren't printed again")
def _():
    said = []
    overseer.say = said.append
    overseer.PRINTED.clear()
    overseer.show_changed(KEY, ["  NEEDS YOU: a", "  note: b", "  note: holding back for 4 more days"])
    overseer.show_changed(KEY, ["  NEEDS YOU: a", "  note: c", "  note: holding back for 3 more days"])
    overseer.say = lambda m: None
    assert said == ["  NEEDS YOU: a", "  note: b", "  note: holding back for 4 more days", "  note: c",
                    "  (2 lines as before: needs you, notes, held)", "  (1 earlier line no longer applies)"], said


@test("budget: thirty busy years stay within each kind's size")
def _():
    m = Memory()
    s0 = with_entrance(state_at(336 * 120))
    atlas.note_entrances(s0, m)
    for d in range(336 * 120, 336 * 150):
        s = state_at(d)
        timeline.record(s, m, [{"kind": "death", "own_civ": True}] if d % 30 == 0 else [], PLANNER_CONFIG)
        if d % 5 == 0:
            atlas.note_events(s, m, [{"kind": "death", "own_civ": True, "x": d % 190, "y": (d * 7) % 190,
                                      "z": d % 150}])
        if d % 20 == 0:
            chronicle.add(m, s, "built", f"a level was finished on day {d}")
        if d % 90 == 0:
            chronicle.add(m, s, "siege", f"a siege on day {d}")
        if d % 30 == 0:
            atlas.consolidate(m, d * DAY)
            chronicle.consolidate(m, d // 336)
    for i in range(450):
        m.atlas["registry"][f"project:{i}"] = {"kind": "bedrooms", "variant": "pillared, engraved, 2 statues",
                                               "status": "built", "changed": "28 Obsidian y150", "tick": i,
                                               "elevation": 0, "era": 3, "b": [100, 100, 120, 110, 100]}
    atlas._trim_registry(m.atlas)
    # knowledge at its caps: every calibration window full, the outcome log full
    m.calibration = {"values": {"drink_per_dwarf": 12}, "changed": {}, "log": [
        {"key": "drink_per_dwarf", "name": "drink kept per dwarf", "old": 10, "new": 12, "up": True,
         "why": "drink fell below the urgent line", "date": "1 Granite y150"}] * 12,
        "windows": {
            "drink_per_dwarf": {"start": 0, "days": [{"day": d, "thin": False, "ratio": 0.812} for d in range(14)]},
            "meals_per_dwarf": {"start": 0, "days": [{"day": d, "thin": False, "ratio": 0.812} for d in range(14)]},
            "farm_tiles_per_dwarf": {"start": 0, "days": [{"day": d, "full": True, "thin": False, "plants_pd": 9.25,
                                                          "idle": 31.5} for d in range(28)]},
            "pasture_margin": {"start": 0, "days": [{"day": d, "too_small": False, "empty_share": 0.61,
                                                    "waiting": 0} for d in range(84)]}}}
    entry = {"kind": "drink_order", "what": "brew drink: drink is low " * 4, "by": "planner", "tick": 1,
             "judge_at": 2, "metric": "drink_pd", "expect": "up", "before": 3.2, "before_days": 7,
             "context": {"pop": 120, "sieges": 3, "deaths": 9}, "date": "1 Granite y150"}
    m.outcomes = {"open": [entry] * outcomes.MAX_OPEN,
                  "recent": [dict(entry, verdict="helped", why="drink per dwarf 3.2 to 6.1 (averages over 7 "
                                  "and 7 days)", judged="15 Granite y150")] * outcomes.MAX_RECENT,
                  "tally": {k: {"helped": 4, "none": 1} for k in outcomes.KINDS}}
    sizes = memstore.sizes(m, TokenBank(), KEY)
    over = memstore.over_budget(m, TokenBank(), KEY)
    assert not over, (over, sizes)
    assert len(m.timeline["years"]) == 29 and len(m.atlas["registry"]) == atlas.MAX_REGISTRY


@test("logs: an autosave folder of a fort goes to the fort's own logs folder (one place over a long run)")
def _():
    (memstore.FORTS_DIR / "region3-77").mkdir(parents=True)
    assert memstore.fort_dir("autosave 1#77").name == "region3-77"
    assert memstore.fort_dir("autosave 2#77").name == "region3-77"
    assert memstore.fort_dir("autosave 1#78").name == "autosave_1-78"          # no fort folder yet
    assert memstore.fort_dir("region3#77").name == "region3-77"


@test("logs folders (0.100.2): a fort's renamed copies share one; a test copy has its own; autosaves follow the save loaded last")
def _():
    memstore.ALIASES.clear()
    for f in ("index.json", "session.json"):
        (memstore.FORTS_DIR / f).unlink(missing_ok=True)
    (memstore.FORTS_DIR / "AI_Run_War-hold-239").mkdir(parents=True, exist_ok=True)
    (memstore.FORTS_DIR / "index.json").write_text('{"The Realm of Tests#239": "AI_Run_War-hold-239"}')
    assert memstore.note_world("region2#239", "The Realm of Tests") == "region2-239"   # an old test mapping replaced
    memstore.fort_dir("region2#239").mkdir(parents=True, exist_ok=True)
    assert memstore.note_world("region2 copy#239", "The Realm of Tests") == "region2-239"   # renamed copy: one folder
    assert memstore.fort_dir("region2 copy#239").name == "region2-239"
    assert memstore.note_world("autosave 1#239", "The Realm of Tests") == "region2-239"
    # a test copy of the same fort: its own folder, and its autosaves follow it
    assert memstore.note_world("AI Run Overnight 2#239", "The Realm of Tests") == "AI_Run_Overnight_2-239"
    memstore.fort_dir("AI Run Overnight 2#239").mkdir(parents=True, exist_ok=True)
    assert memstore.fort_dir("AI Run Overnight 2#239").name == "AI_Run_Overnight_2-239"
    assert memstore.note_world("autosave 2#239", "The Realm of Tests") == "AI_Run_Overnight_2-239"
    assert memstore.fort_dir("autosave 2#239").name == "AI_Run_Overnight_2-239"
    memstore.ALIASES.clear()                                     # a restarted overseer still knows
    assert memstore.note_world("autosave 2#239", "The Realm of Tests") == "AI_Run_Overnight_2-239"
    # the real fort loaded again: its autosaves go home
    assert memstore.note_world("region2#239", "The Realm of Tests") == "region2-239"
    assert memstore.note_world("autosave 3#239", "The Realm of Tests") == "region2-239"
    # same site id in another world: its own
    memstore.note_world("region5#239", "Another World")
    assert memstore.fort_dir("region5#239").name == "region5-239"
    memstore.fort_dir("region5#239").mkdir(parents=True, exist_ok=True)
    assert memstore.note_world("autosave 1#239", "Another World") == "region5-239"
    assert memstore.note_world("autosave 1#239", "A Third World") is None and "autosave 1#239" not in memstore.ALIASES
    memstore.ALIASES.clear()


@test("logs: a growing log is rotated past its cap (one old copy); only the newest snapshots stay")
def _():
    import os
    import soak_report
    d = TMP / "caps"
    d.mkdir(exist_ok=True)
    log = d / "soak.jsonl"
    log.write_text('{"time": "2026-01-01T00:00:00"}\n' * 50, encoding="utf-8")
    memstore.cap_file(log, 10_000)
    assert log.exists()                                       # under the cap: left alone
    memstore.cap_file(log, 100)
    assert not log.exists() and (d / "soak.old.jsonl").exists()
    log.write_text('{"time": "2026-01-02T00:00:00"}\n', encoding="utf-8")
    from datetime import datetime
    rows = soak_report.soak_rows(datetime(2025, 1, 1), log)
    assert len(rows) == 51 and rows[-1]["time"].startswith("2026-01-02"), len(rows)   # both read
    for i in range(5):
        f = d / f"state-{i}.json"
        f.write_text("{}", encoding="utf-8")
        os.utime(f, (1000 + i, 1000 + i))
    memstore.keep_newest(d, "state-*.json", 2)
    assert sorted(p.name for p in d.glob("state-*.json")) == ["state-3.json", "state-4.json"]

@test("bridge memory files (0.104.44): long texts travel as files, both ways")
def _():
    from bridge import Bridge
    d = Path(tempfile.mkdtemp())
    class FakeDF:
        def __init__(self): self.calls = []
        def run_json(self, *args, timeout=None):
            self.calls.append((args, timeout))
            if args[1] == "memory":
                (d / "memory-from-save.working.txt").write_text('{"x":1}', encoding="ascii")
                (d / "memory-from-save.json").write_text(json.dumps(
                    {"kinds": {"working": {"fort": "f", "file": str(d / "memory-from-save.working.txt")},
                               "atlas": {"fort": "f", "text": "small"}}}), encoding="utf-8")
                return {"ok": True, "present": True, "file": str(d / "memory-from-save.json")}
            return {"ok": True}
    b = Bridge(FakeDF())
    b.out_dir = d
    data = b.load_memory()
    assert data["kinds"]["working"]["text"] == '{"x":1}' and data["kinds"]["atlas"]["text"] == "small", data
    assert b.df.calls[0][1] == 60
    b.act = lambda a: {"ok": True}
    assert b.save_memory({"fort": "f", "kinds": {"working": "W" * 50, "atlas": "A"}})
    sent = json.loads((d / "memory-to-save.json").read_text(encoding="utf-8"))
    assert "kinds" not in sent and sent["kinds_files"]["working"] == "memory-to-save.working.txt", sent
    assert (d / "memory-to-save.working.txt").read_text() == "W" * 50

@test("(0.105.0) a scenario copy marked with a run id logs apart from the real fort, its autosaves too")
def _():
    import scenario_mark
    memstore.ALIASES.clear()
    for f in ("index.json", "session.json"):
        (memstore.FORTS_DIR / f).unlink(missing_ok=True)
    memstore.note_world("region2#239", "The Realm")
    memstore.fort_dir("region2#239").mkdir(parents=True, exist_ok=True)
    fort = {"save_dir": "region2", "site_id": 239, "world": "The Realm", "run_id": "202611011200-ab12"}
    key = overseer.fort_key({"fort": fort})
    assert key == "region2@202611011200-ab12#239", key
    assert memstore.note_world(key, "The Realm") == "run-202611011200-ab12-239"
    auto = overseer.fort_key({"fort": dict(fort, save_dir="autosave 1")})
    assert memstore.fort_dir(auto).name == "run-202611011200-ab12-239"           # its autosave: the same folder
    assert memstore.note_world("autosave 2#239", "The Realm") == "region2-239"    # the real fort's untouched
    assert memstore.same_site(key, "region2#239")                                  # the save's memory still reads
    # prepare's pending id is written into the save once
    scenario_mark.PENDING = TMP / "scenario-pending.json"
    rid = scenario_mark.new_run("AI Run X")

    class B:
        acted = []

        def act(self, a):
            self.acted.append(a)
            return {"ok": True, "run_id": a["run_id"]}
    b = B()
    st = {"fort": {"save_dir": "AI Run X", "site_id": 239}}
    assert scenario_mark.mark(b, st, lambda *_: None) and st["fort"]["run_id"] == rid
    assert not scenario_mark.mark(b, st, lambda *_: None) and len(b.acted) == 1     # marked: never again
    assert not scenario_mark.mark(b, {"fort": {"save_dir": "region2", "site_id": 239}}, lambda *_: None)
    memstore.ALIASES.clear()


for name, ok, msg in RESULTS:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        print("    " + msg.replace("\n", "\n    "))
passed = sum(1 for _, ok, _ in RESULTS if ok)
print(f"\n{passed} passed, {len(RESULTS) - passed} failed")
sys.exit(0 if passed == len(RESULTS) else 1)

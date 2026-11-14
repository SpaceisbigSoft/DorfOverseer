"""Tests for the "seen in game" ledger (brain/seen.py, 0.105.46 I1): the
versions read from the code's tags, the overseer's section tally, the
journals and the report read per folder, docs/watch-in-game.md's lines
matched, the health check's "seen" part and the summary across folders.

    python tests/test_seen.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
TMP = Path(tempfile.mkdtemp())
os.environ.setdefault("DFAI_LOG_DIR", str(TMP / "logs"))
sys.path.insert(0, str(ROOT / "brain"))

import seen  # noqa: E402

NOW = datetime.now().replace(microsecond=0)


def dec(typ, ok=True, error=None, when=None, dry=False, waiting=False, result=True, **extra):
    a = {"type": typ, **extra}
    if dry:
        a["dry_run"] = True
    r = None
    if result:
        r = {"ok": ok}
        if error:
            r["error"] = error
        if waiting:
            r["waiting"] = True
    return {"time": (when or NOW - timedelta(hours=2)).isoformat(timespec="seconds"), "kind": "decision",
            "fort": "region4#1", "rule": "r", "reason": "", "action": a,
            "mode": "autopilot" if result else "dry-run", "result": r}


def make_folder(name: str, journal: list[dict], state: dict | None, tally: dict | None = None,
                seasons: dict | None = None) -> Path:
    f = TMP / name
    fort = f / "logs" / "forts" / "region4-1"
    fort.mkdir(parents=True, exist_ok=True)
    with (fort / "journal.jsonl").open("w", encoding="utf-8") as fh:
        for e in journal:
            fh.write(json.dumps(e) + "\n")
    if state is not None:
        game = f / "game"
        (game / "dfhack-config" / "ai-overseer").mkdir(parents=True, exist_ok=True)
        (game / "dfhack-config" / "ai-overseer" / "state.json").write_text(json.dumps(state), encoding="utf-8")
        (f / "logs" / "last-fort.json").write_text(json.dumps({"df_path": str(game), "save_dir": "region4"}),
                                                   encoding="utf-8")
    if tally is not None:
        (fort / seen.TALLY_NAME).write_text(json.dumps(tally), encoding="utf-8")
    for nm, body in (seasons or {}).items():
        (fort / "states").mkdir(exist_ok=True)
        (fort / "states" / nm).write_text(json.dumps(body), encoding="utf-8")
    return f


WATCH = """# Watch in game

## 0.105.45 (14 Nov): hunting

- **All, state.json**: `hunt` with `targets`; no `error`.
- **A `hunt_send` in the journal**: the squads' kill order in the squad screen.
- **Journal**: `hunt_send` and `hunt_recall` lines.
- **Kill zones**: a `build_killzone` journal line.
- **Lures**: `lures` (each pulse) with `lures.candidates`.
- **The report**: `others_on_map.threats` rows with `facts`.
- **Army tab**: the switch Kill zones at the gates.

## 0.105.30 (8 Nov): too old

- `place_hall` in the journal.

**0.105.45 (H5): the shelter**
- The journal shows `shelter_pick` with `levels`.
"""


@test("version tags: on the line, a group's header, the hand table for item tags")
def _():
    assert seen.tag_version("-- (0.105.45) hunting") == "0.105.45"
    assert seen.tag_version("-- (0.105.40b fix) release_only") == "0.105.40"
    assert seen.tag_version("-- (0.105.41, item 4) provisions") == "0.105.41"
    assert seen.tag_version("-- (item5) siege works") == "0.105.41"
    assert seen.tag_version("-- (item 12) the artifacts") == "0.105.41"
    assert seen.tag_version("-- (D0) the Design track") == "0.105.37"
    assert seen.tag_version("-- (13c) a feeder survey") is None
    assert seen.tag_version("-- no tag at all") is None
    lua = """ACTIONS = {
    old_one = act_old_one,
    tagged = act_tagged,        -- (0.105.44)
    -- (0.105.45) a group of two functions
    -- that goes on over two comment lines
    fn_a = function(a)
        return x
    end,
    fn_b = function(a)
        return y
    end,
    single_after = act_single_after,
    -- (0.105.41) two plain ones
    plain_a = act_plain_a,
    plain_b = act_plain_b,      -- (0.105.32)
    plain_c = act_plain_c,
    x_one = act_x, y_two = act_y,   -- (0.105.40)

    after_blank = act_after_blank,
}
"""
    t = seen.parse_table(lua.splitlines(), 0)
    assert t["old_one"] is None and t["tagged"] == "0.105.44", t
    assert t["fn_a"] == "0.105.45" and t["fn_b"] == "0.105.45", t
    assert t["single_after"] is None, t                     # a one-liner after a group of functions
    assert t["plain_a"] == "0.105.41" and t["plain_b"] == "0.105.32" and t["plain_c"] is None, t
    assert t["x_one"] == "0.105.40" and t["y_two"] == "0.105.40", t
    assert t["after_blank"] is None, t


@test("the registry from the real code: the 0.105.32+ actions, sections and switches dated right")
def _():
    reg = seen.registry(ROOT)
    a, s, w = reg["action"], reg["section"], reg["switch"]
    assert a["hunt_send"] == "0.105.45" and a["hunt_recall"] == "0.105.45", (a["hunt_send"], a["hunt_recall"])
    assert a["lure_shut"] == "0.105.45" and a["build_killzone"] == "0.105.45" and a["stuck_reset"] == "0.105.45"
    assert a["killer_cell"] == "0.105.44" and a["release_prisoners"] == "0.105.44" and a["weather_burrow"] == "0.105.44"
    assert a["unstick_gate"] == "0.105.32" and a["dig_way_in"] == "0.105.32"
    assert a["fortify_post"] == "0.105.41" and a["polish_room"] == "0.105.41"
    assert a["add_haulers"] == "0.105.40" and a["relieve_haulers"] == "0.105.40"
    assert a["tool"] is None and a["work_order"] is None, (a["tool"], a["work_order"])
    assert s["killzones"] == "0.105.45" and s["shelter_plan"] == "0.105.45" and s["killers"] == "0.105.44"
    assert s["weather"] == "0.105.40" and s["necro"] == "0.105.41" and s["perf"] == "0.105.39"
    assert s["paused"] is None and s["orders"] is None and s["deep"] is None, (s["paused"], s["orders"])
    assert w["hunt"] == "0.105.45" and w["lure_beasts"] == "0.105.45" and w["killzones"] == "0.105.45"
    assert w["siege_engines"] == "0.105.41" and w["wildlife_hunts"] == "0.105.41"
    assert w["squads_shelter"] is None and w["mode"] is None
    new = seen.new_since(reg, "0.105.45")
    assert {n for _, n in new["action"]} >= {"hunt_send", "build_lure", "shelter_pick", "squad_station"}
    assert all(seen.vtuple(v) >= (0, 105, 45) for v, _ in new["action"] + new["section"] + new["switch"])
    assert seen.since_date("0.105.45") == datetime(2026, 11, 14)
    assert seen.since_date("2026-11-13") == datetime(2026, 11, 13)
    assert seen.since_date("0.105.99") == datetime(2026, 11, 14)        # past the table: its newest


@test("the overseer's tally: full reports counted per section, errors with their text, pulses left out")
def _():
    folder = TMP / "tally"
    t0 = 1_000_000.0
    seen.note_report({"tier": "daily", "bridge_version": "0.105.45", "hunt": {"targets": []},
                      "killzones": {"error": "attempt to index a nil value"}, "_timing": {}}, folder, now=t0)
    data = json.loads((folder / seen.TALLY_NAME).read_text())
    h, k = data["sections"]["hunt"], data["sections"]["killzones"]
    assert h["ok"] == 1 and h["first_ok_bridge"] == "0.105.45" and "_timing" not in data["sections"], data
    assert k["error"] == 1 and k["error_text"] == "attempt to index a nil value" and k["first_error"], k
    seen.note_report({"tier": "pulse", "hunt": {"error": "x"}}, folder, now=t0 + 5)       # a pulse: not counted
    seen.note_report({"tier": "daily", "hunt": {"targets": [1]}, "killzones": {"entrances": []}}, folder, now=t0 + 10)
    # killzones' first ok: written at once
    assert json.loads((folder / seen.TALLY_NAME).read_text())["sections"]["hunt"]["ok"] == 2
    seen.note_report({"tier": "daily", "hunt": {"targets": [1]}}, folder, now=t0 + 20)
    # nothing new: kept in memory, the file not rewritten yet
    assert json.loads((folder / seen.TALLY_NAME).read_text())["sections"]["hunt"]["ok"] == 2
    seen.note_report({"tier": "daily", "hunt": {"targets": [1]}}, folder, now=t0 + seen.TALLY_WRITE_S + 20)
    data = json.loads((folder / seen.TALLY_NAME).read_text())
    assert data["sections"]["hunt"]["ok"] == 4 and data["sections"]["hunt"].get("error", 0) == 0, data
    assert data["sections"]["killzones"]["ok"] == 1 and data["sections"]["killzones"]["error"] == 1, data
    assert data["reports"] == 4
    seen.note_report(None, folder)               # never raises
    seen.note_report({"tier": "daily"}, None)


def fixture_one():
    j = [dec("hunt_send", target_id=5, squad_ids=[1]),
         dec("hunt_send", when=NOW - timedelta(hours=1)),
         dec("build_killzone", ok=False, error="no 1-wide stretch inside entrance 3"),
         dec("build_killzone", ok=False, error="no 1-wide stretch inside entrance 4", when=NOW - timedelta(hours=1)),
         dec("stuck_reset", ok=None, error="no reply from the game (timeout)"),
         dec("lure_open", dry=True),
         dec("shelter_pick", result=False),                       # a dry-run cycle: proposed only
         dec("cistern_step", ok=False, waiting=True, error="digging"),
         dec("lure_shut", when=datetime(2026, 11, 1)),            # before the date: left out
         {"kind": "event", "time": NOW.isoformat(), "event": {"kind": "report"}}]
    state = {"tier": "daily", "bridge_version": "0.105.45",
             "hunt": {"targets": [], "squads": []},
             "killzones": {"error": "ai-killzone.lua:120: attempt to index a nil value"},
             "others_on_map": {"threats": [{"id": 1, "facts": 1}]},
             "settings": {"hunt": "ai", "killzones": True, "lure_beasts": False}}
    tally = {"sections": {"killzones": {"ok": 3, "error": 2, "first_ok": "2026-11-14T13:00:00",
                                        "last_error": (NOW - timedelta(hours=3)).isoformat(timespec="seconds"),
                                        "error_text": "ai-killzone.lua:120: attempt to index a nil value"},
                          "stuck": {"ok": 0, "error": 4,
                                    "last_error": (NOW - timedelta(hours=30)).isoformat(timespec="seconds"),
                                    "error_text": "ai-stuck.lua:9: bad"}}}
    return make_folder("A", j, state, tally)


@test("one folder's ledger: sections present, in error or not met; actions done, refused, failed, dry only")
def _():
    f = fixture_one()
    (TMP / "watch.md").write_text(WATCH, encoding="utf-8")
    L = seen.ledger(f, since_version="0.105.32", code_root=ROOT, watch=TMP / "watch.md", now=NOW)
    secs = {s["name"]: s for s in L["sections"]}
    assert secs["hunt"]["status"] == "seen", secs["hunt"]
    assert secs["killzones"]["status"] == "error" and secs["killzones"]["errors"] == 2, secs["killzones"]
    assert secs["stuck"]["status"] == "error" and "bad" in secs["stuck"]["detail"], secs["stuck"]   # only errors so far
    assert secs["lures"]["status"] == "not yet met", secs["lures"]
    acts = {a["name"]: a for a in L["actions"]}
    hs = acts["hunt_send"]
    assert hs["status"] == "seen" and hs["ok"] == 2 and hs["first_ok"] == (NOW - timedelta(hours=2)).isoformat(), hs
    bk = acts["build_killzone"]
    assert bk["status"] == "refused" and bk["refused"] == 2 and bk["refused_why"].endswith("entrance 3"), bk
    assert acts["stuck_reset"]["status"] == "failed" and "no reply" in acts["stuck_reset"]["failed_why"]
    assert acts["lure_open"]["status"] == "not yet met" and acts["lure_open"]["dry"] == 1
    assert acts["shelter_pick"]["proposed"] == 1 and acts["shelter_pick"]["status"] == "not yet met"
    assert acts["lure_shut"]["status"] == "not yet met", acts["lure_shut"]       # 1 Nov: before 0.105.32 came
    assert seen.short_status(acts["lure_open"]) == "not yet met (dry run ok x1)"
    sw = {s["name"]: s for s in L["switches"]}
    assert sw["hunt"]["value"] == "ai" and sw["lure_beasts"]["value"] is False and not sw["traffic"]["known"]
    assert L["errors_now"] == {"killzones": "ai-killzone.lua:120: attempt to index a nil value"}
    c = L["counts"]
    assert c["errors"] == 2 and c["seen"] >= 2 and c["refused"] >= 2, c
    assert c["seen"] + c["refused"] + c["not yet met"] + c["errors"] == len(L["sections"]) + len(L["actions"])
    text = (f / "logs" / seen.LEDGER_NAME).read_text(encoding="utf-8")
    assert text.startswith("# Seen in game: A") and "| 0.105.45 | `hunt_send` | seen | 2 |" in text, text[:2000]
    assert "refused (no 1-wide stretch inside entrance 3)" in text
    assert "## Sections in error in the last report" in text and "`killzones`" in text


@test("watch lines: ticked only on full evidence; how it looks stays 'needs eyes'; old blocks left out")
def _():
    L = seen.ledger(TMP / "A", since_version="0.105.32", code_root=ROOT, watch=TMP / "watch.md", now=NOW, write=False)
    titles = [b["title"] for b in L["watch"]]
    assert not any("too old" in t for t in titles) and any(t.startswith("0.105.45 (H5)") for t in titles), titles
    rows = {r["text"][:30]: r for b in L["watch"] for r in b["lines"]}
    by = lambda start: next(r for k, r in rows.items() if k.startswith(start))   # noqa: E731
    assert by("**All, state.json**: `hunt`")["status"] == "seen"
    assert by("**A `hunt_send` in the journal")["status"] == "needs eyes"        # the squad screen: eyes
    assert any("hunt_send seen" in e for e in by("**A `hunt_send` in the journal")["evidence"])
    assert by("**Journal**: `hunt_send` and")["status"] == "partly seen"         # hunt_recall not yet
    k = by("**Kill zones**")
    assert k["status"] == "refused" and "entrance 3" in k["evidence"][0], k
    assert by("**Lures**")["status"] == "not met"
    assert by("**The report**")["status"] == "seen"                              # others_on_map.threats there
    assert by("**Army tab**")["status"] == "needs eyes" and not by("**Army tab**")["evidence"]
    assert by("The journal shows `shelter_")["status"] == "not met"
    text = seen.render(L)
    assert "- [x] **seen**: **All, state.json**: `hunt`" in text, text
    assert "- [ ] **needs eyes**: **A `hunt_send`" in text
    # a field the report doesn't carry: not met, though the section is there
    st = {"hunt": {"targets": []}}
    r = seen.match_line("`hunt.history` rows", seen.registry(ROOT), {}, st, {})
    assert r["status"] == "not met" and "field not in the report" in r["evidence"][0], r
    # the line's other names looked for in the section it names: one missing, not ticked
    st = {"others_on_map": {"threats": [{"id": 1, "facts": 1}]}}
    reg = seen.registry(ROOT)
    r = seen.match_line("each `others_on_map.threats` row has `facts` and `attacks`; no `error`", reg, {}, st, {})
    assert r["status"] == "partly seen" and "not in the report: attacks" in r["evidence"][-1], r
    st["others_on_map"]["threats"][0]["attacks"] = {"count": 2}
    assert seen.match_line("each `others_on_map.threats` row has `facts` and `attacks`", reg, {}, st, {})["status"] == "seen"
    # a "never" line: the journal can't show what didn't happen
    acts = {"hunt_send": {"ok": 3}}
    r = seen.match_line("**Never**: a `hunt_send` during a siege", reg, acts, {}, {})
    assert r["status"] == "needs eyes" and r["evidence"] == ["hunt_send seen (ok 3)"], r


@test("a pulse on disk: the newest season copy fills the sections; season copies in error counted")
def _():
    pulse = {"tier": "pulse", "bridge_version": "0.105.45", "hunt": {"targets": []}}
    seasons = {"256-spring.json": {"_run": "x", "tier": "daily", "lures": {"error": "boom"}, "stuck": {"list": []}},
               "256-summer.json": {"_run": "x", "tier": "daily", "lures": {"beasts": []}, "stuck": {"list": []}}}
    f = make_folder("B", [], pulse, seasons=seasons)
    os.utime(f / "logs/forts/region4-1/states/256-spring.json", (time.time() - 100, time.time() - 100))
    L = seen.ledger(f, since_version="0.105.45", code_root=ROOT, watch=TMP / "none.md", now=NOW, write=False)
    secs = {s["name"]: s for s in L["sections"]}
    assert secs["lures"]["status"] == "seen" and secs["lures"]["season_errors"] == 1, secs["lures"]
    assert secs["stuck"]["status"] == "seen" and secs["hunt"]["status"] == "seen"
    assert secs["killzones"]["status"] == "not yet met"
    assert "season copy 256-summer.json" in L["report"], L["report"]
    # no report at all: everything not yet met, said so
    g = make_folder("C", [], None)
    L = seen.ledger(g, since_version="0.105.45", code_root=ROOT, watch=TMP / "none.md", now=NOW, write=False)
    assert L["report"] == "no report found" and L["counts"]["seen"] == 0 and L["counts"]["errors"] == 0, L["counts"]
    # an older bridge in the game: the reason given
    h = make_folder("D", [], {"tier": "daily", "bridge_version": "0.105.43"})
    L = seen.ledger(h, since_version="0.105.45", code_root=ROOT, watch=TMP / "none.md", now=NOW, write=False)
    assert all("bridge 0.105.43" in s["detail"] for s in L["sections"]), L["sections"]


@test("state.json found through config.json state_path and dfhack_config too")
def _():
    f = TMP / "cfg"
    (f / "logs").mkdir(parents=True, exist_ok=True)
    sp = TMP / "elsewhere" / "state.json"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text("{}", encoding="utf-8")
    (f / "config.json").write_text(json.dumps({"state_path": str(sp)}), encoding="utf-8")
    assert seen.state_path(f) == sp
    dc = TMP / "dfc"
    (dc / "ai-overseer").mkdir(parents=True, exist_ok=True)
    (dc / "ai-overseer" / "state.json").write_text("{}", encoding="utf-8")
    (f / "config.json").write_text(json.dumps({"dfhack_config": str(dc), "df_launch": "steam://run/975370"}),
                                   encoding="utf-8")
    assert seen.state_path(f) == dc / "ai-overseer" / "state.json"
    (f / "config.json").write_text("{}", encoding="utf-8")
    assert seen.state_path(f) is None


@test("the health check's part: counts, and a flag for a section in error now or lately")
def _():
    L = seen.ledger(TMP / "A", since_version="0.105.32", code_root=ROOT, watch=TMP / "watch.md", now=NOW, write=False)
    flags, plain = seen.health_part(L, 24, NOW)
    assert plain[0].startswith("seen since 0.105.32: ") and "section errors" in plain[0], plain
    assert any("watch-in-game lines" in p for p in plain), plain
    assert any("'killzones' returns an error" in f for f in flags), flags
    assert not any("'stuck'" in f for f in flags), flags            # its last error 14 Nov: outside the day
    flags, _ = seen.health_part(L, 48, NOW)
    assert any("'stuck' (0.105.45) returned an error 4 time(s)" in f for f in flags), flags


@test("health_check.check runs the seen part and writes logs/seen-ledger.md (the keeper's daily check)")
def _():
    import health_check as hc
    f = TMP / "A"
    logs = f / "logs"
    old = (hc.LOG_DIR, hc.REPORT, hc.FLAGS, hc.STANDING)
    hc.LOG_DIR, hc.REPORT, hc.FLAGS, hc.STANDING = logs, logs / "health-check.txt", logs / "health-check.json", \
        logs / "standing.json"
    (logs / seen.LEDGER_NAME).unlink(missing_ok=True)
    try:
        flags, page = hc.check(24, selftest=False, now=datetime.now())
    finally:
        hc.LOG_DIR, hc.REPORT, hc.FLAGS, hc.STANDING = old
    assert "seen:" in page, page
    i = page.index("seen:")
    assert page[i + 1].startswith("  seen since 0.105.32: "), page[i:i + 3]
    assert any("'killzones' returns an error" in x for x in flags), flags
    assert (logs / seen.LEDGER_NAME).exists()


@test("several folders: each its own page, and a summary across them; the command line")
def _():
    out = TMP / "summary.md"
    rc = seen.main(["--folders", str(TMP / "A"), str(TMP / "B"), "--since", "0.105.45", "--out", str(out)])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "| folder | seen |" in text and "| A |" in text and "| B |" in text, text
    assert "| 0.105.45 | `hunt_send` | seen | - | seen |" in text, text
    assert "| 0.105.45 | `killzones` | ERROR | - | ERROR |" in text, text
    assert "## Not seen in any folder" in text and "`lure_shut` (0.105.45)" in text
    assert (TMP / "B" / "logs" / seen.LEDGER_NAME).exists()
    # a date for the journals, the version picking what's new stays the default
    day = (NOW - timedelta(hours=3)).isoformat(timespec="minutes")
    L = seen.ledger(TMP / "A", since=day, code_root=ROOT, watch=TMP / "watch.md", now=NOW, write=False)
    assert L["since_version"] == "0.105.32" and L["since"] == day
    assert {a["name"]: a for a in L["actions"]}["hunt_send"]["ok"] == 2


@test("the default folders: DF-AI* beside this one, else this one")
def _():
    base = TMP / "pc"
    for n in ("DF-AI", "DF-AI-B", "DF-AI-C", "other"):
        (base / n / "logs").mkdir(parents=True, exist_ok=True)
    got = seen.default_folders(base / "DF-AI")
    assert [p.name for p in got] == ["DF-AI", "DF-AI-B", "DF-AI-C"], got
    assert [seen._label(p) for p in got] == ["A", "B", "C"]
    lone = TMP / "lone" / "work"
    lone.mkdir(parents=True, exist_ok=True)
    assert seen.default_folders(lone) == [lone]


@test("the overseer tallies each report before normalize() swaps its errors for defaults")
def _():
    src = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    i = src.index("seen_ledger.note_report(state, memstore.fort_dir(key))")
    j = src.index("normalize(state)      # (13c) once, in place")
    assert i < j and "import seen as seen_ledger" in src


if __name__ == "__main__":
    finish()

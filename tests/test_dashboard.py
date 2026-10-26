"""Tests for brain/dashboard_data.py (0.104.85): the fort dashboard's data files.

    python tests/test_dashboard.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
import dashboard_data as D  # noqa: E402

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


REPORT = """# Report: Enxah

## 1 Opal y77 (winter), written Sun

- **The fort:** 88 dwarves, 15.62 drinks per dwarf, wealth 842,556, 64 FPS
- **Phase:** decline since 2 Malachite y76
- **Ready for a siege?** NOT YET: soldiers armed 17
- **This season the AI works to:** arm the soldiers; train the soldiers
- **Lately:**
  - 22 Galena y77: a tomb level was finished
  - 2 Limestone y77: the fort set its heart on a garden
- **The game keeps refusing:** pair_chairs (12 times in a row)
- **Needs you:**
  - the hospital keeps less than it should
"""


@test("dashboard data: weekly days, seasons from the timeline, the latest report's parts, the stress levels")
def _():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "fort"
        f.mkdir()
        lines = ["day,pop,drink_pd,meals_pd,plants_pd,unhappy_pct,happy_pct,idle_pct,needs_care,hungry,unpastured,"
                 "free_beds,wealth,deaths,threats,drink_ratio,meals_ratio,report_ms"]
        for d in range(77 * 336, 77 * 336 + 100):
            lines.append(f"{d},88,15,60,8,{30 + d % 3},10,20,1,0,0,5,{800000 + d},{1 if d % 50 == 0 else 0},0,1,1,100")
        (f / "timeline.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (f / "report.md").write_text(REPORT, encoding="utf-8")
        state = {"date": {"day": 1, "month": "Opal", "year": 77},
                 "dwarves": {"stress": {"miserable": 8, "fine": 20}},
                 "military": {"gear": {"soldiers": 23, "on_duty": 19, "armed": 17}},
                 "society": {"animals": {"in_training": 7, "war_trained": 0}, "recreation": {"members": 12}},
                 "stocks": {"cheese": 13}, "supplies": {"nest_boxes": 2}, "needs": {"needs": {"BeWithFriends": {"badly": 40}}}}
        out = Path(tmp) / "out"
        counts = D.build(f, state, out)
        assert counts == {"days": 16, "seasons": 2, "now": 1, "stress": 7, "notes": 6}, counts
        days = json.loads((out / "days.json").read_text())
        assert days[0]["date"] == "1 Granite y77" and days[-1]["day"] == 77 * 336 + 99
        seasons = json.loads((out / "seasons.json").read_text())
        assert [s["season"] for s in seasons] == ["spring y77", "summer y77"] and seasons[0]["days"] == 84
        assert seasons[0]["deaths"] == 2, seasons[0]
        now = json.loads((out / "now.json").read_text())[0]
        assert now["phase"].startswith("decline") and now["fps"] == 64 and now["armed"] == 17 and now["want_friends"] == 40
        notes = json.loads((out / "notes.json").read_text())
        kinds = [n["kind"] for n in notes]
        assert kinds == ["needs you", "lately", "lately", "works to", "works to", "refusing"], kinds
        assert notes[1]["text"].startswith("2 Limestone"), notes[1]                     # newest first
        stress = json.loads((out / "stress.json").read_text())
        assert stress[0] == {"level": "miserable", "order": 0, "dwarves": 8}


@test("seasons.csv (0.104.86): written when a newer season finishes, also once memory's 24 are full")
def _():
    import overseer
    class M:
        timeline = {"seasons": [{"season": s} for s in range(260, 284)]}
    assert overseer._newest_season(M) == 283
    M.timeline = {"seasons": [{"season": s} for s in range(261, 285)]}    # still 24, one newer
    assert overseer._newest_season(M) == 284
    M.timeline = {}
    assert overseer._newest_season(M) is None


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

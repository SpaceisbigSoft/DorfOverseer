"""Report sections missing or failed in the game, with the AI strategist on:
the cycle runs, the review is asked for (or skipped with a reason when the AI
settings themselves can't be read), and the strategist is told which sections
are missing. (A missing date or fort is the overseer's own skip, tested in
test_overseer.py and test_planner.py.)

    python tests/test_strategist_sections.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import overseer  # noqa: E402
from digest import REQUIRED, SECTION_DEFAULTS  # noqa: E402
import test_overseer as T  # noqa: E402   (its fakes and its reset; its tests don't run here)

test = T.test
# every section: the ones the bridge reports (dicts in the fixture fort) and
# the ones normalize() knows (newer than the fixture: missing there already)
SECTIONS = sorted((set(SECTION_DEFAULTS) | {k for k, v in T.BASE.items() if isinstance(v, dict)
                                             and not k.startswith("_")}) - {"date", "fort"})


def cycle(state):
    c, b = T.FakeClaude(), T.FakeBridge(state=state)
    overseer.one_cycle(b, autopilot=True, backend=c)
    return c, b


def broken(section, how):
    st = copy.deepcopy(T.BASE)
    if how == "missing":
        st.pop(section, None)
    else:
        st[section] = {"error": "lua: attempt to index a nil value"}
    return st


for how in ("missing", "failed"):
    @test(f"strategist on, each report section {how} in turn: the cycle runs and the review is asked, told what's missing")
    def _(how=how):
        bad = []
        for sec in SECTIONS:
            T._before()
            try:
                c, b = cycle(broken(sec, how))
            except Exception as e:  # noqa: BLE001
                bad.append(f"{sec}: the cycle crashed ({type(e).__name__}: {e})")
                continue
            if sec == "settings":
                if c.calls or not any("AI review skipped" in s and "settings" in s for s in T.SAID):
                    bad.append("settings: the review should be skipped, and say why")
                continue
            if len(c.calls) != 1:
                bad.append(f"{sec}: {len(c.calls)} reviews")
                continue
            told = [x for x in c.calls[0][1].splitlines() if x.startswith("MISSING_SECTIONS ")]
            # (normalize() knows these; a section it doesn't, e.g. map, only has to do no harm)
            if (sec in SECTION_DEFAULTS and (how == "failed" or sec in REQUIRED)
                    and not (told and sec in told[0].split())):
                bad.append(f"{sec}: the strategist isn't told it is missing ({told})")
        assert not bad, "\n".join(bad)


if __name__ == "__main__":
    finish()

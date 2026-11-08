"""The shared test runner for tests/test_*.py.

    from harness import test, finish        # at the top of a test file
    test = make_test(before=reset)          # or: a reset before every test

    @test("what it checks")
    def _():
        assert ...

    if __name__ == "__main__":
        finish()

@test runs the function at once and keeps the result; finish() prints one
line a test, the totals, and exits 1 if any failed. Each file stays runnable
alone (python tests/test_x.py) and through tests/run_all.py.

Run alone, a file gets its own temporary logs folder (DFAI_LOG_DIR), as
run_all gives each file, so no test writes into the real DF-AI/logs. Import
this module before the brain's modules: several read DFAI_LOG_DIR on import.
"""

from __future__ import annotations

import atexit
import os
import re
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS: list[tuple[str, bool, str]] = []
TIMES: list[tuple[float, str]] = []      # (seconds, name): DFAI_TEST_TIMES=1 prints the slowest

# DFAI_TEST_SHARD="i/n": run only every n-th test from the i-th (run_all splits
# the slowest files over several processes this way)
_SHARD = tuple(int(x) for x in os.environ.get("DFAI_TEST_SHARD", "0/1").split("/"))
_SEEN = [0]

if not os.environ.get("DFAI_LOG_DIR"):
    _TMP = tempfile.mkdtemp(prefix="dfai-test-logs-")
    os.environ["DFAI_LOG_DIR"] = _TMP
    atexit.register(shutil.rmtree, _TMP, True)


def run(name, fn, before=None) -> None:
    """Run one test now and keep its result. A failed assert keeps its
    message; any other error keeps the traceback."""
    t0 = time.perf_counter()
    try:
        if before is not None:
            before()
        fn()
        RESULTS.append((name, True, ""))
    except AssertionError as e:
        msg = str(e) or traceback.format_exc(limit=-1).strip()
        RESULTS.append((name, False, msg))
    except Exception as e:  # noqa: BLE001
        RESULTS.append((name, False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"))
    TIMES.append((time.perf_counter() - t0, name))


def make_test(before=None):
    """A @test decorator that calls before() ahead of every test.

    Tests run only in the file being run: another test file imported for
    its helpers (import test_planner) does not run its tests again."""
    def test(name):
        def wrap(fn):
            if fn.__module__ == "__main__":
                _SEEN[0] += 1
                if (_SEEN[0] - 1) % _SHARD[1] == _SHARD[0]:
                    run(name, fn, before)
            return fn
        return wrap
    return test


test = make_test()


def code_has(src: str, snippet: str) -> bool:
    """A snippet of Lua (or Python) source in a file, whatever the spacing:
    a check that an action or a switch is wired in survives reformatting."""
    squash = lambda t: re.sub(r"\s+", " ", t).strip()          # noqa: E731
    return squash(snippet) in squash(src)


def finish(skipped: str | None = None) -> None:
    """Print the results and exit (1 if any failed)."""
    if skipped and not RESULTS:
        print(f"SKIPPED: {skipped}")
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok or not msg else
                                                       "\n" + "\n".join("        " + x for x in msg.splitlines())))
    if os.environ.get("DFAI_TEST_TIMES"):
        print("\nslowest:")
        for sec, name in sorted(TIMES, reverse=True)[:int(os.environ["DFAI_TEST_TIMES"]) or 10]:
            print(f"  {sec:6.2f}s  {name}")
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

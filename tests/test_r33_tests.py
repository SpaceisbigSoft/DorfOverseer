"""Round 0.105.33, the tests themselves (T1): the real-state smoke test fails
when a rule crashes, the grandeur test fails when the rule proposes nothing,
and run_all counts the files that skipped.

    python tests/test_r33_tests.py
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402

# A rule made to raise, then the test file run as __main__ in a fresh process
# (the same injection as the audit's raise/ and mut/ probes).
_INJECT = """
import runpy, sys
sys.path[:0] = [{brain!r}, {tests!r}]
import planner
def boom(*a, **k):
    raise TypeError("injected")
boom.__name__ = {rule!r}
setattr(planner, {rule!r}, boom)
sys.argv = [{file!r}]
runpy.run_path({file!r}, run_name="__main__")
"""


def _run_with(rule: str | None, file: str) -> subprocess.CompletedProcess:
    path = str(ROOT / "tests" / file)
    cmd = ([sys.executable, "-c", _INJECT.format(brain=str(ROOT / "brain"), tests=str(ROOT / "tests"),
                                                 rule=rule, file=path)]
           if rule else [sys.executable, path])
    with tempfile.TemporaryDirectory(prefix="dfai-test-logs-") as d:
        env = dict(os.environ, DFAI_LOG_DIR=d, PYTHONIOENCODING="utf-8")
        env.pop("DFAI_TEST_SHARD", None)
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env, cwd=str(ROOT))


@test("real states (T1): a rule that raises on every report fails the smoke test")
def _():
    for rule in ("_threat_rules", "_well_rule"):
        r = _run_with(rule, "test_real_states.py")
        assert r.returncode != 0, (rule, r.stdout[-800:])
        assert f"rule {rule} failed (TypeError: injected)" in r.stdout, (rule, r.stdout[-800:])


@test("real states (T1): untouched, every real report plans with no crashed rule")
def _():
    r = _run_with(None, "test_real_states.py")
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    assert " 0 failed" in r.stdout.strip().splitlines()[-1], r.stdout[-400:]


@test("real states (T1): only _guard's crash notes count, not the missing-section note")
def _():
    sys.path.insert(0, str(ROOT / "tests"))
    src = (ROOT / "tests" / "test_real_states.py").read_text(encoding="utf-8")
    ns: dict = {}
    start = src.index("def crashed(")
    exec(src[start:src.index("\ndef check(")], ns)
    crashed = ns["crashed"]
    assert crashed(["rule _well_rule failed (TypeError: x); the others ran"])
    assert not crashed(["skipped rules that need report section(s) moods (failed)",
                        "drink: target of 200 (failed to reach)"])


@test("grandeur (T1): the test fails when _grandeur_rule proposes nothing")
def _():
    r = _run_with(None, "test_planner.py")
    assert "[PASS] grandeur (0.102.6)" in r.stdout, r.stdout[-800:]
    code = _INJECT.replace('raise TypeError("injected")', "return None")
    path = str(ROOT / "tests" / "test_planner.py")
    with tempfile.TemporaryDirectory(prefix="dfai-test-logs-") as d:
        env = dict(os.environ, DFAI_LOG_DIR=d, PYTHONIOENCODING="utf-8")
        env.pop("DFAI_TEST_SHARD", None)
        r = subprocess.run([sys.executable, "-c", code.format(brain=str(ROOT / "brain"), tests=str(ROOT / "tests"),
                                                               rule="_grandeur_rule", file=path)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=str(ROOT))
    assert r.returncode != 0 and "[FAIL] grandeur (0.102.6)" in r.stdout, r.stdout[-800:]


@test("run_all (T1): a file that skips is named and counted in the summary")
def _():
    sys.path.insert(0, str(ROOT / "tests"))
    import run_all
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "test_a_skips.py").write_text('print("SKIPPED: no lupa")\nprint()\nprint("0 passed, 0 failed")\n')
        (Path(d) / "test_b_runs.py").write_text('print("[PASS] x")\nprint()\nprint("1 passed, 0 failed")\n')
        old = run_all.HERE
        run_all.HERE = Path(d)
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                code = run_all.main(["-j", "1"])
        finally:
            run_all.HERE = old
    text = out.getvalue()
    assert code == 0, text
    assert "1 file(s) skipped: test_a_skips.py" in text, text
    assert "All passed." in text, text
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "test_b_runs.py").write_text('print("1 passed, 0 failed")\n')
        run_all.HERE = Path(d)
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                run_all.main(["-j", "1"])
        finally:
            run_all.HERE = old
    assert "skipped" not in out.getvalue(), out.getvalue()


if __name__ == "__main__":
    finish()

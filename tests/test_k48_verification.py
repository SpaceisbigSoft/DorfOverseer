"""(0.105.48 K10) The suite's own honesty (audit A12, findings 6-9, 14):

- a test that cannot run is SKIPPED, never passed: harness.skip()/need_lua()
  count it, run_all names it, and a whole file that skips for want of lupa
  while lupa is installed (its import failed for something else) fails;
- a file that ends without its totals line fails;
- without lupa run_all says so, loudly, at the start and at the end;
- no test compares with a git ref or branch (they are not in every clone and
  `main` moves): committed snapshots instead (tests/snapshots.py), each of
  which fails when missing or different;
- no wall-clock bound in the tests (a loaded machine failed one).

    python tests/test_k48_verification.py
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import finish, test  # noqa: E402

import run_all  # noqa: E402
import snapshots  # noqa: E402

TESTS = ROOT / "tests"


def run_dir(files: dict[str, str], *args: str, lupa: bool | None = None) -> tuple[int, str]:
    """run_all.main over a folder holding only `files`; lupa=True/False pretends."""
    with tempfile.TemporaryDirectory() as d:
        for name, src in files.items():
            (Path(d) / name).write_text(src, encoding="utf-8")
        (Path(d) / "harness.py").write_text((TESTS / "harness.py").read_text(encoding="utf-8"), encoding="utf-8")
        old_here, old_found = run_all.HERE, run_all.lupa_found
        run_all.HERE = Path(d)
        if lupa is not None:
            run_all.lupa_found = lambda: lupa
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                code = run_all.main(["-j", "1", *args])
        finally:
            run_all.HERE, run_all.lupa_found = old_here, old_found
            run_all.NO_LUPA[:] = []
    return code, out.getvalue()


USES_HARNESS = ("import os, sys\nsys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n"
                "from harness import test, finish, need_lua, skip\n")


@test("harness: a skipped test is listed [SKIP] and counted on the totals line; the file still exits 0")
def _():
    src = USES_HARNESS + ("@test('runs')\ndef _():\n    assert True\n\n"
                          "@test('cannot run here')\ndef _():\n    skip('no fort data')\n\nfinish()\n")
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "harness.py").write_text((TESTS / "harness.py").read_text(encoding="utf-8"), encoding="utf-8")
        p = Path(d) / "test_x.py"
        p.write_text(src, encoding="utf-8")
        r = subprocess.run([sys.executable, str(p)], capture_output=True, text=True, cwd=d)
    lines = r.stdout.strip().splitlines()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[SKIP] cannot run here: no fort data" in lines and "[PASS] runs" in lines, lines
    assert lines[-1] == "1 passed, 0 failed, 1 skipped", lines
    assert run_all.TOTALS.match(lines[-1]).group(3) == "1"
    assert run_all.TOTALS.match("3 passed, 0 failed").group(3) is None


@test("run_all: tests skipped inside a file are named in the summary, not hidden among the passes")
def _():
    src = USES_HARNESS + "@test('a')\ndef _():\n    skip('x')\n\n@test('b')\ndef _():\n    pass\n\nfinish()\n"
    code, out = run_dir({"test_part.py": src}, lupa=True)
    assert code == 0, out
    assert "test_part.py" in out and "1 passed, 0 failed, 1 SKIPPED" in out, out
    assert "1 file(s) with skipped tests: test_part.py (1)" in out, out


@test("run_all: a file skipping for want of lupa while lupa is installed fails (an import failed)")
def _():
    src = 'print("SKIPPED: these tests need the lupa package (pip install lupa)")\n'
    code, out = run_dir({"test_imp.py": src}, lupa=True)
    assert code == 1 and "FAILED: skipped for want of lupa, but lupa is installed" in out, out
    assert "Failed: test_imp.py" in out, out
    # without lupa the same file is a skip, counted and named
    code, out = run_dir({"test_imp.py": src}, lupa=False)
    assert code == 0 and "1 file(s) skipped: test_imp.py" in out, out


@test("run_all: a file that exits 0 without its totals line (an early exit) fails")
def _():
    code, out = run_dir({"test_early.py": 'print("ok")\n'}, lupa=True)
    assert code == 1 and "ended without its totals line" in out and "Failed: test_early.py" in out, out


@test("run_all --no-lupa: lupa hidden from the files, and a loud warning at the start and at the end")
def _():
    src = ("try:\n    import lupa\n    print('lupa here')\nexcept ImportError as e:\n    print('SKIPPED: ' + str(e) + ' (lupa)')\n")
    code, out = run_dir({"test_l.py": src}, "--no-lupa")
    assert code == 0, out
    assert "SKIPPED: lupa hidden by run_all --no-lupa" in out, out
    assert out.count("WARNING: lupa is not installed") == 2, out
    assert out.index("WARNING") < out.index("test_l.py") < out.rindex("WARNING"), out
    code, out = run_dir({"test_ok.py": 'print("1 passed, 0 failed")\n'}, lupa=True)
    assert "WARNING" not in out, out


@test("snapshots: a missing or a different snapshot fails; DFAI_SNAPSHOT_WRITE records it")
def _():
    old_dir = snapshots.DIR
    with tempfile.TemporaryDirectory() as d:
        snapshots.DIR = Path(d)
        try:
            try:
                snapshots.snapshot("k48_probe", {"a": [1, 2]})
                raise RuntimeError("a missing snapshot passed")
            except AssertionError as e:
                assert "no snapshot k48_probe.json" in str(e), e
            os.environ["DFAI_SNAPSHOT_WRITE"] = "1"
            try:
                snapshots.snapshot("k48_probe", {"a": [1, 2], "s": {3, 1}})
            finally:
                del os.environ["DFAI_SNAPSHOT_WRITE"]
            assert json.loads((Path(d) / "k48_probe.json").read_text()) == {"a": [1, 2], "s": [1, 3]}
            snapshots.snapshot("k48_probe", {"a": (1, 2), "s": {1, 3}})        # tuples and sets as stored
            try:
                snapshots.snapshot("k48_probe", {"a": [1, 3], "s": [1, 3]})
                raise RuntimeError("a different value passed")
            except AssertionError as e:
                assert "differs from snapshot k48_probe.json: .a[1]" in str(e), e
            assert snapshots.digest({"x": 1}) == snapshots.digest({"x": 1}) != snapshots.digest({"x": 2})
        finally:
            snapshots.DIR = old_dir


GIT_REF = re.compile(r'"git"[^\n]*"(?:show|archive|cat-file)"|git show \w+:|"archive", "main"')
ONE_OFF = {"test_r40_gates_scan.py", "test_r40_sections.py"}     # skip, counted, without their old commit


@test("no test compares with a git ref or branch (but the two one-off proofs, which skip without it)")
def _():
    bad = []
    for p in sorted(TESTS.glob("test_*.py")):
        if p.name in ONE_OFF or p.name == Path(__file__).name:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if GIT_REF.search(line) and not line.lstrip().startswith("#"):
                bad.append(f"{p.name}:{i}: {line.strip()[:100]}")
    assert not bad, "\n".join(bad)
    # every snapshot a test names is committed, and every committed one is named
    named = set()
    for p in TESTS.glob("test_*.py"):
        src = p.read_text(encoding="utf-8")
        if "from snapshots import" in src:
            named |= set(re.findall(r'(?<![\w.])(?:snapshot|recorded)\("([\w-]+)"', src))
    named.discard("k48_probe")
    have = {p.stem for p in snapshots.DIR.glob("*.json")}
    assert named == have, (sorted(named - have), sorted(have - named))


@test("no test returns early as a pass without lupa, and none asserts on the wall clock")
def _():
    quiet = re.compile(r"^([ \t]+)if (?:LuaRuntime is None|SKIP|not HAVE_LUPA|not HAVE_OLD):[ \t]*\n"
                       r"(?:\1[ \t]+print\([^\n]*\)\n)?\1[ \t]+return\b", re.M)
    clock = re.compile(r"assert[^\n]*\b(?:dt|elapsed|secs|seconds)\s*<")
    bad = []
    for p in sorted(TESTS.glob("test_*.py")):
        src = p.read_text(encoding="utf-8")
        bad += [f"{p.name}: early return as a pass" for _ in quiet.finditer(src)]
        bad += [f"{p.name}: wall-clock assert" for _ in clock.finditer(src)]
    assert not bad, "\n".join(bad)


@test("test_item4_alarm: the fire_guard line can fail (it was `... or True`)")
def _():
    src = (TESTS / "test_item4_alarm.py").read_text(encoding="utf-8")
    assert not re.search(r"\] or True\b", src)


if __name__ == "__main__":
    finish()

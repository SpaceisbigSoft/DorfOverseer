"""Run every test file and print one line each.

    python tests/run_all.py            # all files, in parallel processes
    python tests/run_all.py -j 1       # one at a time
    python tests/run_all.py builder    # only the files whose name has "builder"
    python tests/run_all.py --no-lupa  # as on a PC without lupa (lupa hidden)

Each file runs in its own process with its own temporary logs folder
(DFAI_LOG_DIR), so no test writes into the real DF-AI/logs. The slowest files
are split over several processes (DFAI_TEST_SHARD, see harness.py). Results
print in file order. A file that fails shows its failed tests; a file that
crashes (an error outside any test, or no totals line) shows its traceback
and counts as failed; so does a file that ends without its totals line and
without saying SKIPPED, and one that skips for want of lupa while lupa is
installed (its import failed for another reason).

Skipped is never passed: a file that prints SKIPPED, and each test that
calls harness.skip() or need_lua() ("[SKIP] ..."; the totals line then ends
"..., N skipped"), are counted and named in the summary. Without lupa a
third of the suite does not run: the run says so at its start and its end.
"""

from __future__ import annotations

import os
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHARDS = {"test_builder.py": 4}        # the slow files, split this many ways
TOTALS = re.compile(r"^(\d+) passed, (\d+) failed(?:, (\d+) skipped)?$")
NO_LUPA: list[str] = []          # a folder whose lupa/ fails to import (--no-lupa), else empty


def lupa_found() -> bool:
    if NO_LUPA:
        return False
    try:
        return importlib.util.find_spec("lupa") is not None
    except (ImportError, ValueError):
        return False


def hide_lupa() -> str:
    """A folder to put first on PYTHONPATH, where `import lupa` fails."""
    d = Path(tempfile.mkdtemp(prefix="dfai-no-lupa-"))
    (d / "lupa").mkdir()
    (d / "lupa" / "__init__.py").write_text('raise ImportError("lupa hidden by run_all --no-lupa")\n')
    return str(d)


def run_one(path: Path, shard: tuple[int, int] | None) -> dict:
    tmp = tempfile.mkdtemp(prefix="dfai-test-logs-")
    env = dict(os.environ, DFAI_LOG_DIR=tmp, PYTHONIOENCODING="utf-8")
    if NO_LUPA:
        env["PYTHONPATH"] = os.pathsep.join([NO_LUPA[0]] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    if shard:
        env["DFAI_TEST_SHARD"] = f"{shard[0]}/{shard[1]}"
    t0 = time.perf_counter()
    try:
        r = subprocess.run([sys.executable, str(path)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env, cwd=str(HERE.parent))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    lines = r.stdout.strip().splitlines()
    m = TOTALS.match(lines[-1]) if lines else None
    return {"code": r.returncode, "stdout": lines, "stderr": r.stderr.strip(),
            "passed": int(m.group(1)) if m else 0, "failed": int(m.group(2)) if m else 0,
            "tests_skipped": int(m.group(3) or 0) if m else 0,
            "totals": m is not None, "skipped": any(x.startswith("SKIPPED") for x in lines),
            "secs": time.perf_counter() - t0}


def merge(parts: list[dict]) -> dict:
    return {"code": max(p["code"] for p in parts), "stdout": [x for p in parts for x in p["stdout"]],
            "stderr": "\n".join(p["stderr"] for p in parts if p["stderr"]),
            "passed": sum(p["passed"] for p in parts), "failed": sum(p["failed"] for p in parts),
            "tests_skipped": sum(p["tests_skipped"] for p in parts),
            "totals": all(p["totals"] for p in parts), "skipped": any(p["skipped"] for p in parts),
            "secs": max(p["secs"] for p in parts)}


def verdict(r: dict) -> str | None:
    """Why a file that exited 0 still failed, or None."""
    if r["code"] != 0:
        return None
    if r["skipped"] and lupa_found() and any(x.startswith("SKIPPED") and "lupa" in x for x in r["stdout"]):
        return "skipped for want of lupa, but lupa is installed: an import failed"
    if not r["totals"] and not r["skipped"]:
        return "ended without its totals line (an early exit?)"
    return None


def show(name: str, r: dict) -> bool:
    """Print a file's line (and why it failed); True if it passed."""
    crashed = r["code"] != 0 and (not r["totals"] or r["failed"] == 0)
    bad = verdict(r)
    sk = f", {r['tests_skipped']} SKIPPED" if r["tests_skipped"] else ""
    if crashed:
        print(f"{name:26} CRASHED (exit {r['code']})")
    elif bad:
        print(f"{name:26} FAILED: {bad}")
    elif r["totals"]:
        print(f"{name:26} {r['passed']} passed, {r['failed']} failed{sk}   ({r['secs']:.1f} s)")
    else:
        print(f"{name:26} {(r['stdout'] or ['(no output)'])[-1]}")
    if r["code"] == 0 and not bad:
        return True
    if bad:
        print("\n".join("    | " + x for x in r["stdout"][-10:]))
        return False
    for i, x in enumerate(r["stdout"]):
        if x.startswith("[FAIL]"):
            print("    " + x)
            for y in r["stdout"][i + 1:]:
                if not y.startswith("        "):
                    break
                print("    " + y)
    if r["stderr"]:
        print("\n".join("    | " + x for x in r["stderr"].splitlines()))
    elif crashed and r["stdout"]:
        print("\n".join("    | " + x for x in r["stdout"][-20:]))
    return False


def main(argv: list[str]) -> int:
    jobs = os.cpu_count() or 2
    if "-j" in argv:
        i = argv.index("-j")
        jobs = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if "--no-lupa" in argv:
        argv = [a for a in argv if a != "--no-lupa"]
        NO_LUPA[:] = [hide_lupa()]
    files = [t for t in sorted(HERE.glob("test_*.py")) if not argv or any(a in t.name for a in argv)]
    warn = None if lupa_found() else (
        "WARNING: lupa is not installed" + (" (hidden: --no-lupa)" if NO_LUPA else "") +
        ": every test that runs the Lua bridge is SKIPPED, not run. Install it (pip install lupa) "
        "before calling a run good.")
    if warn:
        print("!" * 78 + "\n" + warn + "\n" + "!" * 78)
    tasks = [(t, (i, SHARDS[t.name]) if t.name in SHARDS else None)
             for t in files for i in range(SHARDS.get(t.name, 1))]
    tasks.sort(key=lambda x: x[1] is None)            # the split (slow) files start first
    t0 = time.perf_counter()
    failed, skipped, part_skipped = [], [], []
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {task: pool.submit(run_one, *task) for task in tasks}
        for t in files:                                # print in file order, as each is ready
            parts = [f.result() for (p, _), f in futures.items() if p == t]
            r = merge(parts)
            if not show(t.name, r):
                failed.append(t.name)
            elif r["skipped"] and not r["passed"]:
                skipped.append(t.name)
            elif r["skipped"] or r["tests_skipped"]:
                part_skipped.append(f"{t.name} ({r['tests_skipped'] or 'part'})")
    print(f"\n{len(files)} files in {time.perf_counter() - t0:.0f} s.")
    if skipped:
        print(f"{len(skipped)} file(s) skipped: {', '.join(skipped)}")
    if part_skipped:
        print(f"{len(part_skipped)} file(s) with skipped tests: {', '.join(part_skipped)}")
    if warn:
        print("!" * 78 + "\n" + warn + "\n" + "!" * 78)
    print("All passed." if not failed else f"Failed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

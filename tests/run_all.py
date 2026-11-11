"""Run every test file and print one line each.

    python tests/run_all.py            # all files, in parallel processes
    python tests/run_all.py -j 1       # one at a time
    python tests/run_all.py builder    # only the files whose name has "builder"

Each file runs in its own process with its own temporary logs folder
(DFAI_LOG_DIR), so no test writes into the real DF-AI/logs. The slowest files
are split over several processes (DFAI_TEST_SHARD, see harness.py). Results
print in file order. A file that fails shows its failed tests; a file that
crashes (an error outside any test, or no totals line) shows its traceback
and counts as failed.
"""

from __future__ import annotations

import os
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
TOTALS = re.compile(r"^(\d+) passed, (\d+) failed$")


def run_one(path: Path, shard: tuple[int, int] | None) -> dict:
    tmp = tempfile.mkdtemp(prefix="dfai-test-logs-")
    env = dict(os.environ, DFAI_LOG_DIR=tmp, PYTHONIOENCODING="utf-8")
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
            "totals": m is not None, "skipped": any(x.startswith("SKIPPED") for x in lines),
            "secs": time.perf_counter() - t0}


def merge(parts: list[dict]) -> dict:
    return {"code": max(p["code"] for p in parts), "stdout": [x for p in parts for x in p["stdout"]],
            "stderr": "\n".join(p["stderr"] for p in parts if p["stderr"]),
            "passed": sum(p["passed"] for p in parts), "failed": sum(p["failed"] for p in parts),
            "totals": all(p["totals"] for p in parts), "skipped": any(p["skipped"] for p in parts),
            "secs": max(p["secs"] for p in parts)}


def show(name: str, r: dict) -> bool:
    """Print a file's line (and why it failed); True if it passed."""
    crashed = r["code"] != 0 and (not r["totals"] or r["failed"] == 0)
    if crashed:
        print(f"{name:26} CRASHED (exit {r['code']})")
    elif r["totals"]:
        print(f"{name:26} {r['passed']} passed, {r['failed']} failed   ({r['secs']:.1f} s)")
    else:
        print(f"{name:26} {(r['stdout'] or ['(no output)'])[-1]}")
    if r["code"] == 0:
        return True
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
    files = [t for t in sorted(HERE.glob("test_*.py")) if not argv or any(a in t.name for a in argv)]
    tasks = [(t, (i, SHARDS[t.name]) if t.name in SHARDS else None)
             for t in files for i in range(SHARDS.get(t.name, 1))]
    tasks.sort(key=lambda x: x[1] is None)            # the split (slow) files start first
    t0 = time.perf_counter()
    failed, skipped = [], []
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {task: pool.submit(run_one, *task) for task in tasks}
        for t in files:                                # print in file order, as each is ready
            parts = [f.result() for (p, _), f in futures.items() if p == t]
            r = merge(parts)
            if not show(t.name, r):
                failed.append(t.name)
            elif r["skipped"]:
                skipped.append(t.name)
    print(f"\n{len(files)} files in {time.perf_counter() - t0:.0f} s.")
    if skipped:
        print(f"{len(skipped)} file(s) skipped: {', '.join(skipped)}")
    print("All passed." if not failed else f"Failed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

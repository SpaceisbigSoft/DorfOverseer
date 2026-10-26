"""Run every test file and print one line each.

    python tests/run_all.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    failed = []
    # (13c) every test file writes its logs to a temporary folder, not the
    # real DF-AI\logs (test_keeper added fake soak rows there; test_tools
    # rewrote the probe files)
    tmp = tempfile.mkdtemp(prefix="dfai-test-logs-")
    env = dict(os.environ, DFAI_LOG_DIR=tmp)
    for t in sorted(HERE.glob("test_*.py")):
        r = subprocess.run([sys.executable, str(t)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env)
        last = (r.stdout.strip().splitlines() or ["(no output)"])[-1]
        print(f"{t.name:24} {last}")
        if r.returncode != 0:
            failed.append(t.name)
            print("\n".join("    " + x for x in r.stdout.splitlines() if x.startswith("[FAIL]") or x.startswith("    ")))
            if r.stderr.strip():
                print("    " + r.stderr.strip().splitlines()[-1])
    shutil.rmtree(tmp, ignore_errors=True)
    print("\nAll passed." if not failed else f"\nFailed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

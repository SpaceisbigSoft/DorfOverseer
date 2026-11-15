"""Committed output snapshots, in place of comparisons with old git refs.

Several regression tests once proved "byte for byte as before" by running an
old commit's source (git show 4b0de9a:..., git archive main) beside today's.
Those commits are not in every clone, and `main` moves, so the tests failed,
skipped or compared the tree with itself (audit A12, findings 7 and 8). They
now compare today's output with a JSON snapshot under tests/fixtures/snapshots/,
recorded once (0.105.48, from 0.105.47's code, which passed those comparisons)
and committed:

    from snapshots import snapshot
    snapshot("x_e1_blueprints", value)        # value: JSON-able

    DFAI_SNAPSHOT_WRITE=1 python tests/test_x.py   # (re)record, then review the diff
    DFAI_SNAPSHOT_WRITE=1 python tests/run_all.py  # all of them (after a merge that changes plans)

A missing snapshot fails the test (it never passes quietly). Change a snapshot
only on purpose, when a change of the output is meant, and say so in the commit.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DIR = Path(__file__).resolve().parent / "fixtures" / "snapshots"


def _norm(v):
    """JSON round trip: tuples and sets become lists, keys strings, as on disk."""
    def other(o):
        if isinstance(o, (set, frozenset)):
            return sorted(o, key=repr)
        raise TypeError(f"not JSON-able for a snapshot: {type(o).__name__}")
    return json.loads(json.dumps(v, sort_keys=True, ensure_ascii=False, default=other))


def digest(v) -> str:
    """A short fingerprint of a large JSON-able value, for a snapshot that
    would otherwise run to megabytes (a difference then shows where, not what)."""
    import hashlib
    return "sha256:" + hashlib.sha256(json.dumps(_norm(v), sort_keys=True).encode("utf-8")).hexdigest()[:24]


def snapshot(name: str, value) -> None:
    """Assert value equals the committed snapshot `name` (or write it)."""
    path = DIR / f"{name}.json"
    got = _norm(value)
    if os.environ.get("DFAI_SNAPSHOT_WRITE"):
        DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(got, sort_keys=True, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return
    assert path.exists(), f"no snapshot {path.name}: record it with DFAI_SNAPSHOT_WRITE=1"
    want = json.loads(path.read_text(encoding="utf-8"))
    if got != want:
        raise AssertionError(f"differs from snapshot {path.name}: " + first_difference(want, got))


def plan_cases(out: str | dict) -> dict:
    """A planner probe's output ({case: [cycle, ...]}, a cycle a dict such as
    {"props": [[rule, action, reason, priority], ...], "notes": [...]}) made
    small for a snapshot: each cycle's rules in order, and a fingerprint of
    each of its parts."""
    cases = json.loads(out) if isinstance(out, str) else out
    small = {}
    for k, cycles in cases.items():
        rows = []
        for c in cycles if isinstance(cycles, list) else [cycles]:
            if not isinstance(c, dict):
                rows.append(digest(c))
                continue
            row = {part: digest(v) for part, v in c.items()}
            if isinstance(c.get("props"), list):
                row["rules"] = [p[0] if isinstance(p, list) else p for p in c["props"]]
            rows.append(row)
        small[k] = rows
    return small


def recorded(name: str, value):
    """The committed snapshot `name`, for a test that checks more than
    equality (a subset, a bound); DFAI_SNAPSHOT_WRITE=1 records `value`."""
    path = DIR / f"{name}.json"
    if os.environ.get("DFAI_SNAPSHOT_WRITE"):
        snapshot(name, value)
    assert path.exists(), f"no snapshot {path.name}: record it with DFAI_SNAPSHOT_WRITE=1"
    return json.loads(path.read_text(encoding="utf-8"))


def first_difference(a, b, where: str = "") -> str:
    """Where two JSON values first differ (for the failure message)."""
    if type(a) is not type(b):
        return f"{where or '.'}: {str(a)[:200]!r} != {str(b)[:200]!r}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{where}.{k}: only in {'the snapshot' if k in a else 'the output'}"
            if a[k] != b[k]:
                return first_difference(a[k], b[k], f"{where}.{k}")
    if isinstance(a, list):
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return first_difference(x, y, f"{where}[{i}]")
        if len(a) != len(b):
            return f"{where}: {len(a)} items in the snapshot, {len(b)} now"
    if isinstance(a, str) and a != b:
        i = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
        return f"{where or '.'} at char {i}: {a[max(0, i - 60):i + 60]!r} != {b[max(0, i - 60):i + 60]!r}"
    return f"{where or '.'}: {str(a)[:200]!r} != {str(b)[:200]!r}"

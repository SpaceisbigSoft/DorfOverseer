"""(0.105.0) A scenario copy's mark: a run id kept in the save's site data.

A test copy of a fort shared its logs folder and log memory with the real
fort (logs are keyed by world and site, and DF's autosave renames the loaded
save, so the folder name can't tell them apart). `scenario.py prepare`
records the new copy's folder name and a fresh run id here
(logs/scenario-pending.json); the first time the overseer sees that save
loaded without a mark, it writes the id into the save (the `mark_run`
action). From then on the report's fort section carries run_id, the fort key
becomes "<save>@<run id>#<site>" and the copy logs under
logs/forts/run-<id>-<site>/, its autosaves too.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime
from pathlib import Path

from dfhack import PROJECT_ROOT

PENDING = Path(os.environ.get("DFAI_LOG_DIR") or PROJECT_ROOT / "logs") / "scenario-pending.json"
PENDING_MAX = 20


def _read() -> dict:
    try:
        d = json.loads(PENDING.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def new_run(save_dir: str) -> str:
    """prepare: a run id for the copy just made under `save_dir`."""
    run_id = datetime.now().strftime("%Y%m%d%H%M") + "-" + secrets.token_hex(2)
    d = _read()
    d[save_dir] = run_id
    d = dict(list(d.items())[-PENDING_MAX:])
    PENDING.parent.mkdir(parents=True, exist_ok=True)
    from dfhack import write_atomic
    write_atomic(PENDING, json.dumps(d, indent=1))
    return run_id


def wanted(fort: dict) -> str | None:
    """The run id the loaded save should carry and doesn't yet, or None."""
    if not isinstance(fort, dict) or fort.get("run_id") or not fort.get("save_dir"):
        return None
    rid = _read().get(fort["save_dir"])
    return rid if isinstance(rid, str) and rid else None


def mark(bridge, state: dict, say=print) -> bool:
    """Writes the run id into a prepared copy's save once. True if the
    report's fort section now carries it (the fort key changes)."""
    fort = state.get("fort") if isinstance(state.get("fort"), dict) else None
    rid = wanted(fort)
    if not rid:
        return False
    try:
        r = bridge.act({"type": "mark_run", "run_id": rid})
    except Exception as e:  # noqa: BLE001  (a mark never stops the fort)
        say(f"Scenario: couldn't mark this test copy as run {rid} ({e}); it logs with the real fort for now.")
        return False
    if not isinstance(r, dict) or not r.get("ok"):
        say(f"Scenario: couldn't mark this test copy as run {rid} ({(r or {}).get('error')}).")
        return False
    fort["run_id"] = rid
    say(f"Scenario: this test copy is run {rid}; its logs go to their own folder, apart from the real fort.")
    return True

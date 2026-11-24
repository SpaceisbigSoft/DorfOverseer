"""(r7 d6) brain/planner_config.py split into themed parts (planner_config_base,
_society, _works, _features, _rounds), applied in their old order. This proves:

- PLANNER_CONFIG is the dict it was at 6298b4a: the same keys, values (and
  their types) and key order (a digest of the dump taken there);
- planner_config's names (dir()) are the same as at 6298b4a;
- each part's keys come in PLANNER_CONFIG in the part's order, the parts in
  the order planner_config applies them, and each final value is the last
  part's that sets it (or the layout B block's);
- the (layout B) block is still the last thing in planner_config.py, the
  applying lines just above it (where a new block goes);
- every file is under the size limit, and the modules import cleanly in a
  fresh interpreter in any order.

    python tests/test_r7_d6.py
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import itertools
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from py_parts import py_parts  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import planner_config  # noqa: E402
from planner_config import PLANNER_CONFIG  # noqa: E402

BRAIN = ROOT / "brain"
PARTS = ["planner_config_base", "planner_config_society", "planner_config_works",
         "planner_config_features", "planner_config_rounds"]
LIMIT = 60 * 1024

# dir(planner_config) at 6298b4a
NAMES_6298B4A = ['DISPOSAL_ACTION_MAX', 'PLANNER_CONFIG', '__all__', '__builtins__', '__cached__', '__doc__',
                 '__file__', '__loader__', '__name__', '__package__', '__spec__']
# sha256 of repr(list(PLANNER_CONFIG.items())) and of repr(list(PLANNER_CONFIG)) at 6298b4a
# (r9 c1) re-pinned after the garden court's two keys (garden_court_lift_ticks,
# court_meeting_cooldown_ticks); (r10) re-pinned after r10 p1's three petition keys and p3's
# eleven contact_* keys, (r10 p3 fixes) and three more contact_* keys, (r11 n1) and the six interim
# messenger / office swap keys (n1_*, office_swap_cooldown_ticks), (r14 m1) and the two stale-holder
# keys (m1_free_stale, m1_messenger_reappoint_days), (r14 m1 fixes) and m1_stale_confirm_days, no existing key changed or moved; the split itself was proven against 6298b4a in 0.105.63
# (0.105.93) re-pinned after one deliberate value change: hospital_guard_hold_ticks 1200 -> 3600
# (B: a one-day hold ran out every cycle); keys and order unchanged
# (0.105.97) re-pinned after eight deliberate keys (h9_caravan_edge_max, h9_caravan_dismiss_max,
# h9_caravan_step_days; floor_max_share_peaceful, floor_keep_days, floor_fade_half_life_days,
# floor_forget_share, floor_days_per_year) and two values (h9_caravan_cooldown_ticks 28 -> 14 days,
# squad_trim_cooldown_ticks 3 -> 1 day): B, 23 Nov
DUMP_6298B4A = "d46eddb7ee569a1b141dbecf6122235aafce0a498f3763dfcc13aa27afc3a761"
KEYS_6298B4A = "745c14c2d29aa25eb13f9c54d90939fa80e6dac14d86b644ae9a96963c1c42a1"
COUNT_6298B4A = 1294
LAYOUT_B = ("# (layout B) hallway-first floors (brain/floor_grammar.py, brain/masterplan_floors.py, "
            "brain/planner_floor_notes.py; lua/ai-floorplan.lua)\nPLANNER_CONFIG.update({\n")


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@test("PLANNER_CONFIG is the 6298b4a dict: the same keys, values, types and key order")
def _():
    assert len(PLANNER_CONFIG) == COUNT_6298B4A, len(PLANNER_CONFIG)
    assert _sha(repr(list(PLANNER_CONFIG))) == KEYS_6298B4A, "key order changed"
    assert _sha(repr(list(PLANNER_CONFIG.items()))) == DUMP_6298B4A, "a value changed"
    assert list(PLANNER_CONFIG)[0] == "drink_per_dwarf" and list(PLANNER_CONFIG)[-1] == "floor_note_days"


@test("planner_config's names are the same as at 6298b4a")
def _():
    assert sorted(dir(planner_config)) == NAMES_6298B4A, sorted(dir(planner_config))
    assert planner_config.__all__ == ["PLANNER_CONFIG", "DISPOSAL_ACTION_MAX"]
    assert planner_config.DISPOSAL_ACTION_MAX == 500
    import planner_core
    assert planner_core.PLANNER_CONFIG is PLANNER_CONFIG
    assert planner_core.DISPOSAL_ACTION_MAX is planner_config.DISPOSAL_ACTION_MAX


@test("the parts apply in order: each part's keys in its order, the last setter's value wins")
def _():
    assert py_parts("planner_config") == PARTS
    mods = [importlib.import_module(p) for p in PARTS]
    for m in mods:
        assert m.__all__ == ["PART"] and isinstance(m.PART, dict) and m.PART, m.__name__
    order = list(PLANNER_CONFIG)
    rebuilt = {}
    for m in mods:
        rebuilt.update(m.PART)
    # the parts' keys are PLANNER_CONFIG's, in its order, before the blocks in planner_config.py itself
    assert order[:len(rebuilt)] == list(rebuilt)
    tail = ast.literal_eval("{" + (BRAIN / "planner_config.py").read_text(encoding="utf-8")
                            .split(LAYOUT_B)[1].rstrip().removesuffix("})") + "}")
    rebuilt.update(tail)
    assert list(rebuilt) == order and rebuilt == PLANNER_CONFIG
    for k in PLANNER_CONFIG:
        last = [m.PART[k] for m in mods if k in m.PART] + ([tail[k]] if k in tail else [])
        assert last[-1] is PLANNER_CONFIG[k] or last[-1] == PLANNER_CONFIG[k], k


@test("planner_config.py keeps the parts' applying lines and the (layout B) block last")
def _():
    src = (BRAIN / "planner_config.py").read_text(encoding="utf-8")
    assert src.count(LAYOUT_B) == 1
    above, block = src.split(LAYOUT_B)
    assert block.rstrip().endswith("})") and "PLANNER_CONFIG" not in block
    lines = [ln for ln in above.splitlines() if ln.startswith("PLANNER_CONFIG")]
    assert lines == ([f'PLANNER_CONFIG = dict(__import__("{PARTS[0]}").PART)']
                     + [f'PLANNER_CONFIG.update(__import__("{p}").PART)' for p in PARTS[1:]]), lines
    assert above.endswith(lines[-1] + "\n\n\n")
    for p in PARTS:
        psrc = (BRAIN / f"{p}.py").read_text(encoding="utf-8")
        assert "PLANNER_CONFIG" not in psrc.split('"""', 2)[2], p
        assert not any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(ast.parse(psrc))), p


@test("every file under the size limit")
def _():
    for p in ["planner_config"] + PARTS:
        n = (BRAIN / f"{p}.py").stat().st_size
        assert n < LIMIT, (p, n)


@test("the modules import cleanly in a fresh interpreter in any order")
def _():
    mods = ["planner_config"] + PARTS
    orders = [mods, mods[::-1]] + [list(o) for o in itertools.islice(itertools.permutations(mods), 1, 720, 97)]
    code = ("import sys, hashlib; sys.path.insert(0, sys.argv[1])\n"
            "for m in sys.argv[2:]: __import__(m)\n"
            "import planner_config as p\n"
            "print(hashlib.sha256(repr(list(p.PLANNER_CONFIG.items())).encode()).hexdigest())\n")
    for o in orders:
        r = subprocess.run([sys.executable, "-c", code, str(BRAIN)] + o, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, (o, r.stderr[-400:])
        assert r.stdout.strip() == DUMP_6298B4A, o


if __name__ == "__main__":
    finish()

"""(layout B, B10) Tests for brain/floor_grammar.py (sliders, style, pattern,
quirks and customs into the floor grammar) and the floor_* block of
brain/planner_config.py.

    python tests/test_b10_floor_grammar.py
"""

from __future__ import annotations

import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import make_test, finish, need_lua  # noqa: E402
from py_parts import py_parts  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import floor_grammar  # noqa: E402
from floor_grammar import grammar  # noqa: E402
from planner_config import PLANNER_CONFIG  # noqa: E402

test = make_test()

# the contract's table of PLANNER_CONFIG keys, written out again here on purpose
TABLE = {
    "floor_gap": 1, "floor_gap_wide": 50, "floor_gap_far": 100, "floor_tight_spacing": -50,
    "floor_kind_gap": 1, "floor_lead": 2, "floor_run": 30, "floor_run_deep": 20, "floor_run_very_deep": 14,
    "floor_run_flat": 44, "floor_run_very_flat": 60, "floor_run_dogleg": 0.6, "floor_run_aspect": 1.25,
    "floor_run_min": 10, "floor_run_room": 0.15, "floor_arms_deep": 1, "floor_arms": 2, "floor_arms_flat": 4,
    "floor_node_grandeur": 60, "floor_axial_grandeur": 40, "floor_pile_small": 5, "floor_pile": 5,
    "floor_pile_large": 7, "floor_piles_new": 1, "floor_piles_stock": 50, "floor_elevs_max": 4,
    "floor_full_retry_days": 28, "floor_note_days": 3,
}
KEYS = ["gap", "kind_gap", "lead", "ahead", "run_max", "run_min", "arms_max", "sides", "stagger", "bay", "node",
        "grow", "turns", "balance", "axial", "neck", "pile_w", "piles_new", "full_retry_days"]
# the bridge's ranges (ai-floorplan's G; parse_floor), written out again here on purpose
RANGES = {"gap": (1, 4), "kind_gap": (0, 6), "lead": (0, 8), "ahead": (0, 3), "run_max": (12, 80),
          "run_min": (4, 30), "arms_max": (1, 4), "stagger": (0, 6), "pile_w": (3, 11), "piles_new": (0, 3),
          "full_retry_days": (1, 336)}
SEED = "fort"
BASE = grammar({}, None, {}, seed=SEED)


def g(traits=None, style=None, cfg=None, **kw):
    kw.setdefault("seed", SEED)
    return grammar(traits or {}, style, {} if cfg is None else cfg, **kw)


def moved(got: dict, base: dict = None) -> dict:
    base = BASE if base is None else base
    return {k: v for k, v in got.items() if v != base[k]}


def in_ranges(got: dict) -> str | None:
    """None when the grammar is one the bridge's parse_floor takes, else what is wrong."""
    if list(got) != KEYS:
        return f"keys {list(got)}"
    for k, (lo, hi) in RANGES.items():
        v = got[k]
        if type(v) is not int or not lo <= v <= hi:
            return f"{k} = {v!r} not a whole number in {lo}..{hi}"
    if got["run_min"] > got["run_max"]:
        return f"run_min {got['run_min']} > run_max {got['run_max']}"
    if got["sides"] not in ("both", "one", "alternate"):
        return f"sides {got['sides']!r}"
    if got["bay"] not in (0, 3, 4, 5, 6) or type(got["bay"]) is not int:
        return f"bay {got['bay']!r}"
    if got["node"] not in (3, 5) or type(got["node"]) is not int:
        return f"node {got['node']!r}"
    if (not isinstance(got["grow"], list) or not got["grow"] or len(set(got["grow"])) != len(got["grow"])
            or any(x not in ("turn", "arm") for x in got["grow"])):
        return f"grow {got['grow']!r}"
    if got["turns"] not in ("left", "right", "alternate", "both"):
        return f"turns {got['turns']!r}"
    for k in ("balance", "axial", "neck"):
        if type(got[k]) is not bool:
            return f"{k} = {got[k]!r} not a bool"
    return None


def presets() -> dict:
    """BUILTIN_PRESETS as lua/ai-overseer-settings.lua has it (the table alone, run in a Lua engine)."""
    from lupa.lua53 import LuaRuntime
    src = (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    m = re.search(r"^BUILTIN_PRESETS = (\{.*?^\})", src, re.S | re.M)
    assert m, "BUILTIN_PRESETS not found"
    table = LuaRuntime(unpack_returned_tuples=True).execute("return " + m.group(1))
    return {name: {k: int(v) for k, v in sliders.items()} for name, sliders in table.items()}


# ---- 1: the config block ----

@test("config: every floor_* key of the table is in PLANNER_CONFIG with the table's default")
def _():
    for k, v in TABLE.items():
        assert k in PLANNER_CONFIG, k
        assert PLANNER_CONFIG[k] == v and type(PLANNER_CONFIG[k]) is type(v), (k, PLANNER_CONFIG[k])
    assert floor_grammar.DEFAULTS == TABLE
    assert floor_grammar.RANGES == RANGES and list(floor_grammar.KEYS) == KEYS


@test("config: the block is the last thing in planner_config.py, under its comment, each key with a comment")
def _():
    src = (ROOT / "brain" / "planner_config.py").read_text(encoding="utf-8")
    head = ("# (layout B) hallway-first floors (brain/floor_grammar.py, brain/masterplan_floors.py, "
            "brain/planner_floor_notes.py; lua/ai-floorplan.lua)\nPLANNER_CONFIG.update({\n")
    assert src.count(head) == 1
    block = src.split(head)[1]
    assert block.rstrip().endswith("})") and block.count("PLANNER_CONFIG") == 0
    rows = [ln for ln in block.splitlines() if ln.strip().startswith('"')]
    assert len(rows) == len(TABLE)
    for ln in rows:
        assert re.match(r'\s+"floor_\w+": [-\d.]+,\s+# \S', ln), ln
    assert sorted(re.findall(r'"(floor_\w+)":', block)) == sorted(TABLE)
    # written nowhere else (the older floor_* keys above are the defence floor's, 0.105.54: other names)
    # (r7 d6) ...and none in the parts planner_config applies before it
    others = "".join((ROOT / "brain" / (p + ".py")).read_text(encoding="utf-8") for p in py_parts("planner_config"))
    before = set(re.findall(r'"(floor_\w+)":', src.split(head)[0] + others))
    assert not before & set(TABLE), before & set(TABLE)


@test("config: an empty cfg, PLANNER_CONFIG, no cfg and a junk cfg all give the same grammar")
def _():
    styles = [None, {"aspect": "long", "scale": 140, "rhythm": 4, "symmetry": "mirror"}, {"arms": "ring", "grand": True}]
    rng = random.Random(1)
    for i in range(300):
        tr = {k: rng.randint(-200, 200) for k in ("spacing", "size", "verticality", "grandeur", "fortification",
                                                   "stockpile")}
        kw = dict(pattern=rng.choice(["grid", "rings", "branching", "stacked"]), language=bool(i % 2),
                  grand=bool(i % 3), seed=f"s{i}")
        a = grammar(tr, styles[i % 3], {}, **kw)
        assert a == grammar(tr, styles[i % 3], PLANNER_CONFIG, **kw)
        assert a == grammar(tr, styles[i % 3], **kw) == grammar(tr, styles[i % 3], None, **kw)
        assert a == grammar(tr, styles[i % 3], "junk", **kw)
        assert a == grammar(tr, styles[i % 3], {k: "x" for k in TABLE}, **kw)


@test("the default grammar: exactly the nineteen keys, the bridge's own defaults (but the seeded stagger)")
def _():
    assert list(BASE) == KEYS
    assert BASE["stagger"] in (0, 2, 3)
    rest = {k: v for k, v in BASE.items() if k != "stagger"}
    assert rest == {"gap": 1, "kind_gap": 1, "lead": 2, "ahead": 1, "run_max": 30, "run_min": 10, "arms_max": 2,
                    "sides": "both", "bay": 0, "node": 3, "grow": ["arm", "turn"], "turns": "alternate",
                    "balance": False, "axial": False, "neck": False, "pile_w": 5, "piles_new": 1,
                    "full_retry_days": 28}
    assert in_ranges(BASE) is None


@test("the config's numbers are read: a changed key moves its grammar key")
def _():
    assert g(cfg={"floor_gap": 2})["gap"] == 2
    assert g({"spacing": 30}, cfg={"floor_gap_wide": 30})["gap"] == 2
    assert g({"spacing": 60}, cfg={"floor_gap_far": 60})["gap"] == 3
    assert g({"spacing": -20}, cfg={"floor_tight_spacing": -20})["lead"] == 0
    assert g(cfg={"floor_kind_gap": 2})["kind_gap"] == 2 and g(cfg={"floor_lead": 3})["lead"] == 3
    for key, depth, n in (("floor_run", 0, 36), ("floor_run_deep", 40, 24), ("floor_run_very_deep", 100, 16),
                          ("floor_run_flat", -40, 50), ("floor_run_very_flat", -100, 70)):
        assert g({"verticality": depth}, cfg={key: n})["run_max"] == n, key
    assert g({"fortification": 50}, cfg={"floor_run_dogleg": 0.5})["run_max"] == 15
    assert g(style={"aspect": "long"}, cfg={"floor_run_aspect": 2})["run_max"] == 60
    assert g({"size": 50}, cfg={"floor_run_room": 0.5})["run_max"] == 45
    assert g(cfg={"floor_run_min": 12})["run_min"] == 12
    assert g({"verticality": 40}, cfg={"floor_arms_deep": 2})["arms_max"] == 2
    assert g(cfg={"floor_arms": 3})["arms_max"] == 3
    assert g({"verticality": -40}, cfg={"floor_arms_flat": 3})["arms_max"] == 3
    assert g({"grandeur": 30}, cfg={"floor_node_grandeur": 30})["node"] == 5
    assert g({"grandeur": 20}, cfg={"floor_axial_grandeur": 20}, grand=True)["axial"] is True
    assert g({"size": -50}, cfg={"floor_pile_small": 3})["pile_w"] == 3
    assert g(cfg={"floor_pile": 6})["pile_w"] == 6
    assert g({"size": 50}, cfg={"floor_pile_large": 9})["pile_w"] == 9
    assert g(cfg={"floor_piles_new": 2})["piles_new"] == 2
    assert g({"stockpile": 20}, cfg={"floor_piles_stock": 20})["piles_new"] == 2
    assert g(cfg={"floor_full_retry_days": 56})["full_retry_days"] == 56
    # a config out of the bridge's ranges is clamped, never sent as it is
    wild = g({"spacing": 100}, cfg={"floor_gap": 9, "floor_lead": 20, "floor_kind_gap": 9, "floor_run": 500,
                                    "floor_run_min": 99, "floor_arms": 9, "floor_pile": 40, "floor_piles_new": 7,
                                    "floor_full_retry_days": 0})
    assert in_ranges(wild) is None, in_ranges(wild)
    assert (wild["gap"], wild["lead"], wild["kind_gap"], wild["run_max"], wild["run_min"]) == (4, 8, 6, 80, 30)
    assert in_ranges(g(cfg={"floor_run": 1, "floor_run_min": 30})) is None      # run_min never above run_max


# ---- 2-4: Spacing, Room size, Depth: separate sliders ----

@test("Spacing alone moves gap, kind_gap, lead, ahead and sides, and nothing else")
def _():
    want = {-100: {"kind_gap": 0, "lead": 0, "ahead": 0},
            -50: {"kind_gap": 0, "lead": 0, "ahead": 0},
            0: {},
            49: {},
            50: {"gap": 2, "kind_gap": 3, "lead": 4},
            100: {"gap": 3, "kind_gap": 5, "lead": 6},
            150: {"gap": 3, "kind_gap": 5, "lead": 6, "sides": "one"}}
    for sp, diff in want.items():
        assert moved(g({"spacing": sp})) == diff, (sp, moved(g({"spacing": sp})))
    assert moved(g({"spacing": -49})) == {} and moved(g({"spacing": 149})) == want[100]
    assert g({"spacing": 200})["node"] == 3            # Spacing never widens the turns


@test("Room size alone moves pile_w and run_max, and nothing else")
def _():
    want = {-100: {"run_max": 21}, -50: {"run_max": 26}, 0: {}, 50: {"run_max": 35, "pile_w": 7},
            100: {"run_max": 39, "pile_w": 7}}
    for size, diff in want.items():
        assert moved(g({"size": size})) == diff, (size, moved(g({"size": size})))
    # the small pile room is its own number (the same 5 by default)
    assert moved(g({"size": -50}, cfg={"floor_pile_small": 3})) == {"run_max": 26, "pile_w": 3}
    assert moved(g({"size": 49})) == {} and moved(g({"size": -49})) == {}


@test("Spacing and Room size each act, and on different keys")
def _():
    a, b = moved(g({"spacing": 100})), moved(g({"size": 100}))
    assert a and b and not set(a) & set(b)
    both = g({"spacing": 100, "size": 100})
    assert moved(both) == {**a, **b}


@test("Depth alone moves run_max and arms_max, and nothing else")
def _():
    want = {-100: {"run_max": 60, "arms_max": 4}, -40: {"run_max": 44, "arms_max": 4}, 0: {},
            40: {"run_max": 20, "arms_max": 1}, 100: {"run_max": 14, "arms_max": 1}}
    for depth, diff in want.items():
        assert moved(g({"verticality": depth})) == diff, (depth, moved(g({"verticality": depth})))
    assert moved(g({"verticality": 39})) == {} and moved(g({"verticality": -39})) == {}
    assert g({"verticality": 99})["run_max"] == 20 and g({"verticality": -99})["run_max"] == 44


# ---- 5: Grandeur, Fortification, Reserves ----

@test("Grandeur alone: the 5x5 turn at 60; a grand level's closing hall at 40")
def _():
    assert moved(g({"grandeur": 59})) == {}
    assert moved(g({"grandeur": 60})) == {"node": 5}
    assert moved(g({"grandeur": 200})) == {"node": 5}
    assert moved(g({"grandeur": 39}, grand=True)) == {}
    assert moved(g({"grandeur": 40}, grand=True)) == {"axial": True}
    assert moved(g({"grandeur": 40}, {"grand": True})) == {"axial": True}
    assert moved(g({"grandeur": 60}, grand=True)) == {"node": 5, "axial": True}
    assert moved(g({}, grand=True)) == {} and moved(g({"grandeur": 100})) == {"node": 5}


@test("Fortification alone: the dog-leg fort's shorter run at 50; the neck when the doors are fortified")
def _():
    assert moved(g({"fortification": 49})) == {}
    assert moved(g({"fortification": 50})) == {"run_max": 18}
    assert moved(g({"fortification": 50}, doors="doored")) == {"run_max": 18}
    assert moved(g({"fortification": 70}, doors="fortified")) == {"run_max": 18, "neck": True}
    # the doors the plan names decide; with none named, Fortification 70 says fortified (masterplan._grammar's rule)
    assert moved(g({}, doors="fortified")) == {"neck": True}
    assert moved(g({"fortification": 120}, doors="open")) == {"run_max": 18}
    assert moved(g({"fortification": 120}, doors="doored")) == {"run_max": 18}
    assert moved(g({"fortification": 69})) == {"run_max": 18}
    assert moved(g({"fortification": 70})) == {"run_max": 18, "neck": True}
    assert g({"fortification": 100, "verticality": 100})["run_max"] == 12      # 14 x 0.6, held at the bridge's 12


@test("Reserves alone: one more pile room at 50")
def _():
    assert moved(g({"stockpile": 49})) == {}
    assert moved(g({"stockpile": 50})) == {"piles_new": 2}
    assert moved(g({"stockpile": 200})) == {"piles_new": 2}


@test("the sliders the floor does not read change nothing")
def _():
    others = {k: 150 for k in ("militarism", "piety", "trade", "greed", "mining", "surface", "welfare", "growth",
                               "caution", "outsiders", "engineering", "agriculture", "craftsmanship")}
    assert moved(g(others)) == {}


# ---- 6: the pattern ----

@test("each pattern gives its grow and turns; a style's arms cross / ring overrides it")
def _():
    want = {"grid": (["arm", "turn"], "alternate"), "rings": (["turn", "arm"], "right"),
            "branching": (["turn", "arm"], "both"), "stacked": (["arm"], "alternate")}
    for pattern, (grow, turns) in want.items():
        got = g(pattern=pattern)
        assert (got["grow"], got["turns"]) == (grow, turns), pattern
        assert set(moved(got)) <= {"grow", "turns"}
    for junk in ("junk", "", None, 7, ["grid"]):
        assert g(pattern=junk) == BASE, junk
    for pattern in want:
        ring = g(style={"arms": "ring"}, pattern=pattern)
        assert (ring["grow"], ring["turns"]) == want["rings"]
        assert set(moved(ring)) <= {"grow", "turns"}          # a ring spirals; it opens no more arms
        cross = g(style={"arms": "cross"}, pattern=pattern)
        assert (cross["grow"], cross["turns"]) == want["grid"]
        assert (cross["arms_max"], cross["balance"]) == (4, True)
        corridor = g(style={"arms": "corridor"}, pattern=pattern)
        assert corridor == g(pattern=pattern)
    a, b = g(pattern="grid"), g(pattern="grid")
    a["grow"].append("x")
    assert b["grow"] == ["arm", "turn"] and g(pattern="grid")["grow"] == ["arm", "turn"]   # never a shared list


# ---- 7: the style ----

@test("style: aspect long stretches the run, wide shortens it")
def _():
    assert moved(g(style={"aspect": "long"})) == {"run_max": 38}        # 30 x 1.25 = 37.5
    assert moved(g(style={"aspect": "wide"})) == {"run_max": 24}        # 30 / 1.25
    assert moved(g(style={"aspect": "square"})) == {} and moved(g(style={"aspect": 3})) == {}
    assert g({"verticality": -100}, {"aspect": "long"})["run_max"] == 75
    assert g({"verticality": -100, "size": 100}, {"aspect": "long"})["run_max"] == 80      # 97.5, held at 80
    assert g({"fortification": 50, "size": 50}, {"aspect": "wide"})["run_max"] == 17       # 30 x .6 / 1.25 x 1.15


@test("style: scale 130 widens the turns")
def _():
    assert moved(g(style={"scale": 129})) == {}
    assert moved(g(style={"scale": 130})) == {"node": 5}
    assert moved(g(style={"scale": 150})) == {"node": 5}
    assert moved(g(style={"scale": "150"})) == {} and moved(g(style={"scale": True})) == {}


@test("style: the rhythm is the room rhythm only when the fort follows a design language")
def _():
    for r in (3, 4, 5, 6):
        assert moved(g(style={"rhythm": r}, language=True)) == {"bay": r}
        assert moved(g(style={"rhythm": r})) == {}
    for junk in (0, 2, 7, 4.0, "4", None, True, [4]):
        assert moved(g(style={"rhythm": junk}, language=True)) == {}, junk
    assert moved(g(language=True)) == {}


@test("style: symmetry mirror and radial balance the arms and line the rooms up")
def _():
    seed = next(s for s in (f"s{i}" for i in range(50)) if grammar({}, None, {}, seed=s)["stagger"] != 0)
    base = grammar({}, None, {}, seed=seed)
    assert moved(grammar({}, {"symmetry": "mirror"}, {}, seed=seed), base) == {"stagger": 0, "balance": True}
    assert moved(grammar({}, {"symmetry": "radial"}, {}, seed=seed), base) == {"stagger": 0, "balance": True,
                                                                               "arms_max": 4}
    assert moved(grammar({}, {"symmetry": "none"}, {}, seed=seed), base) == {}
    assert g({"verticality": 100}, {"symmetry": "mirror"})["arms_max"] == 2       # at least two
    assert g({"verticality": -100}, {"symmetry": "mirror"})["arms_max"] == 4      # never fewer than Depth gives
    assert g({"verticality": 100}, {"symmetry": "radial"})["arms_max"] == 4
    # arms cross opens the four arms evenly, and leaves the stagger to the seed
    assert moved(grammar({}, {"arms": "cross"}, {}, seed=seed), base) == {"balance": True, "arms_max": 4}


@test("style: grand (or the grand flag) lets a hall close a run's end at Grandeur 40")
def _():
    assert g({"grandeur": 40}, {"grand": True})["axial"] is True
    assert g({"grandeur": 40}, None, grand=True)["axial"] is True
    assert g({"grandeur": 40}, {"grand": False})["axial"] is False
    assert g({"grandeur": 40}, {"grand": "yes"})["axial"] is False
    assert g({"grandeur": 39}, {"grand": True}, grand=True)["axial"] is False


# ---- 8: quirks and customs ----

@test("quirk narrow_ways (Warren): rooms alternate, the run is a dog-leg fort's")
def _():
    assert moved(g(quirks=frozenset({"narrow_ways"}))) == {"sides": "alternate", "run_max": 18}
    assert g({"fortification": 100}, quirks={"narrow_ways"})["run_max"] == 18      # dog-leg once, not twice
    assert g({"spacing": 150}, quirks=["narrow_ways"])["sides"] == "alternate"


@test("quirk great_shaft: one hall out of the stair, whatever else asks for more")
def _():
    assert moved(g(quirks=frozenset({"great_shaft"}))) == {"arms_max": 1}
    assert g({"verticality": -100}, {"symmetry": "radial", "arms": "cross"}, quirks={"great_shaft"})["arms_max"] == 1
    assert g({}, None, quirks={"great_shaft", "symmetric"})["arms_max"] == 1


@test("quirk symmetric (Mirror-minded): as the mirror symmetry")
def _():
    seed = next(s for s in (f"s{i}" for i in range(50)) if grammar({}, None, {}, seed=s)["stagger"] != 0)
    base = grammar({}, None, {}, seed=seed)
    assert moved(grammar({}, None, {}, seed=seed, quirks=frozenset({"symmetric"})), base) == {"stagger": 0,
                                                                                             "balance": True}
    assert g({"verticality": 100}, quirks={"symmetric"})["arms_max"] == 2


@test("custom winding_ways: rooms alternate, nothing else")
def _():
    assert moved(g(customs=frozenset({"winding_ways"}))) == {"sides": "alternate"}
    assert moved(g(customs=frozenset({"wide_ways", "field_hall"}))) == {}
    assert moved(g(quirks=frozenset({"winding_ways"}))) == {}       # a custom, not a quirk
    assert moved(g(customs=frozenset({"narrow_ways"}))) == {}       # a quirk, not a custom


# ---- 9: urgent ----

@test("urgent: nothing dug ahead, nothing else changes")
def _():
    assert moved(g(urgent=True)) == {"ahead": 0}
    full = dict(traits={"spacing": 100, "size": 100, "verticality": -100, "grandeur": 100, "fortification": 100,
                        "stockpile": 100}, style={"aspect": "long", "rhythm": 5, "grand": True, "scale": 140})
    a = g(full["traits"], full["style"], language=True, pattern="rings")
    b = g(full["traits"], full["style"], language=True, pattern="rings", urgent=True)
    assert moved(b, a) == {"ahead": 0}


# ---- 10: the six presets ----

@test("the built-in presets: each a grammar the bridge takes, and the forts differ")
def _():
    need_lua()
    ps = presets()
    assert sorted(ps) == ["Deep mine", "Garden fort", "Hermit hold", "Merchant city", "Monastery", "War-hold"]

    def doors(tr):          # as masterplan._grammar
        return "fortified" if tr.get("fortification", 0) >= 70 else "open"
    gs = {name: grammar(tr, None, PLANNER_CONFIG, doors=doors(tr), seed=SEED) for name, tr in ps.items()}
    for name, got in gs.items():
        assert in_ranges(got) is None, (name, in_ranges(got))
    distinct = {repr(sorted(got.items())) for got in gs.values()}
    assert len(distinct) >= 4, len(distinct)
    deep, garden, war = gs["Deep mine"], gs["Garden fort"], gs["War-hold"]
    assert deep["run_max"] < garden["run_max"] and deep["arms_max"] <= garden["arms_max"]
    assert (deep["run_max"], deep["arms_max"]) == (14, 1)
    assert war["neck"] is True and war["run_max"] == 18
    assert (war["lead"], war["kind_gap"], war["ahead"]) == (0, 0, 0)        # Spacing -60: a tight fort
    assert gs["Monastery"]["node"] == 5                                     # Grandeur 60
    assert gs["Hermit hold"]["piles_new"] == 2 and gs["Hermit hold"]["neck"] is True
    assert grammar(ps["Garden fort"], {"grand": True}, PLANNER_CONFIG)["axial"] is True     # Grandeur 40


# ---- 11: anything at all ----

@test("5000 random slider sets, styles and flags: never an exception, always inside the bridge's ranges")
def _():
    rng = random.Random(20261115)
    names = ("spacing", "size", "verticality", "grandeur", "fortification", "stockpile")
    quirk_pool = ("narrow_ways", "great_shaft", "symmetric", "forge_born")
    for i in range(5000):
        tr = {k: rng.randint(-200, 200) for k in names if rng.random() < 0.85}
        st = None if rng.random() < 0.1 else {
            k: v for k, v in (("aspect", rng.choice(["square", "long", "wide", None])),
                              ("arms", rng.choice(["corridor", "cross", "ring", None])),
                              ("symmetry", rng.choice(["none", "mirror", "radial", None])),
                              ("scale", rng.randint(80, 150)), ("rhythm", rng.randint(2, 7)),
                              ("grand", rng.random() < 0.3)) if rng.random() < 0.7}
        kw = dict(pattern=rng.choice(["grid", "rings", "branching", "stacked", "junk"]),
                  quirks=frozenset(q for q in quirk_pool if rng.random() < 0.2),
                  customs=frozenset(q for q in ("winding_ways", "wide_ways") if rng.random() < 0.2),
                  doors=rng.choice([None, "open", "doored", "fortified"]), seed=f"seed-{rng.randint(0, 99)}",
                  language=rng.random() < 0.5, grand=rng.random() < 0.3, urgent=rng.random() < 0.2)
        got = grammar(tr, st, PLANNER_CONFIG, **kw)
        assert in_ranges(got) is None, (in_ranges(got), tr, st, kw)


@test("junk in every argument: never an exception, junk reads as 0 / the default")
def _():
    nan, inf = float("nan"), float("inf")
    junk = [None, "x", [], {}, 3.7, nan, inf, -inf, True, object(), b"x", 10 ** 400, {"a": 1}, ("grid",)]
    rng = random.Random(7)
    for i in range(3000):
        tr = rng.choice(junk) if i % 7 == 0 else {
            k: rng.choice(junk) for k in ("spacing", "size", "verticality", "grandeur", "fortification", "stockpile")}
        st = rng.choice(junk) if i % 5 == 0 else {
            k: rng.choice(junk) for k in ("aspect", "arms", "symmetry", "scale", "rhythm", "grand")}
        cfg = rng.choice(junk) if i % 3 == 0 else {k: rng.choice(junk) for k in TABLE if rng.random() < 0.5}
        got = grammar(tr, st, cfg, pattern=rng.choice(junk), quirks=rng.choice(junk), customs=rng.choice(junk),
                      doors=rng.choice(junk), seed=rng.choice(junk), language=rng.choice(junk),
                      grand=rng.choice(junk), urgent=rng.choice(junk))
        assert in_ranges(got) is None, (in_ranges(got), tr, st, cfg)
    for v in ("100", None, nan, inf, True, [100]):
        assert moved(g({k: v for k in ("spacing", "size", "verticality", "grandeur", "fortification",
                                       "stockpile")})) == {}, v
    assert moved(g({"spacing": 100.0})) == moved(g({"spacing": 100}))
    assert g("junk", "junk") == BASE and g(None, 7) == BASE


# ---- 12: the seed ----

@test("the same inputs give the same grammar; the seed picks the stagger (0, 2 or 3) and nothing else")
def _():
    tr, st = {"spacing": 60, "size": -50, "verticality": 40}, {"aspect": "long", "rhythm": 4}
    assert grammar(tr, st, {}, seed="Ral", language=True) == grammar(dict(tr), dict(st), {}, seed="Ral", language=True)
    assert tr == {"spacing": 60, "size": -50, "verticality": 40} and st == {"aspect": "long", "rhythm": 4}
    import hashlib
    seen = set()
    for i in range(60):
        seed = f"fort-{i}"
        got = grammar({}, None, {}, seed=seed)
        want = (0, 2, 3)[int(hashlib.sha1((seed + "|stagger").encode()).hexdigest()[:8], 16) % 3]
        assert got["stagger"] == want
        assert moved(got, {**BASE, "stagger": want}) == {}
        seen.add(got["stagger"])
    assert seen == {0, 2, 3}


if __name__ == "__main__":
    finish()

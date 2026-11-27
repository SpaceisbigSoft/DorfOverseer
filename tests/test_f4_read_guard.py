"""(F4) Unread is not zero, stale is not fresh, another bridge version is not acted on.

- brain/read_guard.py: each rule plan() calls through _guard reads the report
  through a TrackedState; a rule that read a failed section holds its new
  non-emergency proposals ("held: <rule> read failed section <name>"); an
  action naming ids or tiles from a copy past read_cache_cap_days is held.
- planner.plan's can_use(*sections, max_age=): a copy older than max_age game
  days (perf.cache_age) is not used.
- brain/digest.py: a sub-read's `<field>_error` listed in _errors; age_merged
  ages a pulse cycle's sections from the full report.
- brain/bridge.py + brain/expected_bridge.py: a full report of another bridge
  version (or with stale parts) is marked; plan() acts on nothing.

    python tests/test_f4_read_guard.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish, need_lua  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import planner  # noqa: E402
import read_guard  # noqa: E402
from digest import age_merged, normalize  # noqa: E402
from planner import PLANNER_CONFIG, Memory, Proposal, plan  # noqa: E402
from read_guard import TrackedState  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "real" / "region2-0.50-y52-summer.json"


def fort() -> dict:
    s = json.loads(FIXTURE.read_text(encoding="utf-8"))
    s["date"]["season"] = "spring"
    return s


def rules(props) -> list:
    return [p.rule for p in props]


# --- the tracked view --------------------------------------------------------

@test("TrackedState: named reads recorded, top-level writes reach the report, copies are plain dicts")
def _():
    base = {"stocks": {"wood": 3}, "orders": [], "date": {"tick": 1}}
    v = TrackedState(base)
    assert v["stocks"]["wood"] == 3 and v.get("orders") == [] and "date" not in v.read
    assert v.read == {"stocks", "orders"}, v.read
    v["_slot"] = 1
    v.setdefault("_k", 2)
    v["stocks"]["wood"] = 4                     # nested: the same object
    assert base["_slot"] == 1 and base["_k"] == 2 and base["stocks"]["wood"] == 4
    v.pop("_slot")
    assert "_slot" not in base
    del v["_k"]
    assert "_k" not in base
    v.update(x=1)
    assert base["x"] == 1
    assert type(copy.deepcopy(v)) is dict and type(v.copy()) is dict and type(copy.copy(v)) is dict
    assert json.loads(json.dumps(v))["stocks"]["wood"] == 4
    assert isinstance(v, dict)


@test("wrap_args: only the report itself is swapped (positional or keyword); off: nothing")
def _():
    s, other = {"a": 1}, {"a": 1}
    view, args, kw = read_guard.wrap_args(s, (s, other, 3), {"state": s})
    assert isinstance(view, TrackedState) and args[0] is view and args[1] is other and kw["state"] is view
    assert read_guard.wrap_args(s, (other,), {})[0] is None
    assert read_guard.wrap_args(s, (s,), {}, enabled=False)[0] is None


# --- hold(): failed sections ---------------------------------------------------

def _hold(read, new, errors=None, perf=None, cfg=None, before_props=()):
    s = {"_errors": errors or {}, "stocks": {}, "orders": [], "buildings": {}, "units": {"error": "x"}}
    if perf is not None:
        s["perf"] = perf
    props = list(before_props) + list(new)
    notes, said = [], set()
    read_guard.hold(s, set(read), props, {id(p) for p in before_props}, cfg or dict(PLANNER_CONFIG), "rule_fn",
                    notes, said)
    return props, notes


@test("hold: a rule that read a failed section loses its new proposals; said once; earlier ones kept")
def _():
    old = Proposal("kitchen", {"type": "work_order", "recipe": "x"}, "x", 5)
    a = Proposal("kiln", {"type": "work_order", "recipe": "kiln"}, "x", 5)
    b = Proposal("kiln", {"type": "work_order", "recipe": "kiln2"}, "x", 5)
    props, notes = _hold({"buildings", "stocks"}, [a, b], {"buildings": "boom"}, before_props=[old])
    assert props == [old], rules(props)
    assert notes == ["held: kiln read failed section buildings"], notes
    props, notes = _hold({"stocks"}, [a], {"buildings": "boom"})
    assert props == [a] and not notes                      # the section it read was fine


@test("hold: emergency steps go (EMERGENCY rule, release, stop, a safe flag, a defence step)")
def _():
    keep = [Proposal("threat_alert", {"type": "alert", "on": True}, "x", 0),
            Proposal("kiln", {"type": "work_order", "release": True}, "x", 5),
            Proposal("kiln", {"type": "work_order", "stop": True}, "x", 5),
            Proposal("waterworks_moat", {"type": "waterworks", "shut": True}, "x", 5),
            Proposal("squad_fill", {"type": "squad_fill", "squad_id": 3}, "x", 5)]
    props, notes = _hold({"buildings"}, keep, {"buildings": "boom"})
    assert len(props) == len(keep) and not notes, (rules(props), notes)


@test("hold: a LISTED_ONLY section (left as {error}) holds nothing; unknown_filter's own sections are left to it")
def _():
    a = Proposal("kiln", {"type": "work_order"}, "x", 5)
    props, notes = _hold({"units"}, [a], {"units": "boom"})
    assert props == [a] and not notes
    g = Proposal("gather", {"type": "gather_plants", "count": 5}, "x", 2)   # planner_guards.SECTION_NEEDS: stocks
    props, notes = _hold({"stocks"}, [g], {"stocks": "boom"})
    assert props == [g] and not notes
    h = Proposal("hospital_burrow", {"type": "hospital_burrow", "max": 30}, "x", 2)   # OWN_GUARD_RULES
    props, notes = _hold({"health"}, [h], {"health": "boom"})
    assert props == [h]


# --- hold(): stale copies -------------------------------------------------------

@test("hold: an action naming ids or tiles from a copy past read_cache_cap_days is held; others go")
def _():
    perf = {"sections": {}, "cache_age": {"buildings": 9.0}, "cached": {"buildings": True}}
    ided = Proposal("noble_rooms", {"type": "give_room", "unit_id": 5, "building_id": 7}, "x", 5)
    tile = Proposal("dig", {"type": "dig", "x": 1, "y": 2, "z": 3}, "x", 5)
    plain = Proposal("kiln", {"type": "work_order", "recipe": "x"}, "x", 5)
    props, notes = _hold({"buildings"}, [ided, tile, plain], perf=perf)
    assert props == [plain], rules(props)
    assert any("buildings 9 game days old" in n for n in notes), notes
    perf["cache_age"]["buildings"] = 3.0
    props, _ = _hold({"buildings"}, [ided], perf=perf)
    assert props == [ided]
    perf["cache_age"]["buildings"] = 9.0
    props, _ = _hold({"buildings"}, [ided], perf=perf, cfg=dict(PLANNER_CONFIG, read_cache_cap_days=0))
    assert props == [ided]                                   # 0: no cap
    assert PLANNER_CONFIG["read_cache_cap_days"] == read_guard.READ_GUARD_CONFIG["read_cache_cap_days"]


# --- plan() ---------------------------------------------------------------------

@test("plan: an ungated rule that read a failed section holds its proposals, with the note; off: as before")
def _():
    base, _ = plan(fort(), Memory())
    assert "smelt" in rules(base), rules(base)
    s = fort()
    s["stone_use"] = {"error": "boom"}          # read by the industry rules, no can_use gate on it
    props, notes = plan(s, Memory())
    assert "smelt" not in rules(props), rules(props)
    assert "held: smelt read failed section stone_use" in notes, [n for n in notes if "held" in n]
    s = fort()
    s["stone_use"] = {"error": "boom"}
    props, notes = plan(s, Memory(), dict(PLANNER_CONFIG, read_guard=False))
    assert "smelt" in rules(props) and not any(n.startswith("held:") for n in notes)


@test("plan: nothing held on a clean report (the same proposals with the guard on or off)")
def _():
    a, _ = plan(fort(), Memory())
    b, _ = plan(fort(), Memory(), dict(PLANNER_CONFIG, read_guard=False))
    assert rules(a) == rules(b), (rules(a), rules(b))


@test("plan: a rule's writes to its view reach the report (the next rule and the caller see them)")
def _():
    s = fort()
    orig = planner._society_notes

    def writer(state, *a, **kw):
        state["_f4_mark"] = 1
        return orig(state, *a, **kw)
    planner._society_notes = writer
    try:
        plan(s, Memory())
    finally:
        planner._society_notes = orig
    assert s.get("_f4_mark") == 1


@test("can_use(max_age=): a copy older than max_age game days is skipped, with one note; newer is used")
def _():
    seen = []
    orig = planner._project_rules

    def probe(s, traits, cfg, proposals, notes, can_use, memory):
        seen.append((can_use("industry", max_age=2), can_use("industry", max_age=2),
                     can_use("industry", max_age=20), can_use("industry")))
    planner._project_rules = probe
    try:
        s = fort()
        s["perf"] = {"sections": {}, "cache_age": {"industry": 5.0}, "cached": {"industry": True}}
        _, notes = plan(s, Memory())
    finally:
        planner._project_rules = orig
    assert seen == [(False, False, True, True)], seen
    said = [n for n in notes if "industry (5 days old)" in n]
    assert len(said) == 1 and "under 2 days old" in said[0], notes


# --- digest -----------------------------------------------------------------------

@test("normalize: a failed sub-read (<field>_error) is listed as <section>.<field>; none when it read")
def _():
    s = fort()
    s["water"] = {"waters": [], "waters_found": 0, "cistern_status_error": "attempt to index nil"}
    s["missions"] = {"targets": [], "send_error": "boom"}
    e = normalize(s)["_errors"]
    assert e.get("water.cistern_status") == "attempt to index nil" and e.get("missions.send") == "boom", e
    s = fort()
    s["water"] = {"waters": [], "waters_found": 0, "cistern_status": {"ok": 1}}
    e = normalize(s)["_errors"]
    assert "water.cistern_status" not in e and "missions.send" not in e


@test("age_merged: the full report's sections aged by the game time since; the pulse's own left fresh")
def _():
    import perf
    full = {"date": {"tick": 1000, "year": 5}, "industry": {}, "stocks": {}, "orders": [],
            "perf": {"sections": {}, "cache_age": {"industry": 2.5}}}
    pulse = {"date": {"tick": 1000 + 600, "year": 5}, "stocks": {"wood": 1}, "tier": "pulse",
             "perf": {"sections": {"stocks": 1.0}, "total_ms": 3}}
    merged = json.loads(json.dumps(full))
    merged.update(pulse)
    age_merged(merged, full, pulse)
    assert perf.section_age(merged, "industry") == 3.0, merged["perf"]
    assert perf.section_age(merged, "orders") == 0.5
    assert perf.section_age(merged, "stocks") == 0.0
    assert merged["perf"]["total_ms"] == 3 and "cached" not in merged["perf"]   # the PERF line's count untouched
    m2 = {"date": pulse["date"], "industry": {}}
    age_merged(m2, {"date": full["date"], "industry": {}}, {"date": pulse["date"]})   # no perf at all
    assert perf.section_age(m2, "industry") == 0.5


@test("overseer.get_state: a pulse merged over the last full report marks the full sections' ages")
def _():
    import overseer
    import perf

    class Fake:
        def __init__(self):
            self.calls = []

        def state(self, include_units=True, tier=None):
            self.calls.append(tier)
            if tier == "pulse":
                return {"tier": "pulse", "fort": {"site_id": 1}, "date": {"tick": 1600, "year": 3},
                        "stocks": {}, "perf": {"sections": {}}}
            return {"tier": "daily", "fort": {"site_id": 1}, "date": {"tick": 1000, "year": 3},
                    "stocks": {}, "industry": {}, "perf": {"sections": {}, "cache_age": {"industry": 1.0}}}
    saved = dict(overseer.LAST_FULL)
    try:
        overseer.LAST_FULL.clear()
        b = Fake()
        overseer.get_state(b, "daily")
        st = overseer.get_state(b, "pulse")
        assert b.calls == [None, "pulse"], b.calls
        assert perf.section_age(st, "industry") == 1.5 and perf.section_age(st, "stocks") == 0.0, st.get("perf")
    finally:
        overseer.LAST_FULL.clear()
        overseer.LAST_FULL.update(saved)


# --- the bridge version -------------------------------------------------------------

@test("expected_bridge: EXPECTED_BRIDGE_VERSION is lua/ai-bridge.lua's BRIDGE_VERSION (bumped with it)")
def _():
    from expected_bridge import EXPECTED_BRIDGE_VERSION
    m = re.search(r"^BRIDGE_VERSION = '([^']+)'", (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8"), re.M)
    assert m and m.group(1) == EXPECTED_BRIDGE_VERSION, (m and m.group(1), EXPECTED_BRIDGE_VERSION)


@test("version_mismatch: another version or stale parts say why (a keeper restart); same or absent: None")
def _():
    from bridge import version_mismatch
    assert version_mismatch({"bridge_version": "1.0.0"}, "1.0.0") is None
    assert version_mismatch({}, "1.0.0") is None
    why = version_mismatch({"bridge_version": "1.0.1"}, "1.0.0")
    assert why and "1.0.1" in why and "1.0.0" in why and "restart" in why, why
    why = version_mismatch({"bridge_version": "1.0.0", "stale_parts": ["ai-builder-farms (1.0.0x)"]}, "1.0.0")
    assert why and "ai-builder-farms" in why and "restart" in why, why


@test("Bridge.state: a full report of another version is marked (logged once); a pulse is not checked")
def _():
    import tempfile
    import bridge as B
    from expected_bridge import EXPECTED_BRIDGE_VERSION as want
    d = Path(tempfile.mkdtemp())
    br = B.Bridge.__new__(B.Bridge)

    class Log:
        lines = []

        def warning(self, fmt, *a):
            self.lines.append(fmt % a)
    br.log = Log()

    def make(version, tier):
        p = d / f"state-{version}-{tier}.json"
        p.write_text(json.dumps({"bridge_version": version, "tier": tier, "date": {"tick": 1}}), encoding="utf-8")
        return lambda *args, timeout=None: {"ok": True, "file": str(p)}
    B.WARNED_STALE.clear()
    br._call = make("0.0.1", "daily")
    st = br.state(include_units=False)
    assert "0.0.1" in st["_bridge_stale"] and want in st["_bridge_stale"]
    br.state(include_units=False)
    assert len(br.log.lines) == 1, br.log.lines
    br._call = make("0.0.1", "pulse")
    assert "_bridge_stale" not in br.state(include_units=False, tier="pulse")
    br._call = make(want, "daily")
    assert "_bridge_stale" not in br.state(include_units=False)


@test("plan: a report marked _bridge_stale plans nothing and says why (the keeper restart)")
def _():
    s = fort()
    s["_bridge_stale"] = "the game runs ai-bridge 9 but this Python expects 8: ... restarted"
    props, notes = plan(s, Memory())
    assert props == [] and notes == [s["_bridge_stale"]], (rules(props), notes)


# --- Lua (lupa: these run on the PC) ---------------------------------------------------

@test("Lua: water and missions say a failed sub-read as cistern_status_error / send_error; the section stands")
def _():
    need_lua()
    import bridge_behaviour as BB
    L = BB.lua()
    good, _ = BB.stand_in(L.table_from({"marker": "r5p5"}))
    bad, _ = BB.stand_in(None, raise_=True)
    env = BB.hub({"ai-water": good, "ai-builder": bad})
    w = env.SECTIONS.water()
    assert w.error is None and w.cistern_status is None and "stand-in" in str(w.cistern_status_error), BB.to_py(w)
    good2, _ = BB.stand_in(L.table_from({"marker": "r5p5"}))
    env = BB.hub({"ai-missions": good2, "ai-mission-send": bad})
    m = env.SECTIONS.missions()
    assert m.error is None and m.send is None and "stand-in" in str(m.send_error), BB.to_py(m)
    good3, _ = BB.stand_in(L.table_from({"marker": "r5p5"}))
    ok_send, _ = BB.stand_in(L.table_from({"running": False}))
    env = BB.hub({"ai-missions": good3, "ai-mission-send": ok_send})
    m = env.SECTIONS.missions()
    assert m.send is not None and m.send_error is None, BB.to_py(m)


finish()

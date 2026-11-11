"""r33: plan() made cheaper without changing a decision.

culture.profile_from is kept by its inputs' content (a plan asked for it 2-6
times with the same sliders and history), weights.choose_all works out the
leanings once for all the areas, and score_area adds only the leanings that
lean a slider. This file proves the plans are the same: every fixture, with
several cultures and slider sets, planned (and selected) with the pre-r33
code (kept below, verbatim) and with the new code, cold and warm, must give
the same proposals, notes, held-back lines, memory and choices.

    python tests/test_r33_plancost.py
"""

from __future__ import annotations

import copy
import json
import pickle
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import culture  # noqa: E402
import weights  # noqa: E402
from digest import normalize  # noqa: E402
from planner import Memory, plan, select  # noqa: E402
from planner_core import _traits  # noqa: E402

FIXTURES = sorted((ROOT / "tests" / "fixtures").glob("*.json")) + \
    sorted((ROOT / "tests" / "fixtures" / "real").glob("*.json"))


# --- the pre-r33 code, verbatim (the reference) ------------------------------------

def _old_score_area(area_id, traits, history=None, quirks=None, extra=None):
    from weights import (areas, history_counts, held_quirks, _slider, TRAIT_NAMES, HISTORY_NAMES, data)
    area = areas()[area_id]
    counts = history_counts(history)
    quirks = held_quirks(history) if quirks is None else quirks
    learned = (history or {}).get("learned")
    learned = learned.get(area_id) if isinstance(learned, dict) else None
    design = (history or {}).get("design")
    design = design.get(area_id) if isinstance(design, dict) else None
    from leanings import extras
    extra = extras(history)                  # (the old code: worked out here, every area)
    out = []
    for oid, o in area["options"].items():
        parts = []
        score = float(o.get("bias", 0))
        for s, a in (o.get("sliders") or {}).items():
            v = _slider(traits, s)
            if v and a:
                score += a * v / 100
                parts.append((f"{TRAIT_NAMES.get(s, s)} {int(v):+d}", a * v / 100))
            room_hi, room_lo = 200 - v, -200 - v
            for label, d in extra:
                e = d.get(s)
                if not e or not a:
                    continue
                e = max(room_lo, min(room_hi, float(e)))
                room_hi, room_lo = room_hi - e, room_lo - e
                if e:
                    score += a * e / 100
                    parts.append((f"{label} ({TRAIT_NAMES.get(s, s)} {int(e):+d})", a * e / 100))
        for k, (w, cap) in (o.get("history") or {}).items():
            n = min(counts.get(k, 0), cap)
            if n:
                score += w * n
                one, many = HISTORY_NAMES.get(k, (k, k))
                parts.append((f"{n} {one if n == 1 else many}", w * n))
        for q in quirks:
            bonus = ((data()["quirks"][q].get("weights") or {}).get(area_id) or {}).get(oid)
            if bonus:
                score += bonus
                parts.append((data()["quirks"][q]["name"], bonus))
        lean = learned.get(oid) if isinstance(learned, dict) else None
        if isinstance(lean, (int, float)) and lean:
            score += lean
            parts.append(("you turned this down", lean))
        rec = design.get(oid) if isinstance(design, dict) else None
        if isinstance(rec, list) and len(rec) == 2 and isinstance(rec[0], (int, float)) and rec[0]:
            score += rec[0]
            parts.append((str(rec[1]), rec[0]))
        out.append({"id": oid, "label": o["label"], "value": o["value"], "score": round(score, 4),
                    "parts": parts})
    out.sort(key=lambda r: -r["score"])
    return out


def _old_choose_all(traits, history=None):
    return {a: weights.choose(a, traits, history) for a in weights.areas()}


def _old_profile_from(traits, history=None):
    h = history or culture.new_history()
    t = culture.effective_traits(traits, h)
    profile = {c["key"]: c["value"] for c in _old_choose_all(traits, h).values()}
    profile["spacing"] = culture._clamp(t.get("spacing", 0), -200, 200)
    profile["memorials"] = [b for b in h.get("beasts_slain", []) if b not in h.get("memorials_built", [])]
    for k, ov in culture.ai_choices(profile, h).items():
        profile[k] = ov.get("value")
    return profile


LIVE = {"score_area": weights.score_area, "choose_all": weights.choose_all, "profile_from": culture.profile_from}
OLD = {"score_area": _old_score_area, "choose_all": _old_choose_all, "profile_from": _old_profile_from}


@contextmanager
def reference():
    """The pre-r33 functions everywhere a module holds the new ones (the
    planner's parts import profile_from by name)."""
    swapped = []
    for mod in list(sys.modules.values()):
        for name, fn in LIVE.items():
            if getattr(mod, name, None) is fn:
                setattr(mod, name, OLD[name])
                swapped.append((mod, name))
    try:
        yield
    finally:
        for mod, name in swapped:
            setattr(mod, name, LIVE[name])


# --- the cultures and sliders the fixtures are planned with ---------------------

def _cultures():
    rich = {"seed": "regionX#77", "sieges": 2, "citizen_deaths": 11, "last_siege_year": 251,
            "beasts_slain": ["Shulmik the Jackalowls", "Ber the Ash"], "memorials_built": ["Ber the Ash"],
            "choices": {"halls": "rounded", "materials": "light", "traps": "cage", "defence": "plain"},
            "eras": [{"style": {"hall": "rounded"}, "title": "Pale era", "year": 250}],
            "explore": {"rate": 0.3, "turn": 252},
            "leanings": {"missing": {}, "own": {"agriculture": 9, "caution": 9, "fortification": -11, "grandeur": 2,
                                                "mining": 14, "piety": -14, "spacing": -14, "size": 3},
                         "site": [{"trait": "mining", "amount": 10, "why": "rich ore", "short": "ore"},
                                  {"trait": "surface", "amount": -8, "why": "a cold site"}]},
            "learned": {"halls": {"pillared": -0.4}}, "design": {"traps": {"stone": [0.3, "held 2 sieges"]},
                                                                "defence": {"moat": [-0.5, "a siege broke it"]}},
            "quirks": {"mead_hall": {"why": "x", "year": 251}, "frozen_hold": {"why": "y", "year": 253}},
            "overrides": {}, "guide": "pale stone, rounded halls"}
    over = copy.deepcopy(rich)
    over["overrides"] = {"hall": {"value": "pillared", "base": None, "reason": "the strategist"}}
    base = culture._profile_from({}, dict(over, overrides={}))
    over["overrides"]["hall"]["base"] = base["hall"]
    return {"new": None, "empty": {}, "fresh": culture.new_history(), "rich": rich, "override": over}


SLIDERS = {"as_is": None,
           "proud": {"grandeur": 150, "craftsmanship": 80, "fortification": 120, "piety": 60, "spacing": 40},
           "lean": {"grandeur": -150, "fortification": -120, "caution": -90, "size": -60, "verticality": 100}}


def _cases():
    for f in FIXTURES:
        st = json.loads(f.read_text(encoding="utf-8"))
        for cn, cult in _cultures().items():
            for sn, sl in SLIDERS.items():
                s = copy.deepcopy(st)
                if sl is not None:
                    s.setdefault("settings", {})
                    if isinstance(s["settings"], dict):
                        s["settings"]["traits"] = dict(s["settings"].get("traits") or {}, **sl)
                yield f"{f.name}/{cn}/{sn}", s, cult


def _run(state, cult) -> dict:
    m = Memory()
    if cult is not None:
        m.culture = copy.deepcopy(cult)
    s = copy.deepcopy(state)
    props, notes = plan(s, m)
    allowed, held = select(props, s, m)
    tr = _traits(normalize(copy.deepcopy(state)))
    out = {"props": [[p.rule, p.action, p.reason, p.priority, p.is_order] for p in props], "notes": notes,
           "allowed": [[p.rule, p.action, p.reason, p.priority, p.is_order] for p in allowed], "held": held,
           "memory": m.to_dict(),
           "profile": culture.profile_from(tr, m.culture or None),
           "explain": culture.explain(tr, m.culture or None),
           "choose_all": weights.choose_all(tr, m.culture or None)}
    return json.loads(json.dumps(out, sort_keys=True, default=repr))


# --- the proof -----------------------------------------------------------------

@test("r33: every fixture x culture x sliders plans (and selects) exactly as the pre-r33 code, cold and warm")
def _():
    cases = list(_cases())
    assert len(cases) >= 7 * 5 * 3, len(cases)
    seen_props = 0
    with reference():
        assert culture.profile_from is _old_profile_from
        ref = {k: _run(s, c) for k, s, c in cases}
    culture._PROFILE_CACHE.clear()
    cold = {k: _run(s, c) for k, s, c in cases}
    warm = {k: _run(s, c) for k, s, c in cases}          # (the second time: every profile from the cache)
    for k in ref:
        for what in ("props", "notes", "allowed", "held", "memory", "profile", "explain", "choose_all"):
            assert cold[k][what] == ref[k][what], (k, what, "cold")
            assert warm[k][what] == ref[k][what], (k, what, "warm")
        seen_props += len(ref[k]["props"])
    assert seen_props > 300, seen_props            # (the cases do plan something)
    # the cultures and sliders do change the choices (the proof covers more than one answer)
    assert len({json.dumps(r["profile"], sort_keys=True) for r in ref.values()}) >= 5


@test("r33: the reference swap reaches the planner's parts, and is undone after")
def _():
    import planner_gates
    import planner_building
    with reference():
        assert planner_gates.profile_from is _old_profile_from and planner_building.profile_from is _old_profile_from
        assert weights.score_area is _old_score_area and culture.choose_all is _old_choose_all
    assert planner_gates.profile_from is culture.profile_from and weights.score_area is LIVE["score_area"]


# --- the cache itself ----------------------------------------------------------------

@test("r33 cache: a changed history or slider is a new answer (kept by content, not by which dict)")
def _():
    culture._PROFILE_CACHE.clear()
    h = culture.new_history()
    t = {"grandeur": 0}
    a = culture.profile_from(t, h)
    h["beasts_slain"].append("Shulmik the Jackalowls")       # the same dict, changed in place
    b = culture.profile_from(t, h)
    assert a["memorials"] == [] and b["memorials"] == ["Shulmik the Jackalowls"], (a, b)
    t["grandeur"] = 200
    c = culture.profile_from(t, h)
    assert c == _old_profile_from(t, h) and b == _old_profile_from({"grandeur": 0}, h)


def _with_value(h, v):
    h = copy.deepcopy(h)
    h["overrides"]["hall"]["value"] = v
    return h


@test("r33 cache: a caller changing its profile changes nothing for the next caller")
def _():
    culture._PROFILE_CACHE.clear()
    h = _cultures()["override"]
    p = culture.profile_from({}, h)
    want = copy.deepcopy(p)
    p["hall"] = "plain"
    p["memorials"].append("x")
    p.clear()
    assert culture.profile_from({}, h) == want == _old_profile_from({}, h)
    # nor does the kept one hold on to the history's own objects
    h2 = copy.deepcopy(h)
    h2["overrides"]["hall"]["value"] = ["a", "list"]
    h2["overrides"]["hall"]["base"] = culture._profile_from({}, dict(h2, overrides={}))["hall"]
    q = culture.profile_from({}, h2)
    assert q["hall"] == ["a", "list"] and q["hall"] is not h2["overrides"]["hall"]["value"]
    h2["overrides"]["hall"]["value"].append("changed")
    assert culture.profile_from({}, copy.deepcopy(_with_value(h2, ["a", "list"])))["hall"] == ["a", "list"]


@test("r33 cache: the key tells a tuple from a list, 1 from 1.0 and True, '1' from 1")
def _():
    for a, b in ((["x"], ("x",)), (1, 1.0), (1, True), ({"1": 0}, {1: 0})):
        assert pickle.dumps(a, protocol=4) != pickle.dumps(b, protocol=4), (a, b)
    culture._PROFILE_CACHE.clear()
    h = culture.new_history()
    h["design"] = {"traps": {"stone": [5.0, "held"]}}
    as_list = culture.profile_from({}, h)
    h["design"] = {"traps": {"stone": (5.0, "held")}}         # (score_area reads only a list)
    as_tuple = culture.profile_from({}, h)
    assert as_list == _old_profile_from({}, dict(h, design={"traps": {"stone": [5.0, "held"]}}))
    assert as_tuple == _old_profile_from({}, h)
    assert len(culture._PROFILE_CACHE) == 2


@test("r33 cache: what can't be pickled is worked out each time; the cache stays small")
def _():
    culture._PROFILE_CACHE.clear()
    h = culture.new_history()
    h["odd"] = lambda: 0
    assert culture.profile_from({}, h) == _old_profile_from({}, h)
    assert not culture._PROFILE_CACHE
    for i in range(culture._PROFILE_CACHE_MAX + 10):
        culture.profile_from({"grandeur": i}, None)
    assert len(culture._PROFILE_CACHE) == culture._PROFILE_CACHE_MAX


@test("r33 cache: a changed choices.json setting is a new answer")
def _():
    culture._PROFILE_CACHE.clear()
    h = dict(culture.new_history(), seed="s1")
    st = weights.data()["settings"]
    old = st["near"]
    try:
        a = culture.profile_from({"grandeur": 10}, h)
        st["near"] = old + 5.0
        b = culture.profile_from({"grandeur": 10}, h)
        assert b == _old_profile_from({"grandeur": 10}, h) and len(culture._PROFILE_CACHE) == 2, (a, b)
    finally:
        st["near"] = old


if __name__ == "__main__":
    finish()

"""Tests for the weights engine (brain/weights.py, brain/choices.json) and the
quirk engine (brain/quirks.py).

    python tests/test_weights.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import weights  # noqa: E402
from culture import apply_style, explain, new_history, profile_from  # noqa: E402
from quirks import describe, fade_text, has_rule, update  # noqa: E402
from weights import TRAIT_NAMES, areas, choose, choose_all, data  # noqa: E402


SLIDERS = sorted(TRAIT_NAMES)
PRESETS = {     # the roadmap's presets, as opposite pairs
    "war-hold": {"fortification": 120, "militarism": 120, "outsiders": -80, "caution": 60, "engineering": 60,
                 "grandeur": -40, "welfare": -40, "piety": -30, "spacing": -60,
                 "verticality": 60, "industriousness": 40, "mining": 60, "greed": -40},
    "garden fort": {"fortification": -120, "militarism": -120, "outsiders": 80, "caution": -60,
                    "engineering": -60, "grandeur": 40, "welfare": 40, "piety": 30,
                    "spacing": 60, "verticality": -60, "industriousness": -40, "mining": -60, "greed": 40},
}


def random_sliders(rng, lo=40, hi=150):
    return {s: rng.choice((-1, 1)) * rng.randint(lo, hi) for s in SLIDERS}


@test("the data file: every option has a label and a value, and only known sliders")
def _():
    for a, area in areas().items():
        assert area["name"] and area["key"] and len(area["options"]) >= 2, a
        for oid, o in area["options"].items():
            assert o["label"] and "value" in o, (a, oid)
            for s, v in (o.get("sliders") or {}).items():
                assert s in TRAIT_NAMES and -1.5 <= v <= 1.5, (a, oid, s, v)


@test("every option can be reached by some slider setting")
def _():
    rng = random.Random(1)
    seen = {a: set() for a in areas()}
    for _ in range(4000):
        t = {s: rng.randint(-200, 200) for s in rng.sample(SLIDERS, rng.randint(1, 4))}
        for a, c in choose_all(t).items():
            seen[a].add(c["id"])
    missing = {a: set(areas()[a]["options"]) - seen[a] for a in areas()}
    assert not any(missing.values()), missing


@test("distinctiveness: opposite slider settings choose differently in every area")
def _():
    rng = random.Random(7)
    per_area = {a: 0 for a in areas()}
    n = 400
    for _ in range(n):
        t = random_sliders(rng)
        opp = {k: -v for k, v in t.items()}
        a1, a2 = choose_all(t), choose_all(opp)
        for a in areas():
            per_area[a] += a1[a]["id"] != a2[a]["id"]
    weak = {a: c / n for a, c in per_area.items() if c / n < 0.85}
    assert not weak, weak
    war, garden = choose_all(PRESETS["war-hold"]), choose_all(PRESETS["garden fort"])
    same = [a for a in areas() if war[a]["id"] == garden[a]["id"]]
    assert not same, same


@test("stairwells (0.104.82): Fortification and Depth keep one great stair; Spacing and Industry spread them; the quirks lean")
def _():
    assert choose("stairwells", {"fortification": 150, "verticality": 100})["id"] == "one"
    assert choose("stairwells", {"caution": 150, "industriousness": 60})["id"] == "two"
    assert choose("stairwells", {"spacing": 150, "industriousness": 100})["id"] == "several"
    assert choose("stairwells", {}, {"quirks": {"hundred_stairs": {}}})["id"] == "several"
    assert choose("stairwells", {"spacing": 80}, {"quirks": {"great_shaft": {}}})["id"] == "one"
    assert "hundred_stairs" in data()["quirks"]["great_shaft"]["clashes"]


@test("all-zero sliders give the modest default, said to be the default")
def _():
    c = choose_all({})
    assert {a: c[a]["id"] for a in c} == {"halls": "plain", "finish": "floors", "statues": "one",
                                          "materials": "any", "defence": "plain", "traps": "none", "level_doors": "open",
                                          "worship": "none", "layout": "grid", "stairwells": "one"}, {a: c[a]["id"] for a in c}
    assert "default" in weights.why_text(c["halls"])


@test("drivers name the sliders and history that pushed the choice")
def _():
    h = new_history()
    h["sieges"] = 3
    c = choose("defence", {"fortification": 80, "outsiders": -40}, h)
    assert c["id"] == "fortified" and "Fortification +80" in c["drivers"], c["drivers"]
    assert "3 sieges" in c["drivers"], c["drivers"]


@test("seeded pick: same fort, same answer; a close call can differ between forts")
def _():
    # rounded vs pillared nearly level
    t = {"grandeur": 120, "craftsmanship": -20, "deference": -20, "welfare": 30, "piety": 10}
    picks = set()
    for seed in range(60):
        h = dict(new_history(), seed=f"fort{seed}")
        a = choose("halls", t, h)["id"]
        assert a == choose("halls", t, dict(h))["id"]          # a reload never changes it
        picks.add(a)
    assert picks == {"rounded", "pillared"}, picks
    # a clear winner is never overturned by the seed
    assert all(choose("halls", {"grandeur": 200}, dict(new_history(), seed=str(i)))["id"] == "pillared"
               for i in range(30))


@test("stickiness: a made choice stays until something clearly beats it")
def _():
    h = dict(new_history(), choices={"halls": "plain"})
    assert choose("halls", {"grandeur": 15}, h)["id"] == "plain"           # rounded only a little ahead
    assert choose("halls", {"grandeur": 15}, h)["kept"]
    assert choose("halls", {"grandeur": 15})["id"] == "rounded"            # a new fort takes rounded
    assert choose("halls", {"grandeur": 100}, h)["id"] != "plain"          # a real push changes it


@test("culture profiles come from the engine; the strategist can overrule with a reason")
def _():
    p = profile_from({"fortification": 100, "engineering": 60})
    assert p["gate"] == "gatehouse" and p["entry_doors"] is True
    h = new_history()
    apply_style(h, {"gate": "grand", "reason": "the king visits"}, {"fortification": 100, "engineering": 60})
    p = profile_from({"fortification": 100, "engineering": 60}, h)
    assert p["gate"] == "grand"
    ex = {c["area"]: c for c in explain({"fortification": 100, "engineering": 60}, h)}
    assert ex["defence"]["by_ai"] and ex["defence"]["why"] == "the king visits", ex["defence"]
    assert ex["halls"]["by_ai"] is False and ex["layout"]["later"]


# --- quirks ------------------------------------------------------------------------

DAY = 1200


def date(year, day=0):
    return {"year": year, "tick": day * DAY}


STONY = {"wood": 100, "boulders": 900}


@test("Stonebound: earned only after the sliders and stock have held a season, with why")
def _():
    h = new_history()
    t = {"craftsmanship": 60, "greed": 40}
    assert update(h, t, STONY, date(100, 0)) == []
    assert update(h, t, STONY, date(100, 50)) == []
    assert update(h, {"craftsmanship": 60}, STONY, date(100, 60)) == []      # greed dropped: starts again
    assert update(h, t, STONY, date(100, 70)) == []
    out = update(h, t, STONY, date(100, 70 + 84))
    assert out and "Stonebound" in out[0] and "Craft +60" in out[0], out
    assert has_rule(h, "stone_containers")
    d = describe(h)[0]
    assert d["name"] == "Stonebound" and d["since"] == 100 and "for a year" in d["fade"], d


@test("Stonebound: a slider dip doesn't lose it; a year of the opposite does")
def _():
    h = new_history()
    t = {"craftsmanship": 60, "greed": 40}
    update(h, t, STONY, date(100, 0))
    update(h, t, STONY, date(100, 90))
    assert "stonebound" in h["quirks"]
    assert update(h, {"craftsmanship": -10}, STONY, date(100, 100)) == []    # dropped, not far enough
    assert update(h, {"craftsmanship": -80}, STONY, date(100, 110)) == []
    assert update(h, {"craftsmanship": -80}, STONY, date(100, 300)) == []
    out = update(h, {"craftsmanship": -80}, STONY, date(101, 110))
    assert out and "no longer Stonebound" in out[0], out
    assert h["quirk_log"][-1]["change"] == "lost"


@test("Restless and Traditionalist: from the fort's eras; they clash, and change how sticky choices are")
def _():
    h = new_history()
    h["eras"] = [{"year": 100}, {"year": 104}, {"year": 105}, {"year": 105}]
    out = update(h, {}, None, date(105, 10))
    assert out and "Restless" in out[0], out
    assert choose("halls", {"grandeur": 40}, dict(h, choices={"halls": "plain"}))["id"] == "rounded"
    h2 = new_history()
    h2["eras"] = [{"year": 100}]
    t = {"caution": 40}
    update(h2, t, None, date(106, 0))
    out = update(h2, t, None, date(106, 90))
    assert out and "Traditionalist" in out[0], out
    assert choose("halls", {"grandeur": 60}, dict(h2, choices={"halls": "plain"}))["id"] == "plain"
    # both can't be held: Restless waits while Traditionalist holds
    h2["eras"] += [{"year": 106}]
    update(h2, t, None, date(107, 0))
    assert "restless" not in h2["quirks"]


@test("limits: one new quirk per season, and the panel says what would make one fade")
def _():
    h = new_history()
    h["eras"] = [{"year": 100}, {"year": 104}, {"year": 105}, {"year": 105}]
    t = {"craftsmanship": 60, "greed": 40}
    update(h, t, STONY, date(105, 0))                 # Restless at once
    assert list(h["quirks"]) == ["restless"]
    update(h, t, STONY, date(105, 84))                # Stonebound ready, but a season hasn't passed
    assert "stonebound" in h["quirks"] or len(h["quirks"]) == 1
    assert fade_text("restless") == "no new style for 3 years"
    assert "Craft at most -50" in fade_text("stonebound")


@test("quirk weights reach the areas they name")
def _():
    h = new_history()
    h["quirks"] = {"stonebound": {"year": 1, "why": ""}}
    base = {r["id"]: r["score"] for r in weights.score_area("materials", {}, new_history())}
    with_q = {r["id"]: r["score"] for r in weights.score_area("materials", {}, h)}
    assert with_q["any"] < base["any"] and with_q["dark"] == base["dark"]
    assert set(data()["quirks"]) >= {"stonebound", "restless", "traditionalist"}


@test("game: the save turns empty {} into [] (DFHack JSON); quirks and choices still work")
def _():
    h = new_history()
    h.update({"quirks": [], "quirk_watch": {"stonebound": []}, "quirk_log": {}, "choices": [], "overrides": []})
    t = {"craftsmanship": 60, "greed": 40}
    assert update(h, t, STONY, date(100, 0)) == []
    assert describe(h) == [] and not has_rule(h, "stone_containers")
    assert choose("halls", {}, h)["id"] == "plain" and profile_from({}, h)["hall"] == "plain"
    assert update(h, t, STONY, date(100, 90)) and "stonebound" in h["quirks"]


# --- the fort's own leanings, the site's, its history (0.95) ---------------------

import leanings  # noqa: E402
import temperament  # noqa: E402

DEFAULT_STYLE = {"halls": "plain", "finish": "floors", "statues": "one", "materials": "any", "defence": "plain",
                 "traps": "none", "level_doors": "open", "worship": "none", "layout": "grid",
                 "stairwells": "one"}

SITE_STATE = {
    "settings": {"traits": {}},
    "industry": {"ores": {"IRON": {"tiles": 446}, "COPPER": {"tiles": 470}, "SILVER": {"tiles": 361},
                          "PLATINUM": {"tiles": 12}}},
    "water": {"magma": {"tiles": 332}, "bodies": [{"kind": "surface", "tiles": 306, "stagnant_share": 100}]},
    "map": {"dwarves": {"by_layer": {"Cavern1": 4, "upper_levels": 130}, "z_bottom": 125},
            "layers": [{"name": "Cavern1", "z_top": 143, "z_bottom": 135}]},
    "diplomacy": {"elves": True, "civs": [{"race": "GOBLIN", "relation": "Peace", "name": "The Devil of Webs"},
                                          {"race": "ELF", "relation": "Peace"},
                                          {"race": "HUMAN", "relation": "Peace"}]},
}


@test("own leanings (0.95): fixed per fort, within 15 either way, never your Militarism or Growth")
def _():
    a, b = leanings.own_leanings("save#1"), leanings.own_leanings("save#2")
    assert a == leanings.own_leanings("save#1") and a != b
    assert all(-15 <= v <= 15 for v in list(a.values()) + list(b.values()))
    assert not {"militarism", "growth"} & (set(a) | set(b))
    assert len(a) >= 15                                     # nearly every trait leans a little


@test("default sliders (0.95): no seed is the plain default; seeds and own leanings make forts differ")
def _():
    assert {a: c["id"] for a, c in choose_all({}, {}).items()} == DEFAULT_STYLE
    styles, per_area = set(), {a: set() for a in areas()}
    for i in range(300):
        seed = f"save{i}#{i * 7}"
        h = {"seed": seed, "leanings": {"own": leanings.own_leanings(seed), "site": []}}
        ch = choose_all({}, h)
        styles.add(tuple(c["id"] for c in ch.values()))
        for a, c in ch.items():
            per_area[a].add(c["id"])
    assert len(styles) >= 100, len(styles)                  # was 1 before 0.95
    assert all(len(v) >= 2 for v in per_area.values()), per_area
    # at 0 the top two of every area sit inside the close-call band
    for a in areas():
        r = weights.score_area(a, {}, {})
        assert r[0]["score"] - r[1]["score"] < data()["settings"]["near"], (a, r[:2])


@test("history counts in full (0.95): beasts make it prouder, deaths more devout, shown with why")
def _():
    base = {r["id"]: r["score"] for r in weights.score_area("halls", {}, new_history())}
    h = dict(new_history(), beasts_slain=["A the B", "C the D", "E the F"])
    proud = {r["id"]: r["score"] for r in weights.score_area("halls", {}, h)}
    assert proud["pillared"] - base["pillared"] > 0.3          # Grandeur +30 plus the beasts' own weight
    h = dict(new_history(), citizen_deaths=14)
    c = choose("worship", {}, h)
    assert c["id"] == "shrine" and any("its history (Piety +10)" in d for d in c["drivers"]), c
    assert profile_from({}, dict(new_history(), sieges=2))["spacing"] == -30   # still huddles


@test("site leanings (0.95): ore, magma, a cavern, the neighbours, each with its reason; capped at 20")
def _():
    site = leanings.site_leanings(SITE_STATE)
    got = {}
    for x in site:
        got[x["trait"]] = got.get(x["trait"], 0) + x["amount"]
    assert got == {"craftsmanship": 15, "greed": 10, "engineering": 5, "caution": 10, "fortification": 10,
                   "mining": 10, "outsiders": 5}, got
    assert any(x["why"] == "rich ore near the fort" for x in site)
    assert "running water" not in str(site)                 # a stagnant pond isn't running water
    war = dict(SITE_STATE, diplomacy={"civs": [{"race": "GOBLIN", "relation": "War", "name": "The Foes"}]})
    assert {"trait": "fortification", "amount": 15, "why": "at war with The Foes", "short": "at war"} \
        in leanings.site_leanings(war)
    river = dict(SITE_STATE, water={"bodies": [{"kind": "river", "tiles": 80, "stagnant_share": 0}]})
    assert any(x["why"] == "running water near the fort" for x in leanings.site_leanings(river))
    rich = dict(SITE_STATE, water={"magma": {"tiles": 9}}, industry={"ores": {"IRON": {"tiles": 900}}})
    craft = sum(x["amount"] for x in leanings.site_leanings(rich) if x["trait"] == "craftsmanship")
    assert craft == 15
    assert leanings.site_leanings({}) is None
    assert "militarism" not in str(site) and "growth" not in str(site)


@test("leanings kept in the history (0.95): own drawn once, the site read again, old kept when unknown")
def _():
    h = dict(new_history(), seed="F#1")
    out = leanings.update(h, SITE_STATE)
    assert out[0].startswith("the fort's own leanings: ") and any("goblins in the world" in o for o in out)
    own = dict(h["leanings"]["own"])
    assert leanings.update(h, SITE_STATE) == []              # nothing new
    assert leanings.update(h, {"date": {}}) == [] and h["leanings"]["site"]   # a report without them: kept
    h["leanings"]["own"]["piety"] = 99                       # stored, not redrawn
    leanings.update(h, SITE_STATE)
    assert h["leanings"]["own"]["piety"] == 99 and own
    # the game's save turns {} into []: still works
    g = dict(new_history(), seed="F#1", leanings=[])
    leanings.update(g, None)
    assert g["leanings"]["own"] == own
    assert choose("halls", {}, dict(g, leanings={"own": [], "site": {}}))["id"] in ("plain", "rounded")


@test("leanings in words (0.95): the panel's Leans line; the why names them")
def _():
    h = dict(new_history(), seed="F#1", citizen_deaths=10)
    leanings.update(h, SITE_STATE)
    w = leanings.words(h, "fortification")
    assert w.startswith("leans ") and "goblins +10" in w, w
    own_p = h["leanings"]["own"].get("piety", 0)
    assert leanings.words(h, "piety") == (f"leans {own_p + 10:+d}: " + (f"own {own_p:+d}, " if own_p else "")
                                          + "history +10")
    assert leanings.words(h, "militarism") == ""
    p = leanings.panel(h)
    assert p["fortification"] == w and "militarism" not in p and all(len(v) <= 100 for v in p.values()), p
    parts = [t for r in weights.score_area("defence", {}, h) for t, _ in r["parts"]]
    assert "the site: goblins in the world (Fortification +10)" in parts, parts
    assert "leans" not in temperament.effects(SITE_STATE)["fortification"]

if __name__ == "__main__":
    finish()

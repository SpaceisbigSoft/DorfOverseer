"""Tests for the Design track's language in the brain (D0, group G1):
brain/design.py, and its hunks in culture.py, customs.py, masterplan.py and
planner_building.py (review/design/d0-spec.md §1.3, §2 G1).

    python tests/test_d0_language.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import chronicle  # noqa: E402
import culture  # noqa: E402
import customs  # noqa: E402
import design  # noqa: E402
import masterplan  # noqa: E402
import memstore  # noqa: E402
import planner_building  # noqa: E402
from planner import Memory, plan  # noqa: E402
from tokens import TokenBank  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CTX = {"stones": {"MICROCLINE", "GRANITE"}, "names": {"Ral", "Shulmik the Jackalowls"}}

FULL = {"name": "The Ashen Spiral", "story": "A fort that winds down toward the fire.",
        "motif": "spiral", "hall": "round", "scale": 120, "aspect": "long", "arms": "ring",
        "symmetry": "mirror", "finish": {"smooth": 2, "statues": 2, "engrave": "halls"},
        "materials": {"palette": "dark", "by_kind": {"Door": "dark", "Table": "warm"},
                      "signature": "MICROCLINE", "blocks": True},
        "customs": ["cloister", "ore_piles"], "emphasis": ["temple", "dining"],
        "naming": {"tone": "solemn", "words": ["Ash", "Ember", "Coil"], "pattern": "of"},
        "landmarks": [{"kind": "god_hall", "for": "Ral", "words": "a hall in the god's spiral"},
                      {"kind": "chronicle_hall", "for": "Shulmik the Jackalowls"}],
        "era": 2, "changes": "hall and motif"}


def history_with(lang, mode="guided", **more):
    h = culture.new_history()
    h["design"] = dict({"mode": mode, "lang": copy.deepcopy(lang), "by": "rules", "era": 0}, **more)
    return h


# --- check_language ---------------------------------------------------------------

@test("check_language: a full good language passes whole, with no reasons")
def _():
    lang, rej = design.check_language(FULL, CTX)
    assert rej == [], rej
    assert lang == FULL, lang
    assert design._bytes(lang) <= design.LANG_MAX_BYTES


@test("check_language: each bad field is dropped with a reason, the others are kept")
def _():
    bad = {"hall": "triangular", "motif": "dragon", "arms": "spokes", "symmetry": "both", "aspect": "tall",
           "scale": 200, "era": "two", "name": "!!!", "story": 7, "colour": "red",
           "customs": ["hidden_hold", "winding_ways"], "emphasis": ["throne room"],
           "finish": {"smooth": 9, "statues": True, "engrave": "everywhere"},
           "materials": {"palette": "neon", "signature": "ADAMANTINE", "by_kind": {"Throne": "dark"}},
           "naming": {"tone": "silly", "pattern": "random", "words": ["123"]},
           "landmarks": [{"kind": "palace"}, {"kind": "god_hall", "for": "Armok"}]}
    for k, v in bad.items():
        obj = dict(FULL, **{k: v})
        lang, rej = design.check_language(obj, CTX)
        assert rej, (k, v)
        assert all(r.startswith("design: ") for r in rej), rej
        for other in FULL:
            if other != k and other not in ("finish", "materials", "naming", "landmarks"):
                assert lang.get(other) == FULL[other], (k, other, lang)
        if k in ("hall", "motif", "arms", "symmetry", "aspect", "scale", "era", "name", "story", "colour"):
            assert k not in lang, (k, lang)
    lang, rej = design.check_language({"hall": "nave", "colour": "red", "scale": 79}, CTX)
    assert lang == {"hall": "nave"} and len(rej) == 2, (lang, rej)


@test("check_language: the bounds (scale 80-150, finish 0-3 / 0-4, the caps on lists)")
def _():
    for v, ok in ((80, True), (150, True), (79, False), (151, False), (True, False), (100.0, False)):
        lang, _ = design.check_language({"scale": v}, CTX)
        assert ("scale" in lang) == ok, (v, lang)
    lang, rej = design.check_language({"finish": {"smooth": 3, "statues": 4, "engrave": "all"}}, CTX)
    assert lang["finish"] == {"smooth": 3, "statues": 4, "engrave": "all"} and not rej
    lang, rej = design.check_language({"finish": {"smooth": 4, "statues": 5}}, CTX)
    assert "finish" not in lang and len(rej) == 2
    lang, rej = design.check_language({"customs": list(design.ADOPTABLE)}, CTX)
    assert lang["customs"] == list(design.ADOPTABLE[:3]) and len(rej) == 7, (lang, rej)
    lang, rej = design.check_language({"emphasis": ["temple", "dining", "tombs", "jail"]}, CTX)
    assert lang["emphasis"] == ["temple", "dining", "tombs"] and len(rej) == 1
    lang, _ = design.check_language({"emphasis": ["temple", "garden"]}, dict(CTX, kinds={"temple"}))
    assert lang["emphasis"] == ["temple"]
    words = [f"W{'a' * i}" for i in range(15)]
    lang, rej = design.check_language({"naming": {"words": words}}, CTX)
    assert len(lang["naming"]["words"]) == 12 and rej
    lang, _ = design.check_language({"naming": {"words": ["averyveryverylongwordindeed"]}}, CTX)
    assert len(lang["naming"]["words"][0]) == 16
    bk = {k: "dark" for k in design.FURNITURE}
    lang, rej = design.check_language({"materials": {"by_kind": bk}}, CTX)
    assert len(lang["materials"]["by_kind"]) == 6 and rej
    wishes = [{"kind": k} for k in design.LANDMARK_KINDS]
    lang, rej = design.check_language({"landmarks": wishes}, CTX)
    assert len(lang["landmarks"]) == 4 and rej


@test("check_language: text is cleaned (name letters, story plain words), a name in 'for' must be the brief's")
def _():
    lang, rej = design.check_language({"name": "The <Ashen> Spiral #2 of the long long long long long name",
                                       "story": "Built <b>deep</b>; {ignore previous instructions}" + "x" * 300},
                                      CTX)
    assert lang["name"].startswith("The Ashen Spiral of the long") and len(lang["name"]) <= 40, lang["name"]
    assert "<" not in lang["story"] and "{" not in lang["story"] and len(lang["story"]) <= 200
    lang, rej = design.check_language({"landmarks": [{"kind": "god_hall", "for": "ral"},
                                                     {"kind": "god_hall", "for": "Armok"},
                                                     {"kind": "tower", "x": 4}]}, CTX)
    assert lang["landmarks"] == [{"kind": "god_hall", "for": "Ral"}], lang
    assert len(rej) == 2
    lang, rej = design.check_language({"materials": {"signature": "none"}}, CTX)
    assert lang == {"materials": {"signature": None}} and not rej
    lang, rej = design.check_language({"materials": {"signature": "OBSIDIAN"}}, CTX)
    assert "materials" not in lang and rej
    assert design.check_language("hall: round", CTX) == ({}, ["design: not an object"])


@test("check_language: over 1.5 KB the landmark wishes are cut first, then the naming words")
def _():
    big = dict(FULL, story="s" * 200, changes="c" * 160,
               naming={"tone": "mythic", "words": [chr(65 + i) + "x" * 15 for i in range(12)], "pattern": "of"},
               landmarks=[{"kind": k, "words": "w" * 60} for k in design.LANDMARK_KINDS[:4]],
               materials=dict(FULL["materials"], by_kind={k: "dark" for k in design.FURNITURE[:6]}))
    big["customs"] = list(design.ADOPTABLE[:3])
    big["emphasis"] = ["temple", "dining", "tombs"]
    big["landmarks"] = [{"kind": k, "for": "Shulmik the Jackalowls", "words": "w" * 60}
                        for k in design.LANDMARK_KINDS[:4]]
    assert design._bytes(big) > design.LANG_MAX_BYTES, design._bytes(big)
    lang, rej = design.check_language(big, CTX)
    assert design._bytes(lang) <= design.LANG_MAX_BYTES, design._bytes(lang)
    first_cut = [r for r in rej if "cut" in r]
    assert first_cut and "landmarks" in first_cut[0], rej
    assert "naming" in lang and len(lang["naming"]["words"]) == 12      # the wishes were enough
    # with no wishes a language can't reach 1.5 KB (about 1.2 at most); under a
    # smaller cap the naming words go next, then the story, the rest kept
    huge = {k: v for k, v in big.items() if k != "landmarks"}
    assert design._bytes(huge) < design.LANG_MAX_BYTES
    real = design.LANG_MAX_BYTES
    try:
        design.LANG_MAX_BYTES = design._bytes(huge) - 100
        lang, rej = design.check_language(big, CTX)
        cuts = [r for r in rej if "cut" in r]
        assert len([c for c in cuts if "landmarks" in c]) == 4 and "naming words" in cuts[4], cuts
        assert "story" in lang and lang["materials"] == big["materials"] and lang["hall"] == big["hall"]
        assert design._bytes(lang) <= design.LANG_MAX_BYTES
        design.LANG_MAX_BYTES = 300
        lang, rej = design.check_language(big, CTX)
        assert "story" not in lang and "landmarks" not in lang and "words" not in lang.get("naming", {})
    finally:
        design.LANG_MAX_BYTES = real


# --- the window, apply, the profile -------------------------------------------------

@test("window: finish and statues within one step of the sliders' profile; precious only for a grand fort")
def _():
    prof = {"smooth": 1, "statues": 0, "palette": "dark"}
    w = design.window({"finish": {"smooth": 3, "statues": 4}, "scale": 150}, prof, {})
    assert w["finish"] == {"smooth": 2, "statues": 1}, w
    w = design.window({"finish": {"smooth": 0, "statues": 0}}, {"smooth": 3, "statues": 4}, {})
    assert w["finish"] == {"smooth": 2, "statues": 3}, w
    w = design.window({"finish": {"engrave": "halls"}}, prof, {})
    assert w["finish"]["smooth"] == 2
    w = design.window({"materials": {"palette": "precious"}}, prof, {"grandeur": -100})
    assert "palette" not in w["materials"]
    w = design.window({"materials": {"palette": "precious"}}, prof, {"grandeur": 80})
    assert w["materials"]["palette"] == "precious"
    lang = {"finish": {"smooth": 3}}
    design.window(lang, prof, {})
    assert lang == {"finish": {"smooth": 3}}           # (not changed in place)


@test("apply: at Scripts (or with no language) the profile is exactly the sliders'")
def _():
    for traits in ({}, {"grandeur": 150, "piety": 120}, {"militarism": 100, "grandeur": -100}):
        plain = culture.profile_from(traits, culture.new_history())
        for h in (history_with(FULL, mode="scripts"), history_with(None, mode="guided"),
                  history_with(FULL, mode="nonsense"), dict(culture.new_history(), design="junk")):
            p = culture.profile_from(traits, h)
            assert p == plain, (traits, h.get("design"), p)
            assert "design" not in p
            for kind in (None, "temple", "bedrooms"):
                assert culture.layout_style(p, kind) == culture.layout_style(plain), kind
        p = dict(plain)
        design.apply(p, history_with(FULL, mode="scripts"), traits)
        assert p == plain


@test("apply: at Guided the windowed language sets the hall, finish, palette and profile['design']")
def _():
    traits = {"grandeur": 60}
    plain = culture.profile_from(traits, culture.new_history())
    for mode in ("guided", "architect"):
        p = culture.profile_from(traits, history_with(FULL, mode=mode))
        assert p["hall"] == "round" and p["palette"] == "dark"
        assert abs(p["smooth"] - plain["smooth"]) <= 1 and abs(p["statues"] - plain["statues"]) <= 1
        d = p["design"]
        assert d["hall"] == "round" and d["scale"] == 120 and d["aspect"] == "long" and d["arms"] == "ring"
        assert d["motif"] == "spiral" and d["symmetry"] == "mirror" and d["emphasis"] == ["temple", "dining"]
        assert d["by_kind"] == {"Door": "dark", "Table": "warm"} and d["signature"] == "MICROCLINE"
        assert d["blocks"] is True
    p = culture.profile_from({}, history_with({"symmetry": "radial", "motif": "shield"}))
    assert p["design"]["arms"] == "cross" and p["design"]["motif"] == "ring"


@test("the profile cache still hands out fresh copies (the design dict too)")
def _():
    h = history_with(FULL)
    a = culture.profile_from({"grandeur": 60}, h)
    a["design"]["emphasis"].append("jail")
    a["design"]["by_kind"]["Bed"] = "light"
    a["hall"] = "plain"
    b = culture.profile_from({"grandeur": 60}, h)
    assert b["design"]["emphasis"] == ["temple", "dining"] and "Bed" not in b["design"]["by_kind"]
    assert b["hall"] == "round"
    h["design"]["lang"]["hall"] = "nave"               # the language changed: the cache sees it
    assert culture.profile_from({"grandeur": 60}, h)["hall"] == "nave"


@test("a strategist's set_style still holds with a language on (its base is the sliders')")
def _():
    h = history_with({"name": "Plainish"})
    culture.apply_style(h, {"palette": "light"}, {})
    assert culture.profile_from({}, h)["palette"] == "light"


@test("layout_style: the new keys only when not their default; emphasis makes a kind grand")
def _():
    p = culture.profile_from({"grandeur": 60}, history_with(FULL))
    st = culture.layout_style(p, "temple")
    assert st["scale"] == 140 and st["grand"] is True and st["arms"] == "ring" and st["motif"] == "spiral"
    assert st["aspect"] == "long" and st["hall"] == "round"
    st2 = culture.layout_style(p, "bedrooms")
    assert st2["scale"] == 120 and "grand" not in st2
    assert st["statues"] == min(4, st2["statues"] + 1)
    p = culture.profile_from({}, history_with({"hall": "octagonal", "scale": 100, "arms": "corridor",
                                               "motif": "mountain"}))
    st = culture.layout_style(p, "dining")
    assert set(st) == {"hall", "smooth", "statues", "entry_door", "spacing"} and st["hall"] == "octagonal", st
    assert design.style_fields({"hall": "plain"}, "temple") == {}


@test("era_title and style_guide cover all 7 halls (no KeyError on the new ones)")
def _():
    assert len(culture.HALLS) == 7 and design.HALLS == culture.HALLS
    titles = set()
    for hall in culture.HALLS:
        p = {"hall": hall, "smooth": 2, "statues": 1, "palette": "dark", "entry_doors": False, "temple": "none",
             "memorials": [], "gate": "plain"}
        t = culture.era_title(p)
        assert t.endswith(" era") and "  " not in t, t
        titles.add(t)
        assert culture.style_guide(p)
    assert len(titles) == 7
    assert culture.era_title({"hall": "plain", "smooth": 0, "palette": "any"}) == "Rough Plain era"
    p = culture.profile_from({}, history_with({"name": "The Ashen Spiral", "hall": "nave"}))
    assert culture.era_title(p).startswith("The Ashen Spiral: ") and "Vaulted" in culture.era_title(p)


# --- store, revise, lines, signature -------------------------------------------------

@test("store: the language kept, older eras' in short (3 at most), the mode and ask untouched")
def _():
    m = Memory()
    m.culture = culture.new_history()
    m.culture["design"] = {"mode": "guided", "lang": None, "ask": {"since": 5, "tries": 1, "rejected": []}}
    for era in range(6):
        design.store(m, dict(FULL, era=era, hall=design.HALLS[era]), "rules", 100 + era, era)
    d = m.culture["design"]
    assert d["lang"]["era"] == 5 and d["era"] == 5 and d["written"] == 105 and d["by"] == "rules"
    assert [o["era"] for o in d["old"]] == [2, 3, 4], d["old"]
    assert set(d["old"][0]) == {"era", "name", "hall", "motif", "arms"}
    assert d["mode"] == "guided" and d["ask"]["tries"] == 1
    design.store(m, FULL, "ai", 200, 5)                # the same era again: no old entry
    assert len(d["old"]) == 3 and d["by"] == "ai"
    m2 = Memory()
    m2.culture = None
    design.store(m2, FULL, "x", 1, 0)
    assert m2.culture["design"]["by"] == "rules" and m2.culture["design"]["lang"] == FULL


@test("revise: only the fields named in changes come from the new language")
def _():
    new = dict(FULL, hall="nave", motif="sun", arms="cross", scale=90, era=3, changes="the hall")
    out = design.revise(FULL, new, ["hall"])
    assert out["hall"] == "nave" and out["motif"] == "spiral" and out["arms"] == "ring" and out["scale"] == 120
    assert out["era"] == 3 and out["changes"] == "the hall"
    out = design.revise(FULL, new, "hall and motif")
    assert out["hall"] == "nave" and out["motif"] == "sun" and out["arms"] == "ring"
    out = design.revise(FULL, {"finish": {"smooth": 1}}, ["finish.smooth"])
    assert out["finish"] == {"smooth": 1, "statues": 2, "engrave": "halls"}
    out = design.revise(FULL, {"era": 4}, ["landmarks"])
    assert "landmarks" not in out and out["era"] == 4
    assert FULL["hall"] == "round" and "landmarks" in FULL      # (the old one untouched)
    assert design.revise(None, {"hall": "round"}, ["hall"]) == {"hall": "round"}


@test("mode, current, naming, lines, signature")
def _():
    assert design.mode({}) == "scripts" and design.mode({"settings": {"design": "bold"}}) == "scripts"
    assert design.mode({"settings": {"design": "architect"}}) == "architect"
    assert design.current(history_with(FULL, mode="scripts")) is None
    assert design.current(None) is None and design.current(history_with(FULL)) == FULL
    assert design.naming(history_with(FULL)) == FULL["naming"]
    assert design.naming(history_with({"hall": "round"})) is None
    ls = design.lines(history_with(FULL))
    assert 1 <= len(ls) <= 6 and ls[0].startswith("Design: The Ashen Spiral"), ls
    assert any(x.startswith('"') for x in ls)
    assert design.lines(history_with(FULL, mode="scripts")) == []
    assert design.signature("temple", {"hall": "round", "arms": "ring", "scale": 140, "motif": "spiral",
                                       "orient": 3}) == "temple:round:ring:14:spiral:3"
    assert design.signature("bedrooms", {"hall": "plain"}) == "bedrooms:plain:corridor:10:rows:0"
    assert set(design.MOTIF_FORM) == set(design.MOTIFS) and set(design.MOTIF_FORM.values()) <= set(design.FORMS)
    assert len(design.MOTIFS) == 17


# --- customs ------------------------------------------------------------------------

def _old_active(traits):
    out = []
    for cid, (conds, _o, _w) in customs.CUSTOMS.items():
        if all((customs._v(traits, k) >= n) if op == ">=" else (customs._v(traits, k) <= n) for k, op, n in conds):
            out.append(cid)
    return out


@test("customs.active: unchanged with nothing adopted; adopted ones after the sliders', no duplicates")
def _():
    customs.set_adopted(())
    sets = [{}, None, {"piety": 120, "welfare": 50}, {"militarism": 100, "mining": 120, "verticality": 80},
            {"outsiders": -150, "caution": 40}, {"trade": 90, "outsiders": 60, "agriculture": 90}]
    for t in sets:
        assert customs.active(t) == _old_active(t), t
    try:
        customs.set_adopted(["ore_piles", "cloister", "armoury", "hidden_hold", "nonsense", "cloister"])
        assert customs.adopted() == ["cloister", "armoury", "ore_piles"]
        t = {"militarism": 100}
        assert customs.active(t) == ["gate_barracks", "armoury", "cloister", "ore_piles"], customs.active(t)
        assert customs.has(t, "cloister") and customs.layout_customs(t, "temple") == ["cloister"]
    finally:
        customs.set_adopted(())
    assert customs.adopted() == [] and customs.active({"militarism": 100}) == ["gate_barracks", "armoury"]


@test("adopted_customs: the language's, minus a level the Rules tab switched off; none at Scripts")
def _():
    h = history_with(dict(FULL, customs=["cloister", "armoury", "ore_piles"]))
    assert design.adopted_customs(h, {}) == ["cloister", "armoury", "ore_piles"]
    assert design.adopted_customs(h, {}, {"temple": False}) == ["armoury", "ore_piles"]
    assert design.adopted_customs(h, {}, {"barracks": False, "temple": True}) == ["cloister", "ore_piles"]
    assert design.adopted_customs(history_with(FULL, mode="scripts"), {}) == []


# --- stone ---------------------------------------------------------------------------

STONES = [{"token": "GRANITE", "name": "granite", "count": 200, "rgb": [0.6, 0.6, 0.6], "value": 1},
          {"token": "OBSIDIAN", "name": "obsidian", "count": 40, "rgb": [0.05, 0.05, 0.05], "value": 3},
          {"token": "MICROCLINE", "name": "microcline", "count": 25, "rgb": [0.2, 0.4, 0.9], "value": 2},
          {"token": "JET", "name": "jet", "count": 5, "rgb": [0.0, 0.0, 0.0], "value": 9}]


@test("stone_for: by kind first, then the signature stone if it has `need`, then today's pick")
def _():
    for pal in culture.PALETTES:
        for kind in ("Door", "Table", "Statue"):
            assert culture.stone_for(STONES, pal, kind) == culture.stone_for(STONES, pal, kind, 20, None, None)
    assert culture.stone_for(STONES, "any", "Door", by_kind={"Door": "dark"})["token"] == "OBSIDIAN"
    assert culture.stone_for(STONES, "any", "Door", by_kind={"Door": "dark"},
                             signature="MICROCLINE")["token"] == "OBSIDIAN"
    assert culture.stone_for(STONES, "any", "Table", by_kind={"Door": "dark"},
                             signature="MICROCLINE")["token"] == "MICROCLINE"
    assert culture.stone_for(STONES, "any", "Table", signature="JET")["token"] == "GRANITE"      # too few
    assert culture.stone_for(STONES, "any", "Table", need=30, signature="MICROCLINE")["token"] == "GRANITE"
    assert culture.stone_for(STONES, "purpose", "Coffin", signature="NONE")["token"] == \
        culture.stone_for(STONES, "purpose", "Coffin")["token"]


# --- names ---------------------------------------------------------------------------

@test("district_name: exactly today's with no naming; the language's words, tone and pattern with one")
def _():
    for kind in list(masterplan.NOUNS) + ["mystery"]:
        for pal in list(masterplan.ADJECTIVES) + ["nothing"]:
            for seed in ("fort", "Rakustrovod#41"):
                nouns = masterplan.NOUNS.get(kind) or [kind.title()]
                noun = nouns[masterplan._seed(seed, kind) % len(nouns)]
                adj = masterplan.ADJECTIVES.get(pal, "")
                want = f"the {adj} {noun}" if adj else f"the {noun}"
                assert masterplan.district_name(kind, pal, seed) == want
                assert masterplan.district_name(kind, pal, seed, None) == want
                assert masterplan.district_name(kind, pal, seed, {}) == want
    n = {"tone": "solemn", "words": ["Ash"], "pattern": "of"}
    assert masterplan.district_name("industry", "dark", "fort", n) .endswith(" of Ash")
    assert masterplan.district_name("homes", "dark", "fort", dict(n, pattern="possessive")).startswith("Ash's ")
    c = masterplan.district_name("industry", "dark", "fort", dict(n, pattern="compound"))
    assert c.startswith("the ") and "Ash" in c and " " in c, c
    t = masterplan.district_name("halls", "dark", "fort", {"tone": "martial"})
    assert t.split()[1] in masterplan.TONE_ADJECTIVES["martial"], t
    names = {masterplan.district_name(k, "dark", "fort", n) for k in masterplan.NOUNS}
    assert len(names) == len(masterplan.NOUNS)


SITE = {"stairs": [{"x": 100, "y": 100, "z_top": 160, "z_bottom": 130, "elev_top": 60, "elev_bottom": 30,
                    "count": 8}],
        "citizen_elevation": 50, "soil": [58, 59], "elevation_offset": -100}
PLAN_STATE = {"date": {"year": 150, "tick": 0, "day": 1, "month": "Granite", "season": "spring"},
              "dwarves": {"total": 40}}
PLAN_PROFILE = {"layout": "grid", "palette": "dark", "temple": "shrine", "entry_doors": True}


def _drawn(design_rec=None):
    m = Memory()
    m.culture = {"seed": "Test#1", "eras": [{"year": 150, "title": "Plain era"}]}
    if design_rec is not None:
        m.culture["design"] = design_rec
    m.atlas = {"survey": {"elevation_offset": -100, "tick": 1,
                          "layers": [{"name": "Cavern1", "z_top": 120, "z_bottom": 115, "discovered": True}]},
               "entrances": {}}
    assert masterplan.ensure(copy.deepcopy(PLAN_STATE), m, SITE, {}, PLAN_PROFILE)
    return {d["kind"]: d["name"] for d in m.atlas["plan"]["districts"]}


@test("the plan's districts take the language's names at Guided, today's at Scripts")
def _():
    base = _drawn()
    assert _drawn({"mode": "scripts", "lang": FULL}) == base
    named = _drawn({"mode": "guided", "lang": FULL})
    assert set(named) == set(base) and named != base
    assert all(n.endswith((" of Ash", " of Ember", " of Coil")) for n in named.values()), named


@test("garden_name: the season's name, then the language's words, then the fort's name as today")
def _():
    s = {"fort": {"name": "Rakust Rovod"}}
    m = Memory()
    assert planner_building.garden_name(s, m) == "Rakust Rovod"
    m.gardens_built = ["Rakust Rovod"]
    assert planner_building.garden_name(s, m) == "Rakust Rovod Second"
    m = Memory()
    m.culture = history_with(FULL)
    assert planner_building.garden_name(s, m) == "Ash"
    m.gardens_built = ["Ash", "Ember"]
    assert planner_building.garden_name(s, m) == "Coil"
    m.gardens_built = ["Ash", "Ember", "Coil"]
    assert planner_building.garden_name(s, m) == "Ash Second"
    m.culture["set_piece_name"] = "Hall of Ral"
    assert planner_building.garden_name(s, m) == "Hall of Ral"
    m = Memory()
    m.culture = history_with(FULL, mode="scripts")
    assert planner_building.garden_name(s, m) == "Rakust Rovod"


@test("variety: mirror symmetry gives orient 0 or 3, radial gives 0, none changes nothing")
def _():
    seen = {"none": set(), "mirror": set(), "radial": set()}
    for sym in seen:
        for i in range(40):
            m = Memory()
            m.culture = history_with({"symmetry": sym} if sym != "none" else {"hall": "round"})
            m.culture["seed"] = f"fort{i}"
            m0 = Memory()
            m0.culture = dict(culture.new_history(), seed=f"fort{i}")
            v = masterplan.variety(m, "bedrooms")
            v0 = masterplan.variety(m0, "bedrooms")
            assert v["rhythm"] == v0["rhythm"]
            if sym == "none":
                assert v == v0
            seen[sym].add(v["orient"])
    assert seen["none"] == {0, 1, 2, 3} and seen["mirror"] <= {0, 3} and seen["radial"] == {0}, seen


# --- the planner at Scripts and at Guided -------------------------------------------------

def _settled(**traits):
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["settings"]["traits"] = traits
    s["locations"] = {"count": {"HOSPITAL": 1, "INN_TAVERN": 1, "LIBRARY": 1}, "total": 3}
    s["buildings"]["zones"]["Barracks"] = 0
    return s


def _props(s, culture_):
    m = Memory()
    m.culture = copy.deepcopy(culture_)
    p, notes = plan(copy.deepcopy(s), m)
    return [(x.rule, json.dumps(x.action, sort_keys=True, default=str), x.reason) for x in p], notes


@test("plan() at Scripts: the same proposals with no design key, a scripts one, or a stored language at scripts")
def _():
    for traits in ({"militarism": 100}, {}, {"grandeur": 120, "piety": 120}):
        s = _settled(**traits)
        base = _props(s, culture.new_history())
        for h in (history_with(FULL, mode="scripts"), history_with(None, mode="scripts")):
            s2 = copy.deepcopy(s)
            s2["settings"]["design"] = "scripts"
            assert _props(s2, h) == base, traits
            assert _props(s, h) == base, traits


@test("plan() at Guided: a new level carries the language's hall and style keys")
def _():
    s = _settled(militarism=100)
    s["settings"]["design"] = "guided"
    m = Memory()
    # by the AI (D0 merge): planner_design rewrites a rule language whose rules_key
    # doesn't match the sliders, so the hand-made one here is kept as the AI's
    m.culture = history_with(dict(FULL, emphasis=["barracks"]), by="ai")
    p, _ = plan(copy.deepcopy(s), m)
    lv = [x.action for x in p if x.action.get("type") == "start_project" and x.action.get("kind") == "barracks"]
    assert lv, [x.action for x in p if x.action.get("type") == "start_project"]
    st = lv[0]["style"]
    assert st["hall"] == "round" and st["arms"] == "ring" and st["motif"] == "spiral" and st["grand"] is True
    assert st["scale"] == 140 and st["orient"] in (0, 3), st


# --- the save's budget ----------------------------------------------------------------

@test("memstore: a full language and 3 old eras keep the chronicle kind within its budget")
def _():
    m = Memory()
    for d in range(336 * 120, 336 * 150, 5):
        s = {"date": {"year": d // 336, "day": 1 + d % 28, "month": "Granite", "season": "spring"}}
        if d % 20 == 0:
            chronicle.add(m, s, "built", f"a level was finished on day {d}")
        if d % 90 == 0:
            chronicle.add(m, s, "siege", f"a siege on day {d}")
        if d % 30 == 0:
            chronicle.consolidate(m, d // 336)
    h = culture.new_history()
    h["eras"] = [{"year": 120 + i, "title": "The Ashen Spiral: Dark Engraved Cruciform era",
                  "style": {"hall": "cruciform", "smooth": 3, "statues": 4, "palette": "dark",
                            "entry_doors": True, "temple": "grand"}} for i in range(culture.MAX_ERAS)]
    h["beasts_slain"] = [f"Beast{i} the Terrible" for i in range(12)]
    h["guide"] = "g" * culture.STYLE_GUIDE_MAX
    m.culture = h
    big = dict(FULL, story="s" * 200, changes="c" * 160,
               naming={"tone": "mythic", "words": [chr(65 + i) + "x" * 15 for i in range(12)], "pattern": "of"})
    lang, _ = design.check_language(big, CTX)
    for era in range(4):
        design.store(m, dict(lang, name="N" * 40, era=era), "ai", era, era)
    h["design"]["mode"] = "guided"
    h["design"]["ask"] = {"since": 1, "tries": 2, "rejected": ["design: x" * 10] * 3}
    h["design"]["rules_key"] = "f" * 40
    assert len(h["design"]["old"]) == 3
    size = len(json.dumps(h["design"], separators=(",", ":")))
    assert size <= 2500, size
    over = memstore.over_budget(m, TokenBank(), "AI Test Run#1234")
    assert "chronicle" not in over, over


if __name__ == "__main__":
    finish()

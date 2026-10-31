"""Tests for brain/culture.py: profiles, history, eras, style guide, stone picking.

    python tests/test_culture.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

from culture import (check_style, apply_style, beast_name, new_history, note_events,  # noqa: E402
                     pick_stone, profile_from, style_guide, update_eras)

RESULTS = []


def test(name):
    def wrap(fn):
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return wrap


STONES = [
    {"token": "INORGANIC:GRANITE", "name": "granite", "count": 400, "rgb": [0.6, 0.55, 0.5], "value": 1},
    {"token": "INORGANIC:OBSIDIAN", "name": "obsidian", "count": 60, "rgb": [0.1, 0.1, 0.1], "value": 3},
    {"token": "INORGANIC:MARBLE", "name": "marble", "count": 80, "rgb": [0.95, 0.95, 0.95], "value": 2},
    {"token": "INORGANIC:JASPER", "name": "jasper", "count": 30, "rgb": [0.8, 0.2, 0.1], "value": 2},
    {"token": "INORGANIC:RAREST", "name": "rare stone", "count": 5, "rgb": [0.5, 0.5, 0.9], "value": 9},
]


@test("opposite settings give clearly different forts")
def _():
    grand = profile_from({"grandeur": 150, "piety": 120, "greed": 100})
    rough = profile_from({"grandeur": -100, "fortification": 100, "outsiders": -80})
    assert grand["hall"] == "pillared" and rough["hall"] == "plain"
    assert grand["smooth"] == 3 and rough["smooth"] == 0
    assert grand["statues"] == 4 and rough["statues"] == 0
    assert grand["palette"] == "precious" and rough["palette"] == "dark"
    assert grand["temple"] == "grand" and rough["temple"] == "none"
    assert rough["entry_doors"] and not grand["entry_doors"]
    assert len({k for k in grand if grand[k] != rough[k]}) >= 6


@test("all-zero sliders: a modest, practical default")
def _():
    p = profile_from({})
    assert (p["hall"], p["smooth"], p["statues"], p["palette"], p["temple"]) == ("plain", 1, 1, "any", "none")


@test("history: sieges fortify, slain beasts make the fort prouder and get memorials")
def _():
    h = new_history()
    changed = note_events(h, [{"kind": "invasion"}, {"kind": "invasion"}, {"kind": "invasion"},
                              {"kind": "death", "hostile": True,
                               "name": 'Shulmik Soshoshritas "Jackalowls", Forgotten Beast'}])
    assert any("siege" in c for c in changed) and any("Jackalowls" in c for c in changed)
    p = profile_from({}, h)
    assert p["entry_doors"] and p["palette"] == "dark"         # 3 sieges: +45 fortification, dark stone
    assert p["memorials"] == ["Shulmik the Jackalowls"]
    h["memorials_built"].append("Shulmik the Jackalowls")
    assert profile_from({}, h)["memorials"] == []


@test("a pet or an ordinary hostile dying is not a memorial")
def _():
    h = new_history()
    note_events(h, [{"kind": "death", "hostile": True, "name": "goblin lasher"},
                    {"kind": "death", "animal": True, "own_civ": True, "name": "Crundle"}])
    assert h["beasts_slain"] == []


@test("beast names are cleaned for use as a zone name")
def _():
    assert beast_name('Nol Ongasosta Spos "Dreamedwitches the Abyssal", Forgotten Beast') == \
        "Nol the Dreamedwitches the Abyssal"
    assert beast_name('Evil"; os.exit() "x", Titan').replace(" ", "").isalpha()
    assert beast_name('Juwog Stram "The Intense", Forgotten Beast') == "Juwog the Intense"


@test("first run: unnamed demons and night creatures get no memorial hall")
def _():
    h = new_history()
    note_events(h, [{"kind": "death", "hostile": True, "great": True, "name": "Saffron Fiend"},
                    {"kind": "death", "hostile": True, "great": True, "animal": True, "name": "Specter Of Steam"}])
    assert h["beasts_slain"] == []


@test("eras: a new era only when the style changes")
def _():
    h = new_history()
    assert update_eras(h, profile_from({}), 148)
    assert update_eras(h, profile_from({}), 149) is None
    t = update_eras(h, profile_from({"grandeur": 150}), 150)
    assert t and "Pillared" in t and len(h["eras"]) == 2


@test("style guide is short, readable, and the strategist's own one wins")
def _():
    g = style_guide(profile_from({"grandeur": 150, "piety": 120}), "marble")
    assert "pillared" in g.lower() and "temple" in g and len(g) <= 400
    h = new_history()
    h["guide"] = "Everything in green."
    assert style_guide(profile_from({}), None, h) == "Everything in green."


@test("stone picker: palette first, enough stock required, else the most plentiful")
def _():
    assert pick_stone(STONES, "dark")["name"] == "obsidian"
    assert pick_stone(STONES, "light")["name"] == "marble"
    assert pick_stone(STONES, "warm")["name"] == "jasper"
    assert pick_stone(STONES, "precious")["name"] == "obsidian"     # rare stone has too little
    assert pick_stone(STONES, "cool")["name"] == "granite"          # nothing cool enough: most plentiful
    assert pick_stone([], "dark") is None


@test("strategist style requests: allowed values pass, anything else is refused")
def _():
    ok, bad = check_style({"type": "set_style", "hall": "rounded", "palette": "dark", "statues": 9,
                           "guide": "Dark halls <script>; carved {beasts}", "smooth": "lots",
                           "moat": True, "entry_doors": "yes"})
    assert ok == {"hall": "rounded", "palette": "dark", "statues": 4,
                  "guide": "Dark halls script; carved beasts"}, ok
    assert len(bad) == 3, bad
    h = new_history()
    apply_style(h, ok, {})
    p = profile_from({}, h)
    assert p["hall"] == "rounded" and p["palette"] == "dark" and h["guide"].startswith("Dark halls")



@test("review 4c: a Giant Dragonfly is not a dragon; the game's great-danger flag decides")
def _():
    h = new_history()
    note_events(h, [{"kind": "death", "hostile": True, "name": "Agitated Giant Dragonfly"}])
    note_events(h, [{"kind": "death", "hostile": True, "great": False, "name": 'X "Y", Dragon'}])
    assert h["beasts_slain"] == []
    note_events(h, [{"kind": "death", "hostile": True, "great": True, "name": 'Ber "Ash", Bronze Colossus'}])
    note_events(h, [{"kind": "death", "hostile": True, "name": 'Uz "Fire", Dragon'}])
    assert h["beasts_slain"] == ["Ber the Ash", "Uz the Fire"], h["beasts_slain"]


@test("review 4c: a strategist choice lasts only until the player moves that slider")
def _():
    h = new_history()
    apply_style(h, {"hall": "rounded"}, {})
    assert profile_from({}, h)["hall"] == "rounded"
    assert profile_from({"grandeur": 150}, h)["hall"] == "pillared"     # player's new choice wins


@test("defence quirks: Grudge-keepers after 3 sieges, fading 3 years after the last; Trapsmiths from the sliders")
def _():
    import quirks
    h = new_history()
    for y in (50, 51, 52):
        note_events(h, [{"kind": "invasion", "year": y}])
    assert h["sieges"] == 3 and h["last_siege_year"] == 52
    changes = quirks.update(h, {}, None, {"year": 52, "tick": 0})
    assert "grudge_keepers" in quirks._dict(h, "quirks"), changes
    quirks.update(h, {}, None, {"year": 56, "tick": 0})
    assert "grudge_keepers" not in quirks._dict(h, "quirks")
    h2 = new_history()
    t = {"engineering": 70, "fortification": 50}
    quirks.update(h2, t, None, {"year": 50, "tick": 0})
    quirks.update(h2, t, None, {"year": 50, "tick": 85 * 1200})
    assert "trapsmiths" in quirks._dict(h2, "quirks")
    assert quirks.has_rule(h2, "more_traps")

@test("Forge-born and Communal (0.103.11): earned from the forges near magma, and from a crowded fort")
def _():
    import quirks
    h = {}
    extra = {"forges": 2, "magma_forges": 0, "magma_tiles": 2, "beds_per_dwarf": 1.0}
    quirks.update(h, {}, None, {"year": 50, "tick": 0}, extra)
    quirks.update(h, {}, None, {"year": 50, "tick": 85 * 1200}, extra)
    assert "forge_born" in h["quirks"], h.get("quirks")
    h = {}
    extra = {"forges": 1, "magma_forges": 0, "magma_tiles": 0, "beds_per_dwarf": 0.56}
    quirks.update(h, {}, None, {"year": 50, "tick": 0}, extra)
    quirks.update(h, {}, None, {"year": 50, "tick": 85 * 1200}, extra)
    assert list(h["quirks"]) == ["communal"], h.get("quirks")      # one forge, no magma: not Forge-born
    h = {}
    t = {"welfare": -40, "growth": 70}
    quirks.update(h, t, None, {"year": 50, "tick": 0}, {"beds_per_dwarf": 1.0})
    quirks.update(h, t, None, {"year": 50, "tick": 85 * 1200}, {"beds_per_dwarf": 1.0})
    assert "communal" in h["quirks"], h.get("quirks")


@test("Gem-mad and Nobles' Pride (0.103.15): from a hoard of gems, and from a fort of many nobles")
def _():
    import quirks
    h = {}
    extra = {"gems": 120, "cut_gems": 0, "jewelers": 0, "nobles": 3}
    quirks.update(h, {}, None, {"year": 50, "tick": 0}, extra)
    quirks.update(h, {}, None, {"year": 50, "tick": 85 * 1200}, extra)
    assert list(h["quirks"]) == ["gem_mad"], h.get("quirks")
    h = {}
    extra = {"gems": 10, "cut_gems": 0, "jewelers": 0, "nobles": 8}
    quirks.update(h, {}, None, {"year": 50, "tick": 0}, extra)
    quirks.update(h, {}, None, {"year": 50, "tick": 85 * 1200}, extra)
    assert not h.get("quirks"), h.get("quirks")                     # 168 days, not 84
    quirks.update(h, {}, None, {"year": 50, "tick": 169 * 1200}, extra)
    assert list(h["quirks"]) == ["nobles_pride"], h.get("quirks")


@test("Superstitious (0.103.17): ghosts walking a fort that has buried many, 56 days")
def _():
    import quirks
    h = {"citizen_deaths": 6}
    quirks.update(h, {}, None, {"year": 50, "tick": 0}, {"ghosts": 2})
    quirks.update(h, {}, None, {"year": 50, "tick": 57 * 1200}, {"ghosts": 2})
    assert "superstitious" in h["quirks"] or "haunted" in h["quirks"], h.get("quirks")
    h = {"citizen_deaths": 6, "quirks": {"haunted": {}}}
    quirks.update(h, {}, None, {"year": 50, "tick": 0}, {"ghosts": 2})
    quirks.update(h, {}, None, {"year": 50, "tick": 57 * 1200}, {"ghosts": 2})
    assert "superstitious" in h["quirks"], h.get("quirks")


@test("the last seven designed quirks (0.103.18): each earned by its default path")
def _():
    import quirks
    cases = [("sky_reachers", {"surface_share": 0.35}, 169), ("one_stone", {"top_stone_share": 0.75}, 169),
             ("living_walls", {"legendary": 2}, 85), ("hermit_kingdom", {}, 169),
             ("waste_not", {"materials_pd": 2.5}, 169), ("deep_ambition", {"caverns_reached": 2}, 85),
             ("gambler", {"caverns_reached": 1, "magma_forges": 1}, 85)]
    for qid, extra, days in cases:
        h = {"citizen_deaths": 10 if qid == "living_walls" else 0,
             "eras": [{"year": 40}] if qid == "hermit_kingdom" else [{"year": 50}],
             "quirks": {"living_walls": {"legend_proud": {}, "ancestor_halls": {}}, "gambler": {"forge_born": {}}}.get(qid, {})}
        quirks.update(h, {}, None, {"year": 50, "tick": 0}, extra)
        quirks.update(h, {}, None, {"year": 50, "tick": days * 1200}, extra)
        got = list((h.get("quirks") or {}))
        assert qid in got, (qid, got)
    # a fort that traded this year isn't a hermit
    h = {"eras": [{"year": 40}], "last_trade_year": 50}
    quirks.update(h, {}, None, {"year": 50, "tick": 0}, {})
    quirks.update(h, {}, None, {"year": 50, "tick": 169 * 1200}, {})
    assert "hermit_kingdom" not in (h.get("quirks") or {}), h.get("quirks")


@test("leanings (0.104.141): a site lean stays while the lowest dwarf comes and goes; gone after 20 reads missing")
def _():
    import leanings
    near = {"map": {"dwarves": {"z_bottom": 148}, "layers": [{"name": "Cavern1", "z_top": 143}]}}
    far = {"map": {"dwarves": {"z_bottom": 165}, "layers": [{"name": "Cavern1", "z_top": 143}]}}
    h = {"seed": "Teacheroar"}
    leanings.update(h, near)
    has = lambda: any("cavern close" in x["why"] for x in h["leanings"]["site"])
    assert has()
    for i in range(10):
        changed = leanings.update(h, far if i % 2 else near)
        assert has(), i
        assert not any("cavern" in c for c in changed), changed      # not said again each time it comes back
    for _ in range(leanings.SITE_DROP_AFTER - 2):                   # (the last alternation was a miss)
        leanings.update(h, far)
    assert has()
    leanings.update(h, far)
    assert not has() and not h["leanings"]["missing"]


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

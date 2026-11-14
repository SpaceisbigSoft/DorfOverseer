"""(0.105.47, J12) The Design track's D1: Guided live.

    python tests/test_d1_guided.py

- a Guided fort's new levels, every rule's (not only the ladder's), carry its
  language's style keys to the bridge, and the bridge's parse_style takes
  them; an urgent level the form only; a young fort plain; a rule's own key kept;
- each of the six presets' rule languages differs, and so do their levels;
- the landmark cadence at Guided: the language's library landmark, sites ->
  build_blueprint (library) -> building -> built; one a landmark_pace; never
  the AI's drawing; no surface landmark for the Hermit hold or Deep mine;
  sites near a cavern only by the cavern switch;
- Scripts unchanged: guided_pass changes nothing, no landmark starts;
- a fort switched to Guided mid-life: only new levels change (the other
  rules' actions are Scripts' own; districts with a level keep their names);
- the keeper's --preset: apply_preset by the keeper takes a Scripts fort to
  Guided (Architect stays), the window's Load preset doesn't; the overseer's
  design_switch does it once for a fort the preset was applied to before,
  and a later choice in the window stays;
- the scorecard's Design block: the main hall shape, furniture stones and
  landmark kinds lines.
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import make_test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

TMP = Path(tempfile.mkdtemp())
os.environ["DFAI_LOG_DIR"] = str(TMP / "logs")
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))

import design  # noqa: E402
import design_rules  # noqa: E402
import planner_design as PD  # noqa: E402
import planner_guided as PG  # noqa: E402
from planner import TICKS_PER_DAY, TICKS_PER_YEAR, Memory, Proposal, plan, record  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
PRESETS = design_rules.PRESET_SLIDERS


def reset():
    PD._AI_ALLOWED = None
    PD.AI_ON = False
    PD._LIBRARY = None


test = make_test(before=reset)


def fort(design_="guided", traits=None, pace=None) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["settings"] = dict(s["settings"], ai_frequency=0, ai_effort=0,
                         traits=dict(traits if traits is not None else {"grandeur": 40, "militarism": 20}))
    if design_ is not None:
        s["settings"]["design"] = design_
    if pace is not None:
        s["settings"]["landmark_pace"] = pace
    s["needs"] = {"deity_ids": {"Ral": 11}, "deities": {"Ral": 5}}
    s["stone_types"] = [{"token": "GRANITE", "name": "granite", "boulders": 80}]
    return s


def guided_memory(s) -> Memory:
    m = Memory()
    plan(copy.deepcopy(s), m)               # the rule language is written
    assert design.current(m.culture), m.culture.get("design")
    return m


# --- the bridge's parse_style (lua/ai-bridge-actions.lua) and ai-layouts -------------------

def parse_style_env():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lay = (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8")
    src = (ROOT / "lua" / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    fn = re.search(r"\nlocal function parse_style\(st\)\n.*?\nend\n", src, re.S).group(0)
    env = lua.execute("""
        local lay_src = ...
        LAY = setmetatable({}, {__index = _G})
        assert(load(lay_src, 'ai-layouts', 't', LAY))()
        function reqscript(name) if name == 'ai-layouts' then return LAY end error('no ' .. name) end
        function int_in(v, lo, hi)
            v = math.tointeger(tonumber(v)); if v == nil or v < lo or v > hi then return nil end; return v
        end
    """ + fn + "\nreturn parse_style", lay)
    return lua, env


def lua_value(lua, v):
    if isinstance(v, dict):
        t = lua.table()
        for k, x in v.items():
            t[k] = lua_value(lua, x)
        return t
    if isinstance(v, list):
        return lua.table_from([lua_value(lua, x) for x in v])
    return v


# --- 1. every new level in the language -------------------------------------------------

LANG_KEYS = ("hall", "smooth", "statues", "scale", "aspect", "arms", "motif", "orient", "rhythm")


@test("Guided: a rule's level proposed with no style (a workshop, growth's tavern) gets the language's keys")
def _():
    s = fort("guided", PRESETS["Merchant city"])
    m = guided_memory(s)
    s["dwarves"]["total"] = max(60, s["dwarves"].get("total") or 0)
    ps = [Proposal("industry", {"type": "start_project", "kind": "workshops", "shops": ["Kiln"]}, "x", 5),
          Proposal("growth", {"type": "start_project", "kind": "tavern", "tables": 8}, "y", 5),
          Proposal("other", {"type": "work_order", "recipe": "brew_drink", "amount": 5}, "z", 3)]
    before = copy.deepcopy([p.action for p in ps])
    PG.guided_pass(ps, s, m, s["settings"]["traits"])
    lang = design.current(m.culture)
    for p in ps[:2]:
        st = p.action["style"]
        assert st["hall"] == lang["hall"], (st, lang["hall"])
        for k in ("scale", "arms", "motif", "orient", "rhythm"):
            assert k in st, (k, st)
    assert ps[1].action["style"].get("grand") is True, "the tavern is in Merchant city's emphasis: grand"
    assert ps[2].action == before[2], "only start_project levels are touched"
    lua, parse = parse_style_env()
    for p in ps[:2]:
        res = parse(lua_value(lua, p.action["style"]))
        style, err = res if isinstance(res, tuple) else (res, None)
        assert err is None and style is not None, (p.action["style"], err)
        for k in ("hall", "scale", "aspect", "arms", "motif", "grand"):
            if k in p.action["style"]:
                assert style[k] == p.action["style"][k], (k, style[k], p.action["style"][k])


@test("Guided: an urgent level takes the language's form only (no bigger hall, no statues); a rule's own key stands")
def _():
    s = fort("guided", PRESETS["Monastery"])
    m = guided_memory(s)
    ps = [Proposal("mood", {"type": "start_project", "kind": "workshops", "shops": ["Craftsdwarfs"], "urgent": True},
                   "m", 9),
          Proposal("x", {"type": "start_project", "kind": "dining", "tables": 10,
                         "style": {"hall": "plain", "smooth": 0, "spacing": 5}}, "d", 6)]
    PG.guided_pass(ps, s, m, s["settings"]["traits"])
    st = ps[0].action["style"]
    assert set(st) <= set(PG.URGENT_KEYS) and st["hall"] == design.current(m.culture)["hall"], st
    st = ps[1].action["style"]
    assert st["hall"] == "plain" and st["smooth"] == 0 and st["spacing"] == 5, st
    assert "scale" in st and "statues" in st, st


@test("Guided, plan(): every start_project carries the language's hall (the ladder's and every other rule's)")
def _():
    for name in PRESETS:
        s = fort("guided", PRESETS[name])
        m = guided_memory(s)
        ps, _ = plan(copy.deepcopy(s), m)
        lang = design.current(m.culture)
        for p in ps:
            a = p.action
            if a.get("type") == "start_project":
                st = a.get("style") or {}
                assert st.get("hall") == lang["hall"] or a.get("landmark") is not None, (name, a)


# --- 2. the six languages differ ---------------------------------------------------------

@test("each preset's language differs: hall, motif, arms, symmetry, palette and landmark, pairwise")
def _():
    langs = {}
    for name, sl in PRESETS.items():
        s = fort("guided", sl)
        m = guided_memory(s)
        langs[name] = design.current(m.culture)
    keys = {n: (l.get("hall"), l.get("motif"), l.get("arms"), l.get("symmetry"),
                (l.get("materials") or {}).get("palette"), tuple(w["kind"] for w in l.get("landmarks") or []),
                l.get("scale"), l.get("aspect"))
            for n, l in langs.items()}
    names = list(keys)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert keys[a] != keys[b], (a, b, keys[a])
            diff = sum(1 for x, y in zip(keys[a], keys[b]) if x != y)
            assert diff >= 3, (a, b, keys[a], keys[b])
    # the preset's own landmark is the first wish (Hermit and Deep mine: underground ones)
    for name in PRESETS:
        first = (langs[name].get("landmarks") or [{}])[0].get("kind")
        assert first == design_rules.PRESET_BASE[name]["landmarks"][0], (name, first)
    assert len({k[0] for k in keys.values()}) >= 4, "at least four hall shapes among six forts"


@test("the six forts' levels differ too: the same level kind in each fort's style, signatures pairwise apart")
def _():
    sigs = {}
    for name, sl in PRESETS.items():
        s = fort("guided", sl)
        m = guided_memory(s)
        ps = [Proposal("t", {"type": "start_project", "kind": k}, "", 5) for k in ("dining", "bedrooms", "workshops")]
        PG.guided_pass(ps, s, m, sl)
        sigs[name] = {design.signature(p.action["kind"], p.action["style"]) for p in ps}
    names = list(sigs)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert sigs[a] != sigs[b], (a, b, sigs[a])


# --- 3. the landmark cadence -----------------------------------------------------------------

SITES = [{"id": "S1", "ground": "rock", "words": "in the halls district", "near": []},
         {"id": "S2", "ground": "rock", "words": "below the main stair", "near": ["cavern"]},
         {"id": "S3", "ground": "surface", "words": "on open ground", "near": []}]


class Bridge:
    def __init__(self, sites=None):
        self.seen, self.sites = [], sites or SITES

    def __call__(self, a):
        self.seen.append(a)
        t = a["type"]
        if t == "blueprint_sites":
            return {"ok": True, "asked": 1, "sites": copy.deepcopy(self.sites)}
        if t == "build_blueprint":
            return {"ok": True, "landmark_id": 7 + len(self.seen), "project_ids": [301], "levels": 1}
        if t == "landmark_step":
            return {"ok": True, "landmark_id": a["landmark_id"], "stage": "walls"}
        if t == "start_project":
            return {"ok": True, "project_id": 401}
        return {"ok": True}


def cycle(s, m, br, days=1):
    ps, notes = plan(copy.deepcopy(s), m)
    mine = [p for p in ps if p.rule.startswith("landmark")]
    record([(p, br(p.action)) for p in mine], s, m)
    s["date"]["tick"] += days * TICKS_PER_DAY
    return mine, notes


@test("Guided cadence: the preset's library landmark (War-hold's gate hall): sites -> build (library) -> built")
def _():
    s, br = fort("guided", PRESETS["War-hold"]), Bridge()
    m = Memory()
    p1, _ = cycle(s, m, br)
    assert [p.action["type"] for p in p1] == ["blueprint_sites"], [p.action for p in p1]
    assert p1[0].action["purpose"] == "gate_hall", p1[0].action
    p2, _ = cycle(s, m, br)
    assert [p.action["type"] for p in p2] == ["build_blueprint"], [p.action for p in p2]
    a = p2[0].action
    assert a["by"] == "library" and a["purpose"] == "gate_hall" and a["bp"] == PD.library()["gate_hall"], a["by"]
    e = PD.active_landmark(m)
    assert e and e["status"] == "building", e
    lid = e["landmark_id"]
    # within the season: nothing new
    for _ in range(3):
        p, _ = cycle(s, m, br, days=5)
        assert not [x for x in p if x.action["type"] in ("blueprint_sites", "build_blueprint")]
    s["landmarks"] = {"list": [{"id": lid, "status": "built"}]}
    cycle(s, m, br)
    assert m.atlas["landmarks"]["list"][-1]["status"] == "built"
    started = m.atlas["landmarks"]["last_started"]
    p, _ = cycle(s, m, br)
    assert not [x for x in p if x.action["type"] == "blueprint_sites"], "one a season: not yet"
    # a season on: the next wish of the language, or nothing (each wish once)
    s["date"]["tick"] = started + TICKS_PER_YEAR // 4 + TICKS_PER_DAY
    p, _ = cycle(s, m, br)
    kinds = {x.action.get("purpose") for x in p if x.action["type"] == "blueprint_sites"}
    assert "gate_hall" not in kinds, kinds
    lang = design.current(m.culture)
    assert kinds <= {w["kind"] for w in lang.get("landmarks") or []}, (kinds, lang.get("landmarks"))


@test("Guided cadence: landmark_pace never or year, and the AI never draws at Guided (design_ai on)")
def _():
    s = fort("guided", PRESETS["War-hold"], pace="never")
    ps, _ = plan(copy.deepcopy(s), Memory())
    assert not [p for p in ps if p.rule.startswith("landmark")]
    PD._AI_ALLOWED, PD.AI_ON = True, True
    try:
        s, br, m = fort("guided", PRESETS["War-hold"]), Bridge(), Memory()
        m.culture = {}
        from culture import new_history
        m.culture = new_history()
        PD.design_rule(s, s["settings"]["traits"], __import__("planner").PLANNER_CONFIG, [], [], m)
        # (the AI's turn for the language may hold it a grace; the rules stand in after)
        s["date"]["tick"] += PD.DESIGN_GRACE_TICKS + TICKS_PER_DAY
        for _ in range(3):
            cycle(s, m, br)
        e = (PD.landmarks_of(m) or {}).get("list") or []
        assert e and all(x["by"] == "library" for x in e), e
        assert all(a.get("by") in (None, "library") for a in br.seen), br.seen
    finally:
        reset()


@test("Guided: no surface landmark for the Hermit hold or the Deep mine; the Garden's ziggurat is surface")
def _():
    for name in ("Hermit hold", "Deep mine"):
        s, br, m = fort("guided", PRESETS[name]), Bridge(), Memory()
        p1, _ = cycle(s, m, br)
        for p in p1:
            assert p.action["env"]["ground"] == "rock", (name, p.action)
        assert p1 and p1[0].action["purpose"] == design_rules.PRESET_BASE[name]["landmarks"][0], (name, p1)
    s, br, m = fort("guided", PRESETS["Garden fort"]), Bridge(), Memory()
    p1, _ = cycle(s, m, br)
    assert p1 and p1[0].action["purpose"] == "ziggurat" and p1[0].action["env"]["ground"] == "surface", p1


@test("sites near a cavern: left out at Never, and at AI decides with a cavern not found yet; kept at Always")
def _():
    for mode, kept in (("never", False), ("always", True)):
        s, br, m = fort("guided", PRESETS["War-hold"]), Bridge(), Memory()
        s["settings"]["open_caverns"] = mode
        cycle(s, m, br)
        ids = [x["id"] for x in m.atlas["landmarks"]["sites"]["list"]]
        assert ("S2" in ids) is kept, (mode, ids)
    s = fort("guided")
    s["settings"]["open_caverns"] = "ai"
    s["map"] = {"layers": [{"name": "Cavern1", "z": 30}]}
    s["water"] = {"bodies": []}
    unfound = __import__("planner_wells").unfound_cavern(s)
    assert PD.cavern_edge_ok(s) is (not unfound), unfound
    # every site near a cavern and the switch says no: no site (a try counted)
    s, m = fort("guided", PRESETS["War-hold"]), Memory()
    s["settings"]["open_caverns"] = "never"
    br = Bridge([dict(SITES[1])])
    _, notes = cycle(s, m, br)
    e = (PD.landmarks_of(m) or {})["list"][-1]
    assert e["tries"] == 1 and e["status"] != "building", e


# --- 4. Scripts unchanged -------------------------------------------------------------------------

@test("Scripts: guided_pass changes nothing, no landmark starts, no district renamed")
def _():
    s = fort("scripts", PRESETS["Merchant city"])
    m = Memory()
    m.atlas = {"plan": {"districts": [{"id": "halls", "kind": "halls", "name": "the Old Halls", "levels": []}]}}
    ps = [Proposal("industry", {"type": "start_project", "kind": "workshops", "shops": ["Kiln"]}, "x", 5)]
    before = copy.deepcopy([p.action for p in ps])
    PG.guided_pass(ps, s, m, s["settings"]["traits"])
    assert [p.action for p in ps] == before
    ps, _ = plan(copy.deepcopy(s), m)
    assert not [p for p in ps if p.rule.startswith("landmark")]
    assert m.atlas["plan"]["districts"][0]["name"] == "the Old Halls"
    assert "design" not in (m.culture or {}) or (m.culture["design"].get("mode") == "scripts")
    # no design key at all reads Scripts the same
    s2 = fort(None, PRESETS["Merchant city"])
    a, _ = plan(copy.deepcopy(s), Memory())
    b, _ = plan(copy.deepcopy(s2), Memory())
    assert [json.dumps(p.action, sort_keys=True) for p in a] == [json.dumps(p.action, sort_keys=True) for p in b]


# --- 5. switched to Guided mid-life: only new levels -------------------------------------------

@test("switched mid-life: every other action is Scripts' own; only new levels gain the style; built districts keep names")
def _():
    s = fort("scripts", PRESETS["Garden fort"])
    s["projects"]["open"] = [{"id": 55, "kind": "dining", "phase": "furnish", "params": {"style": {"hall": "plain"}}}]
    m = Memory()
    plan(copy.deepcopy(s), m)
    m.atlas = dict(m.atlas or {}, plan={"districts": [
        {"id": "halls", "kind": "halls", "name": "the Old Halls", "levels": [{"id": 55}], "missed": 0},
        {"id": "homes", "kind": "homes", "name": "the Old Homes", "levels": [], "missed": 0}]})
    m_scripts = copy.deepcopy(m)
    a, _ = plan(copy.deepcopy(s), m_scripts)
    g = fort("guided", PRESETS["Garden fort"])
    g["projects"] = copy.deepcopy(s["projects"])
    b, _ = plan(copy.deepcopy(g), m)

    def others(ps):
        # a new farm level (farm_plots with dig) has a style too: its style is a new level's, the rest the same
        return sorted(json.dumps({k: v for k, v in p.action.items() if k != "style"}, sort_keys=True) for p in ps
                      if p.action.get("type") != "start_project" and not p.rule.startswith("landmark"))
    assert others(a) == others(b), (set(others(a)) ^ set(others(b)))
    for p in b:
        assert p.action.get("project_id") != 55 or p.action.get("type") in ("finish_project", "furnish_project"), \
            p.action
    d = {x["id"]: x for x in m.atlas["plan"]["districts"]}
    assert d["halls"]["name"] == "the Old Halls", "a district with a level keeps its name"
    assert d["homes"]["name"] != "the Old Homes" and d["homes"].get("named_by") == "design", d["homes"]
    words = design.naming(m.culture)["words"]
    assert any(w in d["homes"]["name"] for w in words) or "the" in d["homes"]["name"], d["homes"]
    named = d["homes"]["name"]
    plan(copy.deepcopy(g), m)
    assert d["homes"]["name"] == named, "named once"


# --- 6. the keeper's --preset ----------------------------------------------------------------------

import test_preset as TP  # noqa: E402  (the bridge and the settings with a stub DFHack)


@test("apply_preset by the keeper: a Scripts fort (old save) goes to Guided; Architect stays; the window's Load doesn't")
def _():
    for name in TP.PRESETS:
        TP.reset()
        TP.H.persist["ai-overseer/settings"] = TP.t({"version": 2, "mode": "autopilot"})
        r = TP.act({"type": "apply_preset", "name": name})
        assert r.ok and TP.saved().design == "guided" and r.settings.design == "guided", name
        assert r.rules.design == "guided", name
    TP.reset()
    TP.H.persist["ai-overseer/settings"] = TP.t({"version": 2, "design": "architect"})
    r = TP.act({"type": "apply_preset", "name": "Garden fort"})
    assert r.ok and TP.saved().design == "architect" and r.rules.design is None
    # a dry run saves nothing
    TP.reset()
    TP.H.persist["ai-overseer/settings"] = TP.t({"version": 2, "mode": "autopilot"})
    r = TP.act({"type": "apply_preset", "name": "Deep mine", "dry_run": True})
    assert r.ok and TP.saved().design is None
    # the window's Load preset keeps the fort's design
    S = TP.H.settings()
    s = S.defaults()
    s.design = "scripts"
    assert S.load_preset("Monastery", s).design == "scripts"


import overseer  # noqa: E402


class FakeBridge:
    def __init__(self, ok=True):
        self.acts, self.ok = [], ok

    def act(self, a):
        self.acts.append(a)
        if a["type"] == "set_rules":
            return {"ok": self.ok, "changed": {"design": {"old": "scripts", "new": a["rules"]["design"]}}}
        return {"ok": True}


@test("the overseer: a fort --preset applied before the Design track goes to Guided once; the window's later choice stays")
def _():
    overseer.PRESET_FILE.parent.mkdir(parents=True, exist_ok=True)
    overseer.PRESET_FILE.write_text(json.dumps({"region4#7": {"name": "Garden fort", "run": "r1"}}))
    overseer.PRESET = "Garden fort"
    overseer.PRESET_DONE.clear()
    try:
        state = {"settings": {"design": "scripts", "preset": "Garden fort"}}
        br = FakeBridge()
        overseer.apply_preset(br, state, "region4#7", True)
        assert [a["type"] for a in br.acts] == ["set_rules"] and br.acts[0]["rules"] == {"design": "guided"}, br.acts
        assert br.acts[0]["dry_run"] is False
        assert state["settings"]["design"] == "guided"
        rec = json.loads(overseer.PRESET_FILE.read_text())["region4#7"]
        assert rec["design"] == "guided" and rec["run"] == "r1", rec
        # a restart (a new process): the player chose Scripts in the window since: left alone
        overseer.PRESET_DONE.clear()
        state = {"settings": {"design": "scripts", "preset": "Garden fort"}}
        br = FakeBridge()
        overseer.apply_preset(br, state, "autosave 1#7", True)
        assert br.acts == [] and state["settings"]["design"] == "scripts", br.acts
        assert json.loads(overseer.PRESET_FILE.read_text())["autosave 1#7"]["design"] == "guided"
        # a dry run (no --autopilot) changes nothing and marks nothing
        overseer.PRESET_FILE.write_text(json.dumps({"region4#8": {"name": "Garden fort", "run": "r1"}}))
        overseer.PRESET_DONE.clear()
        state = {"settings": {"design": "scripts", "preset": "Garden fort"}}
        br = FakeBridge()
        overseer.apply_preset(br, state, "region4#8", False)
        assert br.acts[0]["dry_run"] is True and state["settings"]["design"] == "scripts"
        assert "design" not in json.loads(overseer.PRESET_FILE.read_text())["region4#8"]
        # Guided or Architect already: nothing asked
        assert not overseer.design_due("region4#8", {"design": "architect"})
        # a fresh preset (the site cleared): the bridge's apply_preset sets it, and the site is marked
        overseer.PRESET_FILE.write_text("{}")
        overseer.PRESET_DONE.clear()

        class PB(FakeBridge):
            def act(self, a):
                self.acts.append(a)
                return {"ok": True, "traits": {}, "rules": {"design": "guided"}, "previous": None,
                        "settings": {"design": "guided", "preset": "Garden fort"}}
        br = PB()
        state = {"settings": {"design": "scripts"}}
        overseer.apply_preset(br, state, "region4#9", True)
        assert [a["type"] for a in br.acts] == ["apply_preset"] and state["settings"]["design"] == "guided"
        assert json.loads(overseer.PRESET_FILE.read_text())["region4#9"]["design"] == "guided"
    finally:
        overseer.PRESET = None
        overseer.PRESET_DONE.clear()


# --- 7. the scorecard's Design block ------------------------------------------------------------

@test("scorecard: the main hall shape, furniture stones and landmark kinds lines, fort by fort")
def _():
    import scorecard
    j = {"levels": [{"kind": "dining", "style": {"hall": "round"}}, {"kind": "bedrooms", "style": {"hall": "round"}},
                    {"kind": "temple", "style": {"hall": "nave"}}],
         "landmarks": [{"ok": True, "by": "library", "purpose": "ziggurat", "rejected": False, "name": "Z"}],
         "stones": {"INORGANIC:GRANITE": 3, "INORGANIC:MARBLE": 1}, "until": None}
    k = {"levels": [{"kind": "dining", "style": {"hall": "cruciform"}}], "landmarks": [], "stones": {}, "until": None}
    dm = {"G": scorecard.design_measures({"settings": {"design": "guided"}}, j),
          "W": scorecard.design_measures({"settings": {"design": "guided"}}, k)}
    assert dm["G"]["main_hall"] == "round" and dm["G"]["stones_used"] == 2 and dm["G"]["landmark_kinds"] == ["ziggurat"]
    md, _ = scorecard.design_section(["G", "W"], dm)
    text = "\n".join(md)
    assert "| main hall shape | round | cruciform |" in text, text
    assert "| furniture stones ordered | 2 | 0 |" in text and "| landmark kinds begun | ziggurat | none |" in text
    assert "Hall shapes: 2 main shapes among 2 forts (2 a shape of its own)." in text
    # the journal pass counts the stone of a furniture order
    rows = [{"kind": "decision", "date": {"year": 1, "tick": 10},
             "action": {"type": "work_order", "recipe": "stone_table", "amount": 2, "material": "INORGANIC:GRANITE"},
             "result": {"ok": True}}]
    jc = scorecard.journal_counts(rows + [dict(rows[0], action=dict(rows[0]["action"], recipe="wood_table"))],
                                  {"year": 2, "tick": 0})
    assert dict(jc["stones"]) == {"INORGANIC:GRANITE": 1}, jc["stones"]

if __name__ == "__main__":
    finish()

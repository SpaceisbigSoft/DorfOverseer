"""(r10 p3) Initial contact for every fort, then contact and raids by the
fort's character (the player, 22 Nov 00:51): brain/planner_contact.py, its
wiring in brain/planner_world.py and brain/planner_raids.py, and the new
defaults in lua/ai-overseer-settings.lua (an old save's old defaults read as
the new ones; the player's own choice kept), in a real Lua engine (lupa,
Lua 5.3).

    python tests/test_r10_p3.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import test_preset as TP  # noqa: E402  (the settings with a stub DFHack)
import test_r47_raids as TR  # noqa: E402  (its raid fakes; its tests don't run again)
import planner_contact as PC  # noqa: E402
import planner_world as W  # noqa: E402
import planner_raids as PR  # noqa: E402
from planner import PLANNER_CONFIG, Memory, Proposal, TICKS_PER_DAY, TICKS_PER_YEAR, abs_tick, note_cycle, plan  # noqa: E402
from planner_core import player_rules  # noqa: E402

CFG = PLANNER_CONFIG
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
PRESETS = TP.PRESETS


def py(v):
    """A Lua table as Python (dicts; lists when keyed 1..n)."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    keys = list(v.keys())
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in sorted(keys)]
    return {k: py(v[k]) for k in keys}


def preset_settings(name: str | None) -> dict:
    """The settings the brain gets for a new fort given this preset (None: no preset)."""
    TP.reset()
    S = TP.H.settings()
    s = S.defaults() if name is None else S.load_preset(name, S.defaults())
    return py(S.for_ai(s))


SITES = [{"id": 6, "name": "Old Tomb", "relation": "NoContact", "dist": 2, "type": "Monument", "owner_civ": 31},
         {"id": 7, "name": "Far Hall", "relation": "Peace", "dist": 3, "type": "MountainHalls", "owner_civ": 30},
         {"id": 9, "name": "Cottageflings", "relation": "NoContact", "dist": 5, "type": "Town", "owner_civ": 32},
         {"id": 8, "name": "Dark Pits", "relation": "NoContact", "dist": 12, "type": "Hamlet", "owner_civ": 33},
         {"id": 5, "name": "Leafy Rest", "relation": "NoContact", "dist": 30, "type": "ForestRetreat", "owner_civ": 34}]
HELD = {"offices": {"MESSENGER": {"vacant": 0, "held": ["Urist"], "appointable": True}}}


def fort(settings=None, sites=None, send=None, world=None, controllers=()) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    if settings is not None:
        s["settings"] = copy.deepcopy(settings)
    s["offices"] = copy.deepcopy(HELD)
    s["missions"] = {"controllers": list(controllers), "sites": {"nearest": copy.deepcopy(SITES if sites is None else sites)},
                     "send": send if send is not None else {"buttons": ["Diplomacy", "World"], "on": True}}
    s["world"] = world if world is not None else {}
    return s


def contact(props) -> list:
    return [p for p in props if p.rule == "contact" and p.action.get("goal") == "make_contact"]


def sent_outcome(s: dict, sid: int, result="sent", reason=None, ago=0) -> None:
    o = {"goal": "make_contact", "site_id": sid, "site": f"Site{sid}", "result": result, "tick": abs_tick(s) - ago}
    if reason:
        o["reason"] = reason
    s["missions"]["send"]["last_by_goal"] = {"make_contact": o}


def later(s: dict, days: int) -> dict:
    s2 = copy.deepcopy(s)
    s2["date"]["tick"] += days * TICKS_PER_DAY
    s2["missions"]["send"].pop("last_by_goal", None)
    return s2


def done_memory(at: int) -> Memory:
    m = Memory()
    m.world_seen = {"contacts": {"sites": {}, "initial_done": at}}
    return m


# --- initial contact --------------------------------------------------------------------------------

@test("initial contact: every preset (the Hermit hold too) and a fort without one sends Make contact to the nearest "
      "site people live in that it isn't in contact with (never a monument), with the switches as they come")
def _():
    for name in [None] + PRESETS:
        st = preset_settings(name)
        assert st["send_messenger"] is True and st["make_contact"] is True, (name, st.get("send_messenger"))
        assert st["raid_policy"] == "ai" and st["send_missions"] is True and st["missions"] == "all", name
        s = fort(st)
        m = Memory()
        note_cycle(s, m)
        props, notes = plan(s, m)
        p = contact(props)
        assert p and p[0].action == {"type": "send_mission", "goal": "make_contact", "site_id": 9}, (name, notes)
        assert "initial contact (1 of up to 4)" in p[0].reason, p[0].reason


@test("initial contact is booked per site and not repeated: the next site after the gap, a site in contact booked "
      "made, DF's no booked failed and never tried again, then initial contact done")
def _():
    s = fort(preset_settings("Hermit hold"))
    m = Memory()
    sent_outcome(s, 9)
    note_cycle(s, m)
    e = PC.contact_book(m)["sites"]["9"]
    assert e["st"] == "sent" and e["k"] == "initial", e
    # within the gap: nothing; after it: the next site, never 9 again
    assert not contact(plan(later(s, 3), m)[0])
    s2 = later(s, 15)
    note_cycle(s2, m)
    p = contact(plan(s2, m)[0])
    assert p and p[0].action["site_id"] == 8, p
    # 9 in contact now: made
    s3 = later(s2, 1)
    s3["missions"]["sites"]["nearest"][2]["relation"] = "Peace"
    note_cycle(s3, m)
    assert PC.contact_book(m)["sites"]["9"]["st"] == "made"
    # DF says no to 8: failed, never again; 5 (30 tiles, inside 40) is next
    s4 = later(s3, 1)
    sent_outcome(s4, 8, result="stopped", reason="unavailable")
    note_cycle(s4, m)
    assert PC.contact_book(m)["sites"]["8"]["st"] == "failed"
    s5 = later(s4, 20)
    note_cycle(s5, m)
    p = contact(plan(s5, m)[0])
    assert p and p[0].action["site_id"] == 5, p
    sent_outcome(s5, 5)
    note_cycle(s5, m)
    # nothing left once 5 is sent: initial contact done, said that cycle
    book = PC.contact_book(m)
    assert book.get("initial_done") == abs_tick(s5), book
    props, notes = plan(s5, m)
    assert not contact(props) and any(n.startswith("initial contact done: 3 site(s)") for n in notes), notes
    # the Hermit then sends nobody as routine, and says why
    s6 = later(s5, 400)
    s6["missions"]["sites"]["nearest"].append({"id": 4, "name": "New Town", "relation": "NoContact", "dist": 7,
                                               "type": "Town", "owner_civ": 35})
    note_cycle(s6, m)
    props, notes = plan(s6, m)
    assert not contact(props) and not any("initial contact done" in n for n in notes)
    assert any(n.startswith("contact: ") and "Outsiders -150" in n for n in notes), notes


@test("initial contact: at most contact_initial_max sites, within contact_initial_tiles (the nearest always)")
def _():
    far = [{"id": 40 + i, "name": f"Town{i}", "relation": "NoContact", "dist": 50 + i, "type": "Town", "owner_civ": 60 + i}
           for i in range(3)]
    st = PC.initial_state(fort(sites=far), Memory(), CFG)
    assert [x["id"] for x in st["candidates"]] == [40], st          # all beyond 40 tiles: the nearest one only
    many = [{"id": 40 + i, "name": f"Town{i}", "relation": "NoContact", "dist": 3 + i, "type": "Town", "owner_civ": 60 + i}
            for i in range(7)]
    st = PC.initial_state(fort(sites=many), Memory(), CFG)
    assert len(st["candidates"]) == CFG["contact_initial_max"] == 4


@test("initial contact held: a threat, a siege, the civilian alert, a crisis, the player's World screen open")
def _():
    st = preset_settings("Merchant city")
    s = fort(st, world={"sieges": [{"id": 200, "active": True, "n": 1}]})
    props, notes = plan(s, Memory())
    assert not contact(props) and any("not while a siege is on" in n for n in notes), notes
    s = fort(st)
    s["civ_alert"] = True
    assert not contact(plan(s, Memory())[0])
    m = Memory()
    m.crisis = {"since": 1, "why": ["tantrums"]}
    assert PC.contact_hold(fort(st), m, CFG) == "the fort is in crisis"
    assert W._contact_site(fort(st), m) is None
    s = fort(st)
    s["missions"]["screen"] = {"view_mode": "NORMAL"}
    props, notes = plan(s, Memory())
    assert not contact(props) and any("World screen is open" in n for n in notes), notes
    orig = W.reachable_threats
    W.reachable_threats = lambda *a, **k: [1]
    try:
        props, notes = plan(fort(st), Memory())
    finally:
        W.reachable_threats = orig
    assert not contact(props) and any("not while a threat is near" in n for n in notes), notes
    # the messenger out: one mission at a time
    s = fort(st, controllers=[{"goal": "DIPLOMACY", "site": "Cottageflings", "site_id": 9, "returning": False}])
    assert not contact(plan(s, Memory())[0])


# --- after initial contact: by character --------------------------------------------------------------

@test("after initial contact: open forts make routine contact often, measured once a year, the Hermit never as routine")
def _():
    sites = [dict(x) for x in SITES]
    now = abs_tick(fort())
    for name, days, want in (("Merchant city", 29, True), ("Merchant city", 20, False),
                             (None, 100, False), (None, 340, True), ("Hermit hold", 1000, False)):
        st = preset_settings(name)
        s = fort(st, sites=sites)
        m = done_memory(now - days * TICKS_PER_DAY)
        m.world_seen["contact_said"] = now - days * TICKS_PER_DAY
        props, notes = plan(s, m)
        p = contact(props)
        assert bool(p) == want, (name, days, notes)
        if p:
            assert p[0].action["site_id"] == 9 and ("Outsiders" in p[0].reason or "Trade" in p[0].reason), p[0].reason
        else:
            assert W._contact_site(s, m) is None
    assert PC.contact_stance({"settings": {"traits": {"outsiders": -150}}})[0] == "closed"
    assert PC.contact_stance({"settings": {"traits": {"trade": 120}}})[0] == "open"
    assert PC.contact_stance({"settings": {"traits": {}}})[0] == "measured"


@test("the Hermit hold makes contact when the situation calls for it: an attack while short of friends, a war to "
      "end, a needed trade; each says why")
def _():
    st = preset_settings("Hermit hold")
    now = abs_tick(fort())
    year = BASE["date"]["year"]
    # attacked this year by civ 200, no friends: looks for friends (not the attacker's site)
    world = {"civs": [{"id": 200, "relation": "TotalWar", "name": "Goblins"}, {"id": 32, "relation": "Peace"}],
             "sieges": [{"id": 200, "n": 1, "last_year": year, "name": "Goblins", "active": False}]}
    sites = [dict(x) for x in SITES]
    sites[2]["owner_civ"] = 200          # Cottageflings: the attacker's
    s = fort(st, sites=sites, world=world)
    m = done_memory(now - 400 * TICKS_PER_DAY)
    p = contact(plan(s, m)[0])
    assert p, plan(s, m)[1]
    # a war to end comes first: Cottageflings is the enemy's, not in contact
    assert p[0].action["site_id"] == 9 and "a war with Goblins to end" in p[0].reason, p[0].reason
    # the Rules refuse peace: then friends against the attacker (not its site)
    s2 = fort(dict(st, peace="refuse"), sites=sites, world=world)
    p = contact(plan(s2, m)[0])
    assert p and p[0].action["site_id"] == 8 and "Goblins attacked the fort" in p[0].reason \
        and "looks for more" in p[0].reason, p and p[0].reason
    # a needed trade (a strange mood's material), no caravan this year
    s3 = fort(st)
    import planner_moods
    orig = planner_moods.mood_trade_wants
    planner_moods.mood_trade_wants = lambda s: [{"key": "BAR:SILVER", "count": 1}]
    try:
        p = contact(plan(s3, m)[0])
    finally:
        planner_moods.mood_trade_wants = orig
    assert p and "a strange mood waits for bar:silver" in p[0].reason and "trade partner" in p[0].reason, p
    # nothing of the kind: nothing, and the note says why
    props, notes = plan(fort(st), m)
    assert not contact(props) and any("nothing calls for it now" in n for n in notes), notes


@test("raids by character after initial contact: the War-hold raids an enemy but never a friend; the Monastery "
      "doesn't; the Hermit hold only strikes back")
def _():
    year = TR.YEAR
    world = {"civs": [{"id": 21, "relation": "Peace"}, {"id": 22, "relation": "Peace"},
                      {"id": 23, "relation": "Peace"}, {"id": 24, "relation": "Peace"}],
             "caravans": [{"civ_id": 21}]}
    # civ 21's caravan is here (a friend); civ 22 is kept as the second friend at peace (raid_friends_min)
    rows = [TR.site(1, 21, 2, pop=3, typ="Hamlet"), TR.site(2, 24, 6, pop=3, typ="Hamlet")]

    def go(name, rows_, world_):
        st = preset_settings(name)
        s = TR.fort(rows_, world=world_)
        s["settings"] = dict(st, traits=st["traits"])
        return TR.sent(TR.rule(s, TR.Mem())[0])
    a = go("War-hold", rows, world)
    assert a and a[0].action["site_id"] == 2 and a[0].action["policy"] == "aggressive", a   # 1's caravan: a friend
    assert not any(x.action["site_id"] == 1 for x in a)
    assert not go("Monastery", rows, world)
    assert not go("Hermit hold", rows, world)
    # the Hermit hold retaliates: civ 24 besieged it this year and is at war
    w2 = copy.deepcopy(world)
    w2["civs"][3]["relation"] = "TotalWar"
    w2["sieges"] = [{"id": 24, "n": 1, "last_year": year, "last_siege": True, "name": "Civ24"}]
    a = go("Hermit hold", rows, w2)
    assert a and a[0].action["site_id"] == 2 and a[0].action["policy"] == "retaliation", a


@test("the aggressive fort waits for initial contact before raiding a civ that didn't attack it")
def _():
    rows = [TR.site(2, 26, 6, pop=3, typ="Hamlet")]          # civs 22 and 25 kept as the two friends at peace
    s = TR.fort(rows, world={"civs": [{"id": c, "relation": "Peace"} for c in (22, 25, 26)]}, militarism=150)
    s["offices"] = HELD
    s["missions"]["sites"] = {"nearest": [{"id": 9, "name": "Cottageflings", "relation": "NoContact", "dist": 5,
                                           "type": "Town", "owner_civ": 32}]}
    s["settings"]["send_messenger"] = True
    p, notes = TR.rule(s, TR.Mem())
    assert not TR.sent(p) and any("initial contact comes first" in n for n in notes), notes
    m = TR.Mem()
    m.world_seen = {"contacts": {"sites": {}, "initial_done": TR.NOW - TICKS_PER_DAY}}
    assert TR.sent(TR.rule(s, m)[0])[0].action["site_id"] == 2
    # the player forced 'aggressive': no wait
    s["settings"]["raid_policy"] = "aggressive"
    assert TR.sent(TR.rule(s, TR.Mem())[0])


# --- the player's switches ---------------------------------------------------------------------------

@test("the player's switches override: send_messenger off names the site for you, make_contact off nothing, "
      "Raids off no raid")
def _():
    st = preset_settings("Merchant city")
    s = fort(dict(st, send_messenger=False))
    props, notes = plan(s, Memory())
    assert not contact(props) and any("Make contact (13b)" in n and "initial contact" in n for n in notes), notes
    s = fort(dict(st, make_contact=False))
    props, notes = plan(s, Memory())
    assert not contact(props) and not any("Make contact" in n for n in notes)
    rows = [TR.site(2, 22, 6, pop=3, typ="Hamlet")]
    s = TR.fort(rows, world={"civs": [{"id": 22, "relation": "Peace"}]}, militarism=150, raid_policy="off")
    assert not TR.sent(TR.rule(s, TR.Mem())[0])


@test("settings: an old save's old defaults read as the new ones, the player's explicit choices are kept, and a "
      "save with contact_rev keeps its off; an old preset file's old defaults are dropped")
def _():
    TP.reset()
    S = TP.H.settings()
    TP.H.persist["ai-overseer/settings"] = TP.t({"version": 2, "send_messenger": False, "send_missions": False,
                                                 "raid_policy": "off", "missions": "rescue", "construct": False})
    s = S.load_settings()
    assert s.send_messenger is True and s.send_missions is True and s.raid_policy == "ai" and s.missions == "all"
    assert s.construct is False and s.contact_rev == S.CONTACT_REV
    TP.H.persist["ai-overseer/settings"] = TP.t({"version": 2, "raid_policy": "reactive", "missions": "explore"})
    s = S.load_settings()
    assert s.raid_policy == "reactive" and s.missions == "explore"           # chosen by the player: kept
    # saved once (the window, set_rules): the stamp keeps the player's off from then on
    s.send_messenger = False
    S.save_settings(s)
    back = S.load_settings()
    assert back.send_messenger is False and back.raid_policy == "reactive"
    r = TP.act({"type": "set_rules", "rules": {"send_messenger": False, "raid_policy": "off"}})
    assert r.ok and TP.saved().send_messenger is False and TP.saved().raid_policy == "off"
    # an old preset file (no contact_rev) with the old defaults: those dropped, its other choices applied
    TP.reset()
    S = TP.H.settings()
    TP.H.preset_files["/df/dfhack-config/ai-overseer/presets/Mine.json"] = TP.t(
        {"version": 2, "traits": {}, "rules": {"send_messenger": False, "raid_policy": "off", "missions": "rescue",
                                               "send_missions": False, "accept_visitors": False}})
    p = S.load_preset("Mine", S.defaults())
    assert p.send_messenger is True and p.raid_policy == "ai" and p.missions == "all" and p.send_missions is True
    assert p.accept_visitors is False
    # a preset saved now carries contact_rev, and its off is the player's
    s = S.defaults()
    s.send_messenger = False
    S.save_preset("Mine2", s)
    p = S.load_preset("Mine2", S.defaults())
    assert p.send_messenger is False


@test("dry run changes nothing: a dry-run send stamps nothing, planning writes no contact book, apply_preset and "
      "set_rules dry runs save nothing")
def _():
    s = fort(preset_settings("Deep mine"))
    m = Memory()
    note_cycle(s, m)
    before = copy.deepcopy(m.world_seen)
    plan(s, m)
    assert m.world_seen == before
    p = Proposal("contact", {"type": "send_mission", "goal": "make_contact", "site_id": 9, "dry_run": True}, "x", 7)
    W.note_contact_sent(p, {"ok": True, "dry_run": True}, s, m)
    assert m.world_seen == before
    TP.reset()
    r = TP.act({"type": "apply_preset", "name": "Hermit hold", "dry_run": True})
    assert r.ok and TP.H.persist["ai-overseer/settings"] is None
    r = TP.act({"type": "set_rules", "rules": {"send_messenger": False}, "dry_run": True})
    assert r.ok and TP.H.persist["ai-overseer/settings"] is None


@test("the book stays small (BOOK_MAX) and stopped runs give up after TRIES_MAX")
def _():
    s = fort()
    m = Memory()
    for i in range(PC.TRIES_MAX):
        s2 = later(s, i)
        sent_outcome(s2, 9, result="stopped", reason="not_recorded")
        note_cycle(s2, m)
    assert PC.contact_book(m)["sites"]["9"]["st"] == "failed", PC.contact_book(m)
    assert 9 not in [x["id"] for x in PC.contact_candidates(s, m)]
    book = PC.contact_book(m, create=True)
    for i in range(PC.BOOK_MAX + 10):
        book["sites"][str(100 + i)] = {"st": "made", "t": i}
    note_cycle(later(s, 5), m)
    assert len(PC.contact_book(m)["sites"]) <= PC.BOOK_MAX


@test("the changed Lua compiles under Lua 5.3 and stays under 60 KB")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    for rel in ("lua/ai-overseer-settings.lua", "lua/gui/ai-overseer-rules.lua", "lua/ai-mission-send.lua"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        ok = lua.eval("function(src) local f, e = load(src, 'b', 't', {}); return f ~= nil, e end")(src)
        assert ok[0], (rel, ok)
        assert len(src.encode("utf-8")) < 60_000, rel


if __name__ == "__main__":
    finish()

"""planner_core_rules: part of planner_core (split out of planner_core.py in r7, which re-exports every
name): the player's Rules switches (player_rules, Needs you notes, levels refused) and the graded
sliders (growth, mining, noble rooms)."""

from __future__ import annotations
from quirks import has_rule
from digest import _d
from planner_config import PLANNER_CONFIG
from planner_core_base import factor, GEAR_WEAPONS, MEMORIAL_SPAN, OPTIONAL_LEVELS


# Notes for what the game truly won't let the AI do (a screen it can't press,
# a choice DFHack can't make), each saying what the AI does meanwhile. The
# overseer shows them apart: "Needs you". (0.105.35, the player's standing
# decision: nothing waits for the player; what the AI can do, it does.)
NEEDS_YOU = "[you] "


def ask_player(notes: list, text: str) -> None:
    notes.append(NEEDS_YOU + text)


DISPOSAL_LEVELS = ("store", "melt", "dump", "destroy")   # (0.105.27) the Rules key `disposal`, in order


def player_rules(s: dict) -> dict:
    """The Rules tab (lua/ai-overseer-settings.lua), with its defaults when an
    older panel didn't send them."""
    st = s["settings"] if isinstance(s.get("settings"), dict) else {}
    levels = st.get("levels") if isinstance(st.get("levels"), dict) else {}
    pace = st.get("memorial_pace")
    attack = st.get("attack_policy")
    return {"memorial_pace": pace if pace in MEMORIAL_SPAN or pace == "never" else "season",
            "attack_policy": attack if attack in ("all", "ordinary", "never") else "ordinary",
            "fill_squads": st.get("fill_squads") is not False,
            "train_squads": st.get("train_squads") is not False,
            "appoint_nobles": st.get("appoint_nobles") is not False,
            "gate_lever": st.get("gate_lever") is not False,
            "make_gear": st.get("make_gear") is not False,
            "gear_weapon": st.get("gear_weapon") if st.get("gear_weapon") in GEAR_WEAPONS else "axe",
            "engrave_slabs": st.get("engrave_slabs") is not False,
            "import_smelting": st.get("import_smelting") is not False,
            "alert_shelter": st.get("alert_shelter") is not False,
            "pasture_animals": st.get("pasture_animals") is not False,
            "build_gate_doors": st.get("build_gate_doors") is not False,
            "fortify_entrances": st.get("fortify_entrances") is not False,
            "fort_goal": "maintain" if st.get("fort_goal") == "maintain" else "expand",
            "set_pop_cap": st.get("set_pop_cap") is not False,
            "levels": {k: levels.get(k) is not False for k in OPTIONAL_LEVELS},
            "order_supplies": st.get("order_supplies") is not False,
            "mood_workshops": st.get("mood_workshops") is not False,
            "give_trinkets": st.get("give_trinkets") is not False,
            "water_works": st.get("water_works") is not False,
            "expel_vampires": st.get("expel_vampires") is not False,
            "accept_visitors": st.get("accept_visitors") is not False,
            "answer_locations": st.get("answer_locations") is not False,
            # (0.104.167, review) the hospital burrow: off only when the settings say so (then its members let out)
            "hospital_burrow": st.get("hospital_burrow") is not False,
            # (0.104.169) the calm-down burrows: off only when the settings say so (then their members let out)
            "calm_burrow": st.get("calm_burrow") is not False,
            # the in-game fight watcher (lua/ai-fights.lua): off only when the settings say so
            "fight_watch": st.get("fight_watch") is not False,
            # (item3) the watcher ends a tantrum the moment that dwarf attacks a citizen: off only when the settings say so
            "end_tantrums": st.get("end_tantrums") is not False,
            # (R29 W8) the watcher spares DF's beatings of convicts: off only when the settings say so
            "spare_beatings": st.get("spare_beatings") is not False,
            # (item3) the guarded cavern way (brain/planner_cavern_way.py): off only when the settings say so
            "cavern_way": st.get("cavern_way") is not False,
            # (0.105.0) tribute a civilisation asks: 'small' (refuses while the sum can't be read, 0.105.48), pay / refuse
            "tribute": st.get("tribute") if st.get("tribute") in ("small", "pay", "refuse") else "small",
            # (0.105.41, item 8) a peace proposal: the AI decides (sieges, sliders) / accept / refuse
            "peace": st.get("peace") if st.get("peace") in ("ai", "accept", "refuse") else "ai",
            # (0.105.0, 13b) a messenger appointed and sent to make contact with sites not in contact
            "make_contact": st.get("make_contact") is not False,
            # (0.105.24, 13b) the AI drives DF's World screen to send the messenger. (r10 p3, the
            # player 22 Nov) on unless the player says otherwise: every fort makes initial contact
            "send_messenger": st.get("send_messenger") is not False,
            # (0.105.39, 13b) missions on the world map: off / rescue (and stolen artifacts) /
            # explore (and those) / all (raids, pillage, tribute, conquest too: they can start a war)
            # (r10 p3) 'all' by default: the raid policy (the sliders) decides the raids
            "missions": st.get("missions") if st.get("missions") in ("off", "rescue", "explore", "all") else "all",
            # (0.105.39) the AI sends them itself by DF's World screen. (r10 p3) on unless the player says otherwise
            "send_missions": st.get("send_missions") is not False,
            # (0.105.24) locations shut to visitors a while after a heist / when the mayor is swamped by visitors
            "heist_lockout": st.get("heist_lockout") is not False,
            "shut_to_visitors": st.get("shut_to_visitors") is not False,
            # (0.105.30) construction above ground (the hall, gate wings, soil floors): off only when the settings say so
            "construct": st.get("construct") is not False,
            # (0.105.41) traffic zones on the AI's finished levels (lua/ai-traffic.lua): off only when the settings say so
            "traffic": st.get("traffic") is not False,
            # (item 12) the fort's artifacts put on display in the AI's rooms: off only when the settings say so
            "display_artifacts": st.get("display_artifacts") is not False,
            # (0.105.0) water works: the moat (on by default only where the survey found a river:
            # the planner wants one only then), magma workshops, the muddied farm level
            "moat": st.get("moat") is not False,
            "magma_workshops": st.get("magma_workshops") is not False,
            "irrigation": st.get("irrigation") is not False,
            # (0.105.4 review) a cavern well into a cavern layer not yet discovered. (v35 fix)
            # three-state: "ai" (the default: the AI decides), "always", "never"; an old
            # save's true is "always", false "ai"
            "open_caverns": open_caverns_mode(st.get("open_caverns")),
            # (0.105.0) the squads wait in the shelter while the AI hides: off only when the settings say so
            "squads_shelter": st.get("squads_shelter") is not False,
            # (0.105.41, item 2) the AI's feeder piles linked to the AI's own workshops: off only when the settings say so
            "link_feeders": st.get("link_feeders") is not False,
            # (0.105.45) kill zones at the gates and cavern openings (brain/planner_killzone.py): off only when the settings say so
            "killzones": st.get("killzones") is not False,
            # (0.105.45) a great beast sealed in a cavern lured into a pocket and cut off: off only when the settings say so
            "lure_beasts": st.get("lure_beasts") is not False,
            # (0.105.27) forbidden items: store < melt < dump < destroy (each does the ones before);
            # the player's own forbidden items (no game reason) only when the switch says so; the
            # enemy's gear kept from the smelters (the War-hold preset)
            "disposal": st.get("disposal") if st.get("disposal") in DISPOSAL_LEVELS else "destroy",
            "disposal_player_items": st.get("disposal_player_items") is True,
            "keep_enemy_gear": st.get("keep_enemy_gear") is True,
            # (0.105.40, 13e) world cleanup for the game's speed (brain/planner_cleanup.py):
            # off / safe (the default: spatter, old dead units, items lost a year) / full (and
            # unreachable hostile or wild creatures)
            # (item10) cavern trees felled when the caverns are watched and wood is short: off only when the settings say so
            "cavern_logging": st.get("cavern_logging") is not False,
            # (0.105.41, item 11) syndrome carriers kept apart and their spatter cleaned: off only when the settings say so
            "syndrome_care": st.get("syndrome_care") is not False,
            "world_cleanup": st.get("world_cleanup") if st.get("world_cleanup") in ("off", "safe", "full") else "safe",
            "clear_alerts": st.get("clear_alerts") if st.get("clear_alerts") in ("all", "quiet", "none") else "quiet",
            # (0.105.41, item 4) a hunter or two out while it is safe; farm plots on a known, quiet cavern's soil
            "hunting": st.get("hunting") is not False,
            "cavern_farms": st.get("cavern_farms") is not False,
            # (0.105.45) hunting threats the squads can beat: off / small (thieves, ambushes,
            # wounded visitors) / ai (the default: great dangers too) (brain/planner_hunt.py)
            "hunt": st.get("hunt") if st.get("hunt") in ("off", "small", "ai") else "ai",
            # (0.105.47, J17) raids inside missions 'all': by the sliders, or forced (brain/planner_raids.py)
            # (0.105.48, K9) off unless the settings say otherwise (the audit: off until watched live).
            # (r10 p3, the player 22 Nov) 'ai' by default: the fort's character decides; 'off' never
            "raid_policy": st.get("raid_policy") if st.get("raid_policy") in ("ai", "aggressive", "reactive", "off")
            else "ai",
            # (0.105.46, I4) a fallen fort DF sends no migrants to: the AI calls a wave
            # (DFHack's force Migrants; brain/planner_recovery.py): off only when the settings say so
            "call_migrants": st.get("call_migrants") is not False,
            # (layout B) new levels along a main hall on each floor (the default), or each on its own
            "floor_layout": "classic" if st.get("floor_layout") == "classic" else "hallway",
            # (0.105.47) a training-only squad for the keen at high Welfare (brain/planner_training.py)
            "training_squad": st.get("training_squad") is not False}


OPEN_CAVERNS_MODES = ("ai", "always", "never")


def open_caverns_mode(v) -> str:
    """(v35 fix) The Rules switch "Cavern well into an unfound cavern":
    "ai" (the default), "always" or "never"; an old save's true is "always",
    its false "ai"."""
    if v is True:
        return "always"
    return v if v in OPEN_CAVERNS_MODES else "ai"


MAINTAIN_SKIPS = ("library", "memorial", "temple", "garden")


def level_refused(s: dict, kind: str, cfg: dict | None = None) -> str | None:
    """(0.97) Why a new level of this kind is not to be dug (None: it may be):
    its Rules-tab switch, the Maintain goal, Mining -100's needed-only rule.
    The planner's own ladder follows these; the strategist's levels are
    checked against them too (they used to ignore the switches and Maintain)."""
    rules_ = player_rules(s)
    if kind in OPTIONAL_LEVELS and not rules_["levels"].get(kind, True):
        return f"the {kind} level is off on the Rules tab"
    if rules_["fort_goal"] == "maintain" and kind in MAINTAIN_SKIPS:
        return f"the fort's goal is Maintain (no new {kind})"
    if kind in MINING_NEED_ONLY and mining_plan(_traits(s), cfg or PLANNER_CONFIG)["need_only"]:
        return f"Mining is -100: only the levels the fort needs (no {kind})"
    return None


def _traits(s: dict) -> dict:
    t = s["settings"].get("traits")
    return _d(t)


# (0.100) Kinds of level the rules may each ask for in one cycle (about a
# dozen rules propose a workshops level; two may propose a temple): only the
# most urgent that passes the other limits goes ahead in select(); the
# others ask again once it is under way (`_workshops_busy`). (Two rules
# ordering the same recipe are left: each sizes its own need, and the next
# cycle sees both queued.)
ONE_A_CYCLE = ("workshops", "temple")


def growth_mode(s: dict, cfg: dict) -> tuple[str, int | None]:
    """What the Growth slider asks for, from its effective value (Extreme
    doubles it, as on every slider since 0.94):
      ("target", n)    about n dwarves: -100 low (25), 0 average (100), +100
                       high (250); past +100 it keeps rising, 500 at +150
      ("uncapped", None)  +200 (+100 with Extreme): no cap at all
      ("shrink", days) past -100 (Extreme): no newcomers, one dwarf sent away
                       every `days` in-game days (280 at -110, 28 at -200)"""
    v = max(-200.0, min(200.0, float(_traits(s).get("growth", 0))))
    p = cfg["growth_points"]
    if v >= 200:
        return "uncapped", None
    if v > 100:
        return "target", int(p["high"] * 4 ** ((v - 100) / 100) + 0.5)
    if v < -100:
        return "shrink", int(cfg["shrink_days"] * 100 / (abs(v) - 100) + 0.5)
    edge = p["high"] if v >= 0 else p["low"]
    return "target", int(p["average"] + (edge - p["average"]) * abs(v) / 100 + 0.5)


def growth_target(s: dict, cfg: dict) -> int:
    """The population to plan for (bedrooms): the target, or for no cap, far."""
    mode, n = growth_mode(s, cfg)
    if mode == "uncapped":
        return cfg["uncapped"]
    if mode == "shrink":
        return 0
    return n


# --- (0.96) graded behaviour: each slider's numbers in one place -------------
# (brain/temperament.py shows them on the panel; Design Notes 3c). Extreme
# doubles the slider value before it reaches here, as everywhere.

MINING_NEED_ONLY = ("library", "archery", "garden", "barracks", "temple", "jail")


def mining_plan(traits: dict, cfg: dict) -> dict:
    """Mining (shallow - deep): how much the fort digs beyond its needs.
    -100 or lower: only the levels it needs (no library, archery, garden,
    barracks, temple or jail level; bedrooms, storage, workshops, dining,
    tombs, hospital, tavern, wells and farms still dug); -50 or lower: no ore
    veins mined (metal comes by trade); otherwise veins are mined while bars
    run under 50 x factor (25 at -100, 100 at +100), 40 x factor tiles at a
    time; quarries 20 x factor (10-30: the bridge's quarry takes 1-30)."""
    m = traits.get("mining", 0) or 0
    f = factor(traits, "mining")
    return {"need_only": m <= -100,
            "veins": m > -50,
            "bars_below": int(cfg["smelt_when_bars_below"] * f),
            "ore_stock_max": int(cfg["ore_stock_max"] * f),
            "vein_tiles": max(10, min(80, int(40 * f))),
            # (0.105.24) at most 30, what act_quarry accepts: A, B, D and E (2-5
            # Nov) asked 60 at Mining +100 and were refused "quarry needs count
            # 1-30" 112-174 times each (20 x factor keeps the slider graded)
            "quarry": max(10, min(30, int(20 * f)))}


def noble_room_kinds(traits: dict, memory=None) -> tuple:
    """Deference (ignoring - indulgent): which rooms a noble's office gets
    given: none at -100 or lower, a bedroom at -50 or lower, a bedroom and
    an office below 0, all four (and dining room and tomb) from 0.
    (0.103.15) Nobles' Pride: all four unless Deference is at its lowest."""
    d = traits.get("deference", 0) or 0
    if d <= -100:
        return ()
    if memory is not None and has_rule(getattr(memory, "culture", None), "noble_pride"):
        return ("bedroom", "office", "dining", "tomb")
    if d <= -50:
        return ("bedroom",)
    if d < 0:
        return ("bedroom", "office")
    return ("bedroom", "office", "dining", "tomb")

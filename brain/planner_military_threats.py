"""planner_military_threats: weighing the enemy (split out of planner_military
in r7, 0.105.62): a threat's strength, fight or hide and what a called-off
fight taught, the crossing rule, the alerts, war animals, the hazards
(berserk, fire, a ghost...) and the great beasts no melee squad meets.
planner_military re-exports every name here."""

from __future__ import annotations
import json
import math
import re
from dataclasses import asdict, dataclass, field
from culture import layout_style, new_history, pick_stone, profile_from, stone_for
from learning import held_levels
import masterplan
import phases
from quirks import has_rule
from digest import _d, _l, normalize
from planner_core import *  # noqa: F401,F403
from planner_gates import *  # noqa: F401,F403  (13c: split out by theme)
from planner_matchup import facts_mult, judge, matchup  # noqa: F401  (0.105.45) a threat against the squads
from planner_military_squads import no_shelter, weak_squad  # noqa: F401  (the hazard rules shelter the fort)

__all__ = ["GREAT_BASE", "GREAT_KIND", "GREAT_ABILITY", "GREAT_FLIER", "DWARF_SIZE", "BASE_DWARF", "SMALL_FLOOR", "threat_power", "fight_key", "FIGHT_FACTOR_MAX", "called_off_ids", "fight_or_hide", "crossing_value", "ALERT_DANGERS", "alert_ages", "hazard_alert", "no_melee_great", "watched_gate_levers"]


# (0.104.118, phase 11) Fight or hide. A great danger's strength: GREAT_BASE,
# and more for its size (a dwarf is about 60,000; a titan millions); by kind.
GREAT_BASE = 8.0
GREAT_KIND = {"Megabeast": 1.5, "Demon": 1.5, "Titan": 1.2, "ForgottenBeast": 1.3, "SemiMegabeast": 1.0,
              "Undead": 0.8}
# (0.104.139) what size doesn't say: a breath, deadly dust or webs (its
# caste's interactions) kills whole squads; a flier picks its fights
GREAT_ABILITY = 3.0     # (0.105.22: was 2) A, 4-5 Nov: a breathing titan scored 39 against squads of 488; 25 soldiers died in six minutes
GREAT_FLIER = 1.5


# (0.105.48, K1) A creature smaller than a dwarf that is no great danger
# had the same base 8 as a titan: War-hold's falcon (size 129) scored 12.1,
# above one of the fort's best soldiers (a steel axe lord ~11.4 on
# squad_power's scale). Below a dwarf's size an ordinary creature's strength
# now goes with the square root of its body from a dwarf-sized enemy's
# (BASE_DWARF = a goblin's 10, as before): a falcon about 0.7, a cat 3, a
# kobold 6. A dwarf's size and up, and every great danger, as before.
DWARF_SIZE = 60000
BASE_DWARF = GREAT_BASE + 2.0
SMALL_FLOOR = 0.3


def _base_power(t: dict, size: float) -> float:
    great = t.get("great_danger") or (set(_l(t.get("kinds"))) - {"Undead"})
    if size < DWARF_SIZE and not great:
        return max(SMALL_FLOOR, BASE_DWARF * math.sqrt(size / DWARF_SIZE))
    return GREAT_BASE + 2 * math.sqrt(size / DWARF_SIZE)


def threat_power(t: dict) -> float:
    size = t.get("size") if isinstance(t.get("size"), (int, float)) and t.get("size") > 0 else 60000 * 25
    mult = max([GREAT_KIND.get(k, 1.0) for k in _l(t.get("kinds"))] or [1.0])
    base = _base_power(t, size)
    if t.get("facts"):
        # (0.105.45, Phase 11 (a)) the bridge read what it brings (breath by
        # kind, venom, no pain, armour, speed, flight...): planner_matchup
        return base * mult * facts_mult(t)[0]
    if t.get("abilities"):
        mult *= GREAT_ABILITY
    if t.get("flier"):
        mult *= GREAT_FLIER
    return base * mult


def fight_key(t: dict) -> str:
    kinds = [str(k) for k in _l(t.get("kinds"))]
    # (0.104.139) the kind that says most first (forgotten beasts were all "beast")
    for k in ("ForgottenBeast", "Titan", "Megabeast", "Demon", "SemiMegabeast", "Undead", "NightCreature"):
        if k in kinds:
            return k
    return kinds[0] if kinds else "beast"


FIGHT_FACTOR_MAX = 50.0     # (0.105.26) a called-off fight can teach more than the usual cap of 4


def called_off_ids(s: dict, memory) -> set:
    """(0.105.26) Great dangers whose fight was called off (a third of the
    soldiers who went lost): no squad is sent at them again while they stay
    on the map. The flag goes when the danger leaves the map or dies (it is
    no longer in the report's threats)."""
    co = getattr(memory, "called_off", None) if memory is not None else None
    if not isinstance(co, dict) or not co:
        return set()
    oth = s.get("others_on_map")
    if isinstance(oth, dict) and "others_on_map" not in _d(s.get("_errors")) and isinstance(oth.get("threats"), list):
        here = {str(t.get("id")) for t in oth["threats"] if isinstance(t, dict)}
        for k in [k for k in co if k not in here]:
            del co[k]
    out = set()
    for k in co:
        try:
            out.add(int(k))
        except (TypeError, ValueError):
            pass
    return out


def fight_or_hide(s: dict, memory, cfg: dict, great: list, able: list, info: dict | None = None) -> tuple[bool, str]:
    """Squads' strength (the bridge's per-squad `power`) against the great
    dangers' (threat_power), times what the fort learned from its own fights
    of that kind (memory.fight_factor). (0.105.54, the player: "fight when
    roughly even") Fight at planner_matchup.strike_bar or better: about even
    odds (`fight_even_ratio`), a clear win (`fight_ratio`) only for abilities
    the AI can't read, lower for a wounded beast; an all-out attack once the
    wait is over (planner_matchup.all_out); a fight called off for its
    losses goes again when the odds return. The verdict says why.

    (R32 c) One judgement for the sortie and the recall: a great danger the
    military rules judged too strong (note_great_hold) is gone out at again
    only at the full bar (fight_bar), not at one lowered for a moment (it
    "falls back" a few tiles, a wound read): F's Hydra (26 Nov) was hidden
    from at 0.9x, sent at by the x0.8 bar a minute later, and the squads
    called back "too weak now" 50 s after, 5 soldiers dead. One inside the
    fort is judged as before (holding the choke protects nobody). `info`,
    when given, is filled with {army, need, ratio, bar, held, inside}."""
    from planner_matchup import all_out, losses_turned, strike_bar
    from planner_holdfast import retreating_ids
    army = sum(float(_d(q.get("power")).get("power") or 0) for q in able)
    if not army:
        return False, "the squads' strength isn't known (older bridge)" if able else "no squad to send"
    # (0.105.45) the matchup: melee and ranged power weighed by what the
    # dangers bring (a fire breather: only ranged counts); with rows from an
    # older bridge, total power against threat_power as before
    ff_ = _d(getattr(memory, "fight_factor", None))
    j = judge(great, able, lambda t: float(ff_.get(fight_key(t)) or 1.0))
    need, ratio = j["need"], j["ratio"]
    army = j["army"]
    full_bar, bar_why = strike_bar(great, cfg, retreating_ids(memory, cfg))
    # (R32 c) held as too strong, outside: the full bar, never one lowered for a moment
    from planner_great_hold import hold_bar
    full_bar, bar_why, held = hold_bar(s, memory, cfg, great, full_bar, bar_why,
                                       info, army=army, need=need, ratio=ratio)
    words = (f"squads {army:.0f} against {need:.0f} ({ratio:.1f}x; {bar_why})"
             + ("; " + "; ".join(j["reasons"]) if j["reasons"] else ""))
    off = called_off_ids(s, memory) & {t.get("id") for t in great}
    if off:
        # (0.105.26) A's titan was sent at three times: a fight called off for
        # its losses is not begun again at the same odds. (0.105.54) It goes
        # again when the odds return (the squads refilled, trained, the beast
        # wounded: the learned factor makes the old odds short of the bar),
        # or once the wait is over and that long has passed since
        co = _d(getattr(memory, "called_off", None))
        since = min((int(co[str(i)]) for i in off if isinstance(co.get(str(i)), int)), default=None)
        wait_ok = (since is not None
                   and abs_tick(s) - since >= float(cfg.get("siege_wait_max_days", 4)) * TICKS_PER_DAY)
        ao = all_out(s, memory, cfg) if wait_ok else ""
        if ratio >= full_bar or (ao and ratio >= float(cfg.get("all_out_min_ratio", 0.25))):
            for i in off:
                co.pop(str(i), None)
            if memory is not None:
                memory.called_off = co
                memory.fight = {}          # a new fight: its losses counted from now
            why = "the odds are back" if ratio >= full_bar else f"all-out: {ao}"
            return True, words + f"; the fight called off before goes again ({why})"
        return False, (f"the fight with {len(off)} of them was called off for its losses: the squads go again "
                       f"when the odds return ({ratio:.1f}x, {full_bar:g}x needed)")
    # (0.104.139) no flip-flop: a fight begun goes on unless the squads fall
    # well short (three quarters of the bar); hiding ends only clearly above it
    f = getattr(memory, "fight", None)
    on = (isinstance(f, dict) and f
          and 0 <= abs_tick(s) - int(f.get("tick") or 0) < cfg["fight_freeze_days"] * TICKS_PER_DAY)
    # (0.105.22) a fight going badly ends now, not when the danger leaves (A's
    # titan never left: the squads were sent three times as they died). A
    # third of the soldiers who went lost: the fight is called off
    if isinstance(f, dict) and f and f.get("soldiers"):
        now_ = int(_d(s.get("military")).get("soldiers") or 0)
        lost = max(0, int(f["soldiers"]) - now_)
        if lost * 3 >= int(f["soldiers"]):
            # (0.105.26) the dangers fought are flagged (not sent at again
            # at the same odds), and the kind is learned strong enough that
            # even the squads at full strength would hide: x1.5 needed about
            # four lost fights before A's titan was hidden from
            if memory is not None:
                co = memory.called_off if isinstance(getattr(memory, "called_off", None), dict) else {}
                for t in great:
                    if t.get("id") is not None:
                        co.setdefault(str(t["id"]), abs_tick(s))
                memory.called_off = co
            if not f.get("learned"):
                ff = memory.fight_factor if isinstance(getattr(memory, "fight_factor", None), dict) else {}
                full = army * max(int(f["soldiers"]), now_) / max(1, now_)
                base = sum(threat_power(t) for t in great) or 1.0
                # (0.105.54) against the bar it is judged by now (even odds),
                # so the same squads at full strength stay short of it
                hide_at = full / (full_bar * base) * 1.25
                for k in _l(f.get("keys")):
                    old = float(ff.get(k) or 1.0)
                    ff[k] = round(min(FIGHT_FACTOR_MAX, max(0.5, old * 1.5, hide_at)), 2)
                memory.fight_factor = ff
                f["learned"] = True
            return False, words + f"; {lost} of the {f['soldiers']} soldiers who went are lost: the squads come back"
    # (0.105.54) half the soldiers out on them wounded: back too (no lesson
    # learned: the odds decide again as they heal)
    ids = {t.get("id") for t in great}
    out = [q for q in able if q.get("ai_orders") and {x for x in _l(q.get("kill_ids")) if isinstance(x, int)} & ids]
    if on and out:
        turned = losses_turned(out, {}, cfg)
        if turned:
            return False, words + f"; {turned}: the squads come back and go again when the odds return"
    bar = full_bar * (0.75 if on and not held else 1.0)     # (R32 c) held: no fight on to keep going
    if ratio >= bar:
        return True, words
    ao = all_out(s, memory, cfg)
    if ao and ratio >= float(cfg.get("all_out_min_ratio", 0.25)):
        return True, words + f"; all-out: {ao}"
    if ao:
        return False, words + (f"; the wait is over ({ao}) but the squads are only {ratio:.1f}x "
                               f"({cfg.get('all_out_min_ratio', 0.25):g}x at least for an all-out attack)")
    return False, words


def _players(q: dict) -> bool:
    """(0.105.48, K16) A squad on the player's own orders (more orders than the AI's)."""
    return int(q.get("orders") or 0) > int(q.get("ai_orders") or 0)


def _note_fight(s: dict, memory, great: list) -> None:
    """A fight against great dangers begins: what it was and how many soldiers went."""
    if isinstance(getattr(memory, "fight", None), dict) and memory.fight:
        return
    memory.fight = {"tick": abs_tick(s), "keys": sorted({fight_key(t) for t in great}),
                    "soldiers": int(_d(s.get("military")).get("soldiers") or 0)}


def _fight_outcome(s: dict, memory, cfg: dict) -> None:
    """The fight is over (no great danger in reach): lost a third of the
    soldiers or more -> that kind is taken as 50% stronger next time; fewer
    -> 10% weaker (between 0.5 and 4 times the estimate)."""
    f = getattr(memory, "fight", None)
    if not isinstance(f, dict) or not f or great_present(s):
        return
    now = int(_d(s.get("military")).get("soldiers") or 0)
    lost = max(0, int(f.get("soldiers") or 0) - now)
    bad = f.get("soldiers") and lost * 3 >= int(f["soldiers"])
    ff = memory.fight_factor if isinstance(getattr(memory, "fight_factor", None), dict) else {}
    for k in _l(f.get("keys")):
        if f.get("learned"):            # (0.105.22) already counted mid-fight
            continue
        old = float(ff.get(k) or 1.0)
        ff[k] = round(min(max(4.0, old), max(0.5, old * (1.5 if bad else 0.9))), 2)
    memory.fight_factor = ff
    memory.fights = (list(getattr(memory, "fights", None) or []) +
                     [{"tick": abs_tick(s), "keys": f.get("keys"), "lost": lost, "of": f.get("soldiers")}])[-20:]
    memory.fight = {}


def crossing_value(side: dict) -> float:
    """(0.101) What land is worth to the fort, from the crossings survey:
    trees (wood), shrubs and saplings (food, drink, seeds, future trees),
    grass (pasture), and the map's edge (where caravans and migrants come in)."""
    side = _d(side)
    return (2 * (side.get("trees") or 0) + (side.get("shrubs") or 0) + 0.5 * (side.get("saplings") or 0)
            + (side.get("grass") or 0) / 20 + (40 if side.get("edge") else 0))


def _crossing_rule(s: dict, cfg: dict, citizens: int, traits: dict, proposals: list, notes: list,
                   memory=None) -> None:
    """(0.101) Water on the surface cutting the fort off from land it would
    use (the second overnight embark lay in a river's bend). The AI weighs
    each side from the survey and decides: a cheap one-tile bridge early when
    the far side is worth the walk; a wider one once the fort is established
    (Grandeur widens it; at -50 or lower the cheap one stays); the cheap one
    taken down once the new one stands. Only the AI's own bridges."""
    c = _d(s.get("crossings"))
    if c.get("none") or c.get("error"):
        return
    cands = [x for x in _l(c.get("crossings")) if isinstance(x, dict) and x.get("len")]
    mine = [m for m in _l(c.get("mine")) if isinstance(m, dict)]
    near_v = crossing_value(c.get("near"))
    st = _d(s.get("stocks"))
    material = int(st.get("wood") or 0) + int(st.get("blocks") or 0) + int(st.get("boulders") or 0)
    def score(x):
        return crossing_value(x.get("far_side")) - 2 * x["len"] - (x.get("dist") or 0) / 20
    # the old cheap bridge comes down once a refined one stands
    refined_up = [m for m in mine if m.get("kind") == "refined" and m.get("built")]
    if refined_up:
        for m in mine:
            if m.get("kind") == "cheap" and m.get("index"):
                proposals.append(Proposal("crossing", {"type": "remove_crossing", "index": m["index"]},
                                          "the new, wider bridge stands: take down the old narrow one", 7))
                return
    if not cands:
        return
    # the nearest crossing whose far side is worth it (each side's count is
    # capped, so on open land the far sides look alike: the walk decides);
    # with none worth it, the best one is weighed below and found wanting
    worthy = [x for x in cands if crossing_value(x.get("far_side")) >= cfg["crossing_min_value"]]
    best = (min(worthy, key=lambda x: 2 * x["len"] + (x.get("dist") or 0) / 5) if worthy
            else max(cands, key=score))
    far = _d(best.get("far_side"))
    far_v = crossing_value(far)
    where = f"x{best.get('x')} y{best.get('y')}"
    what = (f"{far.get('trees', 0)} trees, {far.get('shrubs', 0)} shrubs, {far.get('grass', 0)} grass"
            + (", the map's edge" if far.get("edge") else ""))
    deep = masterplan.underground_only(traits)
    if not mine:
        near = _d(c.get("near"))
        if deep and not (far.get("edge") and not near.get("edge")):
            return      # (0.105.23) the Deep mine bridges the water only to reach the map's edge (caravans)
        worth = far_v >= cfg["crossing_min_value"] and (
            far_v >= near_v * cfg["crossing_far_share"]
            or (near.get("trees") or 0) < citizens
            or (far.get("edge") and not near.get("edge")))
        if not worth:
            return
        if material < best["len"]:
            notes.append(f"a bridge over the water at {where} waits for {best['len']} logs, blocks or boulders")
            return
        proposals.append(Proposal("crossing", {"type": "build_crossing", "x": best["x"], "y": best["y"],
                                               "z": best.get("z"), "dir": best.get("dir"), "len": best["len"],
                                               "width": 1, "kind": "cheap"},
                                  f"water cuts the fort off from land worth reaching ({what} over there, "
                                  f"{best['len']} tiles across at {where}): a narrow bridge for now", 6))
        return
    if any(m.get("kind") == "refined" for m in mine) or traits.get("grandeur", 0) <= -50 or deep:
        return          # (0.105.23) nor a wider one above ground in the Deep mine
    wealth = s.get("wealth") if isinstance(s.get("wealth"), (int, float)) else 0
    # (0.103) Riverfolk bridge their river properly at half the size and wealth
    river = 0.5 if memory is not None and has_rule(memory.culture, "river_bridges") else 1.0
    if (citizens < cfg["crossing_refine_citizens"] * river or wealth < cfg["crossing_refine_wealth"] * river
            or (young_fort(s, cfg) and river == 1.0)):
        return
    want = 3 if traits.get("grandeur", 0) >= 50 else 2
    wide = [x for x in cands if (x.get("width") or 1) >= 2]
    if not wide:
        return
    pick = min(wide, key=lambda x: 2 * x["len"] + (x.get("dist") or 0) / 5)
    width = min(want, pick.get("width") or 1)
    if material < pick["len"] * width:
        return
    proposals.append(Proposal("crossing", {"type": "build_crossing", "x": pick["x"], "y": pick["y"],
                                           "z": pick.get("z"), "dir": pick.get("dir"), "len": pick["len"],
                                           "width": width, "kind": "refined"},
                              f"the fort has grown ({citizens} dwarves): a {width}-wide bridge over the water at "
                              f"x{pick.get('x')} y{pick.get('y')} in place of the narrow one", 7))


# (0.88) The alert icons: kept for the player while new, the dangers longer
ALERT_DANGERS = ("AMBUSH", "MONSTER", "UNDEAD_ATTACK", "BERSERK", "GHOST", "DEITY_CURSE", "DEATH", "MARTIAL_TRANCE")


def alert_ages(s: dict, cfg: dict, policy: str) -> dict | None:
    """The age (ticks) at which each kind of alert icon is cleared, or None to
    leave them all. 'all': every kind once a day old; 'quiet' (the default):
    the dangers kept a week, and while a threat can reach the dwarves; 'none'."""
    if policy == "none":
        return None
    day = TICKS_PER_DAY
    ages = {"default": int(cfg["alert_keep_days"] * day)}
    if policy == "all":
        return ages
    danger_age = int(cfg["alert_danger_days"] * day)
    for t in ALERT_DANGERS:
        ages[t] = danger_age
    if reachable_threats(s, _traits(s), cfg):
        for t in ("AMBUSH", "MONSTER", "UNDEAD_ATTACK", "BERSERK", "COMBAT"):
            ages[t] = False
    return ages


def _alerts_rule(s: dict, memory, cfg: dict, proposals: list, rules_: dict) -> None:
    """(0.88) The alert icons down the left of the screen pile up (you, Oct
    23: mining, weather, death, combat, nobles...): the AI reads every
    announcement itself, so it clears the old ones, the way right-clicking an
    icon does. The first time only one, as a probe."""
    al = _d(s.get("alerts"))
    by = _d(al.get("by_type"))
    if not by or al.get("open"):
        return
    ages = alert_ages(s, cfg, rules_.get("clear_alerts", "quiet"))
    if not ages:
        return
    due = []
    for t, e in by.items():
        need = ages.get(t, ages.get("default"))
        age = _d(e).get("age")
        if need is not False and need is not None and (age is None or int(age) >= int(need)):
            due.append(t)
    if not due:
        return
    # the first one alone: a probe that the game takes it (nothing done yet)
    done = any(str(k).startswith("alerts:") and v for k, v in (getattr(memory, "action_log", None) or {}).items())
    proposals.append(Proposal("alerts", {"type": "dismiss_alerts", "ages": ages,
                                         "max": cfg["alerts_per_cycle"] if done else 1},
                              f"{len(due)} old alert icon(s) on the screen ({', '.join(sorted(due)[:5]).lower()}"
                              f"{'...' if len(due) > 5 else ''}): the AI has read them; clear them", 8))


def _war_animal_rule(s: dict, cfg: dict, proposals: list, traits: dict | None = None) -> None:
    """(0.104.81) War animals: the tame dogs and the like trained for war
    (DF's trainers do it once an animal has a training assignment), up to
    `war_animals_max`; a dwarf given the animal-training labour first when
    nobody has it. (0.105.47) By Militarism, given the traits: none below
    0 (a peaceful fort keeps its animals for the herd: Husbandry's), past
    0 war_animals_max x the Militarism factor, up to war_animals_cap."""
    if young_fort(s, cfg):
        return
    want = cfg["war_animals_max"]
    if traits is not None:
        mil = traits.get("militarism", 0)
        if mil < 0:
            return
        want = min(cfg.get("war_animals_cap", 24), round(want * factor(traits, "militarism")))
    an = _d(_d(s.get("society")).get("animals"))
    if an.get("error") or not an:
        return
    have = int(an.get("war_trained") or 0) + int(an.get("in_training") or 0)
    cands = int(an.get("war_candidates") or 0)
    if cands <= 0 or have >= want:
        return
    if int(an.get("trainers") or 0) == 0:
        proposals.append(Proposal("animal_trainer", {"type": "assign_labor", "job": "ANIMALTRAIN", "count": 1},
                                  f"{cands} tame animals could be trained for war and nobody may train animals: "
                                  "give one dwarf the labour", 6))
        return
    n = min(3, want - have, cands)
    proposals.append(Proposal("war_animals", {"type": "train_war", "max": n},
                              f"{have} war animals (trained or in training) of {want} wanted, "
                              f"{cands} could be trained: put {n} to war training (they fight beside the dwarves)", 6))


def hazard_alert(s: dict, cfg: dict, raising: bool = False) -> str:
    """Why the civilian alert should stay up for a hazard ("" if none): fire
    or a cloud close to the dwarves, a citizen gone berserk. (item4) Fire
    sounds it only within `fire_alarm_near` (raising), and holds it while
    within `hazard_near`: C's fire 9-14 tiles off, flickering in and out of
    20, sounded it 122 times in one run (the fire guard keeps the dwarves
    off the tiles round it meanwhile)."""
    h = _d(s.get("hazards"))
    # (0.105.47) Caution sets how near (brain/alarm_caution.py): at 0 the config's own
    from alarm_caution import alarm_settings
    lean = alarm_settings(_d(_d(s.get("settings")).get("traits")), cfg)
    near = lean["fire_near"] if raising else lean["fire_hold"]
    if h.get("fire_near") is not None and h["fire_near"] <= near:
        return f"fire {h['fire_near']} tiles from the dwarves"
    if h.get("cloud_near") is not None and h["cloud_near"] <= (lean["cloud_near"] if raising else lean["cloud_hold"]):
        return f"a cloud (gas or vapour) {h['cloud_near']} tiles from the dwarves"
    from planner_military_weres import loose_berserk      # (R30b) a were sealed in their cell: no alarm
    b0 = next((b for b in loose_berserk(s) if isinstance(b, dict)), None)    # (0.105.33) a dict row only
    if b0 is not None:
        return f"{b0.get('name') or 'a dwarf'} " + ("has changed into a beast" if b0.get("changed") else "has gone berserk")
    # (0.105.119 item32) a visiting were in beast form: sounded and held like
    # a berserk citizen (F's Wereskink: the alarm came down while it killed)
    from planner_military_weres import were_alert
    were = were_alert(s)
    if were:
        return were
    from planner_hazards import magma_alarm     # (0.105.41, item 7) spilt magma spreading near the dwarves
    return magma_alarm(s, cfg)


def _hazard_rules(s: dict, memory, cfg: dict, proposals: list, notes: list, rules_: dict) -> None:
    """Phase 11, reflexes for hazards that aren't enemies (lua/ai-bridge.lua
    get_hazards): the civilian alert for fire, clouds and a berserk citizen,
    the squads sent at the berserk one; dwarves in deep water or magma
    (flooding: the cistern's floodgate shut); vampires sent away (Rules tab);
    caught invaders noted."""
    h = _d(s.get("hazards"))
    why = hazard_alert(s, cfg, raising=True)
    if why and not s.get("civ_alert"):
        if s.get("civ_alert_ready") is True:
            proposals.append(Proposal("threat_alert", {"type": "civ_alert", "on": True},
                                      f"{why}: sound the alarm (the civilians go to the shelter)", 0))
        else:
            no_shelter(s, memory, why, proposals, notes)        # (0.105.35) the AI makes one
    from planner_military_weres import loose_berserk      # (R30b) a were sealed in their cell: no squad
    berserk = [b for b in loose_berserk(s) if isinstance(b, dict) and b.get("id") is not None]
    mil = _d(s.get("military"))
    if berserk:
        squads = [q for q in _l(mil.get("squads")) if isinstance(q, dict)]
        able = [q for q in squads if can_fight(q, cfg) and not q.get("ai_orders")]
        names = ", ".join(str(b.get("name")) + (" (changed into a beast)" if b.get("changed") else "")
                          for b in berserk[:3])
        ids = [b["id"] for b in berserk][:10]
        # (0.105.35) nothing waits for the player: a squad out on other orders
        # takes the berserk one on too, else the best squad with anyone armed
        busy = [q for q in squads if can_fight(q, cfg) and q.get("ai_orders") and not q.get("guarding")
                and isinstance(q.get("kill_ids"), list)]
        # (v35 fix) a squad sent at these same targets within
        # `berserk_resend_ticks` isn't sent again (its order may simply not show
        # yet); the loop guard counts these sends (guard)
        now = abs_tick(s)
        sent = _d(getattr(memory, "kill_sent", None)) if memory is not None else {}
        sent_at = _d(getattr(memory, "kill_sent_at", None)) if memory is not None else {}
        resend = int(cfg.get("berserk_resend_ticks", TICKS_PER_DAY))

        def just_sent(q):
            t_ = sent_at.get(str(q.get("id")))
            return (set(ids) <= {x for x in _l(sent.get(str(q.get("id")))) if isinstance(x, int)}
                    and isinstance(t_, int) and 0 <= now - t_ < resend)

        def on_it(q):
            return isinstance(q.get("kill_ids"), list) and set(ids) <= set(q["kill_ids"])

        changed = any(b.get("changed") for b in berserk)
        weak = None if able or busy else weak_squad(squads)
        # (0.105.119 item32) a were in beast form: every free armed squad at
        # once, not one a cycle (A, y253: seven werepanthers, one squad sent
        # a cycle while 54 soldiers stood by); the player's own orders kept
        # and the squads waiting in the shelter go out too
        were_go = []
        if changed:
            were_go = [q for q in squads if can_fight(q, cfg) and not _players(q) and not q.get("guarding")
                       and (not q.get("ai_orders") or q.get("sheltering")) and not just_sent(q)]
        for q in were_go:
            proposals.append(Proposal("squad_attack", {"type": "squad_orders", "squad_id": q["id"], "kill": ids},
                                      f"{names}: a werebeast in beast form attacking others, a top threat: "
                                      f"send {q.get('name') or 'the squad'} (every free squad goes)", 0, guard=True))
        if were_go:
            if busy and not set(ids) <= set(busy[0]["kill_ids"]) and not just_sent(busy[0]):
                q = busy[0]
                kill = list(dict.fromkeys(ids + [x for x in q["kill_ids"] if isinstance(x, int)]))[:50]
                proposals.append(Proposal("squad_attack", {"type": "squad_orders", "squad_id": q["id"], "kill": kill},
                                          f"{names}: a werebeast in beast form: {q.get('name') or 'the squad'} "
                                          "takes them on too", 0, guard=True))
        elif able and just_sent(able[0]):
            notes.append(f"{names} gone berserk: {able[0].get('name') or 'a squad'} was sent after them "
                         f"{(now - sent_at[str(able[0]['id'])]) // 50} hour(s) ago")
        elif able:
            proposals.append(Proposal("squad_attack", {"type": "squad_orders", "squad_id": able[0]["id"],
                                                       "kill": ids},
                                      f"{names} gone berserk and attacking others: send {able[0].get('name') or 'the squad'}",
                                      0, guard=True))
        elif busy and not set(ids) <= set(busy[0]["kill_ids"]) and not just_sent(busy[0]):
            q = busy[0]
            kill = list(dict.fromkeys(ids + [x for x in q["kill_ids"] if isinstance(x, int)]))[:50]
            proposals.append(Proposal("squad_attack", {"type": "squad_orders", "squad_id": q["id"], "kill": kill},
                                      f"{names} gone berserk and no squad free: {q.get('name') or 'the squad'} "
                                      "takes them on too", 0, guard=True))
        elif busy:
            notes.append(f"{names} gone berserk: {busy[0].get('name') or 'a squad'} is after them")
        elif weak is not None and (on_it(weak) or just_sent(weak)):
            notes.append(f"{names} gone berserk: {weak.get('name') or 'a squad'} "
                         f"({_d(weak.get('power')).get('armed')} armed) is after them")
        elif weak is not None and changed and int(_d(weak.get("power")).get("armed") or 0) < int(weak.get("members") or 0):
            # (v35 fix) a werebeast is not taken on by a squad only partly armed
            notes.append(f"{names} gone berserk and no squad has {cfg['min_squad_to_fight']}+ armed: the best has "
                         f"{_d(weak.get('power')).get('armed')} of {weak.get('members')} armed, too few against a "
                         "changed beast; the alarm keeps the others in the shelter meanwhile, and the squads are "
                         "armed first")
        elif weak is not None:
            q = weak
            proposals.append(Proposal("squad_attack", {"type": "squad_orders", "squad_id": q["id"], "kill": ids},
                                      f"{names} gone berserk and no squad has {cfg['min_squad_to_fight']}+ armed: "
                                      f"send {q.get('name') or 'the squad'} ({_d(q.get('power')).get('armed')} armed)",
                                      0, guard=True))
        else:
            notes.append(f"{names} gone berserk and no squad has anyone armed: the alarm keeps the others in "
                         "the shelter meanwhile, and the squads are armed first")
    # (0.105.119 item32) an AI kill order naming one of the fort's own back in
    # their own form (a were changed back, a berserk dwarf calmed): off it
    from planner_military_weres import were_spare_rules
    were_spare_rules(s, cfg, proposals, notes)
    wet, burning = _l(h.get("wet")), _l(h.get("burning"))
    if burning:
        # (0.105.35) a plain note: nobody, the AI or the player, can reach them in time
        notes.append(f"{len(burning)} dwarf(s) in magma: " + ", ".join(str(b.get("name")) for b in burning[:3])
                     + " (nothing can reach them in time)")
    if len(wet) >= cfg["flood_wet_dwarves"]:
        cs = _d(_d(s.get("water")).get("cistern_status"))
        names = ", ".join(str(b.get("name")) for b in wet[:3])
        if cs.get("gate") == "open":
            proposals.append(Proposal("flood", {"type": "cistern_step", "shut": True},
                                      f"{len(wet)} dwarves stand in deep water: shut the cistern's floodgate", 0))
            notes.append(f"{len(wet)} dwarves stand in deep water (a flood?): {names}; the cistern's floodgate "
                         "is shut")
        else:
            # (0.105.35) kept: the game says who is wet, not where the water comes from
            ask_player(notes, f"{len(wet)} dwarves stand in deep water (a flood?): {names}; the cistern's "
                              "floodgate is not open, and DFHack doesn't say where water flows from, so the AI "
                              "can't find the leak; meanwhile the cistern's floodgate (if any) stays shut and the "
                              "wet are watched")
    for c in [c for c in _l(_d(s.get("deep")).get("cursed")) if isinstance(c, dict)]:
        if c.get("kind") == "vampire" and rules_.get("expel_vampires", True) and c.get("id") is not None:
            proposals.append(Proposal("cursed", {"type": "expel_dwarf", "unit_id": c["id"]},
                                      f"{c.get('name')} is a vampire (drinks sleeping dwarves' blood): send them away", 1))
    if (h.get("caged") or 0) > 0:
        notes.append(f"{h['caged']} invader(s) caught in cages: they stay caged (the prisoners rule decides "
                     "what becomes of them)")
    # cage traps re-armed: full cages need an animal stockpile to go to, and
    # empty cages to take their place
    full = int(h.get("cage_traps_full") or 0)
    if full:
        if not h.get("animal_piles") and not _d(_d(s.get("buildings")).get("clearing")).get("cages"):
            proposals.append(Proposal("cages", {"type": "place_surface", "kind": "cages"},
                                      f"{full} cage trap(s) hold a catch and there's no stockpile for full cages: "
                                      "make one, so the traps can be loaded again", 4))
        if int(h.get("free_cages") or 0) < full and not queued(s, {"wooden_cage"}):
            proposals.append(Proposal("cages", {"type": "work_order", "recipe": "wooden_cage", "amount": full},
                                      f"{full} cage trap(s) to load again and {h.get('free_cages') or 0} empty "
                                      "cages: make more", 4, True))
    if (h.get("miasma") or 0) >= cfg["miasma_note"]:
        notes.append(f"miasma in {h['miasma']} places: rot lying indoors (a refuse pile outside takes it)")


def no_melee_great(threats: dict, reach: list, policy: str) -> set:
    """(0.105.54) The great dangers in reach no melee squad goes at: their
    breath (fire, poison gas, a deadly cloud, dust) or webs make closing in
    suicidal (planner_matchup.melee_bar). Under "attack everything": none
    (the player's)."""
    if policy == "all":
        return set()
    from planner_matchup import melee_bar
    return {i for i in reach if _d(threats.get(i)).get("great_danger") and melee_bar(_d(threats.get(i)))}


def _no_melee_beasts(s: dict, memory, cfg: dict, threats: dict, cloud: set, squads: list,
                     proposals: list, notes: list) -> None:
    """(0.105.54) A great beast on the surface or inside that no melee squad may
    face (no_melee_great): melee squads on it come back; the crossbows go at
    it from a safe spot (inside the shut gates at the walls, as at a fire
    breather: planner_firebreath.fire_ranged_ok; or wherever it is when it
    is already inside the fort) when their power alone is about even with
    it (planner_matchup.fight_bar_of); else the dwarves hide and the note
    says the plan, its stage and what is missing."""
    from planner_matchup import fight_bar_of, judge as judge_, melee_bar, ranged_only
    from planner_firebreath import fire_ranged_ok
    from planner_holdfast import _inside_ids
    rows = [threats[i] for i in sorted(cloud, key=str)]
    ff = _d(getattr(memory, "fight_factor", None))
    factor = (lambda t: float(ff.get(fight_key(t)) or 1.0))
    policy = player_rules(s)["attack_policy"]
    off = called_off_ids(s, memory)
    ordered = {p.action.get("squad_id") for p in proposals if p.action.get("type") in ("squad_orders", "squad_station")}
    # melee squads on it: back
    for q in squads:
        kill = {x for x in _l(q.get("kill_ids")) if isinstance(x, int)}
        if (q.get("ai_orders") and kill & cloud and not _players(q) and q.get("id") not in ordered
                and not _shoots(q)):
            t = threats[sorted(kill & cloud, key=str)[0]]
            proposals.append(Proposal("squad_recall", {"type": "squad_orders", "squad_id": q["id"], "clear": True},
                                      f"{t.get('name') or 'the beast'}: {melee_bar(t)}: no melee squad faces it, "
                                      f"{q.get('name') or 'the squad'} comes back", 0))
            ordered.add(q["id"])
    shooters = [q for q in squads if _shoots(q) and can_fight(q, cfg) and not _players(q)]
    j = judge_(rows, ranged_only(shooters), factor)
    bar = fight_bar_of(s, memory, cfg)
    inside = _inside_ids(s)
    try:
        from planner_weather import weather_outside
        wx = weather_outside(s, cfg)
    except Exception:  # noqa: BLE001
        wx = set()
    names = ", ".join(f"{t.get('name') or 'a beast'} ({melee_bar(t)})" for t in rows[:3])
    why_not = {}
    for t in rows:
        i = t.get("id")
        why_not[i] = ("the fight with it was called off" if i in off else
                      "" if i in inside else fire_ranged_ok(s, memory, t, wx))
    may = [t["id"] for t in rows if not why_not[t.get("id")]]
    if policy == "never":
        notes.append(f"{names}: no melee; the dwarves hide (Rules tab: never)")
        return
    if not shooters:
        notes.append(f"{names}: no melee; the plan is crossbows from behind the gates; stage: hiding, missing a "
                     "crossbow squad")
        return
    if j["ratio"] < bar:
        notes.append(f"{names}: no melee; the plan is crossbows from behind the gates; stage: hiding (the "
                     f"crossbows {j['army']:.0f} against {j['need']:.0f}, about {bar * j['need']:.0f} needed: more "
                     "crossbows and bolts)")
        return
    if not may:
        notes.append(f"{names}: no melee; the plan is crossbows (they could take it: {j['army']:.0f} against "
                     f"{j['need']:.0f}); stage: waiting for a safe spot ({why_not[rows[0].get('id')]})")
        return
    on = set()
    for q in shooters:
        if q.get("ai_orders") and not q.get("sheltering"):
            on |= {x for x in _l(q.get("kill_ids")) if isinstance(x, int)}
    todo = [i for i in may if i not in on]
    free = [q for q in shooters if q.get("id") not in ordered and (not q.get("ai_orders") or q.get("sheltering"))]
    if todo and free:
        for q in free:
            proposals.append(Proposal("squad_attack", {"type": "squad_orders", "squad_id": q["id"], "kill": todo[:10]},
                                      f"{names}: no melee; {q.get('name') or 'the crossbow squad'} shoots at it from "
                                      f"a safe spot (the crossbows {j['army']:.0f} against {j['need']:.0f})", 0))
        _note_fight(s, memory, [threats[i] for i in todo])
    notes.append(f"{names}: no melee; the plan is crossbows from a safe spot; stage: "
                 + ("shooting" if (on & set(may)) or (todo and free) else "no free crossbow squad"))


def _shoots(q: dict) -> bool:
    """(0.105.54) A squad that shoots (the AI's crossbow uniform, or ranged power)."""
    from planner_matchup import shoots
    return shoots(q)


def watched_gate_levers(s: dict) -> set:
    """(0.105.33 fix) The levers the gate watcher pulls: each entrance's gate
    levers and a gatehouse's outer drawbridge (its rows carry one lever_id).
    A player's "AI gate" lever among them is the watcher's, not the AI gate's
    (_military_rules and note_gate_lever read the same set)."""
    ents = [e for e in _l(_d(s.get("entrances")).get("entrances")) if isinstance(e, dict)]
    watched = {lid for e in ents for b in _l(e.get("equipment")) if isinstance(b, dict) for lid in _l(b.get("levers"))}
    watched |= {b.get("lever_id") for e in ents for b in _l(e.get("outer"))
                if isinstance(b, dict) and b.get("lever_id") is not None}
    return watched

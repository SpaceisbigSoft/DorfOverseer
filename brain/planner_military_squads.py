"""planner_military_squads: the squads themselves (split out of planner_military
in r7, 0.105.62): the AI shelter when the alert is refused, how many soldiers
and their training, the crossbow squad and its bolts, the uniform weapon and
the anvil, idle hands, one squad sent after a lone intruder. planner_military
re-exports every name here."""

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

__all__ = ["GEAR_HELD", "SHELTER_RETRY_DAYS", "SHELTER_RETRY_THREAT_DAYS", "no_shelter", "weak_squad", "soldier_share", "civilian_cap", "soldiers_wanted", "keen_lift", "note_ranged_need", "crossbows_wanted", "WEAPON_IDS", "idle_hands"]


GEAR_HELD = {"weapons": "armed", "body": "armored", "helms": "helmed", "shields": "shielded", "pants": "legged",
             "boots": "booted", "gloves": "gloved"}


def _shelter_possible(s: dict, memory) -> bool:
    return (s.get("civ_alert_ready") is False and player_rules(s)["alert_shelter"]
            and memory.shelter_attempts < 2)


# (0.105.35) Nothing waits for the player: the AI shelter the game refused
# twice is tried again, every SHELTER_RETRY_DAYS (SHELTER_RETRY_THREAT_DAYS
# while a threat can reach the dwarves), not left to the player for good.
# (0.105.36) This is the shelter's only pace: its refusals book no back-off
# (planner_core note_refusal), so the note's "tried again in N day(s)" holds.
SHELTER_RETRY_DAYS = 28
SHELTER_RETRY_THREAT_DAYS = 3


def _shelter_due(s: dict, memory, threat: bool = False) -> bool:
    """(0.105.35) The AI shelter may be set up now: its first two tries, then
    again after a wait. The Rules switch (alert_shelter off) is the player's."""
    if _shelter_possible(s, memory):
        return True
    if s.get("civ_alert_ready") is not False or not player_rules(s)["alert_shelter"]:
        return False
    last = getattr(memory, "shelter_tick", None)
    if not isinstance(last, int):
        return True                     # (tried before the tick was kept: once more)
    wait = (SHELTER_RETRY_THREAT_DAYS if threat else SHELTER_RETRY_DAYS) * TICKS_PER_DAY
    return not 0 <= abs_tick(s) - last < wait


def _no_shelter_note(s: dict, memory, what: str, threat: bool = True) -> str:
    """(0.105.35) Said (not Needs you) when no alarm can sound: what the AI
    does meanwhile. (0.105.36) An unread alarm burrow is said as unread (it
    claimed a refusal that never happened); the days left use the pace
    _shelter_due uses."""
    meanwhile = "meanwhile the gates close when an enemy comes near and the squads answer by the Rules"
    if not player_rules(s)["alert_shelter"]:
        return (f"{what}, but there is no civilian-alert burrow and the AI shelter is off on the Rules tab, "
                f"so no alarm sounds: {meanwhile}")
    if not isinstance(s.get("civ_alert_ready"), bool):
        return (f"{what}, but the alarm's burrow couldn't be read this cycle, so no alarm is sounded now: "
                f"it is looked at again next cycle; {meanwhile}")
    last = getattr(memory, "shelter_tick", None) if memory is not None else None
    wait = SHELTER_RETRY_THREAT_DAYS if threat else SHELTER_RETRY_DAYS
    left = (max(1, -(-(last + wait * TICKS_PER_DAY - abs_tick(s)) // TICKS_PER_DAY))
            if isinstance(last, int) else 1)
    tries = getattr(memory, "shelter_attempts", 0) if memory is not None else 0
    return (f"{what}, but the game refused the AI shelter burrow ({tries} tries), so no alarm "
            f"can sound yet: it is tried again in {left} day(s); {meanwhile}")


def no_shelter(s: dict, memory, why: str, proposals: list, notes: list) -> None:
    """(0.105.35) An alarm wanted and no civilian-alert burrow to sound it with:
    the AI makes its own shelter now (at once, not at the set-up's leisure);
    with the Rules tab's "AI shelter" off, said (the player's switch).
    (0.105.36) Paced as plan()'s own shelter retry (_shelter_due), and said
    as a note (_no_shelter_note), never a Needs you: it raised "DF refused
    twice" for good while the AI kept trying, and when the burrow was only
    unread."""
    if memory is not None and _shelter_due(s, memory, True):
        proposals.append(Proposal("shelter", {"type": "setup_shelter"},
                                  f"{why}: no civilian-alert burrow, so the AI makes an \"AI shelter\" burrow "
                                  "over the inside of the fort and sounds the alarm with it", 0))
        notes.append(f"{why}: setting up a shelter so the alarm can sound")
    else:
        notes.append(_no_shelter_note(s, memory, why))


def weak_squad(squads: list) -> dict | None:
    """(0.105.35) When no squad has `min_squad_to_fight` armed: the best one
    with an armed soldier at all (most armed, then most members), for a lone
    enemy or a berserk dwarf inside rather than nobody."""
    rows = [q for q in squads if isinstance(q, dict) and q.get("id") is not None and (q.get("members") or 0) > 0]
    armed = [q for q in rows if isinstance(_d(q.get("power")).get("armed"), int)
             and not isinstance(_d(q.get("power")).get("armed"), bool) and _d(q.get("power"))["armed"] > 0]
    if not armed:
        return None
    return max(armed, key=lambda q: (int(_d(q.get("power")).get("armed") or 0), int(q.get("members") or 0)))


def soldier_share(s: dict, cfg: dict) -> float:
    """The share of citizens in squads, from Militarism's effective value
    (Extreme doubles it, since 0.94): -200 none, -100 5%, 0 10%, +100 40%,
    +200 90%, straight lines between."""
    v = max(-200.0, min(200.0, float(_traits(s).get("militarism", 0))))
    lo, mid, hi = cfg["soldier_share_low"], cfg["soldier_share_mid"], cfg["soldier_share_high"]
    top = cfg["soldier_share_extreme_high"]
    if v > 100:
        return hi + (top - hi) * (v - 100) / 100
    if v < -100:
        return lo * (1 - (abs(v) - 100) / 100)
    if v < 0:
        return mid + (mid - lo) * v / 100
    return mid + (hi - mid) * v / 100


def civilian_cap(s: dict, cfg: dict) -> int | None:
    """(0.105.2) The most soldiers the fort can field and still work: the
    adults less a floor of civilians (`civilians_min`, or `civilians_min_share`
    of the adults, the larger). War-hold (2 Nov) at Militarism 150 Extreme
    drafted 29 of 36 adults: the economy and the mood fell (unhappy 77%).
    None when the report has no adult count."""
    adults = _d(s.get("dwarves")).get("adults")
    if not isinstance(adults, int) or isinstance(adults, bool) or adults <= 0:
        return None
    floor = max(cfg["civilians_min"], math.ceil(adults * cfg["civilians_min_share"]))
    return max(0, adults - floor)


def soldiers_wanted(s: dict, citizens: int, cfg: dict, idle: bool = False, memory=None,
                    floor: dict | None = None) -> int:
    """From the Militarism trait; more when many dwarves long to fight or
    train (the Fight / MartialTraining needs: soldiering meets them), unless
    Militarism is at its lowest. (0.105.2) Below 0 the need-driven extra
    shrinks with the slider (gone at -100); never past the civilian cap.
    (0.105.54) Never below the defence floor by threat (planner_defence_floor:
    enough to win an even fight against the biggest threat seen or here),
    whatever the Militarism; the slider's number stays when larger."""
    want = _soldiers_wanted(s, citizens, cfg, idle)
    from planner_defence_floor import defence_floor
    f = floor if isinstance(floor, dict) else defence_floor(s, memory, cfg, citizens)
    want = max(want, int(f.get("soldiers") or 0))
    # (0.105.8) a small guard in every fort of `guard_min_adults`+ adults,
    # whatever the Militarism or preset (the player, 2 Nov: B's Monastery at
    # -100 had 2 soldiers and nothing to wear while thieves came)
    adults = _d(s.get("dwarves")).get("adults")
    adults = min(adults, citizens) if isinstance(adults, int) and not isinstance(adults, bool) else citizens
    if adults >= cfg.get("guard_min_adults", 15):
        want = max(want, cfg.get("guard_min_soldiers", 3))
    cap = civilian_cap(s, cfg)
    return want if cap is None else min(want, cap)


def _soldiers_wanted(s: dict, citizens: int, cfg: dict, idle: bool = False) -> int:
    base = round(citizens * soldier_share(s, cfg))
    # (0.100.1, review) a handful of dwarves keep to their work: no soldiers
    # below SQUAD_MIN_CITIZENS unless a threat can reach them (the alert and
    # the soldiers rule raise one then); on day one of an embark a militia
    # commander took the woodcutter's axe
    if citizens < cfg["squad_min_citizens"] and not _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return 0
    fighters = max(unmet(s, "Fight"), unmet(s, "MartialTraining"))
    traits = _d(_d(s.get("settings")).get("traits"))
    # (0.103.9) a small fort too, by its share: Enxah's 28 had 23 distracted
    # for want of training (the line was 15 of 30+ citizens) and 10 miserable
    need_at = min(cfg["fight_needs_at"], max(4, math.ceil(citizens * cfg["fight_needs_share"])))
    # (0.105.2) a peaceful fort (Militarism below 0) drafts fewer for the
    # needs: Monastery at -60 drafted 32 of 70 (its slider asks 5).
    # (0.105.10, 14.1 step 3) scaled all the way: an eighth of the extra at
    # Militarism 0, all of it at +100, almost none at -60 (the six forts,
    # y257: Militarism 0 forts at 28-41% soldiers, the War-hold 52%: the
    # slider showed only at its top)
    mil = max(-100.0, min(100.0, float(traits.get("militarism", 0) or 0)))
    lean = ((mil + 100) / 200) ** 3             # the extra soldiers: 1/8 at 0, 0.42 at +50, all at +100
    cap_lean = 1 + min(0.0, mil) / 100          # the cap (0.105.2): lower only below 0
    if fighters >= need_at and traits.get("militarism", 0) > -100 and citizens >= cfg["fight_min_citizens"]:
        # (0.104.61) a quarter of the fort badly wanting to train or fight: the
        # wider idle-hands caps (Enxah, winter y74: MartialTraining 30 of 93
        # badly with 25 soldiers, all on constant training; the 30% cap held)
        nd = _d(_d(s.get("needs")).get("needs"))
        badly = max(int(_d(nd.get("MartialTraining")).get("badly") or 0), int(_d(nd.get("Fight")).get("badly") or 0))
        if badly >= citizens * cfg["fight_badly_share"]:
            idle = True
        if idle:
            # (0.83) many idle hands: training costs no work, and it meets
            # Fight, MartialTraining and LearnSomething (a skill rank) at once
            idle = int(_d(s.get("dwarves")).get("idle_adults") or 0)
            extra = min(fighters // 2, max(cfg["fight_soldiers_max"], idle), cfg["idle_fight_soldiers_max"])
            return min(base + round(extra * lean), max(base, round(citizens * cfg["idle_fight_share_max"] * cap_lean)))
        extra = min(fighters // 2, cfg["fight_soldiers_max"])
        return min(base + round(extra * lean), max(base, round(citizens * cfg["fight_share_max"] * cap_lean)))
    return base


def _train_mode_held(s: dict, memory, cfg: dict, want_all: bool) -> bool:
    """(0.104.168) The rotation's mode (every squad training, or half resting)
    held a while once it changes: every squad training at least
    `train_all_hold_days`, half resting at least `train_half_hold_days`.
    The 0.104.149 dead band wasn't enough: the need DF counts as "badly"
    swung past both lines within days (the AI's run of 31 Oct-1 Nov, 8
    squads: all train on day 14, half off on day 19, all on again two days
    later; squad_routine 44-88 times in 90 minutes, every soldier dropping
    what he carried each time). A mode first seen is taken as it is (no hold)."""
    if memory is None:
        return want_all
    now = abs_tick(s)
    tm = _d(getattr(memory, "train_mode", None))
    was, since = tm.get("all"), tm.get("tick")
    if isinstance(was, bool) and was != want_all and isinstance(since, int):
        hold = cfg["train_all_hold_days"] if was else cfg["train_half_hold_days"]
        if 0 <= now - since < hold * TICKS_PER_DAY:
            return was
    if was != want_all:
        memory.train_mode = {"all": want_all, "tick": now if isinstance(was, bool) else None}
    return want_all


def keen_lift(s: dict, memory, cfg: dict, want: int, have: int, citizens: int, threat: bool) -> int:
    """(0.104.168) In a crisis, while civilians badly want to train (they can
    meet MartialTraining only in a squad, and a spar eases stress), the
    soldiers wanted rise so the fill drafts them (the keen first; never a
    mother, a noble, a patient, or one breaking down who doesn't long to
    fight: lua/ai-military.lua candidates): up to `keen_lift_max`, within
    `idle_fight_share_max` of the fort. The lift is remembered and held
    `keen_lift_days` after the keen were last many, so drafting them (the keen
    count falls) doesn't make them extra soldiers to trim (0.104.66). Never
    while threats can reach the fort, nor at Militarism -50 or lower.
    Teacheroar, 1 Nov: 45% unhappy, 18 keen civilians, 89 distracted by
    unmet MartialTraining, 34 soldiers for 33 wanted."""
    if memory is None:
        return want
    traits = _d(_d(s.get("settings")).get("traits"))
    if threat or (traits.get("militarism", 0) or 0) <= -50:
        return want
    now = abs_tick(s)
    kl = _d(getattr(memory, "keen_lift", None))
    lift = 0
    if isinstance(kl.get("tick"), int) and 0 <= now - kl["tick"] < cfg["keen_lift_days"] * TICKS_PER_DAY:
        lift = max(0, int(kl.get("n") or 0))
    # (0.104.168, review) sized on the keen the fill can draft (bridge
    # `keen_draftable`: the fill's own test, strict; never nobles, nursing
    # mothers, patients or the very unhappy); an older bridge without it: no lift
    nd = _d(s.get("needs"))
    kd = nd.get("keen_draftable")
    keen = int(kd) if isinstance(kd, int) and not isinstance(kd, bool) else 0
    if _d(getattr(memory, "crisis", None)).get("why") and keen >= cfg["soldier_swap_keen_min"]:
        # places for every draftable keen one: the soldiers there are and the
        # keen. The lift's places are filled by the keen only (keen_only), so
        # drafting one moves him from one count to the other and the need
        # holds; the most over the held period (a count that bounces can't
        # ratchet it up)
        lift = min(cfg["keen_lift_max"], max(lift, have + keen - want, 0))
        memory.keen_lift = {"n": lift, "tick": now}
    elif not lift and kl:
        memory.keen_lift = {}
    if lift <= 0:
        return want
    return max(want, min(want + lift, round(citizens * cfg["idle_fight_share_max"])))


def _training_rotation(s: dict, memory, squads: list, train_to: str, off: str, cfg: dict,
                       proposals: list) -> set:
    """Two or more squads the AI trains: they take turns, half of them
    training and the rest back at work, the turn passing each month, so the
    fort isn't short of hands and every squad keeps its edge. Only squads
    the AI put on training (or rested itself); one you set is left alone.
    A militant fort (Militarism 50+) trains them all. Returns the squads in
    the rotation."""
    mine = sorted(q["id"] for q in squads
                  if q.get("id") is not None and (q.get("members") or 0) > 0 and not q.get("ai_orders")
                  and q["id"] in memory.squads_trained
                  and ("off duty" not in str(q.get("routine") or "").lower() or q["id"] in memory.squads_rested))
    if len(mine) < 2:
        return set()
    n, k = len(mine), -(-len(mine) // 2)
    # (0.104.53) while many soldiers badly want to train, all of them do
    # (Enxah: MartialTraining 16 badly, 52 distracted, a squad off duty by turns)
    cit = max(1, int(_d(s.get("dwarves")).get("total") or 0))
    # (0.105.80) the soldiers' own longing when the report counts it: B, 23 Nov:
    # 17 badly, 16 of them civilians, kept all 4 squads (34 soldiers) on
    # constant training; the soldiers lost every hour off (20 of 20 missing
    # drink, 13 of 13 merriment, 40% unhappy). Civilians who long to train go
    # through soldier_swap and the training squad, not through more training.
    mtd = _d(_d(_d(s.get("needs")).get("needs")).get("MartialTraining"))
    mts = mtd.get("badly_soldiers")
    mt = int(mts if isinstance(mts, int) and not isinstance(mts, bool) else (mtd.get("badly") or 0))
    # (0.104.149) a dead band: once every squad trains they keep on until the
    # need falls to `train_all_off_share`, read from the squads' own routines
    # (Teacheroar, 1 Nov: one threshold flipped 8 squads on and off duty 64
    # times a night, every soldier dropping what he carried each time)
    by_id0 = {q["id"]: q for q in squads if q.get("id") is not None}
    all_on = all("off duty" not in str(by_id0[sid].get("routine") or "").lower() for sid in mine)
    want_all = mt >= max(5, cit * cfg["train_all_share"]) or (
        all_on and mt >= max(3, cit * cfg["train_all_off_share"]))
    if _train_mode_held(s, memory, cfg, want_all):
        k = n
    # (0.105.97) while a fifth of the soldiers badly miss friends, drink or
    # prayer (planner_leisure.company_short), half the squads train at most,
    # one at least (B, 23 Nov: 2 of 3 squads on constant training, 30 of 32
    # missing drink soldiers, 37 soldiers among 76 of 88 missing friends)
    from planner_leisure import company_short, squad_mostly_short
    short = company_short(s, cfg)
    if short:
        k = min(k, max(1, n // 2))
    turn = abs_tick(s) // (cfg["train_rotate_days"] * TICKS_PER_DAY)
    by_id = {q["id"]: q for q in squads if q.get("id") is not None}
    order = [mine[(turn * k + j) % n] for j in range(n)]
    # (0.105.97) a squad off duty most of whose members badly miss these
    # isn't sent straight back to training: another resting squad takes its
    # turn, and it rests one turn more at most (memory.leisure_hold: squad ->
    # when first held); one squad trains whatever
    now = abs_tick(s)
    hold = _d(getattr(memory, "leisure_hold", None)) if short else {}
    hold_ticks = cfg["train_rotate_days"] * TICKS_PER_DAY
    on, held = [], []
    for sid in order:
        if len(on) >= k:
            break
        resting = "off duty" in str(by_id[sid].get("routine") or "").lower()
        since = hold.get(str(sid))
        if (short and resting and squad_mostly_short(s, cfg, sid)
                and not (isinstance(since, int) and now - since >= hold_ticks)):
            held.append(sid)
            continue
        on.append(sid)
    if not on:
        on = [order[0]]
        held = [x for x in held if x != order[0]]
    if memory is not None and (short or getattr(memory, "leisure_hold", None)):
        # a hold run out is kept while the squad still rests (the routine
        # changes by the next report), so it isn't held afresh meanwhile
        keep = held + [x for x in on if str(x) in hold
                       and "off duty" in str(by_id[x].get("routine") or "").lower()]
        memory.leisure_hold = {str(x): (hold.get(str(x)) if isinstance(hold.get(str(x)), int) else now)
                               for x in keep}
    on = set(on)
    for sid in mine:
        q = by_id[sid]
        resting = "off duty" in str(q.get("routine") or "").lower()
        # (0.100) a squad on its turn still on staggered training (the AI's
        # older choice) moves to the rotation's routine, constant training
        staggered = "staggered" in str(q.get("routine") or "").lower() and "staggered" not in train_to.lower()
        why = (f"; {short} soldiers badly miss friends, drink or prayer: half the squads train at most"
               if short else "")
        if sid in on and (resting or staggered):
            proposals.append(Proposal("train", {"type": "squad_routine", "squad_id": sid, "routine": train_to},
                                      f"{q.get('name') or 'a squad'}'s turn to train this month "
                                      f"({len(on)} of {n} squads train at a time{why})", 4))
        elif sid not in on and not resting:
            proposals.append(Proposal("train", {"type": "squad_routine", "squad_id": sid, "routine": off},
                                      f"{q.get('name') or 'a squad'} has trained its month: back to work while "
                                      f"another squad trains ({len(on)} of {n} at a time{why})", 4))
    return set(mine)


def note_ranged_need(s: dict, memory, cfg: dict | None = None, traits: dict | None = None) -> str:
    """(r2h4) A fire breather or a flier that can reach the dwarves now
    (reachable_threats: no wildlife, nothing down in the underworld):
    remembered (memory.ranged_need {tick, why}), as only crossbows answer
    them (a fire breather: planner_firebreath; a flier: planner_matchup).
    The words, or ""."""
    from planner_matchup import fire_breather
    reach = set(reachable_threats(s, _d(traits), cfg or PLANNER_CONFIG))
    for t in _l(_d(s.get("others_on_map")).get("threats")):
        if not isinstance(t, dict) or t.get("id") not in reach:
            continue
        why = ("a fire breather" if fire_breather(t) else "a flier" if t.get("flier") else "")
        if why:
            words = f"{why} ({t.get('name') or t.get('race') or 'a beast'})"
            if memory is not None:
                try:
                    memory.ranged_need = {"tick": abs_tick(s), "why": words}
                except Exception:                     # (an old memory object): this cycle only
                    pass
            return words
    return ""


def crossbows_wanted(s: dict, memory, cfg: dict, traits: dict | None, manned: list) -> str:
    """(r2h4) Why the fort wants crossbows (and so a Bowyer's workshop), or "".
    No fort ever had a ranged soldier (audit A2 7: `ranged: 0` in all 14
    squads): a fort with a squad and Militarism above the lowest
    (`h4_bowyer_min_militarism`), or one that met a fire breather or a flier
    in the last `h4_ranged_need_days`."""
    now = note_ranged_need(s, memory, cfg, traits)
    if now:
        return f"{now} is on the map: only crossbows answer it"
    rn = _d(getattr(memory, "ranged_need", None)) if memory is not None else {}
    tick = rn.get("tick")
    if isinstance(tick, int) and abs_tick(s) - tick <= cfg.get("h4_ranged_need_days", 1344) * TICKS_PER_DAY:
        return f"the fort met {rn.get('why') or 'a fire breather or a flier'}: only crossbows answer it"
    mil = _d(traits).get("militarism")
    mil = mil if isinstance(mil, (int, float)) and not isinstance(mil, bool) else 0
    if manned and mil > cfg.get("h4_bowyer_min_militarism", -100):
        return f"Militarism {mil:g} and {len(manned)} squad(s): a crossbow squad shoots from behind the gates"
    return ""


def _bowyer_rule(s: dict, cfg: dict, proposals: list, why: str) -> bool:
    """(r2h4) The Bowyer's workshop for crossbows and wooden bolts: asked as
    a lone shop with `crossbows` (the builder gives it no project slot: B
    and E's ordinary `industry` ask lost to "already N unfinished building
    projects" every time, and B met its beast with 0 armed soldiers). Not
    while one is being built. True when asked."""
    from planner_moods import _shop_coming
    if _has_shop(s.get("buildings") or {}, "Bowyers") or _shop_coming(s, "Bowyers"):
        return False
    if "Bowyers" not in BUILDABLE_SHOPS:
        return False
    proposals.append(Proposal("crossbow_shop", {"type": "start_project", "kind": "workshops", "shops": ["Bowyers"],
                                                "crossbows": True},
                              f"{why}; no bowyer's workshop: build one (crossbows and wooden bolts)", 3))
    return True


def _crossbow_order(s: dict, g: dict, cfg: dict, proposals: list, members: int, short: int, shop: bool,
                    wood: int) -> bool:
    """(r2h4) Crossbows for the crossbow soldiers short of one: wooden at the
    bowyer's, else metal at the forge while bars are plenty (no bowyer's
    needed). True when ordered."""
    n = min(short, cfg.get("h4_crossbow_order_max", 5))
    if shop and wood >= n:
        proposals.append(Proposal("arms", {"type": "work_order", "recipe": "wooden_crossbow", "amount": n},
                                  f"{members} crossbow soldiers and {g.get('ranged_armed') or 0} with a "
                                  f"crossbow: make {n} at the bowyer's", 3, True))
        return True
    bars = _d(g.get("bars"))
    metal = next((m for m in GEAR_METALS if (bars.get(m) or 0) >= n + cfg["bolt_bars_keep"]), None)
    if metal and g.get("forges"):
        proposals.append(Proposal("arms", {"type": "work_order", "recipe": "metal_crossbow", "amount": n,
                                           "material": f"INORGANIC:{metal}"},
                                  f"{members} crossbow soldiers and {g.get('ranged_armed') or 0} with a "
                                  f"crossbow" + ("" if shop else " and no bowyer's workshop")
                                  + f": forge {n} in {metal.lower().replace('_', ' ')}", 3, True))
        return True
    return False


def _ranged_squad_rule(s: dict, g: dict, squads: list, templates: list, cfg: dict, proposals: list,
                       squads_made: list | None = None, peaceful: bool = False, memory=None,
                       traits: dict | None = None) -> None:
    """Crossbows: with two squads or more, one (the newest the AI dresses)
    becomes a crossbow squad, in the fort's crossbow uniform with bolts for
    combat and training; then crossbows and bolts for it, wooden at the
    bowyer's (metal bolts at the forge when bars are plenty).
    (0.105.54) `peaceful` (Militarism below 0, bolts can be made: see
    planner_defence_floor.peaceful_ranged): every squad the AI made shoots
    (its new squads are marksdwarves), so a peaceful fort fights from behind
    its gates; the player's own squads keep their arms."""
    manned = [q for q in squads if (q.get("members") or 0) > 0 and q.get("id") is not None]
    if not any("crossbow" in t.lower() for t in templates):
        return
    ranged = [q for q in manned if is_ranged(q)]
    if peaceful:
        made_ = [q for q in manned if q.get("ai_uniform") and q["id"] in (squads_made or []) and not is_ranged(q)]
        # (0.105.54 merge) one melee squad always stays: crossbows alone can't
        # hold a doorway or close on an enemy inside
        if len([q for q in manned if not is_ranged(q)]) <= 1:
            made_ = []
        if made_:
            q = min(made_, key=lambda q: q["id"])
            kind = "metal" if "metal" in str(q.get("ai_uniform") or "").lower() else "leather"
            proposals.append(Proposal("uniform", {"type": "set_uniform", "squad_id": q["id"], "kind": kind,
                                                  "ranged": True},
                                      f"a peaceful fort (Militarism below 0) fights from behind its gates: make "
                                      f"{q.get('name') or 'a squad the AI made'} a crossbow squad", 4))
            return
    # which squad shoots: the newest the AI made itself, never the fort's
    # first squad while there are others (Oct 23: the first squad, with the
    # militia commander and the Axe Lord, was given crossbows because it was
    # the only one whose uniform the AI had recorded)
    mine = [q for q in manned if q.get("ai_uniform")]       # (one without a uniform gets one first)
    first = min((q["id"] for q in manned), default=None)
    made = [q for q in mine if q["id"] in (squads_made or [])]
    pool = made or [q for q in mine if q["id"] != first or len(manned) < 2]
    best = max(pool, key=lambda q: q["id"]) if pool else None

    def kind_of(q):
        return "metal" if "metal" in str(q.get("ai_uniform") or "").lower() else "leather"
    if len(manned) >= cfg["ranged_from_squads"] and best is not None and not is_ranged(best) and (
            not ranged or all(q["id"] not in [b["id"] for b in pool] for q in ranged)):
        proposals.append(Proposal("uniform", {"type": "set_uniform", "squad_id": best["id"], "kind": kind_of(best),
                                              "ranged": True},
                                  (f"{len(manned)} squads and none shoots" if not ranged else
                                   f"{ranged[0].get('name') or 'an older squad'} shoots but its fighters "
                                   "are the fort's best at close quarters")
                                  + f": make {best.get('name') or 'a newer squad'} a crossbow squad (they shoot from "
                                  "behind the gates)", 4))
        return
    if len(ranged) > 1 and not peaceful:
        # one crossbow squad is enough: the others back to their melee uniform
        keep = best if best is not None and is_ranged(best) else max(ranged, key=lambda q: q["id"])
        q = min((q for q in ranged if q["id"] != keep["id"]), key=lambda q: q["id"])
        proposals.append(Proposal("uniform", {"type": "set_uniform", "squad_id": q["id"], "kind": kind_of(q)},
                                  f"{len(ranged)} crossbow squads: {q.get('name') or 'an older squad'} goes back "
                                  "to close combat", 4))
        return
    # (r2h4) the Bowyer's workshop before the crossbow squad needs it
    try:
        want_why = crossbows_wanted(s, memory, cfg, traits, manned)
    except Exception:                                  # never stops the rule
        want_why = ""
    if not ranged:
        if want_why:
            _bowyer_rule(s, cfg, proposals, want_why)
        return
    if "ranged_armed" not in g:
        return
    members = sum(int(q.get("members") or 0) for q in ranged)
    wood = int(_d(s.get("stocks")).get("wood") or 0)
    shop = _has_shop(s["buildings"], "Bowyers")
    have = int(g.get("ranged_armed") or 0) + int(g.get("spare_crossbows") or 0)
    # (0.105.46, I3) every crossbow the fort has, in bins and put away off duty
    # too (370 crossbow orders in a day: a squad off duty read as unarmed and
    # the crossbows in bins as none)
    if isinstance(g.get("crossbows_total"), int) and not isinstance(g.get("crossbows_total"), bool):
        have = max(have, g["crossbows_total"])
    short = members - have - queued(s, {"wooden_crossbow", "metal_crossbow"})
    if short > 0:
        # (r2h4) wood at the bowyer's, else metal at the forge
        if _crossbow_order(s, g, cfg, proposals, members, short, shop, wood):
            return
    want = members * cfg["bolts_per_soldier"]
    bshort = want - int(g.get("bolts") or 0) - 25 * (queued(s, {"wooden_bolts"}) + queued(s, {"metal_bolts"})
                                                     + queued(s, {"bone_bolts"}))
    if bshort > 0:
        jobs = min(5, max(1, -(-bshort // 25)))
        bars = _d(g.get("bars"))
        metal = next((m for m in GEAR_METALS if (bars.get(m) or 0) >= jobs + cfg["bolt_bars_keep"]), None)
        # (0.105.113 item11) the forge's bars go to the soldiers' arms first:
        # while a place waits for a weapon and the bowyer has wood, the bolts
        # (shot away at the range) are wooden. C: ~110 orders of iron bolts in
        # 12 hours, 19 melee places without a weapon and 3 squads unarmoured
        wood_first = shop and wood >= jobs + cfg.get("bolt_wood_keep", 10) and (
            int(g.get("weapon_gaps") or 0) > 0 or int(g.get("armed") or 0) < int(g.get("soldiers") or 0))
        if metal and g.get("forges") and not wood_first:
            proposals.append(Proposal("arms", {"type": "work_order", "recipe": "metal_bolts", "amount": jobs,
                                               "material": f"INORGANIC:{metal}"},
                                      f"{g.get('bolts') or 0} bolts for {members} crossbow soldiers ({want} wanted): "
                                      f"make {jobs} lot(s) in {metal.lower()}", 4, True))
        elif shop and wood >= jobs:
            proposals.append(Proposal("arms", {"type": "work_order", "recipe": "wooden_bolts", "amount": jobs},
                                      f"{g.get('bolts') or 0} bolts for {members} crossbow soldiers ({want} wanted): "
                                      f"make {jobs} lot(s) of wooden bolts", 4, True))
        elif (_has_shop(s["buildings"], "Craftsdwarfs")
              and int(_d(s.get("needs")).get("bones") or 0) >= jobs + cfg.get("h4_bone_bolts_keep", 10)):
            # (r2h4) bone bolts at the craftsdwarf's: no forge bars, no bowyer's
            proposals.append(Proposal("arms", {"type": "work_order", "recipe": "bone_bolts", "amount": jobs},
                                      f"{g.get('bolts') or 0} bolts for {members} crossbow soldiers ({want} wanted): "
                                      f"make {jobs} lot(s) of bone bolts", 4, True))
    # (0.100) a crossbow soldier carries bolts in a quiver and picks a spare
    # one up himself: leather quivers until there is one for each
    sup = _d(s.get("supplies"))
    if isinstance(g.get("ranged_places"), int) and isinstance(g.get("quivers_assigned"), int):
        # (0.105.113 item11) the places themselves (bridge 0.105.0): a quiver
        # worn by a hunter or lying on no equipment list is no soldier's. C:
        # 10 crossbow soldiers, 5 with a quiver, `quivers` 9 and `quivers_worn`
        # 8 read as plenty, and none was made
        qshort = (g["ranged_places"] - g["quivers_assigned"] - int(g.get("quivers_free") or 0)
                  - queued(s, {"leather_quiver"}))
    elif isinstance(sup.get("quivers"), int):
        qshort = (members - sup["quivers"] - int(sup.get("quivers_worn") or 0)
                  - queued(s, {"leather_quiver"}))
    else:
        qshort = 0
    if isinstance(sup.get("quivers"), int) or isinstance(g.get("ranged_places"), int):
        leather = int(_d(s.get("stocks")).get("leather") or 0)
        if qshort > 0 and leather > 0 and _has_shop(s["buildings"], "Leatherworks"):
            n = min(qshort, leather, cfg["max_quiver_order"])
            proposals.append(Proposal("arms", {"type": "work_order", "recipe": "leather_quiver", "amount": n},
                                      (f"{g['ranged_places']} crossbow places, {g['quivers_assigned']} with a "
                                       f"quiver and {int(g.get('quivers_free') or 0)} free"
                                       if isinstance(g.get("ranged_places"), int) and isinstance(g.get("quivers_assigned"), int)
                                       else f"{members} crossbow soldiers, {sup.get('quivers')} spare quiver(s) and "
                                            f"{int(sup.get('quivers_worn') or 0)} worn")
                                      + f": make {n} of leather", 4, True))
    if not shop:
        # (r2h4) asked whatever the shortage (bolts are used up, crossbows
        # break), as a lone shop that takes no project slot (_bowyer_rule)
        _bowyer_rule(s, cfg, proposals, want_why or f"a crossbow squad of {members}")


WEAPON_IDS = {"axe": "ITEM_WEAPON_AXE_BATTLE", "spear": "ITEM_WEAPON_SPEAR", "mace": "ITEM_WEAPON_MACE"}


def _uniform_weapon_rule(s: dict, g: dict, squads: list, rules_: dict, proposals: list) -> None:
    """The fort's templates arm a squad with "any melee weapon", and a mining
    pick is one: region2's soldiers took a miner's pick. Once there are
    enough of the AI's weapon (battle axes by default, the Rules tab's
    choice) for a squad the AI dressed, its uniform asks for that weapon
    and nothing else; the pick goes back to the miners."""
    wid = WEAPON_IDS.get(rules_["gear_weapon"])
    spare = int(_d(g.get("spare_weapons")).get(wid) or 0)
    for q in squads:
        ai = str(q.get("ai_uniform") or "")
        n = int(q.get("members") or 0)
        if is_ranged(q):
            # (0.99.11) a crossbow squad keeps its crossbows: region2's squad 56
            # had its weapon turned to battle axes; it gets the crossbow back
            if "|weapon:" in ai and "|weapon:ITEM_WEAPON_CROSSBOW" not in ai:
                proposals.append(Proposal("uniform", {"type": "set_uniform_weapon", "squad_id": q["id"],
                                                      "weapon": "ITEM_WEAPON_CROSSBOW"},
                                          f"{q.get('name') or 'squad ' + str(q.get('id'))} is a crossbow squad "
                                          "whose uniform asks for another weapon: crossbows again", 3))
                return
            continue
        if not ai or not n or f"|weapon:{wid}" in ai or spare < n:
            continue
        proposals.append(Proposal("uniform", {"type": "set_uniform_weapon", "squad_id": q["id"], "weapon": wid},
                                  f"{spare} {rules_['gear_weapon']}s for the {n} soldiers of "
                                  f"{q.get('name') or 'squad ' + str(q.get('id'))}: their uniform asks for "
                                  f"{rules_['gear_weapon']}s, not any weapon (a soldier may take a miner's pick)", 4))
        return


def _anvil_rule(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """(0.86) A project whose forge has waited STALE_PROJECT_DAYS to be
    built: a forge needs an anvil, and the AI never made one. One anvil at
    the forge the fort has, in the best metal with bars to spare (3 bars)."""
    open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
    stuck = [p for p in open_ if (_d(p.get("furnish")).get("days") or 0) >= STALE_PROJECT_DAYS
             and _d(_d(p.get("furnish")).get("waiting")).get("Workshop")
             and any(k in _d(p.get("furniture")) for k in ("MetalsmithsForge", "MagmaForge"))]
    sup = _d(s.get("supplies"))
    if not stuck or "anvils" not in sup or (sup.get("anvils") or 0) > 0 or queued(s, {"metal_anvil"}):
        return
    if not _has_shop(s["buildings"], "MetalsmithsForge"):
        notes.append("a new forge waits for an anvil and there is no forge to make one: it waits for one from a "
                     "caravan")
        return
    metal = _best_metal(s, 2)
    if not metal:
        notes.append("a new forge waits for an anvil: no weapon-grade metal bars to make one")
        return
    days = max((_d(p.get("furnish")).get("days") or 0) for p in stuck)
    proposals.append(Proposal("anvil", {"type": "work_order", "recipe": "metal_anvil", "amount": 1, "material": metal},
                              f"a new forge has waited {days} days to be built: it needs an anvil: make one in "
                              f"{metal.split(':')[-1].lower()}", 4, True))


def idle_hands(s: dict, memory, cfg: dict) -> bool:
    """Many idle hands (see update_idle); without memory, today's share alone."""
    if memory is not None and isinstance(getattr(memory, "idle_avg", None), (int, float)):
        return bool(memory.idle_hands)
    return _idle_share(s) >= idle_line(s, cfg, "idle_train_share")


# --- (0.105.3) a lone intruder doesn't seal the fort; no AI lockdown without end ----------
#
# B "Monastery" (2 Nov): a human siege killed 10 at 05:13; one thief stayed
# (Trustdaub, unit 7527, 18 tiles and 4 levels from the nearest dwarf, "can
# reach the dwarves"). For him the alarm stayed up and the gate watcher kept
# the only hatch shut for 2.5 real hours: 6 citizens and 51 visitors outside,
# 26 animals being led to pastures outside at once, all re-routing to a way
# in that wasn't there; the game fell to 1-3 FPS, and opening the hatch by
# hand set it racing. A shut gate keeps out what is outside; one already in
# isn't kept out, only everyone else is.


# (0.105.8) A (2 Nov, 14:00): a lone human axeman (a thief) OUTSIDE the
# fort. The watcher shut its only gate, a 1-wide hatch: the three squads sent
# to kill him were shut in, 10 citizens and 4 visitors shut out with him, and
# the game fell to 3 FPS. A gate keeps out a siege; one or two ordinary
# enemies are the squads' to deal with, and the citizens outside need a way in.


def _one_enemy_hold(s: dict, cfg: dict, memory, traits) -> bool:
    """(0.105.47, R2 item 7) the AI gate lever stays shut as the watcher's
    gates do for one ordinary enemy near a gate or too strong (planner_holdfast)."""
    from planner_holdfast import one_enemy_hold
    return bool(one_enemy_hold(s, cfg, memory, traits))


def _lone_squad(s: dict, memory, cfg: dict, squads: list, lone: list, rows: dict,
                proposals: list, notes: list) -> None:
    """One armed squad goes after the lone intruders (whatever the Rules
    tab's "Send squads against" says: a thief inside is for the guard, not a
    battle; B's Monastery said "never" and kept the fort shut instead). B
    sent all four squads, one after another: one is enough, and none goes
    while one is already on them."""
    names = ", ".join(sorted({str(rows[i].get("name") or "?") for i in lone}))[:80]
    want = set(lone)
    for q in squads:
        kill = q.get("kill_ids")
        # (0.105.4 review) only a squad whose kill order names them is on them
        if (q.get("ai_orders") and not q.get("guarding") and not q.get("sheltering")
                and isinstance(kill, list) and want & set(kill)):
            notes.append(f"{q.get('name') or 'a squad'} is after {names} inside the fort")
            return
    if any(p.rule == "squad_attack" and want & set(_l(p.action.get("kill"))) for p in proposals):
        return                              # the thieves rule (planner_threats) sent one this cycle
    # (a squad still on the siege's old orders may go too: a free one first)
    able = [q for q in squads if can_fight(q, cfg) and q.get("id") is not None]
    if not able:
        # (0.105.35) nothing waits for the player: the best squad with anyone
        # armed goes (a lone intruder, not a siege), else said what the AI does
        q = weak_squad(squads)
        if q is not None:
            proposals.append(Proposal("squad_attack", {"type": "squad_orders", "squad_id": q["id"], "kill": lone[:10]},
                                      f"only {names} left, inside the fort, and no squad has "
                                      f"{cfg['min_squad_to_fight']}+ armed: send {q.get('name') or 'the squad'} "
                                      f"({_d(q.get('power')).get('armed')} armed; the gates stay open)", 0))
            return
        notes.append(f"{names} inside the fort and no squad has anyone armed to send: the gates stay open "
                     "(shut, they keep only the others out), the alarm keeps the civilians in the shelter "
                     "meanwhile, and the squads are armed first")
        return
    q = max(able, key=lambda q: (not q.get("ai_orders") or bool(q.get("sheltering")),
                                 int(_d(q.get("power")).get("armed") or 0), int(q.get("members") or 0)))
    proposals.append(Proposal("squad_attack", {"type": "squad_orders", "squad_id": q["id"], "kill": lone[:10]},
                              f"only {names} left, inside the fort: send {q.get('name') or 'the squad'} "
                              "(one squad; the gates stay open)", 0))

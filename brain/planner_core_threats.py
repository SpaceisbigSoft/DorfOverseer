"""planner_core_threats: part of planner_core (split out of planner_core.py in r7, which re-exports
every name): threat triage (wildlife, lone thieves, reachable threats, all clear) and which squads
can fight."""

from __future__ import annotations
from digest import _d, _l
from planner_config import PLANNER_CONFIG
from planner_core_base import abs_tick, TICKS_PER_DAY


# (0.105.48, K1) Threat triage. A falcon, a kobold thief, a wolf and 60
# goblins all got the alarm, the gates and every able squad (audit A6). Two
# kinds of "danger" in DF's sense are no reason for the fort-wide answer:
#   * wildlife: an animal (DF's isAnimal; agitated or not) that is no
#     invader, no great danger, no night creature or undead, breathes no fire,
#     breaks no buildings, and is smaller than `wildlife_alarm_size`: a
#     hunting squad (planner_siege's wildlife rule) at most;
#   * a lone thief or snatcher (the threats section's thieves) when they are
#     all that can reach the dwarves, `lone_intruder_max` at most, nothing held
#     off at the gates: the thieves rule's one squad (planner_threats).
# reachable_threats leaves both out, so no alarm, no gates and no squads of
# the defence for them; the bigger answers stay as they were.
GREAT_LIKE_KINDS = {"ForgottenBeast", "Titan", "Megabeast", "Demon", "SemiMegabeast", "NightCreature", "Undead"}


def wildlife_threat(t: dict, cfg: dict | None = None) -> bool:
    """(0.105.48, K1) Is this others_on_map.threats row wildlife (see above)?
    Rows from an older bridge (no `animal`) never are."""
    if not isinstance(t, dict) or t.get("animal") is not True:
        return False
    if t.get("invader") or t.get("great_danger") or t.get("fire_breather") or t.get("destroyer"):
        return False
    if set(_l(t.get("kinds"))) & GREAT_LIKE_KINDS:
        return False
    size = t.get("size")
    lim = (cfg or PLANNER_CONFIG).get("wildlife_alarm_size", 2000000)
    return isinstance(size, (int, float)) and not isinstance(size, bool) and 0 < size < lim


def wildlife_threats(s: dict, cfg: dict | None = None) -> list:
    """The others_on_map.threats rows that are wildlife."""
    return [t for t in _l(_d(s.get("others_on_map")).get("threats")) if wildlife_threat(t, cfg)]


# (0.105.51) A pack is no small wildlife. C (R3, winter 251): 9 giant dingoes
# (large predators, never agitated: no DF "danger", so not in the threats
# rows at all; only the hunt's targets and the field watch listed them) killed
# 10 of the 14 dwarves with no alarm, no gates and no shelter, one untrained
# soldier in the fort. The wild animals that can reach the dwarves (out of
# the caverns: the cavern alarm is its own) are read from all three lists and
# judged as a group: a danger to the whole fort (the alarm, and a sortie only
# when the free squads beat them) when `wild_pack_min` or more of
# `wild_pack_member_size` or more can reach the dwarves, one of them is inside
# the fort, two or more are more than the free squads beat at `fight_ratio`,
# or a lone one at grips with a dwarf (the field watch's `attacking`) is more
# than they beat (no squad: the civilians in). A lone wolf or falcon that
# attacks nobody stays the hunting squads' (no lockdown).
def _is_cavern(layer) -> bool:
    return str(layer or "").startswith("Cavern")


def _num_(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def wild_rows(s: dict, cfg: dict | None = None) -> list:
    """The wild animals that can reach the dwarves, out of the caverns, merged
    by id from the threats rows (wildlife_threat), the hunt's targets (why
    hostile_wild) and the field watch's wild rows (reach): threat-like rows
    ({id, name, size, flier, attacking, inside, distance_to_nearest_dwarf...})."""
    cfg = cfg or PLANNER_CONFIG
    rows: dict = {}
    order: list = []

    def add(r: dict) -> None:
        i = r.get("id")
        if not isinstance(i, int) or isinstance(i, bool):
            return
        if i not in rows:
            rows[i] = dict(r)
            order.append(i)
        else:
            for k, v in r.items():
                if rows[i].get(k) is None and v is not None:
                    rows[i][k] = v
            rows[i]["attacking"] = bool(rows[i].get("attacking") or r.get("attacking")) or None
            rows[i]["inside"] = bool(rows[i].get("inside") or r.get("inside")) or None
    ent = _d(s.get("entrances"))
    inside_ids = {x for x in _l(ent.get("intruders_inside")) if isinstance(x, int)}
    # the hunt's targets first (they carry the facts the matchup weighs)
    for t in _l(_d(s.get("hunt")).get("targets")):
        if not isinstance(t, dict) or t.get("why") != "hostile_wild" or t.get("can_reach_dwarves") is not True:
            continue
        if t.get("region") == "cavern" or _is_cavern(t.get("layer")):
            continue
        r = dict(t, animal=True, inside=(t.get("region") == "inside") or None)
        if not wildlife_threat(r, cfg):
            continue
        if r.get("distance_to_nearest_dwarf") is None and int(t.get("near_workers") or 0) > 0:
            r["distance_to_nearest_dwarf"] = 0     # by working dwarves (the hunt's count within its near)
        add(r)
    for t in _l(_d(s.get("others_on_map")).get("threats")):
        if (isinstance(t, dict) and wildlife_threat(t, cfg) and t.get("can_reach_dwarves") is True
                and not _is_cavern(t.get("layer"))):
            add(t)
    for w in _l(_d(s.get("field_watch")).get("wild")):
        if not isinstance(w, dict) or w.get("reach") is not True:
            continue
        r = {"id": w.get("id"), "name": w.get("name"), "animal": True, "size": w.get("size"),
             "flier": w.get("flier"), "fire_breather": w.get("fire_breather"), "invader": w.get("invader"),
             "great_danger": w.get("great"), "attacking": w.get("attacking"), "can_reach_dwarves": True,
             "layer": "upper_levels", "distance_to_nearest_dwarf": w.get("distance")}
        if wildlife_threat(r, cfg):
            add(r)
    out = []
    for i in order:
        r = rows[i]
        if i in inside_ids:
            r["inside"] = True
        out.append(r)
    return out


def _wild_free_squads(s: dict, cfg: dict, ids: set) -> list:
    """The squads free for the wild animals: able to fight, not on the
    player's orders, not out at something else."""
    out = []
    for q in _l(_d(s.get("military")).get("squads")):
        if not isinstance(q, dict) or not can_fight(q, cfg):
            continue
        if int(q.get("orders") or 0) > int(q.get("ai_orders") or 0):
            continue
        kill = {x for x in _l(q.get("kill_ids")) if isinstance(x, int)}
        if q.get("ai_orders") and kill and not kill & ids:
            continue
        out.append(q)
    return out


def wild_pack(s: dict, cfg: dict | None = None) -> dict:
    """{ids, rows, danger (why, "" if none), fight (the free squads beat
    them at planner_matchup.fight_bar: about even odds), ratio}: the wild animals that can reach the
    dwarves judged as a group (see above). `ids` are all of them when they
    are a danger, else []."""
    cfg = cfg or PLANNER_CONFIG
    out = {"ids": [], "rows": [], "danger": "", "fight": False, "ratio": 0.0}
    try:
        rows = wild_rows(s, cfg)
    except Exception:   # noqa: BLE001  a malformed section: no pack (as before)
        return out
    big = [r for r in rows if _num_(r.get("size")) and r["size"] >= cfg.get("wild_pack_member_size", 10000)]
    out["rows"] = big
    if not big:
        return out
    from planner_matchup import judge, fight_bar
    squads = _wild_free_squads(s, cfg, {r["id"] for r in big})
    ratio = judge(big, squads)["ratio"] if squads else 0.0
    bar = fight_bar(big, cfg)["bar"]          # (0.105.54) about even odds (the player: "fight back")
    win = ratio >= bar
    out["ratio"], out["fight"] = round(ratio, 2), win
    name = str(big[0].get("name") or "a wild animal")
    inside = [r for r in big if r.get("inside")]
    hit = [r for r in big if r.get("attacking")]
    if inside:
        why = f"{inside[0].get('name') or 'a wild animal'} inside the fort"
    elif len(big) >= int(cfg.get("wild_pack_min", 3)):
        why = f"a pack of {len(big)} wild animals ({name}...) can reach the dwarves"
    elif len(big) >= 2 and not win:
        why = f"{len(big)} wild animals ({name}...) stronger than the free squads"
    elif hit and not win:
        why = f"{hit[0].get('name') or 'a wild animal'} attacking a dwarf and no squad that beats it"
    else:
        return out
    out["danger"] = why + (f" (the free squads beat them: {ratio:.1f}x)" if win else
                           f" (the free squads {ratio:.1f}x, {bar:g}x needed: no sortie, "
                           "the civilians in)")
    out["ids"] = [r["id"] for r in big]
    return out


def thief_ids(s: dict) -> set:
    """The ids of the thieves and snatchers the threats section lists.
    (0.105.51) And the others_on_map threat rows the bridge marks `thief`:
    the threats section is in the full report only, the pulse between
    carries others_on_map alone. E (15 Nov) saw three artifact seekers
    spotted on a pulse cycle: not in the day-old thieves list, each got the
    alarm, the gates and the defence's squad (a mechanic killed, a tavern
    fight)."""
    th = _d(_d(s.get("threats")).get("thieves"))
    out = {x.get("id") for x in _l(th.get("list")) if isinstance(x, dict) and x.get("id") is not None}
    out |= {t.get("id") for t in _l(_d(s.get("others_on_map")).get("threats"))
            if isinstance(t, dict) and t.get("thief") and t.get("id") is not None}
    return out


CROWD_LOCATIONS = ("INN_TAVERN", "TEMPLE", "LIBRARY", "GUILDHALL")


def thief_rows(s: dict, threats: dict | None = None) -> list:
    """(0.105.51) The thieves and snatchers: the threats section's rows
    (the full report), with the others_on_map threat rows the bridge marks
    `thief` merged in (the pulse: fresher reach, place and crowd). A thief
    only in others_on_map is inside when the gate scan says so or it can
    reach the dwarves."""
    th = _d(_d(threats if threats is not None else s.get("threats")).get("thieves"))   # `threats`: the section
    by = {}
    for x in _l(th.get("list")):
        if isinstance(x, dict) and x.get("id") is not None:
            by[x["id"]] = dict(x)
    inside = {x for x in _l(_d(s.get("entrances")).get("intruders_inside")) if isinstance(x, int)}
    for t in _l(_d(s.get("others_on_map")).get("threats")):
        if not isinstance(t, dict) or not t.get("thief") or t.get("id") is None:
            continue
        r = by.get(t["id"])
        if r is None:
            r = by[t["id"]] = {"id": t["id"], "name": t.get("name"), "kind": t.get("thief"),
                               "invader": t.get("invader"), "inside": t["id"] in inside or None}
        for k in ("can_reach_dwarves", "pos", "crowd", "location"):
            if k in t:
                r[k] = t[k]
    return list(by.values())


def crowded_thief(row: dict, cfg: dict | None = None) -> bool:
    """(0.105.51) Is this thief among a crowd: `thief_crowd_min` (3) or more
    people (no animals, no dangers) within a few tiles (the bridge's
    `crowd`), or any in a tavern, temple, library or guildhall with them?
    E (15 Nov): a thief come as a guest was attacked in the tavern three
    times; each fight drew in the bards, dancers and poets (~26 visitors).
    A row without `crowd` (an older bridge) never is."""
    if not isinstance(row, dict):
        return False
    n = row.get("crowd")
    if not isinstance(n, (int, float)) or isinstance(n, bool):
        return False
    least = (cfg or PLANNER_CONFIG).get("thief_crowd_min", 3)
    return n >= least or (row.get("location") in CROWD_LOCATIONS and n >= 1)


def snatcher_ids(s: dict) -> list:
    """(0.105.48, K16) The snatchers among the threats section's thieves that
    are inside the fort or can reach the dwarves. A snatcher takes children:
    it is out of reachable_threats like a lone thief (no gates, no sortie of
    the defence; the thieves rule's one squad), but it keeps the alarm up
    (the civilians in: planner_alarm.snatch_alarm)."""
    th = _d(_d(s.get("threats")).get("thieves"))
    return [x["id"] for x in _l(th.get("list")) if isinstance(x, dict) and x.get("id") is not None
            and x.get("kind") == "snatcher" and (x.get("inside") or x.get("can_reach_dwarves") is True)]


def _lone_thieves(s: dict, cfg: dict, ids: list, rows: dict) -> bool:
    """Are these ids (all that can reach) only a few ordinary thieves, with
    nothing else held off at the gates?"""
    thieves = thief_ids(s)
    if not ids or not thieves or len(ids) > cfg.get("lone_intruder_max", 2):
        return False
    for i in ids:
        t = rows.get(i)
        if (i not in thieves or not isinstance(t, dict) or t.get("great_danger") or t.get("flier")
                or t.get("destroyer") or t.get("fire_breather")):
            return False
    # (0.105.51) held off at the gates means a siege outside: an invader or a
    # great danger. E (15 Nov): a night creature come as a poet, walking the
    # upper levels with its reach unknown that cycle, kept a lone thief off
    # the triage (the alarm, the gates, the defence's squad)
    return not any(t.get("id") not in ids and not wildlife_threat(t, cfg)
                   and (t.get("invader") or t.get("great_danger")) for t in held_off_threats(s))


def reachable_threats(s: dict, traits: dict, cfg: dict) -> list:
    """Ids of threats that can reach the dwarves (plus, at Caution +50 and up
    (0.105.47; +100 before), nearby ones whose reach is unknown). Threats counted but not listed get stand-in ids.
    (0.105.48, K1) Wildlife and a lone thief are left out (the triage above)."""
    o = s["others_on_map"]
    threats = o.get("threats") or []
    listed = [t.get("id") for t in threats if t.get("can_reach_dwarves") is True]
    unlisted = max(0, (o.get("threats_that_can_reach_dwarves") or 0) - len(listed))
    # (0.105.51) a pack (wild_pack) is no small wildlife: in, with the ones
    # only the hunt and the field watch list (DF calls no large predator a danger)
    pack = wild_pack(s, cfg)["ids"]
    wild = {t.get("id") for t in threats if wildlife_threat(t, cfg)} - set(pack)
    threats = [t for t in threats if t.get("id") not in wild]
    ids = [i for i in listed if i not in wild]
    # (0.104.139) a flier in the air (its reach unknown) near the dwarves can
    # reach them whatever DF's walk groups say; and a building destroyer near
    # them isn't held by a shut door, when it is an invader or on the surface
    # (never a cavern beast that can't get up: review)
    ids += [t.get("id") for t in threats
            if t.get("can_reach_dwarves") is not True and t.get("id") not in ids
            and ((t.get("flier") and t.get("can_reach_dwarves") is None)
                 or (t.get("destroyer") and (t.get("invader") or t.get("layer") == "upper_levels")))
            and isinstance(t.get("distance_to_nearest_dwarf"), (int, float))
            and t["distance_to_nearest_dwarf"] <= cfg["near_threat_tiles"]]
    # (0.104.140) an invader by the trade depot while merchants are in: the
    # caravan has no walls (the squads go out to it)
    if int(o.get("merchants") or 0) > 0:
        ids += [t.get("id") for t in threats if t.get("id") not in ids and t.get("invader")
                and t.get("can_reach_dwarves") is not False                       # (review) not behind a wall
                and isinstance(t.get("depot_distance"), (int, float)) and t["depot_distance"] <= cfg["depot_guard_tiles"]]
    # (0.105.47) from Caution `cautious_alert_caution` (was +100 only), fewer levels lower down (alarm_caution)
    from alarm_caution import cautious_levels
    levels = cautious_levels(traits, cfg)
    if levels is not None:
        for t in threats:
            lv = t.get("levels_from_nearest_dwarf")
            if (t.get("can_reach_dwarves") is None and lv is not None and lv <= levels
                    and t.get("id") not in ids):
                ids.append(t.get("id"))
    if not unlisted and not pack and _lone_thieves(s, cfg, ids, {t.get("id"): t for t in threats}):
        return []
    ids += [i for i in pack if i not in ids]
    ids += [f"unlisted{i}" for i in range(unlisted)]
    return ids


def great_present(s: dict) -> bool:
    """(0.104.100) A great danger (titan, forgotten beast, megabeast) that can
    reach the dwarves or walks the surface: cavern ones out of reach don't count
    (they never leave, and would keep the fort shut for good)."""
    o = _d(s.get("others_on_map"))
    return any(isinstance(t, dict) and t.get("great_danger")
               and (t.get("can_reach_dwarves") is True or t.get("layer") == "upper_levels")
               for t in _l(o.get("threats")))


def all_clear(s: dict, memory, cfg: dict) -> tuple[bool, str]:
    """(0.104.100) May the AI lower its alert and open its gates? Quiet for
    `alert_quiet_cycles` cycles, `alert_quiet_days` game days since a threat could
    reach the dwarves, and `alert_quiet_days_great` since a great danger was about.
    (ok, why not) - the why for the log while it holds."""
    if memory.quiet_cycles < cfg["alert_quiet_cycles"]:
        return False, f"quiet for {memory.quiet_cycles} cycle(s)"
    now = abs_tick(s)
    if not isinstance(now, int):
        return True, ""
    gdays = (now - (memory.last_great_tick or 0)) // TICKS_PER_DAY
    if memory.last_great_tick and gdays < cfg["alert_quiet_days_great"]:
        return False, f"a great danger was about {gdays} day(s) ago"
    days = (now - (memory.last_threat_tick or 0)) // TICKS_PER_DAY
    if memory.last_threat_tick and days < cfg["alert_quiet_days"]:
        # (0.105.2) a sealed fort costs more than the wait saves: B (2 Nov)
        # ran at 1-3 FPS behind its shut hatch, 6 citizens and 51 visitors
        # outside re-routing to a way in that wasn't there; unlocking it set
        # the game racing again. With the game slow and nothing hostile left
        # on the map, the quiet days are skipped.
        if s.get("fps_low") and not held_off_threats(s):
            return True, ""
        return False, f"the last threat was {days} day(s) ago"
    return True, ""


def held_off_threats(s: dict) -> list:
    """(0.100.1) Threats on the map that can't walk in right now (a raised
    bridge, a shut door) but are still there: invaders anywhere, and dangers
    up on the surface. Cavern creatures that can't reach aren't counted (they
    never leave, and would keep the fort shut for good)."""
    o = _d(s.get("others_on_map"))
    # (0.104.139) nor the undead an evil land raises on the surface (not
    # invaders, never leaving): they kept the gates shut for good
    # (0.105.48, K1) nor wildlife (a falcon on the surface kept the fort shut)
    return [t for t in _l(o.get("threats")) if isinstance(t, dict) and t.get("can_reach_dwarves") is not True
            and not wildlife_threat(t)
            and (t.get("invader") or (t.get("layer") == "upper_levels"
                                      and not ("Undead" in _l(t.get("kinds")) and not t.get("great_danger"))))]


def _holding_off(s: dict, memory) -> bool:
    """The AI has the alarm up or is keeping watch over the gates."""
    return bool(memory.ai_alert_raised or _d(s.get("entrances")).get("armed"))


def can_fight(q: dict, cfg: dict) -> bool:
    """(0.105.2) A squad worth sending at a threat: `min_squad_to_fight`
    members, and that many of them armed (the bridge's `power.armed`: a
    weapon in hand or one given on a weapon entry). B (2 Nov): all four
    squads went at one thief in turn with no weapon among them, and he
    lived. A bridge without the count: members alone, as before."""
    need = cfg.get("min_squad_to_fight", 3)
    members = q.get("members") or 0
    if members < need:
        return False
    armed = _d(q.get("power")).get("armed")
    if not isinstance(armed, int) or isinstance(armed, bool):
        return True
    return armed >= min(need, members)


def is_ranged(q: dict) -> bool:
    """A squad in a crossbow uniform the AI gave it."""
    return "crossbow" in str(q.get("ai_uniform") or "").lower()

"""(0.105.39, phase 13b offence) Missions on the world map: a rescue, an
artifact recovered, a ruin explored and, only behind the Rules switch at
'all', a raid, pillage, tribute demand or conquest.

The `missions` report (lua/ai-missions.lua) lists the fort's controllers
(its missions out), its squads (members, away, controller), the reports and
spoils that came back, and `targets`: what a mission could go for, best
first (goal, site, distance, the civ, why, a kidnapped citizen or a stolen
artifact, hostile / at war, and `ready`: what DF's open World screen said).
`send` (lua/ai-mission-send.lua) is the World-screen sender: a run under
way, the last run and where it stopped, and per goal whether its buttons
were shown to the AI (`goals`).

  * mission_reserve(): how many soldiers stay home, from the Militarism
    slider (-100: three quarters, 0: half, +100: a quarter), never fewer than
    the guard (3);
  * _mission_rule(): one mission at a time, never while a threat can reach
    the dwarves or a siege is on, the best target the `missions` switch
    allows (raids and the like only against a civilisation at war or
    hostile, and only at 'all'), whole squads beyond the reserve that are
    home, armed, without orders and not hiding; proposed as send_mission
    when `send_missions` is on and the goal's buttons were shown, else named
    in a note (and one Needs you for recording the World screen's last steps);
  * note_missions(): each mission followed to its return; the report and
    spoils (game text, quoted and cut short) in the journal and the
    chronicle, the outcomes counted in memory.missions_seen.

Without `missions.targets` in the report (an older bridge) nothing here
proposes or says anything.
"""

from __future__ import annotations

import math

from digest import _d, _l, game_text
from planner_core import (PLANNER_CONFIG, Proposal, TICKS_PER_DAY, abs_tick, ask_player, player_rules,
                          reachable_threats, _traits)
from planner_threats import alarm_held

__all__ = ["MISSION_GOALS", "OFFENSIVE_GOALS", "MISSION_LEVELS", "allowed_goals", "mission_reserve",
           "sendable_squads", "mission_target", "_mission_rule", "note_missions", "mission_journal",
           "mission_line", "MISSION_WORDS", "last_of_goal", "MISSIONS_SWITCH", "SEND_SWITCH"]

# the goals in the order the AI prefers them (the contract's order)
MISSION_GOALS = ("rescue", "recover_artifact", "explore", "tribute", "raid", "pillage", "conquer")
OFFENSIVE_GOALS = ("tribute", "raid", "pillage", "conquer")    # can start a war: only at 'all', only vs the hostile
# the Rules switch `missions` -> the goals it allows
MISSION_LEVELS = {"off": (), "rescue": ("rescue", "recover_artifact"),
                  "explore": ("rescue", "recover_artifact", "explore"), "all": MISSION_GOALS}
MISSION_WORDS = {"rescue": "rescue", "recover_artifact": "recover an artifact", "explore": "explore",
                 "tribute": "demand tribute", "raid": "raid", "pillage": "pillage", "conquer": "conquer",
                 "make_contact": "make contact"}
# (0.105.39 review) the switches as the Army tab names them (lua/gui/ai-overseer.lua)
MISSIONS_SWITCH = 'the Army tab\'s "Missions to send out"'
SEND_SWITCH = 'the Army tab\'s "Send missions by the World screen"'
JOURNAL_MAX = 12          # mission journal entries waiting for the overseer at most
TRACK_MAX = 10            # missions followed at most (the report's controllers cap)


def _m(s: dict) -> dict:
    return _d(s.get("missions"))


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def allowed_goals(s: dict) -> tuple:
    """The goals the Rules switch `missions` allows."""
    return MISSION_LEVELS.get(player_rules(s)["missions"], ())


# --- the reserve and the squads -----------------------------------------------------

def _home_share(s: dict, cfg: dict) -> float:
    """The share of soldiers that stays home, from the Militarism slider
    (-100 .. 0 .. +100 -> mission_home_share_low .. _mid .. _high, linear;
    an Extreme slider past 100 counts as 100)."""
    m = _traits(s).get("militarism", 0)
    m = m if isinstance(m, (int, float)) and not isinstance(m, bool) else 0
    m = max(-100.0, min(100.0, float(m)))
    lo, mid, hi = cfg["mission_home_share_low"], cfg["mission_home_share_mid"], cfg["mission_home_share_high"]
    return mid + (lo - mid) * (-m / 100) if m < 0 else mid + (hi - mid) * (m / 100)


def _soldiers(s: dict) -> int:
    mil = _d(s.get("military"))
    n = _int(mil.get("soldiers"))
    if n is None:
        n = sum(_int(q.get("members")) or 0 for q in _l(mil.get("squads")) if isinstance(q, dict))
    return max(0, n)


def mission_reserve(s: dict, cfg: dict = PLANNER_CONFIG) -> int:
    """Soldiers that must stay home: max(the guard, ceil(soldiers x share)),
    the share from Militarism."""
    return max(int(cfg.get("guard_min_soldiers", 3)), math.ceil(_soldiers(s) * _home_share(s, cfg) - 1e-9))


def _away_squads(s: dict) -> dict:
    """The `missions` report's squads: id -> row."""
    return {q.get("id"): q for q in _l(_m(s).get("squads")) if isinstance(q, dict) and q.get("id") is not None}


def _squad_free(q: dict, away: dict) -> str | None:
    """None when a squad may go, else why not (words)."""
    members = _int(q.get("members")) or 0
    if members <= 0:
        return "no members"
    if q.get("id") not in away:
        return "not in the missions report"      # (0.105.39 review) where it is isn't known: not free
    a = _d(away.get(q.get("id")))
    if (_int(a.get("away")) or 0) > 0 or _int(a.get("controller")) is not None:
        return "away"
    if q.get("sheltering"):
        return "hiding"
    if q.get("kill_ids") or q.get("guarding"):
        return "in a fight or on guard"
    if (_int(q.get("orders")) or 0) > 0 or (_int(q.get("ai_orders")) or 0) > 0:
        return "on duty"
    if q.get("parched"):
        return "thirsty"
    armed = _d(q.get("power")).get("armed")
    if _int(armed) is None or armed < members:
        return "not all armed"
    return None


def sendable_squads(s: dict, cfg: dict = PLANNER_CONFIG) -> tuple[list, int, int]:
    """(squads, soldiers sent, reserve): whole squads that may go, the
    strongest first, while the soldiers left home stay at the reserve or
    more. Empty when fewer than `mission_min_soldiers` would go."""
    mil = _d(s.get("military"))
    squads = [q for q in _l(mil.get("squads")) if isinstance(q, dict) and q.get("id") is not None]
    away = _away_squads(s)
    reserve = mission_reserve(s, cfg)
    home = _soldiers(s) - sum(_int(_d(a).get("away")) or 0 for a in away.values())
    free = [q for q in squads if _squad_free(q, away) is None]
    free.sort(key=lambda q: (-float(_d(q.get("power")).get("power") or 0), -(_int(q.get("members")) or 0),
                             q.get("id")))
    out, sent = [], 0
    for q in free:
        n = _int(q.get("members")) or 0
        if home - sent - n >= reserve:
            out.append(q)
            sent += n
    if sent < cfg["mission_min_soldiers"]:
        return [], 0, reserve
    return out, sent, reserve


# --- the target ---------------------------------------------------------------------

def last_of_goal(send: dict, goal: str) -> dict:
    """(0.105.39 review) The sender's last run of this goal: `last_by_goal`
    (one outcome per goal, so a Make contact run never hides a stopped
    rescue); an older bridge's single `last` only when it is this goal's
    (no goal: make_contact). {} when there is none."""
    send = _d(send)
    by = send.get("last_by_goal")
    if isinstance(by, dict):
        return _d(by.get(goal))
    last = _d(send.get("last"))
    if (last.get("goal") or "make_contact") == goal:
        return last
    return {}


def _stopped(s: dict, goal: str, cfg: dict) -> dict | None:
    """The sender's last run for this goal when it stopped (or failed) within
    `mission_retry_ticks`: not tried again until then."""
    last = last_of_goal(_d(_m(s).get("send")), goal)
    if last.get("result") not in ("stopped", "error"):
        return None
    t = _int(last.get("tick"))
    if t is None or not 0 <= abs_tick(s) - t < cfg["mission_retry_ticks"]:
        return None
    return last


def mission_target(s: dict, cfg: dict = PLANNER_CONFIG) -> tuple[dict | None, list]:
    """(the best target the switch allows, the goals skipped for a stopped
    run). Goal order first (offensive goals only against a hostile or at-war
    civ), then the nearest; a target DF's screen said no to is passed over."""
    allowed = allowed_goals(s)
    order = {g: i for i, g in enumerate(MISSION_GOALS)}
    stopped, cands = [], []
    for t in _l(_m(s).get("targets")):
        if not isinstance(t, dict) or t.get("goal") not in allowed or _int(t.get("site_id")) is None:
            continue
        if t["goal"] in OFFENSIVE_GOALS and not (t.get("hostile") is True or t.get("at_war") is True):
            continue
        if t.get("ready") not in (None, "OKAY"):
            continue
        if _stopped(s, t["goal"], cfg):
            if t["goal"] not in stopped:
                stopped.append(t["goal"])
            continue
        cands.append(t)
    if not cands:
        return None, stopped
    best = min(cands, key=lambda t: (order[t["goal"]], _int(t.get("dist")) if _int(t.get("dist")) is not None
                                     else 10 ** 6, t["site_id"]))
    return best, stopped


def _target_words(t: dict) -> str:
    goal = t.get("goal")
    site = game_text(t.get("site") or f"site {t.get('site_id')}", 40)
    if goal == "rescue":
        what = f"rescue {game_text(t.get('hf'), 40)} from {site}" if t.get("hf") else f"rescue a citizen from {site}"
    elif goal == "recover_artifact":
        what = (f"recover {game_text(t.get('artifact'), 40)} from {site}" if t.get("artifact")
                else f"recover a stolen artifact from {site}")
    else:
        what = f"{MISSION_WORDS.get(goal, goal)} {site}"
    if t.get("civ"):
        what += f" ({game_text(t.get('civ'), 40)})"
    if _int(t.get("dist")) is not None:
        what += f", {t['dist']} away"
    return what


# the goal buttons on DF's New mission panel (lua/ai-mission-send.lua GOALS)
_GOAL_BUTTON = {"rescue": "Rescue", "recover_artifact": "Recover", "explore": "Explore", "raid": "Raid",
                "pillage": "Pillage", "tribute": "Tribute", "conquer": "Conquer", "make_contact": "Diplomacy"}
_DANGER_SECTIONS = ("others_on_map", "world", "civ_alert")


def _unread_danger(s: dict) -> str:
    """(0.105.39 review) The sections a threat is read from that failed
    (in _errors, or still {"error": ...}): "" when all were read. A failed
    read is never taken for "no threat"."""
    errs = _d(s.get("_errors"))
    bad = [k for k in _DANGER_SECTIONS if k in errs or (isinstance(s.get(k), dict) and "error" in s[k])]
    return " and ".join(f"the {k.replace('_', ' ')} section" for k in bad)


def _stopped_needs_you(s: dict, goal: str, cfg: dict, notes: list) -> None:
    """(0.105.39 review) After a run of this goal stopped: one Needs you
    (the same words each cycle, so listed once) saying where it stopped and
    what the AI does meanwhile, a controller left behind included."""
    last = _stopped(s, goal, cfg)
    if not last:
        return
    site = game_text(last.get("site") or f"site {last.get('site_id')}", 40)
    ask_player(notes, f"missions (13b): the AI's try to {MISSION_WORDS.get(goal, goal)} at \"{site}\" stopped at the "
                      f"World screen's \"{game_text(last.get('step'), 20)}\" step: "
                      f"{game_text(last.get('why') or last.get('reason'), 120)}. "
                      + ("A new army controller was left behind on the World screen's missions. "
                         if last.get("controller_left") else "")
                      + "The AI can't press a step nobody has recorded (DFHack can't make the mission itself): "
                      "the soldiers stay home and the AI tries again in a year; a mission sent by hand while "
                      "python brain\\probe_missions.py --watch runs records the steps for it")


def _fort_missions_out(s: dict) -> list:
    """The fort's missions out but the messenger's (DIPLOMACY): a controller
    with the fort's squads, or a squad away or under a controller."""
    ms = _m(s)
    away = _away_squads(s)
    out = [c for c in _l(ms.get("controllers")) if isinstance(c, dict) and c.get("goal") != "DIPLOMACY"
           and (any(x in away for x in _l(c.get("squads"))) or (_int(c.get("away")) or 0) > 0)]
    if not out:
        out = [q for q in away.values() if (_int(q.get("away")) or 0) > 0 or _int(q.get("controller")) is not None]
    return out


def _mission_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """(0.105.39) The best mission the Rules allow, once nothing else is out,
    no threat or siege is near and enough soldiers beyond the reserve are
    free. Sent by the World screen when `send_missions` is on and the goal's
    buttons were shown, else named for the player."""
    ms = _m(s)
    if not isinstance(ms.get("targets"), list) or not ms["targets"]:
        return                       # nothing to go for (or an older bridge): silent
    rules = player_rules(s)
    if not allowed_goals(s):
        return                       # the switch is off
    out = _fort_missions_out(s)
    if out:
        c = out[0]
        notes.append(f"a mission is out ({game_text(c.get('goal') or 'a squad', 20).lower()}"
                     + (f" to {game_text(c.get('site'), 40)}" if c.get("site") else "")
                     + (", on the way home" if c.get("returning") else "") + "): one mission at a time")
        return
    send = _d(ms.get("send"))
    if _d(send.get("running")):
        notes.append(f"the World screen is being driven (step {game_text(_d(send['running']).get('step'), 20)}): "
                     "a mission waits, one at a time")
        return
    if any(p.action.get("type") == "send_mission" for p in proposals):
        return                       # the messenger goes first this cycle
    target, stopped = mission_target(s, cfg)
    if stopped:
        _stopped_needs_you(s, stopped[0], cfg, notes)
    if target is None:
        if stopped:
            notes.append(f"a mission to {MISSION_WORDS.get(stopped[0], stopped[0])} waits: the last try stopped at a "
                         "World-screen step nobody has recorded; tried again in a year")
        return
    what = _target_words(target)
    unread = _unread_danger(s)
    if unread:
        notes.append(f"a mission could {what}, but {unread} couldn't be read, so whether a threat is near isn't "
                     "known (the soldiers stay home)")
        return
    held = alarm_held(s, memory, cfg)
    if (reachable_threats(s, _traits(s), cfg) or any(_d(e).get("active") for e in _l(_d(s.get("world")).get("sieges")))
            or s.get("civ_alert") is True or held):
        notes.append(f"a mission could {what}, but not while a threat is near (the soldiers stay home)"
                     + (f": {held}" if held else ""))
        return
    squads, sent, reserve = sendable_squads(s, cfg)
    if not squads:
        notes.append(f"a mission could {what}, but too few soldiers are free beyond the {reserve} who stay home "
                     f"(at least {cfg['mission_min_soldiers']} in whole squads, home, armed, without orders)")
        return
    names = ", ".join(game_text(q.get("name") or f"squad {q.get('id')}", 30) for q in squads[:4]) \
        + (f" and {len(squads) - 4} more" if len(squads) > 4 else "")
    goal = target["goal"]
    g = _d(_d(send.get("goals")).get(goal))
    if rules["send_missions"] and g.get("button") is True:
        last = last_of_goal(send, goal)
        lt = _int(last.get("tick"))
        if (last.get("result") == "sent" and lt is not None
                and 0 <= abs_tick(s) - lt < cfg["mission_sent_wait_ticks"]):
            return                   # sent lately: its controller shows in `missions` soon
        action = {"type": "send_mission", "goal": goal, "site_id": target["site_id"],
                  "squad_ids": [q["id"] for q in squads]}
        for k in ("hf_id", "artifact_id"):
            if _int(target.get(k)) is not None:
                action[k] = target[k]
        proposals.append(Proposal("mission", action,
                                  f"send {names} ({sent} soldiers; {reserve} stay home) to {what}, by the World "
                                  "screen", 7))
        return
    button = _GOAL_BUTTON.get(goal, goal.title())
    notes.append(f"a mission could {what}: {names} ({sent} soldiers, {reserve} stay home) are free to go; "
                 + (f"the AI doesn't send it ({SEND_SWITCH} is off)" if not rules["send_missions"]
                    else f"the AI hasn't been shown this mission's World-screen button ({button}) yet"))
    if rules["send_missions"]:
        # (0.105.39 review) the button not shown: the probe command for it, the target and the squads
        ask_player(notes, f"missions (13b): to {what}, the AI needs DF's {button} button shown once: with a site's "
                          f"New mission showing, the mouse on {button} and python brain\\probe_missions.py --here "
                          f"{button}; meanwhile {names} stay home and the AI names the target in its notes")
    else:
        ask_player(notes, f"missions (13b): to {what}, send {names} by hand (or turn on {SEND_SWITCH}) while "
                          "python brain\\probe_missions.py --watch runs, so the AI can learn the last steps; "
                          "meanwhile the AI names the target and the squads free to go in its notes, and keeps the "
                          "soldiers home")


# --- following a mission to its return -----------------------------------------------

GOAL_FROM_DF = (("RESCUE", "rescue"), ("ARTIFACT", "recover_artifact"), ("EXPLORE", "explore"),
                ("TRIBUTE", "tribute"), ("RAID", "raid"), ("PILLAGE", "pillage"), ("CONQUER", "conquer"))
# (0.105.39 review) a SITE_INVASION's intent (invasion_intent_type, the
# report's controllers[].intent) -> our goal
INTENT_GOAL = {"EXPLORE": "explore", "RAID": "raid", "PILLAGE": "pillage", "DEMAND_TRIBUTE": "tribute",
               "TRIBUTE": "tribute", "TAKE_OVER_SITE": "conquer", "CONQUER": "conquer"}


def _goal_of(c: dict, send: dict) -> str:
    """Our goal name for a controller: the sender's last run of a goal that
    went to the same site, else from DF's goal name (a SITE_INVASION by its
    intent when the report gives it, else 'invasion'), else DF's name in
    lower case."""
    by = _d(send.get("last_by_goal")) or {"_": _d(send.get("last"))}
    for o in by.values():
        o = _d(o)
        if o.get("result") == "sent" and o.get("goal") and o.get("site_id") == c.get("site_id"):
            return str(o["goal"])
    df = str(c.get("goal") or "")
    if "INVASION" in df.upper():
        return INTENT_GOAL.get(str(c.get("intent") or "").upper(), "invasion")
    for k, g in GOAL_FROM_DF:
        if k in df.upper():
            return g
    return game_text(df.lower() or "unknown", 24)


def _q(v, n: int = 40) -> str:
    """Game text quoted as data: one line, cut short, in double quotes."""
    return '"' + game_text(v, n).replace('"', "'") + '"'


def _seen(memory) -> dict:
    ms = getattr(memory, "missions_seen", None)
    if not isinstance(ms, dict):
        ms = {}
        memory.missions_seen = ms
    return ms


def note_missions(s: dict, memory) -> list[str]:
    """(0.105.39; planner.note_cycle, before planning) Each of the fort's
    missions followed out and back: counted when first seen, and when its
    controller is gone or its squads are home again, a journal entry and a
    chronicle line from the reports and spoils that came back (game text,
    quoted, cut short); rescues and recoveries counted when the citizen or
    artifact it went for is no longer a target. Returns notes."""
    if memory is None:
        return []
    import chronicle
    ms = _m(s)
    seen = _seen(memory)
    track = seen.setdefault("out", {})
    for k in ("missions_sent", "missions_back", "rescued", "artifacts_recovered"):
        if not isinstance(seen.get(k), int):
            seen[k] = 0
    send = _d(ms.get("send"))
    reports, spoils = _d(ms.get("reports")), _d(ms.get("spoils"))
    targets = [t for t in _l(ms.get("targets")) if isinstance(t, dict)]
    away = _away_squads(s)
    notes: list[str] = []
    pending = seen.setdefault("journal", [])
    done = seen.setdefault("done", [])      # controllers already followed home (DF may keep them listed a while)
    now = abs_tick(s)
    current = {}
    for c in _l(ms.get("controllers")):
        if not isinstance(c, dict) or _int(c.get("id")) is None or c.get("goal") == "DIPLOMACY" \
                or str(c["id"]) in done:
            continue
        sq = [x for x in _l(c.get("squads")) if x in away]
        if not sq and not (_int(c.get("away")) or 0):
            continue                 # not the fort's own squads: someone else's army
        current[str(c["id"])] = (c, sq)
    for cid, (c, sq) in current.items():
        t = track.get(cid)
        n_away = sum(_int(_d(away.get(x)).get("away")) or 0 for x in sq) or (_int(c.get("away")) or 0)
        if t is None:
            if len(track) >= TRACK_MAX:
                continue
            goal = _goal_of(c, send)
            t = {"goal": goal, "site_id": c.get("site_id"), "site": _q(c.get("site"), 40) if c.get("site") else None,
                 "squads": sq, "since": now, "reports": _int(reports.get("n")) or 0,
                 "spoils": _int(spoils.get("n")) or 0, "seen_away": n_away > 0}
            for x in targets:
                if x.get("site_id") == c.get("site_id") and x.get("goal") == goal:
                    for k in ("hf_id", "artifact_id"):
                        if _int(x.get(k)) is not None:
                            t[k] = x[k]
                    break
            track[cid] = t
            seen["missions_sent"] += 1
            pending.append({"event": "out", "goal": goal, "site": t["site"], "site_id": t["site_id"], "squads": sq})
            notes.append(f"a mission went out: {MISSION_WORDS.get(goal, goal)}"
                         + (f" {t['site']}" if t["site"] else ""))
            continue
        if n_away > 0:
            t["seen_away"] = True
        elif t.get("seen_away"):
            current[cid] = None      # its squads are home again: back
    for cid in list(track):
        if current.get(cid) is not None:
            continue
        t = track.pop(cid)
        seen["missions_back"] += 1
        done.append(cid)
        goal = t.get("goal")
        e = {"event": "back", "goal": goal, "site": t.get("site"), "site_id": t.get("site_id"),
             "days": max(0, (now - int(t.get("since") or now)) // TICKS_PER_DAY)}
        words = [f"the mission to {MISSION_WORDS.get(goal, goal)}" + (f" {t['site']}" if t.get("site") else "")
                 + " came back"]
        if (_int(reports.get("n")) or 0) > int(t.get("reports") or 0):
            title = _d(reports.get("last")).get("title")
            if title:
                e["report"] = game_text(title, 60)
                words.append(f'its report: "{e["report"]}"')
        if (_int(spoils.get("n")) or 0) > int(t.get("spoils") or 0):
            last = _d(spoils.get("last"))
            e["spoils"] = {"kind": game_text(last.get("kind") or "spoils", 12), "items": _int(last.get("items"))}
            words.append(f"{e['spoils']['kind']}: {e['spoils']['items'] if e['spoils']['items'] is not None else 'some'} "
                         "item(s)")
        # (0.105.39 review) a rescue or recovery counted only when the report
        # says so: the citizen home, the artifact at the fort (missions.status_of);
        # never from a target merely gone from a partial or failed list
        so = _d(ms.get("status_of"))
        trusted = not ms.get("targets_partial") and "missions" not in _d(s.get("_errors"))
        if goal == "rescue" and _int(t.get("hf_id")) is not None:
            st = _d(so.get("hf")).get(str(t["hf_id"])) if trusted else None
            if st == "home":
                seen["rescued"] += 1
                e["outcome"] = "rescued"
                words.append("the citizen is home again")
            else:
                e["outcome"] = "unknown" if st in (None, "unknown") else st
                words.append("whether the citizen came home isn't known" if st in (None, "unknown")
                             else f"the citizen is {'still held' if st == 'held' else st}")
        if goal == "recover_artifact" and _int(t.get("artifact_id")) is not None:
            st = _d(so.get("artifact")).get(str(t["artifact_id"])) if trusted else None
            if st == "fort":
                seen["artifacts_recovered"] += 1
                e["outcome"] = "recovered"
                words.append("the artifact is back in the fort")
            else:
                e["outcome"] = "unknown" if st in (None, "unknown") else "not recovered"
                words.append("whether the artifact came back isn't known" if st in (None, "unknown")
                             else "the artifact is still away")
        pending.append(e)
        line = "; ".join(words)
        chronicle.add(memory, s, "mission", line)
        notes.append(line)
    del pending[:-JOURNAL_MAX]
    del done[:-2 * TRACK_MAX]
    return notes


def mission_journal(memory) -> list[dict]:
    """The mission entries note_missions kept for the journal, taken (the
    overseer writes them with the fort and the date)."""
    seen = getattr(memory, "missions_seen", None) if memory is not None else None
    if not isinstance(seen, dict) or not seen.get("journal"):
        return []
    out = [x for x in seen["journal"] if isinstance(x, dict)]
    seen["journal"] = []
    return out


def mission_line(s: dict) -> str:
    """(the digest) MISSIONS: targets and missions out, no coordinates; ""
    with no targets and nothing out."""
    ms = _m(s)
    targets = [t for t in _l(ms.get("targets")) if isinstance(t, dict)]
    out = _fort_missions_out(s) if ms else []
    if not targets and not out:
        return ""
    parts = []
    if targets:
        parts.append("targets " + "; ".join(
            f"{t.get('goal')} {game_text(t.get('site') or 'site ' + str(t.get('site_id')), 30)}"
            + (f" ({game_text(t.get('civ'), 24)})" if t.get("civ") else "")
            + (f" d{t['dist']}" if _int(t.get("dist")) is not None else "")
            + (" hostile" if t.get("hostile") or t.get("at_war") else "")
            for t in targets[:5]) + (f" +{len(targets) - 5} more" if len(targets) > 5 else ""))
    if out:
        parts.append(f"out {len(out)}: " + ", ".join(
            game_text(c.get("goal") or "squad", 20).lower() + (f" to {game_text(c.get('site'), 30)}" if c.get("site") else "")
            + (" (returning)" if c.get("returning") else "") for c in out[:3]))
    return "MISSIONS " + " | ".join(parts)

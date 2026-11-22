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
           "mission_line", "MISSION_WORDS", "last_of_goal", "MISSIONS_SWITCH", "SEND_SWITCH",
           "unreachable_sites", "note_unreachable", "SOFT_STOPS", "departure_words", "note_departures",
           "gate_danger", "way_out_gate", "_mission_way_rule"]

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


from util import int_or_none as _int  # noqa: E402  (r6 c2) was a copy here


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
    # (0.105.48, K9) a member gone from the map (the missions report's `gone`:
    # left, sent away, no unit, and no mission) can't be armed: not counted
    gone = min(max(0, _int(a.get("gone")) or 0), members - 1)
    if _int(armed) is None or armed < members - gone:
        return "not all armed"
    return None


def sendable_squads(s: dict, cfg: dict = PLANNER_CONFIG, ignore_pets: bool = False) -> tuple[list, int, int]:
    """(squads, soldiers sent, reserve): whole squads that may go, the
    strongest first, while the soldiers left home stay at the reserve or
    more. Empty when fewer than `mission_min_soldiers` would go.
    (0.105.47, J17) A squad whose soldier's pet is held where the AI can't
    let it out (a cage, a chain, the player's zone) stays home (live 17:38:
    the squad waited at the map edge for its pets) unless ignore_pets."""
    from planner_raids import stuck_pets
    mil = _d(s.get("military"))
    squads = [q for q in _l(mil.get("squads")) if isinstance(q, dict) and q.get("id") is not None]
    away = _away_squads(s)
    reserve = mission_reserve(s, cfg)
    home = _soldiers(s) - sum(_int(_d(a).get("away")) or 0 for a in away.values())
    free = [q for q in squads if _squad_free(q, away) is None
            and (ignore_pets or not stuck_pets(s, [q["id"]]))]
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


# (0.105.39 review 2) a run the player interrupted (took the game back, or it
# ran out of time / went stale): tried again after a day, not a year, and no
# "nobody recorded" Needs you
INTERRUPTED = ("player_busy", "timeout", "stale")


def interrupted(last: dict) -> bool:
    return _d(last).get("reason") in INTERRUPTED


# (0.105.47) a run that stopped for a reason the AI handles itself, not a
# step nobody recorded: DF said the site is INACCESSIBLE (the site is
# dropped: unreachable_sites) or listed no messenger (the messenger rule
# appoints one): the goal isn't blocked and nothing waits for the player
SOFT_STOPS = ("inaccessible", "no_messenger")


def retry_ticks(last: dict, year_ticks: int) -> int:
    """How long a stopped run blocks its goal: a day when the player
    interrupted it (or (0.105.47) DF listed no messenger), else `year_ticks`
    (a step nobody recorded, a surprise)."""
    return TICKS_PER_DAY if interrupted(last) or _d(last).get("reason") == "no_messenger" else year_ticks


def note_unreachable(s: dict, memory, cfg: dict = PLANNER_CONFIG) -> None:
    """(0.105.47) Each goal's last run that DF stopped at the site with
    INACCESSIBLE (lua/ai-mission-send.lua, reason 'inaccessible'): the site
    remembered as unreachable (memory.missions_seen["unreachable"], site id
    -> tick), forgotten after `mission_unreachable_ticks`."""
    if memory is None:
        return
    seen = _seen(memory)
    un = seen.get("unreachable")
    if not isinstance(un, dict):
        un = seen["unreachable"] = {}
    send = _d(_m(s).get("send"))
    outs = list(_d(send.get("last_by_goal")).values()) or [_d(send.get("last"))]
    for o in outs:
        o = _d(o)
        sid, t = _int(o.get("site_id")), _int(o.get("tick"))
        if o.get("reason") == "inaccessible" and sid is not None:
            un[str(sid)] = t if t is not None else abs_tick(s)
    now = abs_tick(s)
    keep = cfg.get("mission_unreachable_ticks", 3 * 403200)
    for k in [k for k, v in un.items() if not isinstance(v, int) or not 0 <= now - v < keep]:
        del un[k]


def unreachable_sites(s: dict, memory=None, cfg: dict = PLANNER_CONFIG) -> set:
    """(0.105.47) The sites a mission can't go to: remembered from DF's
    INACCESSIBLE (memory) and the sender's runs that just said so."""
    out = set()
    seen = getattr(memory, "missions_seen", None) if memory is not None else None
    if isinstance(seen, dict) and isinstance(seen.get("unreachable"), dict):
        now = abs_tick(s)
        keep = cfg.get("mission_unreachable_ticks", 3 * 403200)
        for k, v in seen["unreachable"].items():
            if isinstance(v, int) and 0 <= now - v < keep and str(k).lstrip("-").isdigit():
                out.add(int(k))
    send = _d(_m(s).get("send"))
    for o in list(_d(send.get("last_by_goal")).values()) or [_d(send.get("last"))]:
        o = _d(o)
        if o.get("reason") == "inaccessible" and _int(o.get("site_id")) is not None:
            out.add(o["site_id"])
    return out


# --- (0.105.47) setting out: DF's business, watched ----------------------------------
# Live 14 Nov 17:07: a Make contact and a raid set up by hand had no army 15
# game-minutes later (the messenger on the map milling about, path goal
# MarauderMill). A run ends at "mission set up"; the missions report says
# per controller whether an army points at it (`departed`), when it was set
# up (`since`) and, until it leaves, who it waits on (`waiting`: path goal,
# job). The planner notes a mission that hasn't left after
# `mission_depart_wait_days`, and never sends a second one for it meanwhile
# (the controller counts as out: _fort_missions_out, _messenger_out).

def _age_days(s: dict, c: dict):
    since = _d(c.get("since"))
    if not isinstance(since.get("year"), int) or not isinstance(since.get("tick"), int):
        return None
    from planner_core import TICKS_PER_YEAR
    return max(0, (abs_tick(s) - (since["year"] * TICKS_PER_YEAR + since["tick"])) // TICKS_PER_DAY)


def _who_words(c: dict) -> str:
    parts = []
    for w in _l(c.get("waiting"))[:2]:
        w = _d(w)
        doing = w.get("job") or w.get("path_goal") or "nothing"
        pet = ""
        if isinstance(w.get("pet"), dict):          # (0.105.47, J17) the soldier waits for its pet
            from planner_raids import pet_words
            pet = f", waiting for {pet_words(w['pet'])}"
        parts.append(f"unit {w.get('unit_id')} {'on the map' if w.get('on_map') is not False else 'off the map'}, "
                     f"{game_text(str(doing), 24)}{pet}")
    return "; ".join(parts)


def departure_words(s: dict, c: dict, cfg: dict = PLANNER_CONFIG) -> str:
    """Words for a controller's setting out: "" once it left (or when the
    report can't say), else how long it has waited and, past the wait, who
    it waits on."""
    c = _d(c)
    if c.get("departed") is not False:
        return ""
    days = _age_days(s, c)
    wait = cfg.get("mission_depart_wait_days", 14)
    if days is None or days < wait:
        return f"set up{f' {days} day(s) ago' if days is not None else ''}, not yet set out (DF sends it)"
    who = _who_words(c)
    return f"set up {days} days ago and still hasn't set out" + (f" ({who})" if who else "")


def note_departures(s: dict, memory, cfg: dict = PLANNER_CONFIG) -> list:
    """The fort's missions the AI set up (the sender's `sent_ac`) and the
    ones followed: a note when an army first points at one (it set out),
    and once when one hasn't left after `mission_depart_wait_days`."""
    if memory is None:
        return []
    seen = _seen(memory)
    dep = seen.get("departed")
    if not isinstance(dep, dict):
        dep = seen["departed"] = {}
    late = seen.get("late_said")
    if not isinstance(late, list):
        late = seen["late_said"] = []
    ms = _m(s)
    send = _d(ms.get("send"))
    ours = {str(k) for k in _d(seen.get("out"))}
    for o in list(_d(send.get("last_by_goal")).values()) or [_d(send.get("last"))]:
        if _int(_d(o).get("sent_ac")) is not None:
            ours.add(str(o["sent_ac"]))
    notes = []
    for c in _l(ms.get("controllers")):
        if not isinstance(c, dict) or _int(c.get("id")) is None or str(c["id"]) not in ours:
            continue
        cid = str(c["id"])
        what = (f"{game_text(str(c.get('goal') or 'mission'), 20).lower()}"
                + (f" to {game_text(c.get('site'), 40)}" if c.get("site") else ""))
        if c.get("departed") is True and cid not in dep:
            dep[cid] = abs_tick(s)
            notes.append(f"the mission ({what}) set out: an army left for it")
        elif c.get("departed") is False and cid not in late:
            days = _age_days(s, c)
            if days is not None and days >= cfg.get("mission_depart_wait_days", 14):
                late.append(cid)
                notes.append(f"the mission ({what}) {departure_words(s, c, cfg)}; the AI sends no second one meanwhile")
    for k in list(dep)[:-2 * TRACK_MAX]:
        del dep[k]
    del late[:-2 * TRACK_MAX]
    return notes


# --- (0.105.47, live 17:09) the way off the map -------------------------------------
# Neither mission set out: every way off the map was shut by the AI's own
# gates from the last run. Before a send, the travellers (the messenger,
# every member of the squads going) must be able to walk out (the report's
# `way_out`, lua/ai-mission-way.lua); if the AI's own gates hold the way
# shut and nothing threatens, one is opened (mission_way: open_entrance,
# then a day's hold against the watcher's pre-emptive shut) and the send
# waits a cycle; with danger about, the mission waits. A mission set up
# whose travellers still can't walk out after `mission_way_stuck_hours`
# gets the same opening, once.

def gate_danger(s: dict, cfg: dict, memory=None) -> str:
    """Why the gates stay shut ("" when nothing threatens): a threat that
    can reach the dwarves, a siege, the civilian alert, the alarm's hold."""
    if reachable_threats(s, _traits(s), cfg):
        return "a threat that can reach the dwarves"
    if int(_d(s.get("others_on_map")).get("threats_that_can_reach_dwarves") or 0) > 0:
        return "a threat that can reach the dwarves"
    if any(_d(e).get("active") for e in _l(_d(s.get("world")).get("sieges"))):
        return "a siege"
    if s.get("civ_alert") is True:
        return "the civilian alert"
    held = alarm_held(s, memory, cfg)
    if held:
        return f"the alarm ({held})"
    if _unread_danger(s):
        return f"danger unknown ({_unread_danger(s)} unread)"
    return ""


def _way_open(s: dict, cfg: dict, blocked: int, what: str, key: str, proposals: list, notes: list,
              memory=None) -> None:
    """The opening (or why not) for `blocked` travellers who can't walk out."""
    # (0.105.47, J16) the whole fort sealed in: the way-out guard opens it
    # (planner_way_out, the one check), not a second opening here
    from planner_way_out import sealed
    if sealed(s) is True:
        notes.append(f"{what}: {blocked} traveller(s) can't walk off the map; the whole fort is sealed in, "
                     "and the way-out guard opens it: the mission goes once the walk map shows the way")
        return
    wo = _d(_m(s).get("way_out"))
    shut = [e for e in _l(wo.get("shut")) if isinstance(e, dict) and _int(e.get("id")) is not None]
    if not shut:
        notes.append(f"{what}: {blocked} traveller(s) can't walk off the map and none of the AI's gates holds "
                     "the way (a wall, a collapse or the player's own gate): the mission waits")
        return
    danger = gate_danger(s, cfg, memory)
    if danger:
        notes.append(f"the gates are shut for {danger}: the mission ({what}) waits")
        return
    if any(p.action.get("type") == "mission_way" for p in proposals):
        return
    # (0.105.47, 17:23) opened already (the gate's hold is on): a bridge waits
    # for its lever's pull and DF's walk map is redone; the send goes only
    # once a report shows the travellers' walk group joined the outside
    opening = [e for e in shut if e.get("held")]
    if opening:
        notes.append(f"{what}: the AI's gate at x{opening[0].get('x')} y{opening[0].get('y')} is being opened for "
                     "the travellers; the mission goes once the walk map shows them a way out")
        return
    e = shut[0]
    proposals.append(Proposal("mission_way", {"type": "mission_way", "id": e["id"], "mission": key[:40]},
                              f"{what}: {blocked} traveller(s) can't walk off the map, the AI's own "
                              f"{e.get('kind') or 'gate'} at x{e.get('x')} y{e.get('y')} holds the way shut and "
                              "nothing threatens: open it (held open a day; an enemy at the gate still shuts it)", 6))


def way_out_gate(s: dict, cfg: dict, blocked, what: str, key: str, proposals: list, notes: list,
                 memory=None) -> bool:
    """True when the send may go: the travellers can walk out (or the report
    can't say: the watcher looks again once it is set up). Else False, with
    the opening proposed or why it waits."""
    wo = _d(_m(s).get("way_out"))
    if not wo.get("known") or not blocked:
        return True
    _way_open(s, cfg, int(blocked), what, key, proposals, notes, memory)
    return False


def _mission_way_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """A mission set up (an AI one or one followed) that hasn't set out and
    whose waiting travellers can't walk out for `mission_way_stuck_hours`:
    the same opening, once per mission; after that a note."""
    if memory is None:
        return
    # read only (plan() never writes memory): note_missions books the
    # openings from the gate holds the report shows ("ac <id>")
    seen = getattr(memory, "missions_seen", None)
    tried = _l(_d(seen).get("way_opened")) if isinstance(seen, dict) else []
    ms = _m(s)
    hours = cfg.get("mission_way_stuck_hours", 6)
    for c in _l(ms.get("controllers")):
        c = _d(c)
        if c.get("departed") is not False or not (_int(c.get("way_blocked")) or 0) > 0:
            continue
        days = _age_days(s, c)
        since = _d(c.get("since"))
        if days is None or not isinstance(since.get("tick"), int):
            continue
        from planner_core import TICKS_PER_YEAR
        age = abs_tick(s) - (since["year"] * TICKS_PER_YEAR + since["tick"])
        if age < hours * TICKS_PER_DAY // 24:
            continue
        what = (f"the mission ({game_text(str(c.get('goal') or 'mission'), 20).lower()}"
                + (f" to {game_text(c.get('site'), 40)}" if c.get("site") else "") + ")")
        cid = str(c.get("id"))
        if cid in tried:
            notes.append(f"{what} is set up but its travellers still can't walk off the map after the AI opened "
                         "a gate for them once: the AI leaves it (DF may send them another way)")
            continue
        _way_open(s, cfg, int(c["way_blocked"]), f"{what}, set up {age // (TICKS_PER_DAY // 24)} hour(s) ago,",
                  f"ac {cid}", proposals, notes, memory)


def _stopped(s: dict, goal: str, cfg: dict) -> dict | None:
    """The sender's last run for this goal when it stopped (or failed) within
    `mission_retry_ticks` (a day when the player interrupted it): not tried
    again until then. (0.105.47) A site DF said is INACCESSIBLE blocks only
    that site (unreachable_sites), not the goal."""
    last = last_of_goal(_d(_m(s).get("send")), goal)
    if last.get("result") not in ("stopped", "error"):
        return None
    if last.get("reason") == "inaccessible":
        return None
    t = _int(last.get("tick"))
    if t is None or not 0 <= abs_tick(s) - t < retry_ticks(last, cfg["mission_retry_ticks"]):
        return None
    return last


def left_open_needs_you(s: dict, notes: list) -> None:
    """(0.105.39 review 2) A run that couldn't shut the World screen because
    the player's window was over it (left_open) while the World screen is
    still open: one Needs you."""
    ms = _m(s)
    send = _d(ms.get("send"))
    outs = list(_d(send.get("last_by_goal")).values()) or [_d(send.get("last"))]
    if not ms.get("screen") or not any(_d(o).get("left_open") for o in outs):
        return
    ask_player(notes, "missions (13b): the AI's World screen was left open under your window (the AI never "
                      "presses a key into a window of yours): close it (Esc) when you're done; the AI sends no "
                      "mission and no messenger while it is open")


def mission_target(s: dict, cfg: dict = PLANNER_CONFIG, memory=None, squads=None) -> tuple[dict | None, list]:
    """(the best target the switch allows, the goals skipped for a stopped
    run). Goal order first, then the nearest; a target DF's screen said no
    to is passed over, (0.105.47) and so is a site DF said is INACCESSIBLE
    (unreachable_sites). (0.105.47, J17) The offensive goals only when
    nothing else is to be done, and then as the raid policy picks
    (planner_raids: aggressive / reactive / timid by the sliders, the
    matchup against `squads`, the cooldown); the target carries `policy`
    and `why`."""
    allowed = allowed_goals(s)
    order = {g: i for i, g in enumerate(MISSION_GOALS)}
    stopped, cands, offensive = [], [], []
    gone = unreachable_sites(s, memory, cfg)

    def usable(t) -> bool:
        if t["site_id"] in gone or t.get("inaccessible"):
            return False
        if t.get("ready") not in (None, "OKAY"):
            return False
        if _stopped(s, t["goal"], cfg):
            if t["goal"] not in stopped:
                stopped.append(t["goal"])
            return False
        return True
    for t in _l(_m(s).get("targets")):
        if not isinstance(t, dict) or t.get("goal") not in allowed or _int(t.get("site_id")) is None:
            continue
        if not usable(t):
            continue
        (offensive if t["goal"] in OFFENSIVE_GOALS else cands).append(t)
    if cands:
        best = min(cands, key=lambda t: (order[t["goal"]], _int(t.get("dist")) if _int(t.get("dist")) is not None
                                         else 10 ** 6, t["site_id"]))
        return best, stopped
    if "raid" not in allowed:
        return None, stopped
    from planner_raids import raid_candidates, raid_choice
    if squads is None:
        # the squads that may go; none only for their pets: those (the rule swaps the soldier out)
        squads = sendable_squads(s, cfg)[0] or sendable_squads(s, cfg, ignore_pets=True)[0]
    best, _ = raid_choice(s, cfg, memory, squads, offensive)
    if best is not None and not usable(best):
        # the policy's own rows (raid_sites) pass the same filters
        rest = [t for t in raid_candidates(s, cfg, memory, squads, offensive)[0]
                if t["goal"] in allowed and usable(t)]
        best = rest[0] if rest else None
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
# ((0.105.47) the site invasions share one button, Attack, found by its word)
_GOAL_BUTTON = {"rescue": "Rescue", "recover_artifact": "Recover", "explore": "Attack", "raid": "Attack",
                "pillage": "Attack", "tribute": "Attack", "conquer": "Attack", "make_contact": "Diplomacy"}
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
    if not last or interrupted(last) or last.get("reason") in SOFT_STOPS:
        return                       # interrupted by the player: a short note, tried again tomorrow
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
    with the fort's squads, or a squad under a controller. (0.105.48, K9) A
    squad with no controller is never a mission out, whatever its `away`
    says (the audit: 'away: 1' with nobody out blocked every mission)."""
    ms = _m(s)
    away = _away_squads(s)
    out = [c for c in _l(ms.get("controllers")) if isinstance(c, dict) and c.get("goal") != "DIPLOMACY"
           and (any(x in away for x in _l(c.get("squads"))) or (_int(c.get("away")) or 0) > 0)]
    if not out:
        out = [q for q in away.values() if _int(q.get("controller")) is not None]
    return out


# --- (0.105.47, J17) the raid policy's words; the raid party's pets --------------------

def _raid_notes(s: dict, cfg: dict, notes: list, memory=None) -> None:
    """No mission to go: why no raid (the policy's own words, two at most)."""
    from planner_raids import raid_choice
    _, words = raid_choice(s, cfg, memory)
    for w in words[:2]:
        notes.append(f"raids: {w}")


def _pets_release(s: dict, squads: list, what: str, proposals: list, notes: list) -> bool:
    """True when the soldiers' pets held in the AI's own zones are let out
    first (the send waits a cycle)."""
    from planner_raids import releasable_pets, pet_words
    pets = releasable_pets(s, [q["id"] for q in squads])
    if not pets:
        return False
    if not any(p.action.get("type") == "mission_pets" for p in proposals):
        proposals.append(Proposal("mission_pets", {"type": "mission_pets", "op": "release",
                                                   "pet_ids": [p["pet_id"] for p in pets[:12]]},
                                  f"a mission to {what}: {len(pets)} soldier(s)' pet(s) held at home would hold them "
                                  f"at the map edge (unit {pets[0].get('unit_id')}: {pet_words(pets[0])}): let them "
                                  "out of the AI's zone for the trip, put back once home", 6))
    return True


def _pet_swap(s: dict, cfg: dict, rules: dict, what: str, proposals: list, notes: list) -> bool:
    """No squad can go only because a soldier's pet is held where the AI
    can't let it out (a cage, a chain, the player's zone): that soldier
    swapped out (squad_swap, never for another soldier whose pet is held).
    True when proposed or said."""
    from planner_raids import stuck_pets, pet_words
    if not sendable_squads(s, cfg, ignore_pets=True)[0]:
        return False
    mil = _d(s.get("military"))
    ids = [q["id"] for q in _l(mil.get("squads")) if isinstance(q, dict) and q.get("id") is not None]
    stuck = [p for p in stuck_pets(s, ids) if _int(p.get("unit_id")) is not None]
    if not stuck:
        return False
    p = stuck[0]
    if not rules.get("fill_squads", True) or any(x.action.get("type") == "squad_swap" for x in proposals):
        notes.append(f"a mission could {what}, but soldier {p.get('unit_id')}'s pet is held where the AI can't let "
                     f"it out ({pet_words(p)}): the squad stays home")
        return True
    owners = sorted({x["unit_id"] for x in _l(_d(_d(s.get("missions")).get("pets")).get("held"))
                     if isinstance(x, dict) and _int(x.get("unit_id")) is not None})
    proposals.append(Proposal("mission_pets", {"type": "squad_swap", "unit_id": p["unit_id"], "avoid": owners[:40]},
                              f"a mission could {what}, but soldier {p['unit_id']}'s pet is held where the AI can't "
                              f"let it out ({pet_words(p)}) and would hold the squad at the map edge: swap the soldier "
                              "out for one without such a pet", 6))
    return True


def _pets_restore_rule(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """The pets let out for a mission put back in their zone once they and
    their owners are home, no mission of the fort is out and no send is
    under way."""
    from planner_raids import restore_due
    due = restore_due(s, cfg)
    if not due or _fort_missions_out(s):
        return
    send = _d(_m(s).get("send"))
    if _d(send.get("running")):
        return
    for o in list(_d(send.get("last_by_goal")).values()):
        t = _int(_d(o).get("tick"))
        if _d(o).get("result") == "sent" and t is not None and 0 <= abs_tick(s) - t < cfg["mission_sent_wait_ticks"]:
            return
    proposals.append(Proposal("mission_pets", {"type": "mission_pets", "op": "restore"},
                              f"{len(due)} pet(s) let out for a mission are home again: put them back in their "
                              "pasture", 3))


def _mission_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """(0.105.39) The best mission the Rules allow, once nothing else is out,
    no threat or siege is near and enough soldiers beyond the reserve are
    free. Sent by the World screen when `send_missions` is on and the goal's
    buttons were shown, else named for the player."""
    ms = _m(s)
    left_open_needs_you(s, notes)
    _mission_way_rule(s, cfg, proposals, notes, memory)     # (0.105.47) a set-up mission shut in
    _pets_restore_rule(s, cfg, proposals, notes)             # (0.105.47, J17) pets let out, put back
    # (0.105.47, J17) the raid policy's own sites count as something to go for
    if (not isinstance(ms.get("targets"), list) or not ms["targets"]) and not _l(_d(ms.get("raid_sites")).get("rows")):
        return                       # nothing to go for (or an older bridge): silent
    rules = player_rules(s)
    if not allowed_goals(s):
        return                       # the switch is off
    out = _fort_missions_out(s)
    if out:
        c = out[0]
        dw = departure_words(s, c, cfg)          # (0.105.47) set up but not yet left
        notes.append(f"a mission is out ({game_text(c.get('goal') or 'a squad', 20).lower()}"
                     + (f" to {game_text(c.get('site'), 40)}" if c.get("site") else "")
                     + (", on the way home" if c.get("returning") else "")
                     + (f", {dw}" if dw else "") + "): one mission at a time")
        return
    send = _d(ms.get("send"))
    if _d(send.get("running")):
        notes.append(f"the World screen is being driven (step {game_text(_d(send['running']).get('step'), 20)}): "
                     "a mission waits, one at a time")
        return
    if any(p.action.get("type") == "send_mission" for p in proposals):
        return                       # the messenger goes first this cycle
    target, stopped = mission_target(s, cfg, memory)
    if stopped:
        _stopped_needs_you(s, stopped[0], cfg, notes)
    if target is None and "raid" in allowed_goals(s):
        _raid_notes(s, cfg, notes, memory)
    if target is None:
        if stopped:
            g = stopped[0]
            if interrupted(_stopped(s, g, cfg)):
                notes.append(f"a mission to {MISSION_WORDS.get(g, g)} waits: the last try was interrupted by the "
                             "player; tried again tomorrow")
            else:
                notes.append(f"a mission to {MISSION_WORDS.get(g, g)} waits: the last try stopped at a "
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
        if _pet_swap(s, cfg, rules, what, proposals, notes):
            return
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
        # (0.105.48, K9) the World button shown (this save or any on this PC):
        # without it the bridge refuses every send (needs_button), so nothing is
        # proposed and no pet is let out for a send that can't start
        if "World" not in set(str(b) for b in _l(send.get("buttons"))):
            notes.append(f"a mission could {what}: {names} ({sent} soldiers, {reserve} stay home) are free to go, "
                         "but the AI hasn't been shown DF's World button yet")
            ask_player(notes, f"missions (13b): to {what}, the AI needs DF's World button shown once (the mouse "
                              "on it and python brain\\probe_missions.py --here World); meanwhile "
                              f"{names} stay home and the AI names the target in its notes")
            return
        # (0.105.47) every member of the squads going must be able to walk out
        wo_sq = _d(_d(ms.get("way_out")).get("squads"))
        blocked = sum(_int(wo_sq.get(str(q["id"]))) or 0 for q in squads)
        if not way_out_gate(s, cfg, blocked, f"a mission to {what}", f"{goal} {target['site_id']}",
                            proposals, notes, memory):
            return
        # (0.105.47, J17) a soldier's pet held in the AI's own zone: let out first
        if _pets_release(s, squads, what, proposals, notes):
            return
        action = {"type": "send_mission", "goal": goal, "site_id": target["site_id"],
                  "squad_ids": [q["id"] for q in squads]}
        for k in ("hf_id", "artifact_id"):
            if _int(target.get(k)) is not None:
                action[k] = target[k]
        if goal in OFFENSIVE_GOALS and target.get("policy"):
            action["policy"] = target["policy"]      # (0.105.47, J17) why the bridge may let it go
        proposals.append(Proposal("mission", action,
                                  f"send {names} ({sent} soldiers; {reserve} stay home) to {what}, by the World "
                                  "screen" + (f": {target['why']}" if target.get("why") else ""), 7))
        return
    button = _GOAL_BUTTON.get(goal, goal.title())
    if target.get("why"):
        what = f"{what} ({target['why']})"
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
    note_unreachable(s, memory)          # (0.105.47) DF's INACCESSIBLE remembered per site
    from planner_raids import note_raids
    note_raids(s, memory)                # (0.105.47, J17) sites first seen, traders, the last attack
    dep_notes = note_departures(s, memory)   # (0.105.47) set out yet? (before `out` is updated below)
    # (0.105.47) a way opened for a set-up mission (the gate hold "ac <id>"): once per mission
    tried = seen.get("way_opened")
    if not isinstance(tried, list):
        tried = seen["way_opened"] = []
    for h in _l(_d(ms.get("way_out")).get("holds")):
        k = str(_d(h).get("key") or "")
        if k.startswith("ac ") and k[3:] not in tried:
            tried.append(k[3:])
    del tried[:-2 * TRACK_MAX]
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
    return dep_notes + notes


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

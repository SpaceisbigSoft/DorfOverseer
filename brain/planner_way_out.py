"""(0.105.47, J16) The way out: a fort never left sealed in.

The player (14 Nov 17:25): "something needs to be fixed so the dwarves don't
lock themselves in or can't get out". Live on War-hold: after the last run
the AI's own surface gates (two hatches on "AI gate lever"s, the gatehouse
bridge on its lever) held the fort shut, the citizens' walk group reached
no map-edge tile, and a messenger and a 9-dwarf squad sent on missions could
never leave. The in-game watcher kept a lockdown restored from the save
whose cause was long gone (lua/ai-gates-watch.lua now lifts that itself).

The `way_out` report (lua/ai-way-out.lua): {known, open, inside_group,
edge_groups, shut_by: the surface entrances' shut pieces (ai: the AI's own),
sealed_by_locks, cause: the dangers in sight, nearest_entrances}.

_way_out_rule, each cycle the fort is sealed in:
  * a live cause (a threat that can reach the dwarves, a siege, the alert or
    the alarm's hold, an invader or great danger in sight, a danger within
    `way_out_danger_tiles` of a gate): kept shut, said; the soft causes (the
    alert, the alarm's hold, danger unread) at most `way_out_soft_days`;
  * the cause gone less than `way_out_cause_gone_ticks` (half a day, the
    watcher's reopen): waits the rest;
  * else the nearest surface entrance with a gate of the AI's: way_out_open
    (its levers pulled, its locks undone; the player's gates never), checked
    at the next report; `way_out_tries` tries `way_out_retry_ticks` apart;
  * still sealed after them (or nothing of the AI's shuts the way): a gate
    DF holds shut (a split piece) is the gate_stuck rule's; else a way dug
    out (dig_way_in second, the 0.105.32 way in), `way_out_dig_tries` times;
  * Needs you only when nothing the AI owns can open a way (no AI gate, the
    digs refused).
sealed() is the one check the mission rules (planner_missions) and the
gate_stuck rule (planner_gates) read too.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (AGENDA_THEMES, EMERGENCY, NO_COOLDOWN, STEER_PROTECTED, PLANNER_CONFIG, Proposal,
                          abs_tick, ask_player)

__all__ = ["WAY_OUT_RULES", "sealed", "way_out", "live_cause", "_way_out_rule", "note_way_out",
           "note_way_out_cycle", "leave_open", "LEAVE_ACTION"]

# (0.105.47, J16) a life on each (the messenger, a squad, the fort's trade): no
# action limit, no refusal back-off, never held by the strategist; the rule
# paces its own tries
WAY_OUT_RULES = ("way_out", "way_out_dig")
for _r in WAY_OUT_RULES:
    EMERGENCY.add(_r)
    NO_COOLDOWN.add(_r)
    STEER_PROTECTED.add(_r)
AGENDA_THEMES["way_out"] = "a way off the map for the fort shut in"
AGENDA_THEMES["way_out_dig"] = "a way dug out for the fort shut in"

LEAVE_ACTION = {"type": "way_out_leave"}


def way_out(s: dict) -> dict:
    return _d(s.get("way_out"))


def sealed(s: dict) -> bool | None:
    """The one check: the citizens can't walk off the map (their walk group
    reaches no map-edge tile, or every surface entrance is locked). None when
    the report can't say."""
    wo = way_out(s)
    if not wo.get("known"):
        return None
    if wo.get("open") is False:
        return True
    if wo.get("sealed_by_locks"):
        return True
    return False


def _cfg(cfg: dict, k: str):
    return cfg.get(k, PLANNER_CONFIG.get(k))


def live_cause(s: dict, cfg: dict, memory=None) -> tuple[str, bool]:
    """Why the gates stay shut ("" when nothing does), and whether it is a
    hard cause (a threat, a siege, an enemy in sight) or a soft one (the
    alert, the alarm's hold, danger unread). The mission rules' gate_danger
    and the dangers the way_out report saw in sight."""
    from planner_missions import gate_danger
    c = _d(way_out(s).get("cause"))
    if int(c.get("great") or 0) > 0:
        return "a great danger in sight", True
    if int(c.get("invaders") or 0) > 0:
        return f"{int(c['invaders'])} invader(s) in sight", True
    near = c.get("nearest")
    if isinstance(near, (int, float)) and near <= int(_cfg(cfg, "way_out_danger_tiles")):
        return f"a danger {int(near)} tiles from a gate", True
    why = gate_danger(s, cfg, memory)
    if not why:
        return "", False
    soft = why.startswith("the civilian alert") or why.startswith("the alarm") or why.startswith("danger unknown")
    return why, not soft


def _ai_entrances(wo: dict) -> list:
    """The surface entrances a gate of the AI's holds shut, the nearest to
    the citizens first."""
    ids = []
    for p in _l(wo.get("shut_by")):
        if isinstance(p, dict) and p.get("ai") and isinstance(p.get("entrance"), int) and p["entrance"] not in ids:
            ids.append(p["entrance"])
    order = [i for i in _l(wo.get("nearest_entrances")) if i in ids]
    return order + [i for i in ids if i not in order]


def _players(wo: dict) -> list:
    return [p for p in _l(wo.get("shut_by")) if isinstance(p, dict) and not p.get("ai")]


def _piece_words(p: dict) -> str:
    st = "raised" if p.get("raised") else "shut" if p.get("closed") else "locked" if p.get("locked") else "shut"
    name = f" \"{p['name']}\"" if p.get("name") else ""
    return f"{p.get('kind') or 'gate'}{name} at x{p.get('x')} y{p.get('y')} ({st})"


def _since(rec: dict, k: str, now: int):
    t = rec.get(k)
    return now - t if isinstance(t, int) and now >= t else None


def _way_out_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    if memory is None or sealed(s) is not True:
        return
    wo = way_out(s)
    rec = _d(getattr(memory, "way_out", None))
    now = abs_tick(s)
    sealed_for = _since(rec, "since", now) or 0
    hour = 1200 // 24
    head = (f"the fort is sealed in: the citizens' walk group ({wo.get('inside_group')}) reaches no edge of the map"
            if wo.get("open") is False else
            "the fort is sealed in: every way to the surface is locked")
    why, hard = live_cause(s, cfg, memory)
    if why and (hard or sealed_for < int(_cfg(cfg, "way_out_soft_days")) * 1200):
        notes.append(f"{head}; kept shut for {why}: the AI opens a gate once it has been gone half a day")
        return
    gone = _since(rec, "cause_tick", now)
    wait = int(_cfg(cfg, "way_out_cause_gone_ticks"))
    if not why and gone is not None and gone < wait:
        notes.append(f"{head}; the danger is gone: the AI opens a gate in {(wait - gone) // hour + 1} hour(s) "
                     "if none comes back")
        return
    tries = int(rec.get("tries") or 0)
    last = _since(rec, "last_try", now)
    retry = int(_cfg(cfg, "way_out_retry_ticks"))
    if last is not None and last < retry:
        notes.append(f"{head}; the AI opened its gate {last // hour} hour(s) ago (try {tries}): it looks again "
                     "once the walk map shows the way")
        return
    ents = _ai_entrances(wo)
    players = _players(wo)
    if ents and tries < int(_cfg(cfg, "way_out_tries")):
        if any(p.action.get("type") == "way_out_open" for p in proposals):
            return
        e = ents[0]
        pcs = [p for p in _l(wo.get("shut_by")) if isinstance(p, dict) and p.get("entrance") == e and p.get("ai")]
        what = ", ".join(_piece_words(p) for p in pcs[:3]) or "its gate"
        act = {"type": "way_out_open", "id": e}
        # (0.105.48 round 2, A5 #11) the first try left a bridge to a dwarf's
        # pull; a later one pulls at once (the queued pull taken away first):
        # nobody may come to the lever (cut off, the civilians burrowed)
        if tries >= 1:
            act["instant"] = True
        proposals.append(Proposal("way_out", act,
                                  f"{head} and nothing keeps it shut now: open the AI's own {what} "
                                  f"(try {tries + 1} of {int(_cfg(cfg, 'way_out_tries'))}"
                                  f"{', its levers pulled at once' if tries >= 1 else ''}; the player's gates "
                                  "are left as they are)", -1))
        return
    # only the player's own gates shut the way (a fort the player keeps
    # sealed by their own bridge or door): theirs, left as it is, no hole dug
    if players and not ents and tries == 0:
        notes.append(f"{head}: shut by the player's own {', '.join(_piece_words(p) for p in players[:3])}; "
                     "the AI leaves the player's gates as they are and digs no way past them")
        return
    # still sealed after the tries, or nothing of the AI's on the way
    from planner_gates import split_pieces, _way_in_doing
    if split_pieces(s):
        notes.append(f"{head}; an open gate the game holds shut is on the way: the gate_stuck rule frees it "
                     "step by step, then a way is dug")
        return
    doing = _way_in_doing(s, memory)
    if doing:
        notes.append(f"{head}; a way out is being dug ({doing})")
        return
    digs = int(rec.get("digs") or 0)
    dug = _since(rec, "dig_tick", now)
    if dug is not None and dug < int(_cfg(cfg, "way_out_dig_retry_days")) * 1200:
        notes.append(f"{head}; the AI asked for a way out to be dug {dug // hour} hour(s) ago")
        return
    pl = (f"; shut by the player's own {', '.join(_piece_words(p) for p in players[:3])} (the AI doesn't open "
          "them)") if players else ""
    if digs >= int(_cfg(cfg, "way_out_dig_tries")):
        ask_player(notes, f"{head}{pl}. The AI opened what it owns ({tries} time(s)) and asked {digs} time(s) for "
                          "a stair dug to the surface, and the fort is still shut in: open a way by hand (a "
                          "gate's lever, a door), or dig one")
        return
    why_dig = (f"the AI's gates were opened {tries} time(s) and the walk map still shows no way"
               if tries else "no gate of the AI's holds the way")
    proposals.append(Proposal("way_out_dig", {"type": "dig_way_in", "second": True},
                              f"{head}{pl}; {why_dig}: dig a stair out to the surface", -1))


def note_way_out_cycle(s: dict, memory) -> list:
    """From each report, before planning: since when the fort is sealed, the
    last tick a live cause held it, and the verdict on the last opening (the
    walk group joined the outside, or not)."""
    out = []
    v = sealed(s)
    if v is None:
        return out
    rec = dict(_d(getattr(memory, "way_out", None)))
    now = abs_tick(s)
    if v is False:
        if rec.get("tries") or rec.get("digs"):
            out.append(f"the fort has a way off the map again (after {int(rec.get('tries') or 0)} opening(s) and "
                       f"{int(rec.get('digs') or 0)} dig(s) by the AI)")
        memory.way_out = {}
        return out
    rec.setdefault("since", now)
    why, hard = live_cause(s, PLANNER_CONFIG, memory)
    if why:
        rec["cause_tick"] = now
        rec["cause"] = why[:80]
    memory.way_out = rec
    return out


def note_way_out(p, r: dict, state: dict, memory, now: int) -> None:
    """After an action of the rule's: the try counted (refused with waiting:
    not counted, looked at again soon)."""
    t = p.action.get("type")
    if p.rule not in WAY_OUT_RULES:
        return
    rec = dict(_d(getattr(memory, "way_out", None)))
    if t == "way_out_open":
        if r.get("waiting") and not r.get("ok"):
            rec["last_try"] = now - int(PLANNER_CONFIG["way_out_retry_ticks"]) // 2   # soon again
        else:
            rec["tries"] = int(rec.get("tries") or 0) + 1
            rec["last_try"] = now
            if r.get("ok") is False and r.get("nothing"):
                rec["tries"] = max(rec["tries"], int(PLANNER_CONFIG["way_out_tries"]))   # nothing to open: on to the dig
    elif t == "dig_way_in":
        rec["digs"] = int(rec.get("digs") or 0) + 1
        rec["dig_tick"] = now
        rec["dig_ok"] = r.get("ok")
    memory.way_out = rec


def leave_open(bridge, say=print, check: bool = True) -> dict | None:
    """(0.105.47, J16) The AI stopping (Ctrl-C, the STOP file, the end of a
    run): the fort left open if no enemy is in reach (lua/ai-way-out.lua
    leave), and said. Never raises. check: first read the game's status
    (the keeper, which knows nothing of the fort): not in a fort, or another
    fort than the keeper's pin: left as it is (the overseer checks these
    itself, check=False). (0.105.48, K3) Halted by the player: sent all the
    same (it passes the halt), and the game's leave also lowers the AI's own
    alarm (no enemy in sight) and lets out its burrows (`stood_down`)."""
    try:
        if check:
            st = bridge.status()
            st = st if isinstance(st, dict) else {}
            if not st.get("in_fort"):
                return None
            # (0.105.48, K3) halted: the leave still goes (it passes the halt:
            # it only opens the AI's gates, lowers its alarm, lets out its burrows)
            try:
                import pin
                f = _d(_d(bridge.state(include_units=False, tier="pulse")).get("fort"))
                if f.get("world") and f.get("site_id") is not None and pin.refusal(f.get("world"), f.get("site_id")):
                    return None          # another fort than the run's: not the AI's to open
            except ImportError:
                pass
        r = bridge.act(dict(LEAVE_ACTION))
    except Exception as e:  # noqa: BLE001 - stopping must never fail on this
        say(f"Leaving the fort open failed: {type(e).__name__}: {str(e)[:120]}")
        return None
    r = r if isinstance(r, dict) else {}
    sd = _d(r.get("stood_down"))
    if sd.get("alarm") == "lowered":
        say("The AI's own civilian alert lowered as it stops.")
    elif sd.get("alarm") == "kept":
        say("The AI's own civilian alert stays up: an enemy is in sight (the game lowers it once none is, "
            "or after three days with the overseer away).")
    if _d(sd.get("burrows")):
        say("The AI's burrows let their dwarves out: " + ", ".join(
            f"{k} {v}" for k, v in sorted(_d(sd.get("burrows")).items())) + ".")
    if r.get("ok"):
        say(f"Leaving the fort open: {int(r.get('opened') or 0)} gate piece(s) of the AI's opened, the gate "
            "watcher stood down.")
    elif r.get("enemy"):
        say(f"The fort's gates stay as they are: {r.get('error') or 'an enemy is in reach'} (the in-game watcher "
            "opens them itself once the danger is gone).")
    else:
        say(f"Leaving the fort open: {r.get('error') or 'nothing done'}.")
    return r

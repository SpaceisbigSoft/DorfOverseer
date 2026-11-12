"""(0.105.41, item 8) War and peace: a peace proposal answered by the Rules.

DF 53 gives a fortress no way to offer peace: there is no mission for it and
no meeting topic of the fort's own. Peace comes only when a civilisation's
diplomat brings a proposal (DF's RequestPeace meeting topic). So the AI:

  * answers that proposal by the Rules choice `peace` (the Army tab's
    "Peace offered"): accept, refuse, or (the default) the AI decides: yes
    from a civilisation that has besieged the fort `peace_min_sieges` times
    or more and that the fort hasn't attacked; Militarism raises the bar a
    siege a `peace_slider_step`, Caution lowers it; a civilisation the fort
    attacked gets peace only when Caution beats Militarism by `peace_forgive`.
    The same weighing is in lua/ai-diplomacy.lua (peace_verdict), which
    presses the button; the brain sends the Rules choice, the numbers and the
    civilisations it saw the fort attack (memory.world_seen["attacked"]);
  * keeps that list from the fort's own offensive missions (raids, pillage,
    tribute demanded, conquest: the `missions` report, as planner_missions
    follows them), beside the save's own record that the bridge's
    send_mission keeps (lua/ai-diplomacy.lua note_attacked);
  * says in its notes, for each civilisation at war that keeps besieging the
    fort, what it will answer when their diplomat comes and that until then
    the defences stay as they are (nothing for the player to do: the game
    has no button for it either);
  * a peace proposal on the meeting screen that the AI can't press (the
    screen's buttons not shown to it yet, or several topics open): a Needs
    you saying what the AI would answer and what happens meanwhile.

The planner never writes memory here: note_attacks runs before planning
(planner_world.note_world)."""

from __future__ import annotations

import math

from digest import _d, _l
from planner_core import PLANNER_CONFIG, abs_tick, player_rules, _traits

__all__ = ["peace_need", "peace_verdict", "attacked_civs", "note_attacks", "peace_fields", "civ_peace",
           "_peace_notes", "PEACE_TOPICS"]

HOSTILE = ("TotalWar", "Skirmishing")
PEACE_TOPICS = ("RequestPeace",)


def _round(x: float) -> int:
    return int(math.floor(x + 0.5))       # as Lua's math.floor(x + 0.5): not Python's banker's round


def peace_need(cfg: dict, militarism: float = 0, caution: float = 0) -> int:
    """The sieges a civilisation must have made before the AI takes its peace
    (the Rules' "AI decides"): peace_min_sieges, one more a step of
    Militarism, one fewer a step of Caution, 0-6."""
    step = cfg.get("peace_slider_step") or 50
    n = int(cfg.get("peace_min_sieges", 2)) + _round((militarism or 0) / step) - _round((caution or 0) / step)
    return max(0, min(6, n))


def peace_verdict(policy: str, sieges: int, attacked: bool, traits: dict, cfg: dict = PLANNER_CONFIG) -> tuple[str, str]:
    """('yes' | 'no', why) for a peace proposal, as lua/ai-diplomacy.lua
    peace_verdict answers it."""
    if policy == "accept":
        return "yes", "the Rules: accept peace"
    if policy == "refuse":
        return "no", "the Rules: refuse peace"
    t = _d(traits)
    mil, cau = t.get("militarism", 0) or 0, t.get("caution", 0) or 0
    if attacked:
        if cau - mil >= cfg.get("peace_forgive", 100):
            return "yes", "the fort attacked them, but a cautious fort takes the peace"
        return "no", "the fort attacked them: it keeps its war"
    need = peace_need(cfg, mil, cau)
    if int(sieges or 0) >= need:
        return "yes", f"they have besieged the fort {int(sieges or 0)} time(s) ({need} or more wanted): peace"
    return "no", f"they have besieged the fort {int(sieges or 0)} time(s), fewer than the {need} before the AI takes peace"


def _seen(memory) -> dict:
    ws = getattr(memory, "world_seen", None) if memory is not None else None
    return _d(ws)


def attacked_civs(s: dict, memory=None) -> list[int]:
    """The civilisations the fort attacked: the brain's memory and the save's
    own record (the `world` report's civs[].attacked)."""
    out = set()
    for k in _d(_seen(memory).get("attacked")):
        try:
            out.add(int(k))
        except (TypeError, ValueError):
            pass
    for c in _l(_d(s.get("world")).get("civs")):
        if isinstance(c, dict) and c.get("attacked") and isinstance(c.get("id"), int):
            out.add(c["id"])
    return sorted(out)


def _site_civs(s: dict) -> dict:
    """site id -> its owner's civilisation, from the `missions` report's
    targets (civ_id) and nearest sites (owner_civ)."""
    ms = _d(s.get("missions"))
    out: dict = {}
    for x in _l(_d(ms.get("sites")).get("nearest")):
        if isinstance(x, dict) and isinstance(x.get("id"), int) and isinstance(x.get("owner_civ"), int) \
                and x["owner_civ"] >= 0:
            out[x["id"]] = x["owner_civ"]
    for t in _l(ms.get("targets")):
        if isinstance(t, dict) and isinstance(t.get("site_id"), int) and isinstance(t.get("civ_id"), int) \
                and t["civ_id"] >= 0:
            out[t["site_id"]] = t["civ_id"]
    return out


def note_attacks(s: dict, memory, cfg: dict = PLANNER_CONFIG) -> None:
    """Bookkeeping before planning (planner_world.note_world): every
    offensive mission of the fort's own (planner_missions follows them in
    memory.missions_seen["out"], and the sender's last runs) remembered
    against the civilisation that owns its site
    (memory.world_seen["attacked"]: civ id -> tick)."""
    if memory is None or not isinstance(getattr(memory, "world_seen", None), dict):
        return
    from planner_missions import OFFENSIVE_GOALS
    sites = _site_civs(s)
    if not sites:
        return
    att = memory.world_seen.setdefault("attacked", {})
    now = abs_tick(s)
    hits = []
    ms = getattr(memory, "missions_seen", None)
    for t in _d(_d(ms).get("out")).values():
        if isinstance(t, dict) and t.get("goal") in OFFENSIVE_GOALS:
            hits.append(t.get("site_id"))
    send = _d(_d(s.get("missions")).get("send"))
    for o in list(_d(send.get("last_by_goal")).values()) + [_d(send.get("last"))]:
        o = _d(o)
        if o.get("result") == "sent" and o.get("goal") in OFFENSIVE_GOALS:
            hits.append(o.get("site_id"))
    for site in hits:
        civ = sites.get(site) if isinstance(site, int) else None
        if civ is not None and str(civ) not in att:
            att[str(civ)] = now
    keep = int(cfg.get("peace_attacked_keep", 40))
    if len(att) > keep:
        for k in sorted(att, key=lambda k: int(att[k]) if isinstance(att[k], int) else 0)[:len(att) - keep]:
            del att[k]


def _sieges(s: dict) -> dict:
    return {e["id"]: int(e.get("n") or 0) for e in _l(_d(s.get("world")).get("sieges"))
            if isinstance(e, dict) and isinstance(e.get("id"), int)}


def civ_peace(s: dict, civ_id, memory=None, cfg: dict = PLANNER_CONFIG) -> tuple[str, str]:
    """The AI's answer to a peace proposal from civ `civ_id` now."""
    return peace_verdict(player_rules(s)["peace"], _sieges(s).get(civ_id, 0), civ_id in attacked_civs(s, memory),
                         _traits(s), cfg)


def peace_fields(s: dict, cfg: dict = PLANNER_CONFIG, memory=None) -> dict:
    """What answer_meeting is sent for a peace proposal: the Rules choice,
    the civilisations attacked, the numbers."""
    out = {"peace": player_rules(s)["peace"], "peace_min": int(cfg.get("peace_min_sieges", 2)),
           "peace_step": int(cfg.get("peace_slider_step", 50)), "peace_forgive": int(cfg.get("peace_forgive", 100))}
    att = attacked_civs(s, memory)
    if att:
        out["attacked"] = att[-50:]
    return out


def _peace_notes(s: dict, cfg: dict, notes: list, memory=None) -> None:
    """For each civilisation at war that has besieged the fort, or that has
    offered peace: what the AI answers when their diplomat comes (a proposal
    on the meeting screen too; the AI presses it, planner_world.py)."""
    w = _d(s.get("world"))
    if not w:
        return
    sieges = _sieges(s)
    m = _d(w.get("meeting"))
    for c in _l(w.get("civs")):
        if not isinstance(c, dict) or not isinstance(c.get("id"), int):
            continue
        n = sieges.get(c["id"], 0)
        name = c.get("name") or f"civilisation {c['id']}"
        if not (c.get("relation") in HOSTILE and n > 0) and not c.get("peace_offered"):
            continue
        if m.get("open") and m.get("civ_id") == c["id"]:
            continue                      # the meeting itself says it (below)
        ans, why = civ_peace(s, c["id"], memory, cfg)
        if c.get("peace_offered"):
            notes.append(f"{name} have offered peace: the AI answers {ans} when their diplomat meets the fort ({why})")
        else:
            notes.append(f"at war with {name}, who have besieged the fort {n} time(s): DF lets only their diplomat "
                         f"propose peace (the fort can't offer it), so the defences stay as they are; to a proposal "
                         f"the AI would answer {ans} ({why})")
    # the meeting screen holds a peace proposal
    if not m.get("open") or m.get("requests") or m.get("land_holder"):
        return
    concluded = list(_l(m.get("concluded")))
    pending = []
    for t in _l(m.get("topics")):
        if t in concluded:
            concluded.remove(t)
        else:
            pending.append(t)
    if not any(t in PEACE_TOPICS for t in pending):
        return
    # (fix6) the AI answers the topics one at a time (_meeting_answer_rule,
    # planner_world.py); a screen whose Yes and No it hasn't been shown is
    # planner_locations._meeting_notes' Needs you: here only what it answers
    ans, why = civ_peace(s, m.get("civ_id"), memory, cfg)
    notes.append(f"{m.get('civ') or 'a diplomat'} propose peace on DF's meeting screen: the AI answers "
                 f"{ans.upper()} ({why})")

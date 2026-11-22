"""planner_garden (0.105.47): the Garden fort's gardens. The player (14 Nov):
"garden fort should have gardens". In the run the Garden fort (F) had the
most garden levels (9), statues and meeting halls, but its surface character
never showed: "halls and kitchens by the fields" read 0 and nothing stood by
its 12 surface fields.

- `_garden_court_rule`: the garden court above ground (lua/ai-builder-court.lua,
  `place_garden_court`, one stage a call): a walled court by the fields with
  beds (farm plots), the trees already inside, block paths, statues, seats
  and a meeting area. For high Agriculture + Grandeur + Surface (the Garden
  fort: 120, 40, 80), or a fort whose design language wishes one
  (design_rules: "for the fort's nature lovers") above a low Surface; never
  underground only nor the Hermit hold's hidden_hold. Quiet as every
  construction is (construct_quiet: the halt, the Rules tab's construction
  switch, a crisis, threats); one building above ground at a time (it waits
  for the keep and the surface hall).
- (r9 c1) The player (21 Nov): the court is a meeting area only while no
  danger is about, and only once it is secured. Its 'secure' stage (after
  furnish, before the meeting area) closes the walls all round and has its
  way in a door the AI locks; a court that can't be (a way into the fort
  inside it, a tile that takes no wall, its walls refused or never built)
  stays a plain garden and says why. `_court_meeting_rule` (rule
  court_meeting, garden_court_meeting): the meeting area off at once while
  `court_danger` reads any danger (the threats that can reach the dwarves,
  enemies, a siege held off, a great danger, the gates watched, the alarm,
  a thief or an ambush on record, evil weather, alarm_held's hazards and
  caverns), its door locked too (never with a citizen inside); on again
  only once no danger has been read for `garden_court_lift_ticks` (a day,
  as the gates' lift), so it never flaps.
- `garden_pace`: the statue gardens (planner_building's set piece) come
  sooner by Agriculture (good_times' pace).
- `court_wished`: the design language's garden_court wish, or a landmark
  handed over to the court (planner_design._fallback).

The field customs' surface case (dining and food shops under the surface
fields) is masterplan.hint's (fields.py).
"""

from __future__ import annotations

import re

import customs
import masterplan
from digest import _d, _l
from planner_core import TICKS_PER_DAY, Proposal, abs_tick, emergency, free_stock, young_fort

__all__ = ["court_wanted", "court_wished", "court_opts", "garden_pace", "court_status", "_garden_court_rule",
           "COURT_STAGE_WORDS", "court_danger", "_court_meeting_rule"]

# (r9 c1) the meeting area switched off is a response to danger: no action
# limit, no refusal back-off, never held by the strategist
emergency("court_meeting")

COURT_STAGE_WORDS = {
    None: "a walled garden court by the fields: beds, paths, statues and seats",
    "clearing": "the garden court: the trees on its walls' line are down, raise the walls and the door",
    "walls": "the garden court: its walls stand, lay its beds and paths",
    "beds": "the garden court: its beds are laid, set its statues and seats",
    "furnish": "the garden court: furnished, close it in (walls all round, its gate the AI's) before it is a "
               "meeting place",
    "secure": "the garden court: secure it (walls all round, its door the AI's), then make it a meeting place",
}
NAME_RE = re.compile(r"^[A-Za-z' ]{1,40}$")


def _v(traits: dict | None, k: str) -> float:
    try:
        return float(_d(traits).get(k, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def garden_pace(traits: dict | None, cfg: dict) -> float:
    """(0.105.47) How much sooner the statue gardens come: x2 ** (Agriculture /
    garden_agri_pace_div) for Agriculture above 0 (120: x1.74), else x1."""
    if not cfg.get("garden_fort", True):
        return 1.0
    a = max(0.0, _v(traits, "agriculture"))
    return 2 ** (a / max(1.0, float(cfg.get("garden_agri_pace_div", 150))))


def court_wished(memory) -> bool:
    """The design language wishes a garden court (its landmarks), or a
    garden_court landmark was handed to the court (planner_design)."""
    try:
        import design
        lang = design.current(getattr(memory, "culture", None)) if memory is not None else None
    except Exception:  # noqa: BLE001
        lang = None
    if any(_d(w).get("kind") == "garden_court" for w in _l(_d(lang).get("landmarks"))):
        return True
    lm = _d(_d(getattr(memory, "atlas", None)).get("landmarks"))
    return any(_d(e).get("kind") == "garden_court" and _d(e).get("status") == "court" for e in _l(lm.get("list")))


def court_wanted(traits: dict | None, cfg: dict, memory=None) -> str | None:
    """Why the fort raises a garden court, or None. Never under the ground
    only (Surface -80 or lower) nor with hidden_hold."""
    traits = _d(traits)
    if masterplan.underground_only(traits) or customs.has(traits, "hidden_hold"):
        return None
    a, g, su = _v(traits, "agriculture"), _v(traits, "grandeur"), _v(traits, "surface")
    if (a >= cfg["garden_court_agriculture"] and g >= cfg["garden_court_grandeur"]
            and su >= cfg["garden_court_surface"]):
        return f"Agriculture {a:+.0f}, Grandeur {g:+.0f} and Surface {su:+.0f}"
    if su > cfg["garden_court_wish_surface"] and court_wished(memory):
        return "the fort's design wishes a garden court (for its nature lovers)"
    return None


def court_status(s: dict) -> dict | None:
    st = s.get("garden_court")
    return st if isinstance(st, dict) and st.get("stage") else None


def _court_name(s: dict, memory) -> str:
    """A plain name for the court's meeting area: the fort's next garden
    name (planner_building.garden_name), else "Green"."""
    try:
        from planner_building import garden_name
        n = garden_name(s, memory) if memory is not None else None
    except Exception:  # noqa: BLE001
        n = None
    return n if isinstance(n, str) and NAME_RE.match(n) else "Green"


def court_opts(s: dict, traits: dict, cfg: dict, memory=None) -> dict:
    """What the sliders give the court: block paths with Grandeur
    garden_court_paths_grandeur+, statues by Grandeur (2, or 4 at 40+; only
    free ones are placed), its name."""
    g = _v(traits, "grandeur")
    return {"name": _court_name(s, memory), "paths": g >= cfg["garden_court_paths_grandeur"],
            "statues": 4 if g >= 40 else 2 if g >= 0 else 0}


def _waiting(st: dict) -> str | None:
    stage = st.get("stage")
    if stage == "clearing" and int(st.get("trees_left") or 0) > 0:
        return f"the garden court: the woodcutters fell {st['trees_left']} tree(s) on its walls' line"
    if stage == "walls" and int(st.get("walls_planned") or 0) > 0:
        return f"the garden court: {st['walls_planned']} wall tile(s) still to build"
    # (r9, audit A3 12) a chair or a statue that never comes holds the court
    # COURT_WAIT_DAYS at most: past it (wait_over), or with no start known (an
    # older save: the call records it), the next step is asked anyway
    if (stage in ("beds", "furnish") and int(st.get("planned") or 0) > 0
            and st.get("stage_days") is not None and not st.get("wait_over")):
        return f"the garden court: {st['planned']} piece(s) still to build ({stage})"
    # (r9 c1) secured before it is a meeting place: its walls and door built
    if stage == "secure" and int(st.get("secure_trees") or 0) > 0:
        return f"the garden court: the woodcutters fell {st['secure_trees']} tree(s) on its walls' line"
    if (stage == "secure" and int(st.get("secure_planned") or 0) > 0 and not int(st.get("secure_missing") or 0)
            and not st.get("secure_gap") and st.get("stage_days") is not None and not st.get("wait_over")):
        return (f"the garden court: {st['secure_planned']} wall or door piece(s) still to build before it is "
                "secured (no meeting area until then)")
    return None


def court_danger(s: dict, memory, traits: dict, cfg: dict) -> str:
    """(r9 c1) Why danger is about for the garden court's meeting area ("" when
    none): the fort's own threat signals, none new. Unknown counts as danger."""
    from planner_core import held_off_threats
    from planner_guards import outdoor_danger
    from planner_tantrums import _enemies_about
    why = outdoor_danger(s, memory, traits, cfg)      # the threats that can reach, the alarm, unread
    if why:
        return why
    if _enemies_about(s):
        return "enemies on the map"
    if held_off_threats(s):
        return "a siege is held off at the gates"
    o = _d(s.get("others_on_map"))
    if any(isinstance(t, dict) and t.get("great_danger") and (t.get("can_reach_dwarves") or t.get("layer") == "upper_levels")
           for t in _l(o.get("threats"))):
        return "a great danger on the map"
    if _d(s.get("entrances")).get("armed"):
        return "the gates are watched against danger"
    if s.get("civ_alert") is True or (memory is not None and getattr(memory, "ai_alert_raised", False)):
        return "the alarm is up"
    if memory is not None:
        from planner_threats import alarm_held, unseen_intrusion
        from planner_weather import weather_held
        if unseen_intrusion(s, memory, cfg):
            return "a thief or an ambush is about (DF's invasion record)"
        why = weather_held(s, memory, cfg)
        if why:
            return why
        why = alarm_held(s, memory, cfg)              # hazards, this round's threats, the caverns
        if why:
            return why
    return ""


def _court_meeting_rule(s: dict, cfg: dict, traits: dict, st: dict | None, proposals: list, notes: list,
                        memory=None) -> None:
    """(r9 c1) The garden court's meeting area: off at once while danger is
    about (its door locked too: never with a citizen inside, never a way into
    the fort; the Lua checks), on again once none has been read for
    garden_court_lift_ticks, and only a secured court's. Proposed only when
    the court reads otherwise."""
    if not st or not (st.get("zoned") or st.get("door_built")):
        return
    try:
        why = court_danger(s, memory, traits, cfg)
    except Exception:  # noqa: BLE001  (unknown: kept off)
        why = "the dangers couldn't be judged this cycle"
    try:
        now = abs_tick(s)
    except (KeyError, TypeError):
        now = None
    mem = {}
    if memory is not None:
        from planner_construct import construct_memory
        mem = construct_memory(memory)
    last = mem.get("court_danger_tick")
    if why:
        if isinstance(now, int):
            mem["court_danger_tick"] = last = now
        mem["court_danger_why"] = why
    lift = int(cfg.get("garden_court_lift_ticks", TICKS_PER_DAY) or 0)
    lifting = False
    if not why and isinstance(last, int) and not isinstance(last, bool):
        lifting = not isinstance(now, int) or 0 <= now - last < lift
    secured = bool(st.get("secured")) and not st.get("plain")
    on = st.get("meeting_on")
    locked = st.get("locked") is True
    if secured and not why and not lifting:
        if on is False or locked:
            proposals.append(Proposal("court_meeting", {"type": "garden_court_meeting", "on": True},
                                      "no danger about for a day: the garden court is a meeting place again "
                                      "(its door unlocked)", 6))
        return
    lock = secured and bool(why or lifting)
    want_locked = lock and st.get("lockable") is True and int(st.get("inside") or 0) == 0
    if on is True or (st.get("door_built") and locked != want_locked):
        if why:
            words = f"{why}: the garden court is no meeting place now (its meeting area off"
            words += ", its door locked)" if want_locked else ")"
        elif lifting:
            words = "the garden court's meeting area stays off until a day has passed without danger"
        else:
            words = "the garden court isn't secured yet: no meeting area there until it is"
        proposals.append(Proposal("court_meeting", {"type": "garden_court_meeting", "on": False, "lock": lock},
                                  words, 2))
        return
    if on is False and (why or lifting):
        left = lift - (now - last) if isinstance(now, int) and isinstance(last, int) else None
        notes.append(f"the garden court's meeting area is off: {why}" if why else
                     "the garden court's meeting area is off: on again after a day without danger"
                     + (f" ({max(0, left) // 50} hour(s) to go)" if isinstance(left, int) else ""))


def _garden_court_rule(s: dict, cfg: dict, citizens: int, traits: dict, proposals: list, notes: list,
                       memory=None, rules_: dict | None = None) -> None:
    """(0.105.47) The garden court, one stage a call (see the module)."""
    if not cfg.get("garden_fort", True):
        return
    st = court_status(s)
    _court_meeting_rule(s, cfg, traits, st, proposals, notes, memory)      # (r9 c1) never quiet
    if st and st.get("plain"):
        notes.append(f"the garden court stays a plain garden, no meeting place: {st.get('plain_why') or 'it cannot be secured'}")
        return
    why = court_wanted(traits, cfg, memory)
    if not why:
        return
    if st and (st.get("done") or st.get("stage") == "done"):
        return
    from planner_construct import construct_quiet, hall_open, keep_open
    quiet = construct_quiet(s, memory, traits, cfg, rules_)
    if quiet:
        return
    if st:
        w = _waiting(st)
        if w:
            notes.append(w)
            return
    if young_fort(s, cfg) or citizens < cfg["garden_court_min_citizens"]:
        return
    if not st:
        busy = keep_open(s) or hall_open(s)
        if busy:
            notes.append(f"the garden court waits for the keep or the surface hall ({busy}): one building above "
                         "ground at a time")
            return
        stocks = _d(s.get("stocks"))
        have = free_stock(s, "blocks") + int(stocks.get("boulders") or 0) + int(stocks.get("wood") or 0)
        if have < cfg["garden_court_material"]:
            notes.append(f"the garden court waits for building material ({have} blocks, stone and logs free; "
                         f"its walls want {cfg['garden_court_material']})")
            return
    stage = st.get("stage") if st else None
    words = COURT_STAGE_WORDS.get(stage, "the garden court: its next step")
    if not st:
        words = f"{why}: {words}"
    proposals.append(Proposal("garden_court", {"type": "place_garden_court", **court_opts(s, traits, cfg, memory)},
                              words, 7))

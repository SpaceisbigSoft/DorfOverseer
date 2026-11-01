"""Learning from you: what you decline, undo or correct becomes a preference,
and two of the same kind become a lesson. No tokens.

The signals (each counts 1):
  * you answer No to a co-pilot question;
  * you undo something the AI did: remove an "AI pasture", cancel a big order
    the AI made, switch off a DFHack tool the AI switched on;
  * right after an AI action (within SLIDER_WINDOW_DAYS) you move a slider that
    argues against it by SLIDER_MOVE or more (lower Piety after it starts a
    temple), or switch its Rules option off.

What a preference does, by its weight (signals, plus half of what your other
forts learned):
  1      the AI waits WAIT_DAYS (x the weight) after the last signal before it
         does that kind of thing again, and the weights engine leans away from
         the matching option (e.g. Worship away from temples);
  2+     a lesson: the AI no longer does it on its own; it says so in a note.
         Lessons go to your memory (logs/player-memory.json), shared by all
         your forts: a new fort starts with them at half weight.

What undoes one: a co-pilot Yes for the same kind of thing (-1), or moving the
slider behind it the other way by FORGIVE_MOVE (you changed your mind: gone,
and not inherited again in this fort, 0.97.1).

Your memory, since 0.97.1 (Design Notes "Fort identity" 3e):
  * a fort is one fort in it whatever save folder it's loaded from: its
    copies and autosaves share one key ("line:<world>#<site>"), so a fort
    never inherits its own lessons back (B1);
  * an entry not confirmed by its fort for a real month counts half, two
    months a quarter, and is ignored past that (B2);
  * what another fort passes on is a lean, never a full lesson: at most
    INHERIT_MAX (a wait and the engine's lean, not "left to you") until this
    fort confirms it (B8);
  * "wipe all forts" leaves a stamp the other forts honour the next time they
    run: they wipe their own lessons once instead of writing them back (B3);
  * dry runs don't write it (B11).
Single preferences fade after a year without a new signal; lessons stay until
you wipe them on the panel (Culture tab, Shift-V, then Shift-W).

Rules that keep the fort alive or safe are never held back (drink, food, the
alarm, the gates, the squads in a fight, the basic levels...): a preference
about them is kept and shown, but the AI still does them when the fort needs it.
"""

from __future__ import annotations

import os
import json
from datetime import datetime
from pathlib import Path

from digest import _d, _l, normalize

DAY = 1200
YEAR_TICKS = 403200
WAIT_DAYS = 28
LESSON_WEIGHT = 2.0
SLIDER_WINDOW_DAYS = 3
SLIDER_MOVE = 20
FORGIVE_MOVE = 40
FADE_DAYS = 336                 # a year
MAX_SIGNALS = 6
MAX_RECENT_AI = 20
LOG_MAX = 20
ENGINE_STEP = 0.15              # weights-engine lean per point of weight
ENGINE_MAX = 0.45
ORDER_CANCEL_MIN_JOBS = 20      # an AI order that vanishes with this many jobs left was cancelled
INHERIT_MAX = 1.5               # (0.97.1) the most another fort passes on: below a lesson (2)
AGE_DAYS = 30                   # (0.97.1) a PC entry not confirmed for this many real days counts half...
AGE_DROP = 0.25                 # ...and is ignored once it counts less than this

PLAYER_FILE = Path(os.environ.get("DFAI_LOG_DIR") or Path(__file__).resolve().parent.parent / "logs") / "player-memory.json"

# Rules whose proposals are never held back by a preference.
EXEMPT_RULES = {"threat_alert", "gate", "gates", "squad_attack", "squad_recall", "shelter", "entrances",
                "drink", "food", "containers", "hospital", "project", "furniture", "pop_cap", "mandate"}
# Subjects that are never held back either (a fort can't do without them).
EXEMPT_SUBJECTS = {"level:bedrooms", "level:dining", "level:workshops", "level:storage", "level:tombs"}

# subject (or its prefix) -> sliders that push toward it: (slider, +1 higher favours it / -1 lower does)
DRIVERS = {
    "level:temple": [("piety", 1)], "level:tavern": [("welfare", 1), ("outsiders", 1)],
    "level:library": [("welfare", 1)], "level:hospital": [("welfare", 1)],
    "level:barracks": [("militarism", 1)], "level:memorial": [("grandeur", 1), ("piety", 1)],
    "level:bedrooms": [("growth", 1)],
    "gate:": [("fortification", 1)], "farms:": [("agriculture", 1)],
    "pasture:": [("husbandry", 1)], "expel": [("growth", -1)],
    "squad:": [("militarism", 1)], "tool:autobutcher": [("husbandry", -1)],
    "tool:nestboxes": [("husbandry", 1)], "orders:smelting": [("industriousness", 1)],
    "order:stone_blocks": [("industriousness", 1)],
}
# Rules-tab switch -> subjects (or prefixes) it stands for
RULE_SUBJECTS = {
    "pasture_animals": ["pasture:"], "fortify_entrances": ["gate:"], "build_gate_doors": ["gate:doors"],
    "fill_squads": ["squad:fill"], "train_squads": ["squad:train"], "import_smelting": ["orders:smelting", "order:smelt_ore"],
    "set_pop_cap": [], "mood_workshops": [], "order_supplies": [], "give_trinkets": [], "water_works": [], "expel_vampires": [], "accept_visitors": [], "answer_locations": [],
    "hospital_burrow": [],      # (0.104.168)
}
for _k in ("tombs", "hospital", "tavern", "library", "barracks", "temple"):
    RULE_SUBJECTS[f"levels.{_k}"] = [f"level:{_k}"]
# subject (or prefix) -> the weights-engine area and the options it leans away from
ENGINE = {"level:temple": ("worship", ["shrine", "grand"])}

LEVEL_WORDS = {"temple": "temples", "tavern": "taverns", "library": "libraries", "hospital": "hospitals",
               "barracks": "barracks", "memorial": "memorial halls", "tombs": "tomb levels",
               "bedrooms": "bedroom levels", "dining": "dining halls", "workshops": "workshop levels",
               "storage": "storage levels", "farms": "farm levels", "well": "wells"}
TRAIT_WORDS = {"piety": "Piety", "welfare": "Welfare", "outsiders": "Outsiders", "militarism": "Militarism",
               "grandeur": "Grandeur", "growth": "Growth", "fortification": "Fortification",
               "agriculture": "Agriculture", "husbandry": "Animal husbandry", "industriousness": "Industriousness"}


# --- subjects ---------------------------------------------------------------------

def subject_of(action: dict) -> str | None:
    """The kind of thing an action is, for learning (None: nothing to learn)."""
    t = action.get("type")
    if t == "start_project":
        return f"level:{action.get('kind')}"
    if t == "farm_plots":
        return "farms:dig" if action.get("dig") else "farms:plots"
    if t == "make_pasture":
        return "pasture:new"
    if t == "pasture":
        return "pasture:fill"
    if t == "place_well":
        return "well"
    if t == "fortify_entrance":
        return f"gate:{action.get('style') or 'plain'}"
    if t == "build_gate_doors":
        return "gate:doors"
    if t == "expel_dwarf":
        return "expel"
    if t == "tool" and action.get("enabled"):
        return f"tool:{action.get('name')}"
    if t == "work_order" and action.get("recipe"):
        return f"order:{action.get('recipe')}"
    if t == "squad_fill":
        return "squad:fill"
    if t == "squad_routine":
        # (sending a squad back to work in a small fort isn't a choice to learn from)
        return None if "off duty" in str(action.get("routine") or "").lower() else "squad:train"
    if t == "import_orders":
        return f"orders:{action.get('library')}"
    return None


def subject_text(subject: str) -> str:
    kind, _, rest = subject.partition(":")
    if kind == "level":
        return LEVEL_WORDS.get(rest, f"{rest} levels")
    if kind == "gate":
        return "doors across open entrances" if rest == "doors" else f"{rest} gates at the entrances"
    if kind == "farms":
        return "digging farm levels" if rest == "dig" else "laying out farm plots"
    if kind == "pasture":
        return "making new pastures" if rest == "new" else "putting grazers in pastures"
    if kind == "tool":
        return f"switching on {rest}"
    if kind == "order":
        return f"orders to {rest.replace('_', ' ')}"
    if kind == "orders":
        return f"DFHack's {rest} orders"
    if kind == "squad":
        return "putting dwarves into squads" if rest == "fill" else "putting squads on training"
    return {"well": "digging wells", "expel": "sending dwarves away"}.get(subject, subject)


def _matches(subject: str, key: str) -> bool:
    return subject == key or (key.endswith(":") and subject.startswith(key))


def drivers_of(subject: str) -> list:
    out = []
    for key, d in DRIVERS.items():
        if _matches(subject, key):
            out += d
    return out


# --- state ---------------------------------------------------------------------------

def _state(memory) -> dict:
    l = memory.learning if isinstance(memory.learning, dict) else {}
    memory.learning = l
    for k, default in (("prefs", {}), ("seen", {}), ("recent_ai", []), ("log", [])):
        if not isinstance(l.get(k), type(default)):
            l[k] = default               # (the save turns an empty {} into [])
    return l


def _peek(memory) -> dict:
    """The learning state, read only (plan() must never change memory)."""
    l = memory.learning if isinstance(memory.learning, dict) else {}
    prefs = l.get("prefs") if isinstance(l.get("prefs"), dict) else {}
    return {"prefs": prefs, "log": l.get("log") if isinstance(l.get("log"), list) else []}


def _now(state: dict) -> int:
    d = state["date"]
    return d["year"] * YEAR_TICKS + d["tick"]


def _date(state: dict) -> str:
    d = _d(state.get("date"))
    return f"{d.get('day')} {d.get('month')} y{d.get('year')}"


def _pref(l: dict, subject: str, now: int) -> dict:
    p = l["prefs"].get(subject)
    if not isinstance(p, dict):
        p = l["prefs"][subject] = {"weight": 0.0, "inherited": 0.0, "signals": [], "first": now, "last": now}
    if not isinstance(p.get("signals"), list):
        p["signals"] = []
    return p


def weight(memory, subject: str) -> float:
    p = _peek(memory)["prefs"].get(subject)
    if not isinstance(p, dict):
        return 0.0
    return float(p.get("weight") or 0) + float(p.get("inherited") or 0)


def _log(l: dict, state: dict, text: str) -> None:
    l["log"] = (l["log"] + [{"date": _date(state), "text": text}])[-LOG_MAX:]


def signal(memory, subject: str, how: str, state: dict, amount: float = 1.0) -> str:
    """One more sign that you don't want this kind of thing. Returns what was learned, in words."""
    l = _state(memory)
    now = _now(state)
    p = _pref(l, subject, now)
    was = weight(memory, subject)
    p["weight"] = round(float(p.get("weight") or 0) + amount, 2)
    p["last"] = now
    p["signals"] = (p["signals"] + [{"how": how[:120], "date": _date(state), "tick": now}])[-MAX_SIGNALS:]
    w = weight(memory, subject)
    what = subject_text(subject)
    if w >= LESSON_WEIGHT > was:
        text = f"lesson: you don't want {what} ({how}). The AI leaves it to you from now on"
    else:
        text = f"noted: {how}; the AI holds back on {what} for a while"
    _log(l, state, text)
    return text


def note_decline(memory, action: dict, state: dict) -> str | None:
    subject = subject_of(action)
    if not subject:
        return None
    return signal(memory, subject, f"you declined {subject_text(subject)}", state)


def note_approve(memory, action: dict, state: dict) -> str | None:
    """A Yes for something you'd turned down: one signal less."""
    subject = subject_of(action)
    l = _state(memory)
    p = l["prefs"].get(subject) if subject else None
    if not isinstance(p, dict) or float(p.get("weight") or 0) + float(p.get("inherited") or 0) <= 0:
        return None
    if float(p.get("weight") or 0) > 0:
        p["weight"] = max(0.0, round(float(p["weight"]) - 1, 2))
    else:
        p["inherited"], p["inherited_gone"] = 0.0, True    # your other forts' lesson doesn't hold here
    text = f"you approved {subject_text(subject)}: the AI holds back on it less"
    _log(l, state, text)
    return text


def note_actions(results, state: dict, memory) -> None:
    """Remember what the AI just did, so a slider move right after it can be read."""
    l = _state(memory)
    now = _now(state)
    for p, r in results:
        if not isinstance(r, dict) or r.get("ok") is not True:
            continue
        subject = subject_of(p.action)
        if subject:
            l["recent_ai"] = (l["recent_ai"] + [{"subject": subject, "tick": now}])[-MAX_RECENT_AI:]
        if p.action.get("type") == "make_pasture":
            seen = l["seen"]
            seen["ai_pastures"] = int(seen.get("ai_pastures") or 0) + 1   # the new one isn't a removal
        if p.action.get("type") == "cancel_work_order":
            ids = _l(l["seen"].get("ai_cancelled"))
            l["seen"]["ai_cancelled"] = (ids + [p.action.get("order_id")])[-20:]


# --- watching the fort for your corrections ------------------------------------------

def _rules_of(settings: dict) -> dict:
    """The Rules-tab switches that stand for subjects, flattened."""
    out = {}
    for k in RULE_SUBJECTS:
        if k.startswith("levels."):
            lv = settings.get("levels") if isinstance(settings.get("levels"), dict) else {}
            out[k] = lv.get(k.split(".", 1)[1]) is not False
        else:
            out[k] = settings.get(k) is not False
    return out


def observe(state: dict, memory, fort: str | None = None, write_pc: bool = True) -> list[str]:
    """Every cycle, before planning: the wipe buttons, your corrections, fading
    preferences, and the lessons your other forts left. Returns what changed.
    fort: the fort's line key (line_key); write_pc False (a dry run): your
    memory on the PC is read, never written."""
    s = normalize(state)
    err = s["_errors"]
    l = _state(memory)
    seen = l["seen"]
    now = _now(state)
    out: list[str] = []
    settings = _d(s.get("settings")) if "settings" not in err else None

    # an older save of the same fort: forget what "happened" after today
    l["recent_ai"] = [a for a in l["recent_ai"] if isinstance(a, dict) and 0 <= now - a.get("tick", 0)]

    # The wipe buttons (counters that go up with each press)
    if settings is not None:
        for key, everything in (("wipe_learned", False), ("wipe_learned_all", True)):
            n = settings.get(key)
            if not isinstance(n, int):
                continue
            if key not in seen or n < seen[key]:
                seen[key] = n                 # first look, or an older save: nothing pressed
            elif n > seen[key]:
                wipe(memory, everything=everything and write_pc)
                l = _state(memory)
                seen = l["seen"]
                seen.update({k: settings[k] for k in ("wipe_learned", "wipe_learned_all")
                             if isinstance(settings.get(k), int)})
                out.append("you wiped what the AI had learned" + (" in all your forts" if everything else
                                                                    " in this fort"))
                _log(l, state, out[-1])

    traits = _d(settings.get("traits")) if settings is not None else None
    if traits is not None:
        out += _slider_signals(state, memory, traits, now)
        rules = _rules_of(settings)
        before = seen.get("rules") if isinstance(seen.get("rules"), dict) else None
        if before:
            for k, on in rules.items():
                if before.get(k) is True and on is False:
                    for subj in _recent_subjects(l, now, RULE_SUBJECTS[k]):
                        out.append(signal(memory, subj, f"you switched off \"{k.replace('levels.', '')}\" "
                                                        f"right after the AI did it", state))
        seen["rules"] = rules

    if "society" not in err:
        n = _d(s.get("society")).get("ai_pastures")
        if isinstance(n, int):
            had = int(seen.get("ai_pastures") or 0)
            if n < had:
                out.append(signal(memory, "pasture:new", "you removed an AI pasture", state))
            seen["ai_pastures"] = n

    if "tools" not in err:
        for name, on in _d(s.get("tools")).items():
            if (on is False and name in memory.tools_enabled_by_ai and name in memory.tools_confirmed_on
                    and name not in memory.tools_player_disabled):
                out.append(signal(memory, f"tool:{name}", f"you switched off {name} after the AI switched it on",
                                  state))

    if "orders" not in err:
        out += _order_signals(state, memory, now)

    _fade(memory, now)
    if fort:
        out += _honour_wipe(memory, state, write_pc)
        _inherit(memory, fort, now)
        if write_pc:
            sync_player(memory, fort)
    return out


def line_key(fort: str, world: str | None) -> str:
    """(0.97.1, B1) The key for your memory: one per fort whatever folder its
    save is in (its autosaves and copies): world and site. Without the world,
    the save key as before."""
    site = str(fort or "").rpartition("#")[2]
    return f"line:{world}#{site}" if world and site else str(fort)


def _legacy_same_site(key: str, fort: str) -> bool:
    """An entry from before 0.97.1 ("<save folder>#<site>") for this fort's
    site: one of this fort's own copies (it's folded into the line key)."""
    site = fort.rpartition("#")[2]
    return not key.startswith("line:") and bool(site) and key.rpartition("#")[2] == site


def _age_factor(seen: str | None, today: datetime | None = None) -> float:
    """How much a PC entry still counts: 1 within AGE_DAYS real days of its
    fort confirming it, half per AGE_DAYS after."""
    try:
        days = ((today or datetime.now()) - datetime.fromisoformat(str(seen))).days
    except (TypeError, ValueError):
        return 1.0
    return 0.5 ** max(0, days // AGE_DAYS)


def _entry(v) -> tuple[float, str | None]:
    """A fort's entry in a lesson: {"w", "seen"} (0.97.1) or a bare weight."""
    if isinstance(v, dict):
        w = v.get("w")
        return (float(w) if isinstance(w, (int, float)) else 0.0), v.get("seen")
    return (float(v) if isinstance(v, (int, float)) else 0.0), None


def _honour_wipe(memory, state: dict, write_pc: bool) -> list:
    """(0.97.1, B3) "Wipe all forts" stamped the PC memory: a fort that hasn't
    honoured that stamp wipes its own lessons once (instead of writing them
    back the next time it runs)."""
    stamp = load_player().get("wiped")
    if not isinstance(stamp, str):
        return []
    seen = _state(memory)["seen"]
    if seen.get("wipe_honoured") == stamp:
        return []
    if seen.get("wipe_honoured") is None and not any(
            isinstance(p, dict) and float(p.get("weight") or 0) >= LESSON_WEIGHT
            for p in _state(memory)["prefs"].values()):
        seen["wipe_honoured"] = stamp           # nothing to forget
        return []
    wipe(memory, everything=False, keep_inherit=True)
    _state(memory)["seen"]["wipe_honoured"] = stamp
    text = "you wiped what the AI had learned in all your forts: forgotten here too"
    _log(_state(memory), state, text)
    return [text]


def _recent_subjects(l: dict, now: int, keys: list[str]) -> list[str]:
    found = []
    for a in l["recent_ai"]:
        if 0 <= now - a.get("tick", 0) <= SLIDER_WINDOW_DAYS * DAY and not a.get("used"):
            if any(_matches(a["subject"], k) for k in keys) and a["subject"] not in found:
                a["used"] = True
                found.append(a["subject"])
    return found


def _slider_signals(state: dict, memory, traits: dict, now: int) -> list[str]:
    l = _state(memory)
    seen = l["seen"]
    out = []
    before = seen.get("traits") if isinstance(seen.get("traits"), dict) else None
    current = {k: v for k, v in traits.items() if isinstance(v, (int, float))}
    if before is not None:
        moved = {k: current.get(k, 0) - before.get(k, 0) for k in set(current) | set(before)}
        moved = {k: d for k, d in moved.items() if d}
        # right after an AI action: a move against it is a correction
        for a in l["recent_ai"]:
            if a.get("used") or not 0 <= now - a.get("tick", 0) <= SLIDER_WINDOW_DAYS * DAY:
                continue
            for slider, sign in drivers_of(a["subject"]):
                if -sign * moved.get(slider, 0) >= SLIDER_MOVE:
                    a["used"] = True
                    verb = "lowered" if moved[slider] < 0 else "raised"
                    out.append(signal(memory, a["subject"], f"you {verb} {TRAIT_WORDS.get(slider, slider)} "
                                                             f"right after the AI did it", state))
                    break
        # a big move the other way: you changed your mind about it
        for subject, p in list(l["prefs"].items()):
            for slider, sign in drivers_of(subject):
                if sign * moved.get(slider, 0) >= FORGIVE_MOVE and isinstance(p, dict) \
                        and not (p.get("inherited_gone") and not p.get("weight")):
                    # (0.97.1, B4) kept as forgiven, so the next inheritance in
                    # the same cycle doesn't bring it straight back
                    l["prefs"][subject] = {"weight": 0.0, "inherited": 0.0, "signals": [], "first": now,
                                           "last": now, "inherited_gone": True}
                    text = (f"you {'raised' if moved[slider] > 0 else 'lowered'} "
                            f"{TRAIT_WORDS.get(slider, slider)}: forgot that you didn't want {subject_text(subject)}")
                    _log(l, state, text)
                    out.append(text)
                    break
    seen["traits"] = current
    return out


def _order_signals(state: dict, memory, now: int) -> list[str]:
    """An AI order that disappears with many jobs left wasn't finished: it was cancelled."""
    l = _state(memory)
    seen = l["seen"]
    s = normalize(state)
    out = []
    current = {}
    for o in _l(s.get("orders")):
        if isinstance(o, dict) and o.get("by_ai") and isinstance(o.get("id"), int) and not o.get("repeats"):
            current[str(o["id"])] = {"recipe": o.get("recipe"), "left": o.get("amount_left") or 0,
                                     "total": o.get("amount_total") or 0, "tick": now}
    before = seen.get("orders") if isinstance(seen.get("orders"), dict) else {}
    mine = {str(i) for i in _l(seen.get("ai_cancelled"))}
    for oid, o in before.items():
        if oid in current or oid in mine or not isinstance(o, dict) or not o.get("recipe"):
            continue
        fresh = 0 <= now - (o.get("tick") or 0) <= DAY * 3 // 2
        if fresh and o.get("left", 0) >= ORDER_CANCEL_MIN_JOBS and o.get("left", 0) * 2 >= o.get("total", 0):
            out.append(signal(memory, f"order:{o['recipe']}", f"you cancelled the AI's order for "
                                                               f"{o['left']} {str(o['recipe']).replace('_', ' ')}",
                              state))
    seen["orders"] = current
    return out


def _fade(memory, now: int) -> None:
    """A single preference fades after a year without a new signal; lessons stay."""
    l = _state(memory)
    for subject, p in list(l["prefs"].items()):
        if not isinstance(p, dict):
            del l["prefs"][subject]
            continue
        if p.get("last", 0) > now:
            p["last"] = now                          # an older save
        own = float(p.get("weight") or 0)
        if own < LESSON_WEIGHT and now - p.get("last", now) >= FADE_DAYS * DAY:
            p["weight"] = 0.0
        if (float(p.get("weight") or 0) <= 0 and float(p.get("inherited") or 0) <= 0
                and not p.get("inherited_gone")):
            del l["prefs"][subject]


# --- what preferences do ---------------------------------------------------------------

def hold(memory, subject: str | None, now: int, rule: str = "", priority: int = 9) -> tuple[str | None, str]:
    """('leave' | 'wait' | None, why) for a proposal of this subject."""
    if not subject or rule in EXEMPT_RULES or subject in EXEMPT_SUBJECTS or priority <= 0:
        return None, ""
    w = weight(memory, subject)
    if w <= 0:
        return None, ""
    p = _peek(memory)["prefs"][subject]
    what = subject_text(subject)
    if w >= LESSON_WEIGHT:
        return "leave", (f"left to you: {what} (you turned it down {int(w)} times; "
                         "see What the AI has learned)")
    if w >= 1:
        until = p.get("last", now) + int(WAIT_DAYS * w) * DAY
        if now < until:
            days = (until - now + DAY - 1) // DAY
            how = (p.get("signals") or [{}])[-1].get("how") or "your other forts' lessons"
            return "wait", f"holding back on {what} for {days} more days ({how})"
    return None, ""


def apply(proposals: list, memory, now: int) -> tuple[list, list[str]]:
    """Take out what your preferences hold back. Returns (kept, notes)."""
    kept, notes = [], []
    for p in proposals:
        verdict, why = hold(memory, subject_of(p.action), now, p.rule, p.priority)
        if verdict:
            if why not in notes:
                notes.append(why)
            continue
        kept.append(p)
    return kept, notes


def held_levels(memory, now: int) -> dict:
    """Level kinds held back right now -> why (the planner then tries the next kind)."""
    out = {}
    for subject in list(_peek(memory)["prefs"]):
        if subject.startswith("level:"):
            verdict, why = hold(memory, subject, now, "build", 6)
            if verdict:
                out[subject.split(":", 1)[1]] = why
    return out


def engine_bonuses(memory) -> dict:
    """{area: {option: -lean}} for the weights engine."""
    out: dict = {}
    for subject in _peek(memory)["prefs"]:
        w = weight(memory, subject)
        if w <= 0:
            continue
        area_opts = None
        if subject.startswith("gate:") and subject != "gate:doors":
            area_opts = ("defence", [subject.split(":", 1)[1]])
        else:
            area_opts = next((v for k, v in ENGINE.items() if _matches(subject, k)), None)
        if not area_opts:
            continue
        area, opts = area_opts
        lean = -round(min(ENGINE_MAX, ENGINE_STEP * w), 3)
        for o in opts:
            out.setdefault(area, {})[o] = min(out.get(area, {}).get(o, 0), lean)
    return out


# --- your memory (shared by all your forts) ---------------------------------------------

def load_player() -> dict:
    try:
        d = json.loads(PLAYER_FILE.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("lessons"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"version": 1, "lessons": {}}


def save_player(d: dict) -> None:
    try:
        PLAYER_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PLAYER_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
        tmp.replace(PLAYER_FILE)
    except OSError:
        pass


def sync_player(memory, fort: str) -> None:
    """This fort's lessons go to your memory (under its line key, with today's
    date: it confirms them); ones it has forgotten come out; entries from
    before 0.97.1 of the same site (its own copies) are folded in."""
    d = load_player()
    changed = False
    prefs = _state(memory)["prefs"]
    today = datetime.now().date().isoformat()
    for subject, p in prefs.items():
        own = float(p.get("weight") or 0) if isinstance(p, dict) else 0
        entry = d["lessons"].get(subject)
        if own >= LESSON_WEIGHT:
            if not isinstance(entry, dict):
                entry = d["lessons"][subject] = {"text": subject_text(subject), "forts": {}}
            if entry.get("forts", {}).get(fort) != {"w": own, "seen": today}:
                entry.setdefault("forts", {})[fort] = {"w": own, "seen": today}
                entry["updated"] = datetime.now().isoformat(timespec="seconds")
                changed = True
    for subject, entry in list(d["lessons"].items()):
        forts = entry.get("forts") if isinstance(entry, dict) else None
        if not isinstance(forts, dict):
            del d["lessons"][subject]
            changed = True
            continue
        p = prefs.get(subject)
        own = float(p.get("weight") or 0) if isinstance(p, dict) else 0
        if fort in forts and own < LESSON_WEIGHT:
            del forts[fort]
            changed = True
        for k in [k for k in forts if k != fort and _legacy_same_site(k, fort)]:
            del forts[k]                         # (B1) this fort's own copies, before 0.97.1
            changed = True
        if not forts:
            del d["lessons"][subject]
            changed = True
    if changed:
        save_player(d)


def _inherit(memory, fort: str, now: int) -> None:
    """Your other forts' lessons, as a lean: half the strongest weight, aged
    by how long since its fort confirmed it, at most INHERIT_MAX (0.97.1).
    Never this fort's own (its copies and autosaves share its line key)."""
    l = _state(memory)
    d = load_player()
    want = {}
    for subject, entry in d["lessons"].items():
        forts = entry.get("forts") if isinstance(entry, dict) else None
        others = []
        for k, v in (forts or {}).items():
            if k == fort or _legacy_same_site(k, fort):
                continue
            w, seen = _entry(v)
            f = _age_factor(seen or (entry.get("updated") if isinstance(entry, dict) else None))
            if w > 0 and f >= AGE_DROP:
                others.append(w * f)
        if others:
            want[subject] = round(min(INHERIT_MAX, max(others) / 2), 2)
    for subject, p in list(l["prefs"].items()):
        if isinstance(p, dict) and subject not in want and p.get("inherited"):
            p["inherited"] = 0.0
    for subject, w in want.items():
        p = l["prefs"].get(subject)
        if isinstance(p, dict) and p.get("inherited_gone"):
            continue                              # you approved it here: not inherited again
        if not isinstance(p, dict):
            p = _pref(l, subject, now)
            p["signals"] = [{"how": "learned in your other forts", "date": "", "tick": now}]
        if p.get("inherited") != w:
            p["inherited"] = w


def wipe(memory, everything: bool = False, keep_inherit: bool = False) -> None:
    """Forget what was learned: this fort's preferences, verdicts and tuned
    values (and, with everything, the lessons shared by all your forts, with a
    stamp the other forts honour). keep_inherit: (a wipe honoured from another
    fort) don't stop inheriting."""
    seen = _state(memory)["seen"]
    keep = {k: seen[k] for k in ("traits", "rules", "ai_pastures", "orders", "wipe_learned", "wipe_learned_all")
            if k in seen}
    judged = (memory.learning.get("defence") or {}).get("judged") if isinstance(memory.learning, dict) else None
    memory.learning = {"prefs": {}, "seen": keep, "recent_ai": [], "log": []}
    if isinstance(judged, list):
        # sieges already judged stay judged: their verdicts are forgotten, not re-made
        memory.learning["defence"] = {"judged": judged, "scores": {}}
    memory.outcomes = {}
    memory.calibration = {}
    if isinstance(memory.culture, dict):
        memory.culture["learned"] = {}
    if everything:
        stamp = datetime.now().isoformat(timespec="seconds")
        save_player({"version": 1, "lessons": {}, "wiped": stamp})
        memory.learning["seen"]["wipe_honoured"] = stamp       # (this fort did it)
    elif keep_inherit:
        pass
    else:
        # this fort stops inheriting your other forts' lessons it already had
        for subject in load_player()["lessons"]:
            memory.learning["prefs"][subject] = {"weight": 0.0, "inherited": 0.0, "signals": [], "first": 0,
                                                 "last": 0, "inherited_gone": True}


# --- for the panel and the strategist ------------------------------------------------------

def describe(memory, now: int) -> list[dict]:
    out = []
    for subject, p in sorted(_peek(memory)["prefs"].items()):
        w = weight(memory, subject)
        if not isinstance(p, dict) or w <= 0:
            continue
        verdict, _ = hold(memory, subject, now, "", 9)
        exempt = subject in EXEMPT_SUBJECTS or subject.startswith(("order:brew", "order:prepare"))
        effect = ("still done when the fort needs it" if exempt
                  else "left to you" if verdict == "leave" else "the AI waits before doing it again"
                  if verdict == "wait" else "the AI leans away from it")
        out.append({"subject": subject, "text": subject_text(subject), "weight": round(w, 2),
                    "lesson": w >= LESSON_WEIGHT, "inherited": float(p.get("inherited") or 0) > 0,
                    "how": "; ".join(f"{x.get('how')}" + (f" ({x.get('date')})" if x.get("date") else "")
                                     for x in (p.get("signals") or [])[-3:]),
                    "effect": effect})
    return out


def brief(memory) -> list[str]:
    """One short line per preference, for the strategist."""
    return [f"no {d['text']}" + (" (lesson)" if d["lesson"] else "")
            for d in describe(memory, 0)][:8]


def log_lines(memory, limit: int = 6) -> list[str]:
    return [f"{x.get('date')}: {x.get('text')}" for x in reversed(_peek(memory)["log"][-limit:])
            if isinstance(x, dict)]

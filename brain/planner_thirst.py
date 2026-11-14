"""(0.105.46, I2) The thirst watch: why each thirsty citizen doesn't drink,
the remedy for it, and every death of thirst told with its place and the
last reason known.

Why (the 8-13 Nov run): 186 died of thirst over the six forts (A 29, B 97,
C 10, D 10, E 26, F 14); B's 66 died beside 845 drinks. Access, not supply.
Each cause was found one at a time and got its own rule: an open gate DF
held shut (planner_gates gate_stuck), a wounded visitor in the way of every
Drink job (planner_threats _interrupters), jailed office holders with no
water (planner_society _prisoner_water_rule), cavern wells shut
(planner_wells), the stranded (planner_gates stranded / way_in), a shelter
with no drink (the shelter refresh), the insane (planner_insane). This rule
reads the bridge's `thirst` section (lua/ai-thirst.lua: one `reason` a
dwarf) and, per dwarf, uses the remedy that exists for that reason; a rule
that already acts on it this cycle is left to it (no second action):

  insane       nothing makes them drink: said (the insane rule's doors)
  mood         a strange mood: said (the mood rules bring the materials)
  chained, jailed   release_prisoners for them (unless the prisoners' water
               rule lets them go this cycle)
  cell         the AI's killer cell lets them out to drink: said
  stranded     the gates rules (gate_stuck, way_in, stranded) open or dig
               their way: said, with what they do or why they wait
  interrupted  the threats rule's squad goes at whoever interrupts: said
  alert        the AI shelter is the alarm's burrow: refresh_shelter (it
               takes drink tiles back into it); a player's burrow: said
  burrow       the AI's burrows let the thirsty out at their own check;
               DF lets anyone out of a burrow once dehydrated: said
  forbidden    thirst_unforbid: the forbidden drink in their walk group
               let go, the nearest first (new: no existing action unforbids
               drink; never with the gates shut against enemies or near one)
  no_path      the gate rule's unstick when a gate is split; else
               join_levels (areas on one level joined), and said
  no_drink     brewing and a well (the drink and well rules): said
  injured      water carried from a well to the bedridden: said (the well rules)
  cancelled, unknown, drinking   said only once dehydrated

A drink brought to a dwarf: DF's only job that carries drink to someone is
GiveWater (a bucket from a well or water zone, for a patient resting in
bed); no job brings booze to a dwarf, and DFHack can't make a hauling job
deliver to a unit. So no `drink_to` action: a dwarf with no way to drink
gets a way (gates, joins, unforbid) or water nearby (the well rules).

Each remedy for a dwarf is tried again after `thirst_retry_ticks` at the
soonest (memory.thirst_book). An emergency rule: no action limit, cooldown,
loop guard or strategist hold.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (EMERGENCY, LIMIT_EXEMPT, MULTI_PER_CYCLE, NO_COOLDOWN, STEER_PROTECTED, Proposal,
                          abs_tick)

__all__ = ["RULE", "REASONS", "thirst_rows", "thirst_journal", "_thirst_rule"]

RULE = "thirst"
for _s in (EMERGENCY, NO_COOLDOWN, LIMIT_EXEMPT, STEER_PROTECTED, MULTI_PER_CYCLE):
    _s.add(RULE)

DEHYDRATED = 50000
YEAR = 403200

REASONS = {
    "insane": "insane: they don't drink",
    "mood": "in a strange mood: they drink once the artifact is done",
    "chained": "in chains: only water carried from a well reaches them",
    "jailed": "in the jail: only water carried from a well reaches them",
    "cell": "in the AI's killer cell",
    "stranded": "shut outside with no way in",
    "drinking": "on the way to a drink",
    "interrupted": "their Drink job dropped",
    "alert": "the alarm keeps them in a burrow with no drink nor well",
    "burrow": "their burrow holds no drink nor well",
    "forbidden": "the only drink they can reach is forbidden",
    "no_path": "no path from where they stand to drink or a well",
    "no_drink": "no drink nor well in the fort",
    "injured": "a patient: water is carried to them from a well",
    "cancelled": "their Drink job dropped",
    "unknown": "drink in reach, nothing seen in the way",
}
# reasons acted on from the first thirsty report (no wait for thirst_act_timer):
# nothing else will get them their drink
ACT_EARLY = {"forbidden", "no_path", "alert"}
GATE_ACTIONS = {"open_entrance", "unstick_gate", "dig_way_in", "open_gates", "free_gate_jobs"}


def thirst_rows(s: dict) -> list:
    return [r for r in _l(_d(s.get("thirst")).get("list"))
            if isinstance(r, dict) and isinstance(r.get("id"), int) and not isinstance(r.get("id"), bool)
            and r.get("reason") in REASONS]


def _book(memory) -> dict:
    if memory is None:
        return {"acted": {}, "told": {}, "journaled": {}}
    b = getattr(memory, "thirst_book", None)
    if not isinstance(b, dict):
        b = {}
    for k in ("acted", "told", "journaled"):
        if not isinstance(b.get(k), dict):
            b[k] = {}
    try:
        memory.thirst_book = b
    except AttributeError:
        pass
    return b


def _prune(d: dict, now: int, span: int) -> None:
    for k in [k for k, t in d.items() if not isinstance(t, int) or not 0 <= now - t < span]:
        d.pop(k, None)


def _where(r: dict) -> str:
    if all(isinstance(r.get(k), int) for k in ("x", "y", "z")):
        return f"x{r['x']} y{r['y']} z{r['z']}"
    return "?"


def _cancel_words(c) -> str:
    c = _d(c)
    if not c.get("why"):
        return ""
    return f"last Drink dropped: \"{c['why']}\"" + (f" x{c['n']}" if isinstance(c.get("n"), int) and c["n"] > 1 else "")


def death_words(d: dict) -> str:
    bits = [f"{d.get('name') or 'a dwarf'} died of thirst at {_where(d)}"]
    if d.get("reason") in REASONS:
        bits.append(f"last reason: {d['reason']} ({REASONS[d['reason']]})")
    if d.get("cancel"):
        bits.append(f"last cancelled Drink: \"{d['cancel']}\"")
    if isinstance(d.get("timer"), int):
        bits.append(f"thirst {d['timer']} when last seen")
    return "; ".join(bits)


def thirst_journal(s: dict, memory) -> list[dict]:
    """Each death of thirst once, for the journal: {id, name, x, y, z,
    reason, cancel, timer, text}. Marks it in memory.thirst_book."""
    if memory is None:
        return []
    b = _book(memory)
    now = abs_tick(s)
    _prune(b["journaled"], now, YEAR)
    out = []
    for d in _l(_d(s.get("thirst")).get("deaths")):
        if not isinstance(d, dict) or not isinstance(d.get("id"), int):
            continue
        k = str(d["id"])
        if k in b["journaled"]:
            continue
        b["journaled"][k] = now
        out.append({k2: d.get(k2) for k2 in ("id", "name", "x", "y", "z", "reason", "cancel", "timer")}
                   | {"text": death_words(d)})
    return out


def _existing(proposals: list) -> dict:
    """What the other rules propose this cycle that a thirsty dwarf's remedy
    would duplicate."""
    ex = {"types": set(), "release_all": False, "release_ids": set(), "squad_attack": False}
    for p in proposals:
        a = p.action if isinstance(p.action, dict) else {}
        t = a.get("type")
        ex["types"].add(t)
        if t == "release_prisoners":
            if a.get("ids") is None:
                ex["release_all"] = True
            else:
                ex["release_ids"] |= {i for i in _l(a.get("ids")) if isinstance(i, int)}
        if p.rule == "squad_attack" or (t == "squad_orders" and a.get("kill")):
            ex["squad_attack"] = True
    return ex


def _remedy(r: dict, s: dict, cfg: dict, ex: dict) -> tuple[dict | None, str]:
    """(action or None, words) for one dwarf by its reason."""
    reason, uid = r["reason"], r["id"]
    timer = int(r.get("timer") or 0)
    if reason == "insane":
        return None, (f"{r.get('insane') or 'insane'}: nothing makes them drink (the insane rule keeps the AI's "
                      "doors between them and deadly ground)")
    if reason == "mood":
        return None, f"a {r.get('mood') or 'strange'} mood: the mood rules bring its materials"
    if reason in ("chained", "jailed"):
        if ex["release_all"] or uid in ex["release_ids"]:
            return None, "the prisoners' water rule lets them go this cycle"
        return {"type": "release_prisoners", "ids": [uid]}, "let them go before they die of thirst"
    if reason == "cell":
        return None, ("the AI's cell lets them out to drink" if timer < DEHYDRATED else
                      "the AI's cell should have let them out to drink: look at it")
    if reason == "stranded":
        st = _d(r.get("stranded"))
        if ex["types"] & GATE_ACTIONS:
            return None, "the gates rules open or dig their way in this cycle"
        why = f" ({st.get('cause')})" if st.get("cause") else ""
        return None, (f"the gates rules decide{why}: they open the gate, unstick it or dig a way in, and wait "
                      "only while an enemy is near")
    if reason == "interrupted":
        by = _d(r.get("cancel")).get("by") or "someone"
        if ex["squad_attack"]:
            return None, f"{by} interrupts them; a squad goes after the interrupter this cycle"
        return None, (f"{by} interrupts them; the threats rule sends a squad once DF names it by enough "
                      "dropped jobs")
    if reason == "alert":
        if s.get("civ_alert_shelter") == "ai":
            if "refresh_shelter" in ex["types"]:
                return None, "the AI shelter is redrawn this cycle"
            return {"type": "refresh_shelter"}, "redraw the AI shelter over the fort as it is now (drink taken back in)"
        return None, "the alarm's burrow is the player's: DF lets them out once dehydrated"
    if reason == "burrow":
        if r.get("burrow_ai"):
            return None, "the AI's burrow lets the thirsty out at its own check"
        return None, "a player's burrow (left alone): DF lets them out once dehydrated"
    if reason == "forbidden":
        mx = int(cfg.get("thirst_unforbid_max", 10))
        n = r.get("forbidden_group")
        return ({"type": "thirst_unforbid", "unit_id": uid, "max": mx},
                f"let go the forbidden drink in their reach ({n} there), the nearest first")
    if reason == "no_path":
        if ex["types"] & GATE_ACTIONS:
            return None, "the gates rules open or unstick a gate this cycle"
        if "join_levels" in ex["types"]:
            return None, "areas on one level are joined this cycle"
        return {"type": "join_levels"}, "join the areas of their level that meet only through the stairs"
    if reason == "no_drink":
        return None, "the drink and well rules come first (brewing is urgent, a well)"
    if reason == "injured":
        if "place_well" in ex["types"]:
            return None, "a well is placed this cycle"
        return None, "water is carried to them from a well (the well rules keep one usable)"
    if reason == "cancelled":
        return None, _cancel_words(r.get("cancel")) or "their Drink job dropped"
    if reason == "drinking":
        return None, "on a Drink job"
    return None, "nothing seen in the way"


def _thirst_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """One note a thirsty dwarf (the thirstiest first, `thirst_notes_max`)
    with the reason and the remedy; a remedy action where one exists and no
    other rule acts on it this cycle; each death of thirst told once."""
    t = _d(s.get("thirst"))
    if not t:
        return
    now = abs_tick(s)
    b = _book(memory)
    _prune(b["acted"], now, max(int(cfg.get("thirst_retry_ticks", 600)), 1) * 4)
    _prune(b["told"], now, YEAR)
    for d in _l(t.get("deaths")):
        if isinstance(d, dict) and isinstance(d.get("id"), int) and str(d["id"]) not in b["told"]:
            b["told"][str(d["id"])] = now
            notes.append(death_words(d))
    rows = sorted(thirst_rows(s), key=lambda r: -int(r.get("timer") or 0))
    if not rows:
        return
    note_at = int(cfg.get("thirst_note_timer", 25000))
    act_at = int(cfg.get("thirst_act_timer", 35000))
    retry = int(cfg.get("thirst_retry_ticks", 600))
    acts_max = int(cfg.get("thirst_actions_max", 6))
    notes_max = int(cfg.get("thirst_notes_max", 8))
    ex = _existing(proposals)
    acts, said, rest = 0, 0, {}
    shared = set()          # actions for the whole fort (refresh_shelter, join_levels): once a cycle
    for r in rows:
        timer = int(r.get("timer") or 0)
        reason = r["reason"]
        if timer < note_at:
            continue
        quiet = reason in ("drinking", "unknown", "cancelled") and timer < DEHYDRATED
        action, words = _remedy(r, s, cfg, ex)
        proposed = False
        if action is not None and (timer >= act_at or reason in ACT_EARLY) and acts < acts_max:
            whole = action["type"] in ("refresh_shelter", "join_levels")
            key = f"{action['type']}:{'all' if whole else r['id']}"
            last = b["acted"].get(key)
            if whole and action["type"] in shared:
                words = "the fort-wide remedy is proposed this cycle"
            elif isinstance(last, int) and 0 <= now - last < retry:
                words = f"{words} (tried {max(1, (now - last) // 50)} hour(s) ago; again after {retry // 50})"
            else:
                level = "dehydrated" if timer >= DEHYDRATED else "thirsty"
                proposals.append(Proposal(RULE, action, f"{r.get('name') or 'a dwarf'} is {level} ({timer}): "
                                          f"{REASONS[reason]}: {words}", 0))
                b["acted"][key] = now
                acts += 1
                proposed = True
                if whole:
                    shared.add(action["type"])
                if action["type"] == "release_prisoners":
                    ex["release_ids"].add(r["id"])
        if quiet and not proposed:
            continue
        if said >= notes_max:
            rest[reason] = rest.get(reason, 0) + 1
            continue
        said += 1
        bits = [f"{r.get('name') or 'a dwarf'} thirsty ({timer}{', dehydrated' if timer >= DEHYDRATED else ''}) "
                f"at {_where(r)}: {REASONS[reason]}"]
        cw = _cancel_words(r.get("cancel"))
        if cw and reason not in ("cancelled",):
            bits.append(cw)
        bits.append(("proposed: " if proposed else "") + words)
        notes.append("; ".join(bits))
    if rest:
        notes.append(f"{sum(rest.values())} more thirsty: " + ", ".join(f"{k} {v}" for k, v in sorted(rest.items())))

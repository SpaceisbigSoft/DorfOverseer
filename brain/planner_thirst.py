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
               join_levels (areas on one level joined) once, never again
               soon after one that joined nothing; then (R1 g2) thirst_way:
               the AI's own walls on the way taken down, its locked gate
               doors unlocked, else the shortest dig through natural rock
               (the dig guard); a few tries, then Needs you
  no_drink     brewing and a well (the drink and well rules): said
  injured      (R1 g2) thirst_patient: lifted out of the AI hospital burrow,
               the water carrying counted (carriers, buckets, water in
               reach); the fort's part once a cycle: the carrying labour
               when short, buckets when none, a chief medical dwarf and a
               diagnoser; a few tries, then Needs you once dehydrated
  unknown      (R1 g2) thirst_probe from the act line: their burrows, the
               alarm's, the AI's locked doors near, the drink forbidden or
               claimed: each finding said (the AI's own undone); a few
               tries, then Needs you once dehydrated
  cancelled, drinking   said only once dehydrated

(R1 g2) Every remedy for a dwarf is counted (thirst_book["ladder"]) and
stops after its tries: a no-op is never asked 37 times (F: join_levels,
dead_ends 0, while four founders died behind the AI's own wall). The
bridge's answers are kept (note_thirst, a record hook): what the last try
changed, what it found missing, so the next step and the Needs you say it.

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
                          abs_tick, ask_player, player_rules)

__all__ = ["RULE", "REASONS", "thirst_rows", "thirst_journal", "_thirst_rule", "note_thirst"]

RULE = "thirst"
for _s in (EMERGENCY, NO_COOLDOWN, LIMIT_EXEMPT, STEER_PROTECTED, MULTI_PER_CYCLE):
    _s.add(RULE)

DEHYDRATED = 50000
YEAR = 403200
JOURNALED_KEEP = 500        # (0.105.51) thirst deaths remembered as journaled (ids), the newest kept

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
        return {"acted": {}, "told": {}, "journaled": {}, "ladder": {}, "results": {}}
    b = getattr(memory, "thirst_book", None)
    if not isinstance(b, dict):
        b = {}
    for k in ("acted", "told", "journaled", "ladder", "results"):
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
    # (0.105.51) a death is journaled once for good: pruned after a year (or
    # on an older autosave's clock), A re-recorded unit 17408's thirst death
    # every summer y252-257 while the bridge still listed it. Only the oldest
    # past JOURNALED_KEEP ids are let go.
    jb = b["journaled"]
    if len(jb) > JOURNALED_KEEP:
        for k in sorted(jb, key=lambda k: jb[k] if isinstance(jb[k], int) else -1)[:len(jb) - JOURNALED_KEEP]:
            jb.pop(k, None)
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


# (R1 g2) the per-dwarf actions a ladder counts (a fort-wide one is counted for the dwarf it was asked for)
LADDER_ACTIONS = ("join_levels", "thirst_way", "thirst_patient", "thirst_probe")


def _last(b: dict, key: str) -> dict:
    return _d(_d(b.get("results")).get(key))


def _tries(lad: dict, atype: str) -> int:
    return int(_d(lad.get("n")).get(atype) or 0)


def _no_path_step(r: dict, cfg: dict, ex: dict, b: dict, lad: dict, now: int) -> tuple[dict | None, str, str | None]:
    """(R1 g2) no_path, one step: join_levels once (unless one lately joined
    nothing), then thirst_way a few times; then nothing more but Needs you."""
    uid = r["id"]
    noop = b.get("join_noop")
    noop_recent = isinstance(noop, int) and 0 <= now - noop < int(cfg.get("g2_thirst_join_noop_days", 7)) * 1200
    if "join_levels" in ex["types"]:
        return None, "areas on one level are joined this cycle", None
    if "join_levels" in ex.get("shared", ()):
        return {"type": "join_levels"}, "join the areas of their level that meet only through the stairs", None
    joined = _d(b.get("acted")).get("join_levels:all")
    join_recent = isinstance(joined, int) and 0 <= now - joined < int(cfg.get("thirst_retry_ticks", 600))
    if (_tries(lad, "join_levels") < int(cfg.get("g2_thirst_join_tries", 1)) and not noop_recent
            and not join_recent):
        return {"type": "join_levels"}, "join the areas of their level that meet only through the stairs", None
    way_max = int(cfg.get("g2_thirst_way_tries", 3))
    last = _last(b, f"thirst_way:{uid}")
    why_join = ("the last join of the levels joined nothing" if noop_recent and not _tries(lad, "join_levels")
                else "joining the levels did not reach them")
    if _tries(lad, "thirst_way") >= way_max or (last.get("ok") is False and last.get("error")):
        err = last.get("error") or "each try changed nothing"
        return None, f"the AI could not open a way to drink ({err})", (
            f"{r.get('name') or 'a dwarf'} at {_where(r)} has no way to drink and the AI could not open one "
            f"({err}): dig or open a way to them, or bring drink or a well within their reach")
    words = (f"{why_join}: open the way to drink: the AI's own walls on it taken down, its locked doors unlocked, "
             "else the shortest dig through natural rock")
    if last.get("changed"):
        words += f" (the last try: {last.get('did') or 'changed the way'})"
    return {"type": "thirst_way", "unit_id": uid, "max_dig": int(cfg.get("g2_thirst_way_dig", 30))}, words, None


def _patient_step(r: dict, s: dict, cfg: dict, ex: dict, b: dict, lad: dict) -> tuple[dict | None, str, str | None]:
    """(R1 g2) a patient: thirst_patient (lifted out of the hospital burrow, the
    carrying counted) a few times; then Needs you once dehydrated."""
    uid, timer = r["id"], int(r.get("timer") or 0)
    last = _last(b, f"thirst_patient:{uid}")
    miss = [m for m in _l(last.get("missing")) if isinstance(m, str)]
    if _tries(lad, "thirst_patient") >= int(cfg.get("g2_thirst_patient_tries", 3)):
        what = {"carriers": "too few dwarves carry water", "buckets": "no free bucket",
                "water": "no well or water zone they can be brought water from"}
        lack = ", ".join(what.get(m, m) for m in miss) or "water still doesn't reach them"
        if timer >= DEHYDRATED:
            return None, f"the AI's help did not get water to them ({lack})", (
                f"{r.get('name') or 'a patient'} at {_where(r)} is dehydrated in bed and the AI could not get water "
                f"to them ({lack}): a well or water zone the carriers reach, a bucket, dwarves on the Orderlies "
                "work")
        return None, f"the AI's help is done for now ({lack}); the well and supply rules go on", None
    if "place_well" in ex["types"]:
        tail = "; a well is placed this cycle"
    else:
        tail = ""
    return ({"type": "thirst_patient", "unit_id": uid},
            "let them out of the AI hospital burrow and count what carries water to them (carriers, buckets, a "
            "well in reach)" + tail, None)


def _probe_step(r: dict, cfg: dict, b: dict, lad: dict) -> tuple[dict | None, str, str | None]:
    """(R1 g2) "unknown": thirst_probe a few times, each finding said; then
    Needs you once dehydrated."""
    uid, timer = r["id"], int(r.get("timer") or 0)
    last = _last(b, f"thirst_probe:{uid}")
    found = "; ".join(str(x) for x in _l(last.get("findings"))[:4] if isinstance(x, str))
    if _tries(lad, "thirst_probe") >= int(cfg.get("g2_thirst_probe_tries", 3)):
        if timer >= DEHYDRATED:
            return None, f"looked into {_tries(lad, 'thirst_probe')} times" + (f" (found: {found})" if found else ""), (
                f"{r.get('name') or 'a dwarf'} at {_where(r)} is dehydrated with drink in reach and the AI found "
                f"nothing it can undo" + (f" ({found})" if found else "") + ": look at them in the game")
        return None, "looked into already" + (f" (found: {found})" if found else ""), None
    if timer < int(cfg.get("g2_thirst_probe_timer", 35000)):
        return None, "nothing seen in the way", None
    return ({"type": "thirst_probe", "unit_id": uid},
            "look at what holds them: their burrows, the alarm's, the AI's locked doors near, the drink forbidden "
            "or claimed" + (f" (last time: {found})" if found else ""), None)


def _remedy(r: dict, s: dict, cfg: dict, ex: dict, b: dict | None = None, lad: dict | None = None,
            now: int = 0) -> tuple[dict | None, str, str | None]:
    """(action or None, words, Needs you text or None) for one dwarf by its reason."""
    reason, uid = r["reason"], r["id"]
    timer = int(r.get("timer") or 0)
    b = b if b is not None else {"results": {}}
    lad = lad if lad is not None else {}
    act, words = _remedy_old(r, s, cfg, ex)
    if reason == "no_path" and act is not None:
        return _no_path_step(r, cfg, ex, b, lad, now)
    if reason == "injured":
        return _patient_step(r, s, cfg, ex, b, lad)
    if reason == "unknown":
        return _probe_step(r, cfg, b, lad)
    return act, words, None


def _remedy_old(r: dict, s: dict, cfg: dict, ex: dict) -> tuple[dict | None, str]:
    """(action or None, words) for one dwarf by its reason (before R1 g2)."""
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
            # (0.105.52) the shelter, redrawn over the whole fort, still holds no
            # drink (R3 15 Nov: B's 20 thirst deaths): a dehydrated dwarf gets the
            # AI's alarm lowered for half a day, not another dry redraw
            if ex.get("shelter_dry") and timer >= DEHYDRATED:
                if "civ_alert" in ex["types"]:
                    return None, "the alarm is changed this cycle"
                return ({"type": "civ_alert", "on": False, "why": "thirst"},
                        "the shelter holds no drink even over the whole fort: the AI's alarm comes down for half "
                        "a day so the thirsty can drink")
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


def _queued(s: dict, recipe: str) -> bool:
    return any(isinstance(o, dict) and o.get("recipe") == recipe and int(o.get("amount_left") or 0) > 0
               for o in _l(s.get("orders")))


def _patient_support(s: dict, cfg: dict, proposals: list, b: dict, now: int, patients: list) -> list:
    """(R1 g2) The fort's part in getting water to thirsty patients, each at
    most once a cycle and once every thirst_retry_ticks (memory.thirst_book):
    the water-carrying labour when the last count found too few carriers,
    buckets when the fort has none, a chief medical dwarf when the office is
    empty, a diagnoser when nobody diagnoses. Returns the words said."""
    retry = int(cfg.get("thirst_retry_ticks", 600))
    said = []
    types = {(p.action.get("type"), p.action.get("job"), p.action.get("office"), p.action.get("recipe"))
             for p in proposals if isinstance(p.action, dict)}
    jobs = {t[1] for t in types if t[0] == "assign_labor"}
    offices = {t[2] for t in types if t[0] == "appoint"}
    recipes = {t[3] for t in types if t[0] == "work_order"}
    who = patients[0].get("name") or "a patient"
    n = len(patients)

    def offer(key: str, action: dict, why: str) -> None:
        last = b["acted"].get(key)
        if isinstance(last, int) and 0 <= now - last < retry:
            return
        b["acted"][key] = now
        proposals.append(Proposal(RULE, action, f"{n} patient(s) thirsty ({who} first): {why}", 0))
        said.append(why)

    short = [k for k, v in _d(b.get("results")).items()
             if k.startswith("thirst_patient:") and isinstance(_d(v).get("carriers"), int)
             and "carriers" in _l(_d(v).get("missing")) and 0 <= now - int(_d(v).get("tick") or 0) < 4 * retry]
    if short and "FEED_WATER_CIVILIANS" not in jobs:
        offer("assign_labor:FEED_WATER_CIVILIANS", {"type": "assign_labor", "job": "FEED_WATER_CIVILIANS", "count": 2},
              "too few dwarves carry water to the bedridden: two more given the labour")
    buckets = _d(s.get("supplies")).get("buckets")
    if buckets == 0 and "wooden_bucket" not in recipes and not _queued(s, "wooden_bucket"):
        offer("work_order:wooden_bucket", {"type": "work_order", "recipe": "wooden_bucket",
                                           "amount": int(cfg.get("g2_thirst_buckets", 3))},
              "no bucket to carry water to them: buckets made")
    vacant = _l(_d(s.get("society")).get("vacant"))
    if "CHIEF_MEDICAL_DWARF" in vacant and "CHIEF_MEDICAL_DWARF" not in offices and player_rules(s)["appoint_nobles"]:
        offer("appoint:CHIEF_MEDICAL_DWARF", {"type": "appoint", "office": "CHIEF_MEDICAL_DWARF"},
              "nobody is chief medical dwarf: the best-suited appointed")
    diag = _d(s.get("infection")).get("diagnosers")
    if diag == 0 and "DIAGNOSE" not in jobs:
        offer("assign_labor:DIAGNOSE", {"type": "assign_labor", "job": "DIAGNOSE", "count": 1},
              "nobody outside the military diagnoses: the best civilian at it given the labour")
    return said


def note_thirst(p, r, memory, now: int) -> None:
    """(R1 g2) A record hook: what the bridge answered to the thirst rule's
    actions (and to any join_levels), kept for the next step and its words:
    {tick, ok, changed, did, error, missing, carriers, findings}."""
    a = p.action if isinstance(getattr(p, "action", None), dict) else {}
    t = a.get("type")
    if t not in LADDER_ACTIONS or memory is None:
        return
    r = r if isinstance(r, dict) else {}
    b = _book(memory)
    if t == "join_levels":
        changed = bool(r.get("joined") or r.get("widened"))
        if not changed and r.get("ok") is not False:
            b["join_noop"] = now
        if getattr(p, "rule", None) != RULE:
            return
    did = []
    for k, w in (("removed", "the AI's walls taken down"), ("unlocked", "doors unlocked"), ("dug", "tiles marked to dig"),
                 ("pending", "tiles already marked"), ("acted", "undone"), ("lifted", "out of the hospital burrow")):
        v = r.get(k)
        if v is True or (isinstance(v, int) and not isinstance(v, bool) and v > 0):
            did.append(w if v is True else f"{v} {w}")
    if t == "join_levels":
        changed = bool(r.get("joined") or r.get("widened"))
    else:
        changed = bool(did)
    key = f"{t}:{a.get('unit_id') if a.get('unit_id') is not None else 'all'}"
    b["results"][key] = {"tick": now, "ok": r.get("ok"), "changed": changed, "did": ", ".join(did) or None,
                         "error": str(r.get("error") or "")[:200] or None,
                         "missing": [m for m in _l(r.get("missing")) if isinstance(m, str)][:4] or None,
                         "carriers": r.get("carriers") if isinstance(r.get("carriers"), int) else None,
                         "findings": [str(f)[:120] for f in _l(r.get("findings"))[:6]] or None}


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
    # (R1 g2) a dwarf no longer thirsty (drank, or gone) starts afresh next time
    here = {str(r["id"]) for r in rows}
    for k in [k for k in b["ladder"] if k not in here]:
        b["ladder"].pop(k, None)
    for k in [k for k, v in b["results"].items()
              if not isinstance(_d(v).get("tick"), int) or not 0 <= now - _d(v)["tick"] < YEAR]:
        b["results"].pop(k, None)
    if not rows:
        return
    note_at = int(cfg.get("thirst_note_timer", 25000))
    act_at = int(cfg.get("thirst_act_timer", 35000))
    retry = int(cfg.get("thirst_retry_ticks", 600))
    acts_max = int(cfg.get("thirst_actions_max", 6))
    notes_max = int(cfg.get("thirst_notes_max", 8))
    ex = _existing(proposals)
    ex["shelter_dry"] = bool(_d(getattr(memory, "shelter_supply", None)).get("dry")) if memory is not None else False
    acts, said, rest = 0, 0, {}
    patients: list = []
    shared = set()          # actions for the whole fort (refresh_shelter, join_levels): once a cycle
    ex["shared"] = shared
    for r in rows:
        timer = int(r.get("timer") or 0)
        reason = r["reason"]
        if timer < note_at:
            continue
        quiet = reason in ("drinking", "unknown", "cancelled") and timer < DEHYDRATED
        lad = b["ladder"].setdefault(str(r["id"]), {"since": now, "n": {}})
        if not isinstance(lad.get("n"), dict):
            lad["n"] = {}
        action, words, needs_you = _remedy(r, s, cfg, ex, b, lad, now)
        if reason == "injured" and timer >= act_at:
            patients.append(r)
        proposed = False
        if action is not None and (timer >= act_at or reason in ACT_EARLY) and acts < acts_max:
            whole = action["type"] in ("refresh_shelter", "join_levels")
            key = f"{action['type']}:{'all' if whole else r['id']}"
            last = b["acted"].get(key)
            if whole and action["type"] in shared:
                words = "the fort-wide remedy is proposed this cycle"
                if action["type"] in LADDER_ACTIONS:      # (R1 g2) asked for them too: counted
                    lad["n"][action["type"]] = int(lad["n"].get(action["type"]) or 0) + 1
            elif isinstance(last, int) and 0 <= now - last < retry:
                words = f"{words} (tried {max(1, (now - last) // 50)} hour(s) ago; again after {retry // 50})"
            else:
                level = "dehydrated" if timer >= DEHYDRATED else "thirsty"
                proposals.append(Proposal(RULE, action, f"{r.get('name') or 'a dwarf'} is {level} ({timer}): "
                                          f"{REASONS[reason]}: {words}", 0))
                b["acted"][key] = now
                acts += 1
                proposed = True
                if action["type"] in LADDER_ACTIONS:
                    lad["n"][action["type"]] = int(lad["n"].get(action["type"]) or 0) + 1
                if whole:
                    shared.add(action["type"])
                if action["type"] == "release_prisoners":
                    ex["release_ids"].add(r["id"])
        if needs_you and timer >= act_at:
            # (R1 g2) every remedy tried: the player's, said each cycle while it holds
            ask_player(notes, needs_you)
            continue
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
    if patients:
        for w in _patient_support(s, cfg, proposals, b, now, patients):
            notes.append(f"thirsty patients: proposed: {w}")

"""(0.105.47, R2) The dwarves who badly want to fight or train.

Two things, from the 14 Nov investigations (I7b cause 2, I7c "soldier
ping-pong") and the player's decision of 14 Nov 14:11.

1. The squad ping-pong ends. The fill drafted the miserable who longed to
   train (keen first); in the squad the need was met, so the needs report
   no longer said they longed for it, and stress care released them
   ("soldiering weighs on the stress-prone"); out of the squad the need
   went unmet again and the fill drafted them back. E's Logem went in 5
   times and out 4, Mebzuth 10 in and 5 out; their MartialTraining stayed
   unmet for years. One theory per dwarf now:
   * a dwarf who has the need at all (the needs report's `fight_need`,
     met in a squad or not), or whose need is unmet now, is never released
     by stress care: the squad is what meets it (planner_society._stress_care);
     one breaking down out of a squad whose TOP unmet need is to train or
     fight goes into the training squad, if there is one with room
     (stress_train below);
   * otherwise a stress release means "never draft" for that dwarf
     (memory.never_draft): passed to every fill and swap as `avoid`
     (recently_home), forgotten after `never_draft_days` or once the
     dwarf is content or better (the report's `needs.content_ids`).

2. The training squad (the player: "high Welfare allows a small
   TRAINING-ONLY squad for civilians who badly want to fight, even at low
   Militarism"; the Monastery at Militarism -60, Welfare 80). Rules:
   * Welfare `training_squad_welfare` (50) or more, and the Rules switch
     `training_squad` (Army tab, on by default). Any Militarism: at high
     Militarism the fill already drafts the keen first, so it rarely forms.
   * Size: at most `training_squad_max` (10, a DF squad) and one per
     `training_squad_adults_per` (5) adults; none where that is under
     `training_squad_min` (2). Made once `training_squad_keen_min` civilians
     badly want to fight or train; filled only with volunteers by need (the
     bridge's keen-only fill: Fight or MartialTraining badly unmet).
   * It is led from a vacant captain's office (the militia commander stays
     for the fort's guard) by a volunteer, and gets no uniform: it trains as
     it is (sparring and wrestling meet MartialTraining) on "Staggered
     training" where the fort has it (its months off leave time for the
     other needs), else any training routine.
   * Never counted as the fort's soldiers: prepare_training takes it out of
     the military report's squads and soldier counts before any rule runs,
     so Militarism's share, the trim (also refused bridge-side), the fill,
     the uniforms, the gear orders, hunts, missions and every kill order
     pass it by. The guard minimum (`guard_min_soldiers`) is untouched: it
     is counted on the regular squads alone.
   * Kill orders: none in peace. Decision: only when enemies can reach the
     dwarves AND no regular squad can fight (can_fight) is it counted back
     in as an ordinary squad for that attack; the usual armed test still
     applies, so unarmed it still isn't sent. Any kill order on it outside
     that case is recalled, and guard_training_orders drops any proposal
     that would send it.
   * Welfare falls under the line, or the switch is turned off: it is let go
     (`training_squad` forget): an ordinary squad again, which the trim
     brings back to Militarism's size.
"""
from __future__ import annotations

from planner_core import (AGENDA_THEMES, PLANNER_CONFIG, TICKS_PER_DAY, Proposal, abs_tick, can_fight, player_rules,
                          reachable_threats, _traits)


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _l(v) -> list:
    return v if isinstance(v, list) else []


def _int(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


__all__ = ["FIGHT_NEEDS", "prepare_training", "training_squads", "training_needed", "training_cap",
           "never_draft_ids", "note_never_draft", "note_training", "stress_train", "longs_to_train",
           "_training_squad_rule", "guard_training_orders"]

FIGHT_NEEDS = {"MartialTraining", "Fight"}

AGENDA_THEMES.update({"training_squad": "let the keen train"})

# actions that would send a squad to fight (by squad_id or a list of squads)
SENDING = {"squad_orders", "hunt_send", "send_mission"}


def training_squads(s: dict) -> list:
    """The training squads in the report (the bridge marks them `training`),
    taken out of the squads by prepare_training or not."""
    mil = _d(s.get("military"))
    if isinstance(mil.get("training_squads"), list):
        return [q for q in mil["training_squads"] if isinstance(q, dict)]
    return [q for q in _l(mil.get("squads")) if isinstance(q, dict) and q.get("training")]


def training_needed(s: dict, cfg: dict, regular: list) -> bool:
    """Enemies can reach the dwarves and no regular squad can fight."""
    try:
        reach = bool(reachable_threats(s, _traits(s), cfg))
    except Exception:  # noqa: BLE001  (an odd report: not needed)
        reach = False
    return reach and not any(can_fight(q, cfg) for q in regular if isinstance(q, dict))


def prepare_training(s: dict, cfg: dict = PLANNER_CONFIG) -> None:
    """Before any rule: the training squads out of the fort's squads and
    soldier counts (a new military dict; the report's own is not changed),
    unless training_needed. Once a plan (a second call changes nothing)."""
    mil = s.get("military")
    if not isinstance(mil, dict) or "training_squads" in mil:
        return
    squads = _l(mil.get("squads"))
    train = [q for q in squads if isinstance(q, dict) and q.get("training")]
    if not train:
        return
    for q in train:
        q["training_squad"] = True
    regular = [q for q in squads if not (isinstance(q, dict) and q.get("training"))]
    if training_needed(s, cfg, regular):
        s["military"] = dict(mil, training_squads=train, training_called=True)
        return
    ids = {q.get("id") for q in train}
    n = sum(_int(q.get("members")) or 0 for q in train)
    gear = dict(_d(mil.get("gear")))
    for k in ("soldiers", "on_duty"):
        if _int(gear.get(k)) is not None:
            gear[k] = max(0, gear[k] - n)
    if _int(gear.get("squads")) is not None:
        gear["squads"] = max(0, gear["squads"] - len(train))
    if _int(gear.get("squads_with_uniform")) is not None:
        gear["squads_with_uniform"] = max(0, gear["squads_with_uniform"] - sum(1 for q in train if q.get("uniform")))
    soldiers = _int(mil.get("soldiers")) or 0
    s["military"] = dict(mil, squads=regular, soldiers=max(0, soldiers - n), soldiers_all=soldiers,
                         training_squads=train, gear=gear)
    # the hunt section's own list of squads: never a hunting party
    h = s.get("hunt")
    if isinstance(h, dict) and isinstance(h.get("squads"), list):
        s["hunt"] = dict(h, squads=[q for q in h["squads"] if not (isinstance(q, dict) and q.get("id") in ids)])


def training_cap(s: dict, cfg: dict) -> int:
    adults = _int(_d(s.get("dwarves")).get("adults")) or 0
    return min(cfg["training_squad_max"], adults // max(1, cfg["training_squad_adults_per"]))


def _allowed(s: dict, cfg: dict) -> tuple[bool, str]:
    welfare = _traits(s).get("welfare", 0) or 0
    if not player_rules(s).get("training_squad", True):
        return False, "the Rules switch for the training squad is off"
    if welfare < cfg["training_squad_welfare"]:
        return False, f"Welfare {int(welfare):+d} is under {cfg['training_squad_welfare']}"
    return True, ""


def longs_to_train(x: dict) -> bool:
    """A stressed dwarf (the needs report's row) whose need to fight or train
    is theirs: met in a squad now, or unmet."""
    return bool(x.get("fight_need") or x.get("wants_fight") or set(_l(x.get("unmet"))) & FIGHT_NEEDS)


# --- "never draft" -------------------------------------------------------------------

def _never_live(s: dict, memory, cfg: dict) -> dict:
    now = abs_tick(s)
    content = {str(i) for i in _l(_d(s.get("needs")).get("content_ids"))}
    days = cfg.get("never_draft_days", 672)
    out = {}
    for k, v in _d(getattr(memory, "never_draft", None)).items():
        at = _d(v).get("at")
        if isinstance(at, int) and 0 <= now - at < days * TICKS_PER_DAY and str(k) not in content:
            out[str(k)] = v
    return out


def never_draft_ids(s: dict, memory, cfg: dict = PLANNER_CONFIG) -> list:
    """The units stress care sent home for good, newest first (for `avoid`)."""
    if memory is None:
        return []
    rows = sorted(((int(_d(v).get("at") or 0), k) for k, v in _never_live(s, memory, cfg).items()), reverse=True)
    return [int(k) for _, k in rows if str(k).isdigit()][:100]


def note_never_draft(s: dict, memory, cfg: dict = PLANNER_CONFIG) -> None:
    """(note_cycle) Forget those sent home long ago, and those whose mood rose
    to content or better (a big change: the stress that made them unfit is gone)."""
    if not isinstance(getattr(memory, "never_draft", None), dict) or not memory.never_draft:
        return
    if "needs" in _d(s.get("_errors")):
        # unread: only the age forgets (the mood isn't known)
        s = dict(s, needs={})
    live = _never_live(s, memory, cfg)
    for k in [k for k in memory.never_draft if str(k) not in live]:
        del memory.never_draft[k]


def note_training(p: Proposal, r: dict, memory, now: int) -> None:
    """(record) Stress care's release done: never drafted again (until the
    memory forgets it)."""
    a = p.action
    if (p.rule == "stress_care" and a.get("type") == "squad_release" and not a.get("mother")
            and r.get("ok") is True and a.get("unit_id") is not None and not a.get("dry_run")):
        if not isinstance(getattr(memory, "never_draft", None), dict):
            memory.never_draft = {}
        memory.never_draft[str(a["unit_id"])] = {"at": now}


# --- stress care: into the training squad ----------------------------------------------

def _room(q: dict, cap: int) -> int:
    members = _int(q.get("members")) or 0
    places = min(9, (_int(q.get("size")) or 0) - 1) - max(0, members - (1 if q.get("leader") else 0))
    return max(0, min(places, cap - members))


def stress_train(s: dict, cfg: dict, x: dict, memory=None) -> Proposal | None:
    """A dwarf breaking down, in no squad, whose top unmet need is to train or
    fight: into the training squad, when one has room and all is quiet."""
    if x.get("squad") or x.get("id") is None:
        return None
    top = _l(x.get("unmet"))[:1]
    if not top or top[0] not in FIGHT_NEEDS:
        return None
    if memory is not None and x["id"] in never_draft_ids(s, memory, cfg):
        return None
    if _d(s.get("military")).get("training_called") or _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return None
    ok, _why = _allowed(s, cfg)
    if not ok:
        return None
    cap = training_cap(s, cfg)
    q = next((q for q in training_squads(s) if q.get("id") is not None and _room(q, cap) > 0), None)
    if q is None:
        return None
    return Proposal("stress_care", {"type": "training_squad", "mode": "fill", "squad_id": q["id"],
                                    "unit_id": x["id"], "count": 1},
                    f"{x.get('name')} is {str(x.get('stress')).replace('_', ' ')} and longs most to "
                    f"{'train' if top[0] == 'MartialTraining' else 'fight'}: into the training squad "
                    f"{q.get('name') or ''} (it only trains)", 3)


# --- the training squad ---------------------------------------------------------------

def _train_routine(s: dict) -> str | None:
    routines = [r for r in _l(_d(s.get("military")).get("routines")) if isinstance(r, str)]
    return (next((r for r in routines if "staggered" in r.lower()), None)
            or next((r for r in routines if "training" in r.lower()), None))


def _training_squad_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    mil = _d(s.get("military"))
    train = training_squads(s)
    called = bool(mil.get("training_called"))
    # a kill order on it outside an attack it is needed for: called back
    if not called:
        for q in train:
            if q.get("ai_orders") and isinstance(q.get("kill_ids"), list) and q.get("id") is not None:
                proposals.append(Proposal("squad_recall", {"type": "squad_orders", "squad_id": q["id"], "clear": True},
                                          f"{q.get('name') or 'the training squad'} only trains: called back", 1))
    ok, why = _allowed(s, cfg)
    if not ok:
        for q in train:
            if q.get("id") is not None:
                proposals.append(Proposal("training_squad", {"type": "training_squad", "mode": "forget",
                                                             "squad_id": q["id"]},
                                          f"{why}: {q.get('name') or 'the training squad'} is no longer a training "
                                          "squad (an ordinary squad, counted with the soldiers)", 5))
        return
    if called:
        notes.append("enemies can reach the dwarves and no other squad can fight: the training squad counts as "
                     "an ordinary squad until it is over")
        return
    if _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves") or _l(_d(s.get("hazards")).get("berserk")):
        return
    nd = _d(s.get("needs"))
    kd = _int(nd.get("keen_draftable"))
    keen = kd if kd is not None else (_int(nd.get("keen_civilians")) or 0)
    cap = training_cap(s, cfg)
    traits = _traits(s)
    if not train:
        if cap < cfg["training_squad_min"] or keen < cfg["training_squad_keen_min"]:
            return
        proposals.append(Proposal("training_squad", {"type": "training_squad", "mode": "make"},
                                  f"{keen} civilians badly want to fight or train (Welfare "
                                  f"{int(traits.get('welfare', 0) or 0):+d}, Militarism "
                                  f"{int(traits.get('militarism', 0) or 0):+d}): a training squad of volunteers, "
                                  f"up to {cap}, that only trains and is never counted as soldiers", 4))
        return
    q = train[0]
    if q.get("id") is None:
        return
    members = _int(q.get("members")) or 0
    routine = _train_routine(s)
    if members > 0 and routine and (not q.get("routine") or "off duty" in str(q.get("routine")).lower()):
        proposals.append(Proposal("training_squad", {"type": "squad_routine", "squad_id": q["id"], "routine": routine},
                                  f"{q.get('name') or 'the training squad'} is there to train: "
                                  f"{routine.lower()}", 4))
    room = _room(q, cap)
    if room > 0 and keen > 0:
        from planner_core import recently_home
        n = min(room, keen, cfg["training_squad_fill_max"])
        act = {"type": "training_squad", "mode": "fill", "squad_id": q["id"], "count": n}
        home = recently_home(s, memory)
        if home:
            act["avoid"] = home
        proposals.append(Proposal("training_squad", act,
                                  f"{keen} civilians badly want to fight or train: {n} volunteer(s) into "
                                  f"{q.get('name') or 'the training squad'} ({members} of up to {cap})", 4))
    notes.append(f"training squad {q.get('name') or q['id']}: {members} of up to {cap} volunteers train "
                 f"(Welfare {int(traits.get('welfare', 0) or 0):+d}); not counted among the fort's soldiers, "
                 "never sent to fight in peace")
    if members > cap:
        notes.append(f"the training squad has {members}, over its cap of {cap} (the fort is smaller): no new "
                     "volunteers until it is under")


def guard_training_orders(s: dict, proposals: list, notes: list) -> list:
    """The last word: no proposal sends a training squad to fight, unless the
    fort needs it (training_called)."""
    mil = _d(s.get("military"))
    if mil.get("training_called"):
        return proposals
    ids = {q.get("id") for q in training_squads(s) if q.get("id") is not None}
    if not ids:
        return proposals
    kept = []
    for p in proposals:
        a = p.action if isinstance(p.action, dict) else {}
        t = a.get("type")
        hit = False
        if t in SENDING:
            named = {x for x in _l(a.get("squad_ids")) + _l(a.get("squads")) if isinstance(x, int)}
            if a.get("squad_id") in ids or named & ids:
                hit = t != "squad_orders" or bool(a.get("kill"))
        if hit:
            notes.append(f"{p.reason[:80]}: not sent (the training squad only trains)")
            continue
        kept.append(p)
    return kept

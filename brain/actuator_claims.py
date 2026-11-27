"""(F2c) Actuator claims: one owner per squad, lever, gate, the alarm, burrow
and zone, across cycles, with an expiry. Used by planner_select.select()
(kept out of planner_select itself: tests/test_r7_d2.py pins the planner
parts' globals).

Squads, levers, gates, the alarm, burrows and zones
are shared: two rules that each pull "their" lever every other cycle undo
each other (the lever alternates). Each action kind that works one names
the actuator(s) it uses as (kind, id) keys; select() gives each key one
owner: the rule whose proposal went, with its tier (hold_classes:
survival > defence > expansion) and priority, kept in Memory.claims across
cycles until the owner proposes the actuator's "off/return" step (a
release) or the claim expires (claim_expiry_cycles cycles or
claim_expiry_seconds of real time, the first to come). Another rule's
proposal on an owned key is dropped unless it ranks strictly higher (then
it takes the claim). Squads keep their per-cycle rules (squad_claim: kill
orders merge, a list loses the squads taken) and are held across cycles
only when "squad" is in claim_persist_kinds (not by default: the recall's
exceptions in planner_military still say when a squad stays out).
"""

from __future__ import annotations

from planner_select import SQUAD_ORDER_KEYS

SQUAD, LEVER, GATE, ALARM, BURROW, ZONE = "squad", "lever", "gate", "alarm", "burrow", "zone"
TOGGLE = "toggle"      # a release mark: the owner's next use of the key returns it (a lever pull)


def _ids(v) -> list:
    out = v if isinstance(v, list) else [v]
    return [i for i in out if i is not None and not isinstance(i, bool)]


def _squad_keys(key):
    return lambda a: [(SQUAD, i) for i in _ids(a.get(key))]


def _one(kind, ident):
    return lambda a: [(kind, ident)]


def _named(kind, prefix, field_):
    return lambda a: [(kind, f"{prefix}:{a.get(field_)}")] if a.get(field_) is not None else []


def _cavern_way_keys(a):
    return [(GATE, "cavern_way")] if a.get("step") in ("open", "shut") or a.get("shut") else []


# action type -> (the actuator keys it uses, from its params; whether it is
# the off/return step that releases them: a predicate, or TOGGLE)
ACTUATORS = {t: (_squad_keys(k), (lambda a: bool(a.get("clear"))) if t == "squad_orders"
                 else (lambda a: True) if t == "hunt_recall" else (lambda a: False))
             for t, k in SQUAD_ORDER_KEYS.items()}
ACTUATORS.update({
    "pull_gate": (lambda a: [(LEVER, i) for i in _ids(a.get("lever_id"))], TOGGLE),
    "civ_alert": (_one(ALARM, "alarm"), lambda a: a.get("on") is False),
    "close_threatened_gates": (_one(GATE, "gates"), lambda a: False),
    "open_gates": (_one(GATE, "gates"), lambda a: True),
    "lure_open": (_named(GATE, "lure", "opening"), lambda a: False),
    "lure_shut": (_named(GATE, "lure", "opening"), lambda a: True),
    "cavern_way": (_cavern_way_keys, lambda a: bool(a.get("shut")) or a.get("step") == "shut"),
    "seal_cavern": (_named(GATE, "cavern", "layer"), lambda a: not a.get("open")),
    "weather_burrow": (_one(BURROW, "weather"), lambda a: a.get("on") is False),
    "hospital_burrow": (_one(BURROW, "hospital"), lambda a: bool(a.get("release"))),
    "calm_burrow": (_one(BURROW, "calm"), lambda a: bool(a.get("release"))),
})


def actuator_keys(a) -> list:
    """The (kind, id) actuators action `a` uses (none for any other action)."""
    ent = ACTUATORS.get(a.get("type")) if isinstance(a, dict) else None
    if ent is None:
        return []
    try:
        return [k for k in ent[0](a) if k[1] is not None and not isinstance(k[1], bool)]
    except Exception:  # noqa: BLE001  an odd action names no actuator
        return []


def ordered_squads(a: dict) -> list:
    """The squad ids action `a` gives orders to (none for any other action)."""
    return [i for k, i in actuator_keys(a) if k == SQUAD]


_TIER = {"survival": 0, "defence": 1, "expansion": 2}


def claim_rank(p) -> tuple:
    """(tier, priority): lower ranks higher."""
    try:
        from hold_classes import step_class
        t = _TIER.get(step_class(p), 0)
    except Exception:  # noqa: BLE001
        t = 0
    return (t, int(getattr(p, "priority", 0) or 0))


def _clock() -> float:     # (tests patch it)
    import time
    return time.time()


def _ckey(k) -> str:
    return f"{k[0]}:{k[1]}"


def _persisted(kind, cfg) -> bool:
    return kind in (cfg.get("claim_persist_kinds") or ())


def claims_open(memory, cfg) -> dict:
    """This cycle's claim table (Memory.claims: {"n": cycle, "own": {key: rec}}),
    the cycle counted on and the expired claims dropped."""
    c = getattr(memory, "claims", None)
    if not isinstance(c, dict):
        c = {}
        try:
            memory.claims = c
        except Exception:  # noqa: BLE001
            pass
    n = int(c.get("n") or 0) + 1 if isinstance(c.get("n"), int) else 1
    c["n"] = n
    own = c.get("own") if isinstance(c.get("own"), dict) else {}
    c["own"] = {k: r for k, r in own.items() if isinstance(r, dict) and claim_live(r, n, cfg)}
    return c


def claim_live(rec: dict, n: int, cfg) -> bool:
    try:
        return (n - int(rec.get("n") or 0) < int(cfg.get("claim_expiry_cycles", 12))
                and _clock() - float(rec.get("t") or 0) < float(cfg.get("claim_expiry_seconds", 1800)))
    except Exception:  # noqa: BLE001
        return False


def _beats(p, rec: dict) -> bool:
    return claim_rank(p) < (int(rec.get("tier") or 0), int(rec.get("prio") or 0))


def _claim_keys(p, cfg) -> list:
    """The keys p is judged on here: every non-squad actuator, a squad only
    when squads are held across cycles."""
    return [k for k in actuator_keys(getattr(p, "action", None)) if k[0] != SQUAD or _persisted(SQUAD, cfg)]


def _say(k) -> str:
    return "the alarm" if k[0] == ALARM else f"{k[0]} {k[1]}"


def claims_outranked(proposals: list, claims: dict, cfg) -> dict:
    """(F2c) Within one cycle, the proposals another rule's proposal on the
    same actuator outranks (and may use: not stopped by a claim): id(p) ->
    why. The cycle's order is by priority alone, so without this a defence
    rule's lever pull at priority 0 went before a survival rule's at 2, every
    cycle."""
    own, n = claims.get("own") or {}, claims.get("n") or 0
    by_key: dict = {}
    for p in proposals:
        for k in _claim_keys(p, cfg):
            if k[0] == SQUAD:
                continue             # squads: squad_claim's own per-cycle rules
            by_key.setdefault(_ckey(k), []).append((k, p))
    out = {}
    for ps in by_key.values():
        if len({p.rule for _, p in ps}) < 2:
            continue

        def ok(p, k):
            r = own.get(_ckey(k))
            return not r or r.get("rule") == p.rule or not claim_live(r, n, cfg) or _beats(p, r)
        for k, p in ps:
            win = [q for _, q in ps if q.rule != p.rule and ok(q, k) and claim_rank(q) < claim_rank(p)]
            if win:
                out.setdefault(id(p), f"{p.rule}: {_say(k)} goes to {win[0].rule} this cycle (higher tier or "
                                      "priority); this one waits")
    return out


# (F2c, merge 0.105.135) the safety directions a claim from an earlier cycle
# never holds while an enemy is within the emergency distance ("gates close
# late": danger within 12 tiles shuts them, whoever opened them)
SAFETY_STEPS = {"close_threatened_gates": lambda a: True,
                "civ_alert": lambda a: bool(a.get("on", True))}


def safety_step(p) -> bool:
    a = getattr(p, "action", None)
    f = SAFETY_STEPS.get(a.get("type")) if isinstance(a, dict) else None
    return bool(f and f(a))


def actuator_claim(p, claims: dict, used: dict, outranked: dict, cfg, danger: bool = False) -> str | None:
    """(F2c) p against the actuator owners: why it is held, or None (it may
    go). `used`: key -> the proposal that went this cycle. `danger`: an enemy
    within the emergency distance: a safety step skips the earlier cycles'
    claims (this cycle's users and outranking still apply)."""
    if id(p) in outranked:
        return outranked[id(p)]
    own, n = claims.get("own") or {}, claims.get("n") or 0
    for k in _claim_keys(p, cfg):
        ck = _ckey(k)
        q = used.get(ck)
        if q is not None and q.rule != p.rule and k[0] != SQUAD:
            return f"{p.rule}: {_say(k)} is used by {q.rule} this cycle; this one waits"
        if not _persisted(k[0], cfg) or (danger and safety_step(p)):
            continue
        r = own.get(ck)
        if r and r.get("rule") != p.rule and claim_live(r, n, cfg) and not _beats(p, r):
            left = max(1, int(cfg.get("claim_expiry_cycles", 12)) - (n - int(r.get("n") or 0)))
            return (f"{p.rule}: {_say(k)} is {r.get('rule')}'s (a rule of the same or a higher tier set it "
                    f"{n - int(r.get('n') or 0)} cycle(s) ago); free once it lets it go or in {left} cycle(s)")
    return None


def claims_commit(p, claims: dict, used: dict, now_tick, cfg) -> None:
    """(F2c) p went: it owns its actuators now, or lets them go (its off step)."""
    a = getattr(p, "action", None)
    ent = ACTUATORS.get(a.get("type")) if isinstance(a, dict) else None
    if ent is None:
        return
    own, n = claims.setdefault("own", {}), claims.get("n") or 0
    for k in actuator_keys(a):
        ck = _ckey(k)
        used.setdefault(ck, p)
        if not _persisted(k[0], cfg):
            continue
        r = own.get(ck)
        if ent[1] is TOGGLE:
            release = bool(r) and r.get("rule") == p.rule
        else:
            try:
                release = bool(ent[1](a))
            except Exception:  # noqa: BLE001
                release = False
        if release:
            own.pop(ck, None)
        else:
            t, pr = claim_rank(p)
            own[ck] = {"rule": p.rule, "tier": t, "prio": pr, "n": n, "t": _clock(), "tick": now_tick}

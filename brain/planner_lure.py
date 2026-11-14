"""(0.105.45) A great danger sealed in a cavern, lured in and cut off.

Since 0.105.26 every way into the caverns is locked while a forgotten beast
(or a titan, a megabeast, a demon) is loose down there (planner_threats'
seal). A sealed beast sits there for good, and the cavern's farms, trees and
water with it. When the squads can't simply win (planner_military's
fight_or_hide says no) or can't get at it, this rule lures it into a pocket
behind one of the AI's own cavern doors (lua/ai-lure.lua) and cuts it off:

  * the beast has sat in the sealed caverns `lure_after_days` and the fort
    has the mechanisms: the pocket is built (build_lure, step by step: cage
    traps and a locked inner door for a beast traps catch; drawbridges on
    the AI's own levers at its mouth and as its inner gate for one they
    can't, TRAPAVOID);
  * ready, the inner gate shut (lure_shut shuts it first), nobody down in
    the caverns and nobody in or beside the pocket: the door is opened into
    the pocket (lure_open; the bridge refuses it otherwise too);
  * open: the beast caged in a trap, or inside the pocket (the mouth then
    raised behind it): shut (lure_shut), noted done; a citizen goes down or
    near, or the Rules switch goes off: shut at once; nothing within
    `lure_open_days`: shut, and opened again after `lure_retry_days`,
    doubled each try up to `lure_retry_max_days`;
  * a caged beast stays caged (the AI never lets one out); one shut in waits
    for the crossbows (an archer post where a fortification looks into the
    pocket, when the siege report has one near) or stays there for good.

The seal stays the seal: the lure opens only its own door, in its own
phase `open`, and the bridge marks that door `lure_open` (planner_threats
counts it as meant, ai-threats' seal leaves it). Rules switch `lure_beasts`.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (AGENDA_THEMES, LIMIT_EXEMPT, PLANNER_CONFIG, STEER_PROTECTED, TICKS_PER_DAY, Proposal,
                          abs_tick, can_fight, player_rules)

__all__ = ["_lure_rule", "lure_rows", "backoff_days", "PHASES"]

PHASES = ("idle", "building", "ready", "open", "caught", "shut_in", "done")
ALL_CAVERNS = "all caverns"          # planner_threats' seal record

LIMIT_EXEMPT.update({"lure_shut"})            # shutting the pocket waits for no action slot
STEER_PROTECTED.update({"lure_shut"})         # and the strategist never holds it
AGENDA_THEMES.update({"lure_build": "a lure pocket for the beast in the caverns",
                      "lure_open": "lure the beast in the caverns into the pocket",
                      "lure_shut": "lure the beast in the caverns into the pocket",
                      "lure_archer": "crossbows at the beast shut in the pocket"})


def _c(cfg: dict, k: str):
    return (cfg or {}).get(k, PLANNER_CONFIG.get(k))


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def lure_rows(s: dict) -> list:
    """The bridge's lure pockets (rows with a key and a known phase)."""
    return [r for r in _l(_d(s.get("lures")).get("lures"))
            if isinstance(r, dict) and isinstance(r.get("key"), str) and r.get("phase") in PHASES]


def backoff_days(tries: int, cfg: dict) -> int:
    """Days to wait before the lure opens again after `tries` empty openings:
    lure_retry_days, doubled each try, up to lure_retry_max_days (0 before any)."""
    if tries <= 0:
        return 0
    base = int(_c(cfg, "lure_retry_days") or 1)
    return int(min(int(_c(cfg, "lure_retry_max_days") or base), base * 2 ** (tries - 1)))


def _who(r: dict) -> str:
    return str(r.get("beast_name") or r.get("beast_kind") or "the beast")


def _where(r: dict) -> str:
    o = _d(r.get("opening"))
    return f"the cavern door at x{o.get('x')} y{o.get('y')}"


def _loose_beasts(s: dict) -> list:
    """The great dangers the lure is for: loose (not caged), not shut in a
    pocket, in the caverns (on a cavern tile; a forgotten beast anywhere)."""
    L = _d(s.get("lures"))
    held = set(_l(L.get("held_beasts")))
    out = []
    for b in _l(L.get("beasts")):
        if not isinstance(b, dict) or b.get("caged") or b.get("id") in held:
            continue
        if b.get("cavern") or b.get("kind") == "forgotten beast":
            out.append(b)
    return out


def _sealed_days(s: dict):
    rec = _d(_d(_d(s.get("threats")).get("sealed")).get(ALL_CAVERNS))
    days = rec.get("days")
    return days if _num(days) else None


def _squads_win(s: dict, memory, cfg: dict, beast: dict) -> tuple[bool, str]:
    """(fight, words): the squads could take it and reach it (then no lure)."""
    able = [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict) and can_fight(q, cfg)]
    if not able:
        return False, "no squad able to fight"
    reach = any(isinstance(x, dict) and x.get("id") == beast.get("id") and x.get("can_reach_dwarves") is True
                for x in _l(_d(s.get("deep")).get("dangers")))
    try:
        from planner_military import fight_or_hide
        th = {str(o.get("id")): o for o in _l(_d(s.get("others_on_map")).get("threats")) if isinstance(o, dict)}
        fight, verdict = fight_or_hide(s, memory, cfg, [th.get(str(beast.get("id"))) or {"name": beast.get("name"),
                                                                                          "id": beast.get("id")}],
                                       able)
    except Exception:  # noqa: BLE001
        return False, "the squads' strength can't be judged"
    if fight and reach:
        return True, verdict
    return False, verdict if not fight else "the squads could take it but can't get at it (the caverns are sealed)"


def _archer_post(s: dict, r: dict, cfg: dict, proposals: list, notes: list) -> None:
    """(optional) Crossbows behind a fortification that looks into the pocket:
    an entrance of the siege report with posts within 8 tiles of it, on its
    level. None: the beast stays shut in."""
    o = _d(r.get("opening"))
    ents = [e for e in _l(_d(s.get("siege")).get("entrances")) if isinstance(e, dict) and int(e.get("posts") or 0) > 0
            and e.get("z") == o.get("z") and _num(e.get("x")) and _num(o.get("x"))
            and max(abs(e["x"] - o["x"]), abs(e.get("y", 0) - o.get("y", 0))) <= 8]
    if not ents or not player_rules(s).get("archer_posts", True):
        notes.append(f"{_who(r)} is shut in the lure pocket behind {_where(r)}: no fortification looks into it, "
                     "so it stays shut in")
        return
    from planner_core import is_ranged
    free = [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict) and is_ranged(q)
            and can_fight(q, cfg) and not q.get("ai_orders") and not (q.get("orders") or 0)]
    if not free:
        notes.append(f"{_who(r)} is shut in the lure pocket: no crossbow squad free to post at the fortifications")
        return
    e = ents[0]
    proposals.append(Proposal("lure_archer", {"type": "archer_post", "entrance_id": e["id"],
                                              "squads": [q["id"] for q in free][:6]},
                              f"{_who(r)} is shut in the lure pocket: crossbows behind the fortifications at "
                              f"x{e.get('x')} y{e.get('y')} to shoot it", 2))


def _lure_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    L = s.get("lures")
    if not isinstance(L, dict) or "error" in L or not isinstance(L.get("lures"), list):
        return
    on = player_rules(s).get("lure_beasts", True) is not False
    now = abs_tick(s)
    mem = getattr(memory, "lure", None) if memory is not None else None
    if not isinstance(mem, dict):
        mem = {}
        if memory is not None:
            memory.lure = mem
    rows = lure_rows(s)
    for k in [k for k in mem if k not in {r["key"] for r in rows}]:
        mem.pop(k, None)
    cave_n = int(L.get("cavern_citizens") or 0)
    open_max = int(_c(cfg, "lure_open_days") or 3) * TICKS_PER_DAY
    active = False
    for r in rows:
        key, ph = r["key"], r["phase"]
        m = mem.setdefault(key, {})
        if m.get("phase") != ph:
            m["phase"], m["since"] = ph, now
        who, where = _who(r), _where(r)
        if m.get("beast") != r.get("beast_id"):
            # another beast for this pocket: its tries start again
            m.update({"beast": r.get("beast_id"), "tries": 0})
            m.pop("next_try", None)
        shut = lambda why, p=0: proposals.append(Proposal("lure_shut", {"type": "lure_shut", "opening": key},  # noqa: E731
                                                          why, p))
        if r.get("open"):
            active = True
            if not isinstance(m.get("opened"), int):
                m["opened"] = now
            open_ticks = r.get("open_ticks") if _num(r.get("open_ticks")) else now - m["opened"]
            if not on:
                shut(f"luring beasts is off on the Rules tab: {where} locked again")
            elif cave_n:
                shut(f"{cave_n} citizen(s) went down into the caverns while the lure is open: {where} locked again")
            elif int(r.get("citizens_near") or 0):
                shut(f"a citizen is in or beside the lure pocket behind {where}: locked again")
            elif ph == "caught" or r.get("caught"):
                m["caught"] = r.get("beast_id")
                shut(f"{who} is caught in a cage in the lure pocket: {where} locked again (it stays caged)")
            elif r.get("beast_in_pocket") and r.get("immune"):
                shut(f"{who} is inside the lure pocket: its mouth raised behind it, {where} locked again")
            elif r.get("beast_gone"):
                shut(f"{who} is gone: {where} locked again")
            elif open_ticks >= open_max:
                m["tries"] = int(m.get("tries") or 0) + 1
                wait = backoff_days(m["tries"], cfg)
                m["next_try"] = now + wait * TICKS_PER_DAY
                shut(f"the lure behind {where} was open {open_ticks // TICKS_PER_DAY} day(s) and {who} didn't come: "
                     f"locked again, opened again in {wait} day(s) (try {m['tries']})", 2)
            else:
                notes.append(f"the lure behind {where} is open for {who}: "
                             f"{'cage traps wait' if not r.get('immune') else 'its mouth is raised once it is in'}")
            continue
        m.pop("opened", None)
        if ph in ("caught", "shut_in"):
            # caught or inside with the door locked already: marked done (the bridge notes it)
            if ph == "caught":
                m["caught"] = r.get("beast_id")
            shut(f"{who} is {'caught in a cage' if ph == 'caught' else 'shut in'} in the lure pocket behind "
                 f"{where}: the lure is done", 1)
            active = True
            continue
        if ph == "done":
            how = _d(r.get("done")).get("how")
            if how == "caught":
                m["caught"] = r.get("beast_id")
                notes.append(f"{who} was caught in a cage by the lure behind {where}: it stays caged (the AI "
                             "never lets it out)")
            elif how == "shut_in":
                _archer_post(s, r, cfg, proposals, notes)
            continue
        if ph == "building":
            active = True
            if on:
                proposals.append(Proposal("lure_build", {"type": "build_lure", "opening": key},
                                          f"the lure pocket behind {where} for {who}: its next step "
                                          f"({int(r.get('pieces_built') or 0)} of {int(r.get('pieces') or 0)} "
                                          "pieces done)", 3))
            continue
        if ph == "ready":
            if r.get("beast_gone") or r.get("beast_id") is None:
                continue
            active = True
            if not on:
                continue
            nt = m.get("next_try")
            if isinstance(nt, int) and now < nt:
                notes.append(f"the lure behind {where} waits {max(1, (nt - now) // TICKS_PER_DAY)} more day(s) "
                             f"before it opens again for {who}")
                continue
            inner, mouth = _d(r.get("inner")), r.get("mouth")
            if not inner.get("shut") or (isinstance(mouth, dict) and not mouth.get("shut")):
                shut(f"the lure pocket behind {where} is built: its gates shut before it opens", 2)
                continue
            if cave_n:
                notes.append(f"the lure behind {where} is ready; {cave_n} citizen(s) are in the caverns: it opens "
                             "once they are out")
                continue
            if int(r.get("citizens_near") or 0):
                notes.append(f"the lure behind {where} is ready; a citizen is in or beside the pocket: it opens "
                             "once they've gone")
                continue
            proposals.append(Proposal("lure_open", {"type": "lure_open", "opening": key},
                                      f"{who} sits in the sealed caverns: open {where} into the lure pocket "
                                      f"({'cage traps' if not r.get('immune') else 'its mouth raised behind it'}; "
                                      "the pocket's inner gate shut)", 1))
    if active or not on:
        return
    # a new lure: a great danger sealed in the caverns long enough
    beasts = _loose_beasts(s)
    if not beasts:
        return
    days = _sealed_days(s)
    if days is None:
        return
    after = int(_c(cfg, "lure_after_days") or 7)
    beast = beasts[0]
    who = str(beast.get("name") or beast.get("kind") or "a great beast")
    if days < after:
        notes.append(f"{who} is sealed in the caverns ({days} day(s)): a lure pocket is built after {after}")
        return
    win, words = _squads_win(s, memory, cfg, beast)
    if win:
        notes.append(f"{who}: the squads can take it ({words}): no lure")
        return
    cands = [c for c in _l(L.get("candidates")) if isinstance(c, dict) and c.get("fits") and c.get("key")]
    done = {r["key"] for r in rows if r["phase"] == "done" or r.get("beast_gone")}
    cands.sort(key=lambda c: (0 if c["key"] in done else 1, c["key"]))
    if not cands:
        whys = [str(c.get("why")) for c in _l(L.get("candidates")) if isinstance(c, dict) and c.get("why")]
        notes.append(f"{who} is sealed in the caverns {days} day(s), but no cavern door of the AI's has room behind "
                     "it for a lure pocket" + (f" ({whys[0]})" if whys else ""))
        return
    c = cands[0]
    need = 6 if beast.get("immune") else min(6, int(c.get("length") or 6))
    have = L.get("mechanisms")
    if _num(have) and have < need:
        notes.append(f"{who} is sealed in the caverns: a lure pocket needs {need} mechanism(s), {have} free "
                     "(the mechanics make more)")
        return
    trap = "drawbridges on levers (traps don't catch it)" if beast.get("immune") else "cage traps"
    proposals.append(Proposal("lure_build", {"type": "build_lure", "opening": c["key"], "beast": beast.get("id")},
                              f"{who} has sat {days} day(s) in the sealed caverns and the squads can't settle it "
                              f"({words}): a lure pocket behind the cavern door at x{c.get('x')} y{c.get('y')} "
                              f"with {trap}", 3))

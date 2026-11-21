"""(R2 h3) Building slots: what holds them, and what is never starved of one.

The bridge refuses a new level with "already N unfinished building projects"
past its cap (lua/ai-builder-projects.lua slot_cap). The audit (A1 4, A3 B3,
R-CE): levels held slots for years on one missing piece (E's two Millstone
levels 500-640 days, F's bedrooms 711 days on one bed and one box), while the
paper shop, a mood's workshops, homes, the metal works and wells were refused
by that very cap, again and again.

  * _park_rule       a level being furnished that has waited on the same
                     pieces for `h3_park_days` is parked (park_project): it
                     stays open, its pieces still ordered (the building rule's
                     furniture orders read every open level), and holds no
                     slot until one of them comes (its waiting list changes:
                     the bridge counts it again). Pieces nothing in the fort
                     makes are taken off and the level finished (finish_project
                     give_up with `drop`), and so are those that never came in
                     `h3_park_drop_days`: the reason names them.
  * _dig_check_rule  a level with no tile dug for `h3_dig_check_days`: are its
                     tiles designated, can a dwarf reach where it starts, is
                     there a miner, is the alarm keeping them in? Given up at
                     once (its spot kept off-limits) when no dwarf can reach
                     any of its waiting tiles; said otherwise (the dig rules
                     unstick it: priority, freed jobs, marker tiles made real).
  * needs_pass       the small needs (a paper shop, a mood's workshops, a
                     still or a kitchen while drink or meals are short)
                     marked `need`: the bridge gives them a pool of their own
                     (NEED_SLOTS), outside the ordinary cap; a well
                     (place_well) is always one, and a strange mood's
                     workshops (`mood`, R1 g6) too: one pool, one number.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import TICKS_PER_DAY, Proposal, abs_tick

__all__ = ["furnish_sig", "HANDLED_KINDS", "KEEP_KINDS", "need_of", "needs_pass", "_park_rule", "_dig_check_rule",
           "need_slots_free", "slots_rules"]

# Pieces some rule of the AI orders or makes for a waiting level (planner_building's
# FURNITURE_RECIPES, the restraints' chains, the statues' decor_only finish, the
# workshops' give-up, the well rule's parts and lids, the slabs and benches)
HANDLED_KINDS = {"Bed", "Door", "Table", "Chair", "Cabinet", "Box", "Statue", "Armorstand", "Weaponrack",
                 "Coffin", "Bookcase", "Chain", "Workshop", "Furnace", "Well", "Hatch", "Slab", "TractionBench",
                 "Cage"}
# never taken off however long they wait (a well without its well, a lid over a shaft)
KEEP_KINDS = {"Well", "Hatch"}


def furnish_sig(fur: dict) -> str:
    """A level's missing pieces in one word, as the bridge writes it ("Bed:1,Box:1")."""
    sig = _d(fur).get("sig")
    if isinstance(sig, str):
        return sig
    keys = [f"{k}:{int(n)}" for k, n in _d(_d(fur).get("waiting")).items()
            if isinstance(n, (int, float)) and not isinstance(n, bool) and n > 0]
    return ",".join(sorted(keys))


def _kinds(sig: str) -> list[str]:
    return [x.split(":", 1)[0] for x in sig.split(",") if x]


def _open(s: dict) -> list:
    return [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]


def need_slots_free(s: dict) -> int:
    """Free places in the small needs' pool (0 from an older bridge that has none)."""
    n = _d(s.get("projects")).get("need_slots_free")
    return n if isinstance(n, int) and not isinstance(n, bool) else 0


def _park_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    if memory is None:
        return
    now = abs_tick(s)
    seen = memory.furnish_seen if isinstance(memory.furnish_seen, dict) else {}
    memory.furnish_seen = seen
    live = set()
    busy = {_d(p.action).get("project_id") for p in proposals
            if _d(p.action).get("type") in ("finish_project", "cancel_project", "furnish_project")}
    for p in _open(s):
        if p.get("phase") != "furnish" or not isinstance(p.get("id"), int) or isinstance(p.get("id"), bool):
            continue
        fur = _d(p.get("furnish"))
        sig = furnish_sig(fur)
        if not sig:
            continue
        k = str(p["id"])
        live.add(k)
        rec = seen.get(k)
        if not isinstance(rec, dict) or rec.get("sig") != sig or not isinstance(rec.get("tick"), int):
            seen[k] = {"sig": sig, "tick": now}
            continue
        days = max(0, (now - rec["tick"]) // TICKS_PER_DAY)
        what = f"the {p.get('kind')} level (project {p['id']})"
        kinds = _kinds(sig)
        pieces = sig.replace(":", " ").replace(",", ", ")
        if p["id"] in busy:
            continue                    # another rule finishes or gives it up this cycle
        if p.get("parked") is True:
            pdays = p.get("parked_days") if isinstance(p.get("parked_days"), int) else days
            unmade = sorted(x for x in kinds if x not in HANDLED_KINDS)
            if unmade and set(kinds) <= set(unmade):     # (a waiting workshop: the 0.105.51 give-up's, at its age)
                proposals.append(Proposal("slots", {"type": "finish_project", "project_id": p["id"], "give_up": True,
                                                    "drop": unmade},
                                          f"{what} has waited {days} days for {pieces}; nothing in the fort makes "
                                          f"{', '.join(unmade)}: take {'it' if len(unmade) == 1 else 'them'} off "
                                          "the level and finish it", 4))
            elif (pdays >= int(cfg["h3_park_drop_days"]) and not set(kinds) & KEEP_KINDS):
                proposals.append(Proposal("slots", {"type": "finish_project", "project_id": p["id"], "give_up": True,
                                                    "drop": sorted(kinds)},
                                          f"{what} has waited {days} days for {pieces}, ordered and never come: "
                                          f"take {', '.join(sorted(kinds))} off the level and finish it", 4))
            else:
                notes.append(f"{what} waits apart for {pieces} ({days} days): it holds no building slot; "
                             "it takes one again when they come")
            continue
        if days >= int(cfg["h3_park_days"]):
            proposals.append(Proposal("slots", {"type": "park_project", "project_id": p["id"], "sig": sig},
                                      f"{what} has waited {days} days for the same pieces ({pieces}): it stops "
                                      "holding a building slot and waits apart (its pieces stay ordered; it takes a "
                                      "slot again when they come)", 4))
    for k in list(seen):
        if k not in live:
            del seen[k]


REACH_WORDS = ("can't reach", "no open ground beside it")


def _dig_check_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """A level with nothing dug for h3_dig_check_days (memory.dig_seen: the dig
    rule's last progress), checked: given up when no dwarf can reach any of its
    waiting tiles, else said why (the dig rules unstick it)."""
    if memory is None or not isinstance(memory.dig_seen, dict):
        return
    now = abs_tick(s)
    lb = _d(s.get("labor"))
    miners = lb.get("miners") if isinstance(lb.get("miners"), int) else None
    taken = {_d(p.action).get("project_id") for p in proposals
             if _d(p.action).get("type") in ("cancel_project", "furnish_project")}
    for p in _open(s):
        if p.get("phase") != "dig" or not isinstance(p.get("id"), int) or p.get("kind") in ("well", "way_in"):
            continue
        dig = _d(p.get("dig"))
        dug, total = int(dig.get("dug") or 0), int(dig.get("total") or 0)
        if dug or total <= 0 or p["id"] in taken:
            continue
        rec = _d(memory.dig_seen.get(str(p["id"])))
        if not isinstance(rec.get("tick"), int):
            continue
        days = (now - rec["tick"]) // TICKS_PER_DAY
        if days < int(cfg["h3_dig_check_days"]):
            continue
        what = f"the {p.get('kind')} level (project {p['id']}: 0 of {total} tiles dug in {days} days)"
        waiting = [str(w) for w in _l(dig.get("waiting"))]
        left = total - int(dig.get("stuck") or 0) - int(dig.get("marked") or 0)
        if waiting and all(any(r in w for r in REACH_WORDS) for w in waiting):
            proposals.append(Proposal("slots", {"type": "cancel_project", "project_id": p["id"], "unreached": True},
                                      f"{what}: no dwarf can reach where its digging starts ({waiting[0]}): give "
                                      "it up and keep off that spot a while, so its building slot goes to what waits",
                                      4))
        elif left <= 0:
            notes.append(f"{what}: none of its tiles is designated for digging any more: it is given up "
                         "(marker tiles are made real first)")
        elif miners == 0:
            notes.append(f"{what}: the fort has no miner: it waits for the labour rule to name one")
        elif s.get("civ_alert") is True:
            notes.append(f"{what}: the alarm keeps the miners in the shelter: it waits for the alarm")
        elif not int(dig.get("digging") or 0):
            notes.append(f"{what}: its tiles are designated, but no dig job has been made for them: "
                         "it is raised to the front of the digging")


def need_of(s: dict, cfg: dict, p: Proposal, memory=None) -> str | None:
    """The small need a proposal's new level or well is for, or None."""
    a = _d(p.action)
    t = a.get("type")
    if t != "start_project":        # (a well is the bridge's own small need: place_well takes the pool)
        return None
    if a.get("kind") != "workshops":
        return None
    if a.get("mood") is True:
        return None                 # the bridge reads a mood's shop as that need itself (R1 g6's `mood`)
    if p.rule in ("mood", "mood_reserve", "mood_help"):
        return "mood"
    if p.rule == "paper_shop":
        return "paper"
    added = set(_l(a.get("added_shops")))
    shops = [x for x in _l(a.get("shops")) if x not in added]
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 0))
    if shops == ["Still"]:
        from planner_farms import drink_below_target
        if drink_below_target(s, citizens, cfg, memory):
            return "drink"
    if shops == ["Kitchen"]:
        meals = _d(s.get("stocks")).get("prepared_meals")
        if isinstance(meals, (int, float)) and meals < citizens * float(cfg.get("meals_per_dwarf") or 0):
            return "meals"
    return None


def needs_pass(s: dict, cfg: dict, proposals: list, memory=None) -> None:
    """Marks each small need's new level or well (`need`), after every rule."""
    for p in proposals:
        if "need" in _d(p.action):
            continue
        need = need_of(s, cfg, p, memory)
        if need:
            p.action = dict(p.action, need=need)


def slots_rules(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """The slot rules (planner._project_rules' neighbours), each guarded by the caller."""
    _park_rule(s, memory, cfg, proposals, notes)
    _dig_check_rule(s, memory, cfg, proposals, notes)

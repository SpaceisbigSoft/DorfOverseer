"""(0.105.40, phase 13e performance) World cleanup: what slows the game down
over years of unattended play and no dwarf can clean up, taken off the map
only past thresholds.

The `cleanup` report (lua/ai-cleanup.lua) counts the items by state, the
items no citizen's walk group reaches and for how long, the loose refuse,
the spatter on the map (inside the fort's built-up areas and outside), the
dead units on the game's active list (and how many are long dead and
unreferenced), the hostile and wild creatures no citizen can reach and for
how long, and the blocks with flowing liquid. The bridge walks them in
slices of its own budget, one full pass a game day at most.

Dwarves first: loose refuse, forbidden clutter, the dump and the dead are
the existing rules' (planner_industry _disposal_rules and _clutter_rules:
the refuse and dump standing orders, burial, prune_remains, remove_webs,
scrub_dead_units). This rule takes only what no dwarf can:

  * cleanup_spatter: blood and the like outside the fort's areas (mud and
    snow kept); inside too only while the game runs slowly and the whole map
    holds very many;
  * cleanup_dead_units: dead units dead a year and referred to by nothing,
    off the game's active list (as DFHack's fix/dead-units);
  * cleanup_items: items no citizen has reached for a year, oldest first, in
    batches (never artifacts, named, owned, stored or the player's things,
    nothing a mood or a job needs: the bridge's own checks);
  * cleanup_units (Rules `world_cleanup` at 'full' only): hostile or wild
    creatures that are no historical figure, unreachable a season.

Each past its threshold (planner_config cleanup_*), divided by
cleanup_slow_factor while the game runs slowly; the item threshold grows
with the items on the map. The first time per kind the call is a dry run
(a trial: it counts and removes nothing); the journal says what it found,
and before every real deletion the overseer writes a journal line.

The Rules switch `world_cleanup`: off (nothing), safe (the default:
spatter, dead units, items), full (and creatures). Without a `cleanup`
section in the report (an older bridge), or before its first full pass,
nothing here proposes or says anything.
"""

from __future__ import annotations

import math

from digest import _d, _l
from planner_core import Proposal, abs_tick, player_rules

__all__ = ["CLEANUP_ACTIONS", "CLEANUP_LEVELS", "cleanup_report", "cleanup_thresholds", "_world_cleanup_rule",
           "note_cleanup", "cleanup_journal", "cleanup_line", "cleanup_words"]

# the action type -> its kind (the rule is cleanup_<kind>, its trial cleanup_<kind>_dry)
CLEANUP_ACTIONS = {"cleanup_spatter": "spatter", "cleanup_dead_units": "dead", "cleanup_items": "items",
                   "cleanup_units": "units"}
# the Rules switch -> the kinds it allows
CLEANUP_LEVELS = {"off": (), "safe": ("spatter", "dead", "items"), "full": ("spatter", "dead", "items", "units")}
JOURNAL_MAX = 12


def _int(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def cleanup_report(s: dict) -> dict | None:
    """The bridge's cleanup section after a full pass, or None (an older
    bridge, a failed section, or no pass finished yet)."""
    c = s.get("cleanup")
    if not isinstance(c, dict) or not c or "error" in c or c.get("partial"):
        return None
    if not isinstance(c.get("items"), dict) or not isinstance(c.get("units"), dict):
        return None
    return c


def _slow(s: dict) -> bool:
    return bool(s.get("fps_low"))


def cleanup_thresholds(s: dict, cfg: dict, c: dict) -> dict:
    """The counts past which each kind is cleaned: lower while the game runs
    slowly (cleanup_slow_factor); the items' grows with the items on the map."""
    f = cfg["cleanup_slow_factor"] if _slow(s) else 1
    total = _int(_d(c.get("items")).get("total"))
    items = max(cfg["cleanup_items_min"], cfg["cleanup_items_share"] * total)
    return {"spatter": math.ceil(cfg["cleanup_spatter_min"] / f),
            "spatter_all": math.ceil(cfg["cleanup_spatter_all_min"] / f),
            "dead": math.ceil(cfg["cleanup_dead_min"] / f),
            "items": math.ceil(items / f),
            "units": math.ceil(cfg["cleanup_units_min"] / f)}


def _seen(memory) -> dict:
    if memory is None:
        return {}
    if not isinstance(getattr(memory, "cleanup_seen", None), dict):
        memory.cleanup_seen = {}
    return memory.cleanup_seen


def _world_cleanup_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None,
                        rules: dict | None = None) -> None:
    """(0.105.40) What no dwarf can clean up, past its threshold (see the module)."""
    c = cleanup_report(s)
    if c is None:
        return
    rules = rules or player_rules(s)
    allowed = CLEANUP_LEVELS.get(rules.get("world_cleanup", "safe"), ())
    if not allowed:
        return
    th = cleanup_thresholds(s, cfg, c)
    dry = _d(_seen(memory).get("dry"))
    slow = _slow(s)
    why_slow = " while the game runs slowly" if slow else ""

    def propose(kind: str, action: dict, reason: str, prio: int = 7) -> None:
        if kind not in allowed:
            return
        if kind not in dry:
            proposals.append(Proposal(f"cleanup_{kind}_dry", {**action, "dry_run": True},
                                      "a trial first (counts, removes nothing): " + reason, prio))
        else:
            proposals.append(Proposal(f"cleanup_{kind}", action, reason, prio))

    it, un = _d(c.get("items")), _d(c.get("units"))
    sp = _d(c.get("spatter"))
    # spatter: outside the fort's areas first; inside too only while slow
    out_n, all_n = _int(sp.get("outside")), _int(sp.get("events"))
    if out_n >= th["spatter"]:
        propose("spatter", {"type": "cleanup_spatter", "scope": "outside",
                            "budget_ms": cfg["cleanup_spatter_budget_ms"]},
                f"{out_n} spatters (blood, vomit...) lie outside the fort's areas{why_slow}, past "
                f"{th['spatter']}: cleaned off the map's blocks (mud and snow kept)")
    elif slow and all_n >= th["spatter_all"]:
        propose("spatter", {"type": "cleanup_spatter", "scope": "all",
                            "budget_ms": cfg["cleanup_spatter_budget_ms"]},
                f"{all_n} spatters on the map while the game runs slowly, past {th['spatter_all']}: cleaned "
                "inside the fort too (mud and snow kept)")
    # dead units long dead and unreferenced, off the active list
    dead = _int(un.get("dead_removable"))
    if dead >= th["dead"]:
        propose("dead", {"type": "cleanup_dead_units", "min_age": cfg["cleanup_dead_age_ticks"]},
                f"{dead} of the {_int(un.get('dead_active'))} dead on the game's active list died over a year ago "
                f"and nothing refers to them{why_slow} (past {th['dead']}): taken off the list (the fort's own "
                "dead, ghosts and anyone in a squad or burrow are kept)")
    # items no citizen has reached for a year
    old = _int(it.get("unreachable_old"))
    if old >= th["items"]:
        batch = min(cfg["cleanup_items_batch"], 500)
        propose("items", {"type": "cleanup_items", "max": batch, "min_age": cfg["cleanup_items_age_ticks"]},
                f"{old} of the {_int(it.get('total'))} items on the map lie where no citizen has reached for a "
                f"year{why_slow} (past {th['items']}): the oldest {batch} deleted (never artifacts, named, owned, "
                "stored, the player's or what a mood or job needs)")
    # creatures no citizen can reach (full only)
    ucount = _int(un.get("unreachable_old"))
    if ucount >= th["units"]:
        if "units" in allowed:
            propose("units", {"type": "cleanup_units", "max": cfg["cleanup_units_batch"],
                              "min_age": cfg["cleanup_units_age_ticks"]},
                    f"{ucount} hostile or wild creatures no citizen can reach have been out of reach a season"
                    f"{why_slow} (past {th['units']}): vaporized (never citizens, pets, tame, visitors, "
                    "merchants, prisoners or historical figures)", 8)
        else:
            notes.append(f"{ucount} hostile or wild creatures no citizen can reach have been out of reach a "
                         "season; the Rules' World cleanup at 'full' would remove them")


def _kind_of(action: dict) -> str | None:
    return CLEANUP_ACTIONS.get(_d(action).get("type"))


def cleanup_words(action: dict, result: dict | None = None) -> str:
    """One line on a cleanup call (the journal's)."""
    a, r = _d(action), _d(result)
    kind = _kind_of(a)
    what = {"spatter": "spatters", "dead": "dead units' records", "items": "unreachable items",
            "units": "unreachable creatures"}.get(kind, "things")
    if result is None:
        return f"about to remove {what} ({a.get('type')}, {', '.join(f'{k}={v}' for k, v in sorted(a.items()) if k != 'type')})"
    if a.get("dry_run"):
        n = r.get("would_remove")
        return f"trial: {n if n is not None else 0} {what} would go" + (
            f" (kept: {', '.join(f'{k} {v}' for k, v in sorted(_d(r.get('kept')).items()))})" if r.get("kept") else "")
    return f"removed {_int(r.get('removed'))} {what}" + (" (more left)" if r.get("more") else "")


def note_cleanup(p, r: dict, state: dict, memory, now: int | None = None) -> None:
    """After a cleanup call: the trial marked done for its kind (a real call
    follows), the count removed, a journal line queued (cleanup_journal)."""
    kind = _kind_of(getattr(p, "action", None))
    if kind is None or memory is None:
        return
    r = _d(r)
    now = abs_tick(state) if now is None else now
    seen = _seen(memory)
    if p.action.get("dry_run"):
        if r.get("ok") is True:
            seen.setdefault("dry", {})[kind] = now
    elif r.get("ok") is True:
        removed = seen.setdefault("removed", {})
        removed[kind] = _int(removed.get(kind)) + _int(r.get("removed"))
    if r.get("ok") is not None:
        j = seen.setdefault("journal", [])
        j.append({"what": kind, "action": p.action, "ok": r.get("ok"), "text": cleanup_words(p.action, r)})
        del j[:-JOURNAL_MAX]


def cleanup_journal(memory) -> list:
    """The journal entries waiting (each written once)."""
    seen = _seen(memory)
    out = [e for e in _l(seen.get("journal")) if isinstance(e, dict)]
    seen["journal"] = []
    return out


def cleanup_line(s: dict) -> str:
    """The digest's CLEANUP line, or "" without a cleanup section."""
    c = s.get("cleanup")
    if not isinstance(c, dict) or not c or "error" in c or not isinstance(c.get("items"), dict):
        return ""
    it, un, sp = _d(c.get("items")), _d(c.get("units")), _d(c.get("spatter"))
    ur = _d(un.get("unreachable"))
    level = player_rules(s)["world_cleanup"] if isinstance(s.get("settings"), dict) else "safe"
    return (f"CLEANUP ({level}{', first pass under way' if c.get('partial') else ''}) items {_int(it.get('total'))}"
            f" on_ground {_int(it.get('on_ground'))} unreachable {_int(it.get('unreachable'))}"
            f" (a year: {_int(it.get('unreachable_old'))}) refuse_loose {_int(it.get('refuse_loose'))}"
            f" | spatter {_int(sp.get('events'))}{'+' if sp.get('capped') else ''} (outside {_int(sp.get('outside'))})"
            f" | dead on the active list {_int(un.get('dead_active'))} (old, unreferenced {_int(un.get('dead_removable'))})"
            f" of {_int(un.get('all'))} units | out of reach: hostile {_int(ur.get('hostile'))} wild {_int(ur.get('wild'))}"
            f" (a season: {_int(un.get('unreachable_old'))}) | flowing blocks {_int(_d(c.get('fluids')).get('blocks'))}")


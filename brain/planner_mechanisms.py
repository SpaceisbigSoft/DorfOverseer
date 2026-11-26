"""(0.105.119 item30) Enough free mechanisms for every lever link waiting.

Journal, 25 Nov 15:00-18:30: every lever link was starved. A's were cells
were refused 33 times ("a link needs 2 free mechanisms (1 free; 1 where no
dwarf can walk)"), E's "(1 free; 1 an artifact)", D's gate lever 22 times
and its kill zone 12 ("(0 free)"). Each rule that wants mechanisms orders
only its own few, and only while no mechanisms order at all is queued, so
the spare rule's order of 2 kept the rest quiet while buildingplan took
what was made: the drawbridge were cells stood unlinked and A's werepanther
outbreak (16:38, y253) killed 25.

The rule (_mechanism_stock_rule, after every rule that orders mechanisms):
  * what is wanted, in order: the were cells (2 a built lever not yet
    linked, 3 a cell whose lever is not built: the lever and its link; 3 a
    cell of a were_cells level still being dug), the gates (2 a drawbridge
    no lever works, and a lever for each beyond the free AI levers), the
    kill zones (2 a built drawbridge not linked), (item6) the cavern way
    (2 for its gate's link, 1 more before its lever is placed), the rest (what
    buildingplan's waiting buildings lack);
  * what there is: the free mechanisms (the bridge's mechanisms_free: not in
    a building, not encased, not an artifact, where a dwarf can walk), the
    queued orders, and the mechanisms orders other rules propose this cycle;
  * short: `make mechanisms` for the shortfall and a reserve
    (`mechanism_reserve`), at most `mechanism_order_max` at once; urgent
    while a werebeast citizen is known; never more than the boulders of
    ordinary stone there are (DF: "Needs non-economic hard stone boulders"),
    and short of them a quarry, whatever other digging waits. No Mechanic's
    workshop: one dug and
    built (the workshops level, as the wells' parts); nobody with the
    Mechanics labour: it is given to a dwarf.

    python tests/test_item30_mechanisms.py
"""

from __future__ import annotations

from digest import _d, _l
from planner_leisure import _int  # (r6 c2) the same positive count, not a second copy
from planner_core import PLANNER_CONFIG, Proposal, _has_shop, _workshops_busy, free_stock, queued

__all__ = ["MECHANISM_CONFIG", "mechanism_demand", "mechanism_supply", "_mechanism_stock_rule"]

MECHANISM_CONFIG = {
    "mechanism_reserve": 4,                  # (0.105.119 item30) kept free beyond the links waiting
    "mechanism_order_max": 15,               # ...ordered at most this many at once
    "mechanism_stock_cooldown_ticks": 1200,  # ...a day apart
}
PLANNER_CONFIG.update({k: v for k, v in MECHANISM_CONFIG.items() if k not in PLANNER_CONFIG})

LINK = 2          # a lever's link takes two mechanisms
LEVER = 1         # a lever is built of one


def _werebeasts(s: dict) -> list:
    w = _d(_d(s.get("threats")).get("were"))
    return [x for x in _l(w.get("list")) if isinstance(x, dict) and x.get("id") is not None]


def _were_need(s: dict) -> tuple[int, str]:
    w = _d(_d(s.get("threats")).get("were"))
    wc = _d(w.get("were_cells"))
    n, built, unlinked = _int(wc.get("n")), _int(wc.get("built")), _int(wc.get("unlinked"))
    need = unlinked * LINK + max(0, n - built) * (LEVER + LINK)
    bits = []
    if unlinked:
        bits.append(f"{unlinked} lever(s) to link")
    if n > built:
        bits.append(f"{n - built} cell(s) still to build")
    if n == 0:
        # a were_cells level being dug: its levers and links come next
        for p in _l(_d(s.get("projects")).get("open")):
            if isinstance(p, dict) and p.get("kind") == "were_cells":
                k = _int(p.get("cells")) or 3
                need += k * (LEVER + LINK)
                bits.append(f"{k} cell(s) being dug")
    return need, ", ".join(bits)


def _gate_need(s: dict, bridges: set) -> tuple[int, str]:
    from planner_gates import _free_gate_levers, _link_wanted
    want = 0
    for e in _l(_d(s.get("entrances")).get("entrances")):
        if not isinstance(e, dict):
            continue
        for bid in _link_wanted(s, e, None, hatches=False):
            if bid not in bridges:
                bridges.add(bid)
                want += 1
    if not want:
        return 0, ""
    levers = len(_free_gate_levers(s))
    need = want * LINK + max(0, want - levers) * LEVER
    return need, f"{want} drawbridge(s) no lever works"


def _killzone_need(s: dict, bridges: set) -> tuple[int, str]:
    from planner_killzone import _rows, killzones_of
    want = 0
    for e in _rows(killzones_of(s)):
        br = _d(e.get("drawbridge"))
        if br.get("built") and br.get("linked") is False and br.get("id") not in bridges:
            bridges.add(br.get("id"))
            want += 1
    return want * LINK, (f"{want} kill-zone drawbridge(s) to link" if want else "")


# (item6, R32 e) the cavern way's states before its lever is linked, and
# whether its lever (one mechanism) is still to be placed
CAVERN_WAY_BEFORE_LINK = {"dig": True, "digging": True, "lever": True, "lever_building": False, "hatch": False,
                          "hatch_building": False, "link": False}


def _cavern_way_need(s: dict) -> tuple[int, str]:
    """(item6, R32 e) The guarded cavern way's gate link (2) and, before its
    lever is placed, the lever's own (D: "2 free mechanisms are needed for the
    link" 69 times, nothing ordered them)."""
    from planner_cavern_way import cavern_way
    w = cavern_way(s)
    st = w.get("state") if w else None
    if st not in CAVERN_WAY_BEFORE_LINK:
        return 0, ""
    n = LINK + (LEVER if CAVERN_WAY_BEFORE_LINK[st] else 0)
    have = w.get("mechanisms")
    if st == "link" and isinstance(have, int) and not isinstance(have, bool) and have < LINK:
        # the stock's free ones the way's link can't use (the bridge counts those a
        # linker may take): not supply for it
        n += max(0, free_stock(s, "mechanisms") - have)
    return n, ("its gate's lever link" if st == "link" else f"its lever and link to come ({st.replace('_', ' ')})")


def _planned_need(s: dict) -> tuple[int, str]:
    from planner_building_stores import planned_wants
    n = _int(planned_wants(s).get("mechanism"))
    return n, (f"{n} for planned buildings" if n else "")


def mechanism_demand(s: dict) -> list:
    """[(what, mechanisms, words)] for the links and levers waiting, were
    cells first, then the gates, the kill zones and the rest."""
    bridges: set = set()
    out = []
    for what, fn in (("were cells", lambda: _were_need(s)), ("gates", lambda: _gate_need(s, bridges)),
                     ("kill zones", lambda: _killzone_need(s, bridges)),
                     ("the cavern way", lambda: _cavern_way_need(s)), ("the rest", lambda: _planned_need(s))):
        try:
            n, words = fn()
        except Exception:  # noqa: BLE001  (one part unreadable leaves the others)
            continue
        if n > 0:
            out.append((what, n, words))
    return out


def mechanism_supply(s: dict, proposals: list) -> tuple[int, int, int]:
    """(free, queued, proposed this cycle by other rules)."""
    proposed = sum(_int(_d(p.action).get("amount")) or 1 for p in proposals
                   if _d(p.action).get("type") == "work_order" and _d(p.action).get("recipe") == "mechanisms")
    return max(0, free_stock(s, "mechanisms")), queued(s, {"mechanisms"}), proposed


def _stone_for_mechanisms(s: dict):
    """The boulders a mechanic may use (DF: "Needs non-economic hard stone
    boulders"): the stone report's usable count, None when not reported."""
    su = _d(s.get("stone_use"))
    v = su.get("usable")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _quarry_for_links(s: dict, cfg: dict, memory, proposals: list, notes: list, stone: int, short: int,
                      what: str) -> None:
    """(item30, D 25 Nov) No stone for the mechanisms: a quarry, whatever other
    digging waits (D had 1,395 tiles queued, 3 usable boulders, every other
    boulder ore: the stone rule's quarry waits for the digging, and only
    comes with none usable at all), paced by the stone rule's own wait."""
    if any(_d(p.action).get("type") == "quarry" for p in proposals):
        return
    from planner_industry_stone import quarry_size, quarry_wait
    wait = quarry_wait(s, memory, cfg)
    if wait:
        notes.append(f"mechanisms for the lever links ({what}) wait for stone: {wait}")
        return
    proposals.append(Proposal("quarry", {"type": "quarry", "count": quarry_size(s, cfg)},
                              f"{short} mechanisms wanted for the lever links ({what}) and only {stone} boulders "
                              "of ordinary hard stone (DF makes them of nothing else; the rest is ore or "
                              "economic): dig a small quarry in ordinary stone near the fort", 3 if short else 4))


def _mechanism_stock_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    demand = mechanism_demand(s)
    if not demand:
        return
    need = sum(n for _, n, _ in demand)
    free, on_order, proposed = mechanism_supply(s, proposals)
    target = need + int(cfg.get("mechanism_reserve", 4))
    short = target - free - on_order - proposed
    if short <= 0:
        return
    were = _werebeasts(s)
    urgent = bool(were)
    prio = 2 if urgent else 5
    what = "; ".join(f"{w}: {n} ({words})" if words else f"{w}: {n}" for w, n, words in demand)
    b = _d(s.get("buildings"))
    if not _has_shop(b, "Mechanics"):
        if "workshops" not in b:
            return                          # no workshop list (older bridge): nothing known
        open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
        if _workshops_busy(open_):
            notes.append(f"{need} mechanisms wanted ({what}): made at a Mechanic's workshop once the workshops "
                         "being dug are done")
            return
        action = {"type": "start_project", "kind": "workshops", "shops": ["Mechanics"]}
        if urgent:
            action["urgent"] = True
        proposals.append(Proposal("mechanism_stock", action,
                                  f"{need} mechanisms wanted ({what}) and no Mechanic's workshop to make "
                                  "them: dig and build one", prio))
        return
    holders = _d(_d(s.get("order_desk")).get("labor_holders"))
    if "MECHANIC" in holders and not _int(holders.get("MECHANIC")):
        proposals.append(Proposal("mechanism_stock", {"type": "assign_labor", "job": "MECHANIC", "count": 1},
                                  f"{need} mechanisms wanted ({what}) and nobody with the Mechanics labour: "
                                  "the labour given to a dwarf", prio))
        return
    amount = min(short, int(cfg.get("mechanism_order_max", 15)))
    # (item30, D 25 Nov) DF makes mechanisms only of non-economic hard stone:
    # D's orders sat at "5 left" four times ("cancels Make rock mechanisms:
    # Needs non-economic hard stone boulders"), every boulder but 3 an ore.
    # Never more than the stone there is; short of stone, a quarry
    stone = _stone_for_mechanisms(s)
    if stone is not None and stone < amount:
        _quarry_for_links(s, cfg, memory, proposals, notes, stone, short, what)
        if stone < LINK:
            notes.append(f"{need} mechanisms wanted ({what}) and {stone} boulders of ordinary stone: none "
                         "ordered until the quarry brings some")
            return
        amount = stone
    lead = (f"werebeast citizen(s) ({', '.join(str(x.get('name')) for x in were[:2])}) and their cells' "
            "links wait: " if urgent and demand[0][0] == "were cells" else "")
    proposals.append(Proposal("mechanism_stock", {"type": "work_order", "recipe": "mechanisms", "amount": amount},
                              f"{lead}the lever links want {need} mechanisms ({what}); {free} free, "
                              f"{on_order + proposed} on order: make {amount} at the Mechanic's workshop "
                              f"(with {int(cfg.get('mechanism_reserve', 4))} kept spare)", prio, True))

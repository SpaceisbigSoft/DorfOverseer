"""(0.105.41, item 2) Wheelbarrows for the AI's stone piles, and the AI's
feeder piles linked to the workshops they feed.

The coverage audit's "should" list: stone is the heaviest thing dwarves
carry, and a stockpile's own wheelbarrows (its max wheelbarrows setting)
are what haulers push it in with; a workshop linked to the pile beside it
takes its materials from that pile only, so the walk is the pile's few
tiles (DF wiki, Stockpile; Workshop).

The `pile_links` report (lua/ai-pile-links.lua): the fort's wheelbarrows
(owned, held by a pile, free, in a job, wanted by every pile's setting and
by the AI's own piles), the AI's own stone piles (tiles, max wheelbarrows,
held), and the AI's feeder piles (place_feeder's, remembered with their
workshop): linked or why not, links only, the pile's used tiles, the
workshop's jobs and those being worked, days empty or idle while linked.

  * barrows: one AI stone pile a cycle (the biggest first) whose max
    wheelbarrows is under what it wants (one per barrow_tiles_per tiles,
    1..barrow_pile_max, never past its tiles - 1) is set to it, while the
    AI's piles want no more than barrow_ai_min or one per
    barrow_citizens_per citizens. Never in a young fort; never the
    player's piles (the bridge refuses them too). Only raised, never lowered.
  * barrow_order: the piles' unmet want (every pile's max wheelbarrows less
    those held) more than the free ones, those in a job and those ordered:
    the rest made at a carpenter's (barrow_order_max at most), when the
    Rules tab orders supplies and no other rule orders wheelbarrows this cycle.
  * feeder_link (Rules: link_feeders): a linked feeder whose pile has
    stood empty feeder_starve_days, or whose workshop has had work and
    nobody at it feeder_idle_days, while it has work, is unlinked (the
    bridge then never links that workshop again); else one AI feeder a
    cycle beside an AI workshop of FEEDER_LINK_KINDS, with no link the
    player made and something in the pile, is linked (feeder_links_only:
    fed from the AI's bigger pile of its kind on its level when there is
    one, taking from links only).

Without a `pile_links` section nothing here proposes or says anything.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import AGENDA_THEMES, Proposal, _has_shop, queued, young_fort

__all__ = ["FEEDER_LINK_KINDS", "pile_links", "barrows_want", "_pile_links_rule", "pile_links_line"]

# the workshops whose feeder is linked (each uses one material, any of it; the
# bridge's LINKABLE adds the leatherworks, loom and clothier's)
FEEDER_LINK_KINDS = ("Masons", "Carpenters", "WoodFurnace")

AGENDA_THEMES.update({"barrows": "shorten the hauling", "barrow_order": "shorten the hauling",
                      "feeder_link": "shorten the hauling"})


def _int(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def pile_links(s: dict) -> dict | None:
    """The `pile_links` section, or None when it is missing or failed."""
    p = s.get("pile_links")
    if not isinstance(p, dict) or not p or p.get("error"):
        return None
    return p


def barrows_want(tiles: int, cfg: dict) -> int:
    """The wheelbarrows an AI stone pile of `tiles` tiles wants."""
    if tiles < cfg["barrow_pile_min_tiles"]:
        return 0
    n = max(1, tiles // max(1, cfg["barrow_tiles_per"]))
    return max(0, min(n, cfg["barrow_pile_max"], tiles - 1))


def _barrows(p: dict, s: dict, cfg: dict, citizens: int, proposals: list) -> None:
    b = _d(p.get("barrows"))
    cap = max(cfg["barrow_ai_min"], citizens // max(1, cfg["barrow_citizens_per"]))
    have = _int(b.get("ai_wanted"))
    if have >= cap:
        return
    # the AI's own feeder piles (beside a workshop) take no wheelbarrows: a
    # barrow there would bring a load to a pile that feeds one workshop
    for r in sorted((r for r in _l(p.get("stone_piles")) if isinstance(r, dict) and isinstance(r.get("id"), int)
                     and not r.get("feeder")),
                    key=lambda r: (-_int(r.get("tiles")), r["id"])):
        cur = _int(r.get("barrows"))
        want = min(barrows_want(_int(r.get("tiles")), cfg), cur + cap - have)
        if want > cur:
            proposals.append(Proposal("barrows", {"type": "pile_barrows", "pile_id": r["id"], "barrows": want},
                                      f"the AI's stone pile at x{r.get('x1')} y{r.get('y1')} ({_int(r.get('tiles'))} "
                                      f"tiles) takes {cur} wheelbarrows: let it take {want}, so stone comes in "
                                      "barrows", 7))
            return


def _barrow_order(p: dict, s: dict, cfg: dict, proposals: list) -> None:
    if any(_d(x.action).get("recipe") == "wheelbarrow" for x in proposals):
        return                       # the hauling rule orders them this cycle
    b = _d(p.get("barrows"))
    unmet = _int(b.get("wanted")) - _int(b.get("assigned"))
    coming = _int(b.get("free")) + _int(b.get("in_job")) + queued(s, {"wheelbarrow"})
    need = min(unmet - coming, cfg["barrow_order_max"])
    if need <= 0 or not _has_shop(s.get("buildings") or {}, "Carpenters"):
        return
    if _int(_d(s.get("stocks")).get("wood")) < cfg["barrow_order_wood_min"]:
        return
    proposals.append(Proposal("barrow_order", {"type": "work_order", "recipe": "wheelbarrow", "amount": need},
                              f"the stockpiles want {unmet} more wheelbarrows than they hold and {_int(b.get('free'))} "
                              f"are free: make {need}", 7, True))


def _feeder_links(p: dict, cfg: dict, proposals: list) -> None:
    rows = [r for r in _l(p.get("feeders")) if isinstance(r, dict) and isinstance(r.get("pile_id"), int)]
    for r in rows:
        if not r.get("linked") or _int(r.get("jobs")) <= 0:
            continue
        empty, idle = r.get("empty_days"), r.get("idle_days")
        why = (f"its pile has stood empty {empty} days" if isinstance(empty, int) and empty >= cfg["feeder_starve_days"]
               else f"nobody has worked there {idle} days" if isinstance(idle, int) and idle >= cfg["feeder_idle_days"]
               else None)
        if why:
            proposals.append(Proposal("feeder_link", {"type": "feeder_link", "pile_id": r["pile_id"], "unlink": True},
                                      f"the {r.get('kind')} linked to its feeder has work waiting and {why}: unlink it, "
                                      "so it takes from any pile again", 5))
            return
    for r in rows:
        if (r.get("linked") or r.get("why") or r.get("unlinked") or r.get("kind") not in FEEDER_LINK_KINDS
                or _int(r.get("used")) <= 0):
            continue
        only = bool(cfg["feeder_links_only"]) and isinstance(r.get("main"), int)
        a = {"type": "feeder_link", "pile_id": r["pile_id"]}
        if only:
            a["links_only"] = True
        proposals.append(Proposal("feeder_link", a,
                                  f"the {r.get('kind')}'s feeder pile at x{r.get('x')} y{r.get('y')} is not linked: "
                                  "link it, so the workshop takes from the pile beside it"
                                  + (" (fed from the AI's bigger pile, links only)" if only else ""), 7))
        return


def _pile_links_rule(s: dict, cfg: dict, citizens: int, proposals: list, rules_: dict) -> None:
    p = pile_links(s)
    if p is None:
        return
    if not young_fort(s, cfg):
        _barrows(p, s, cfg, citizens, proposals)
        if rules_.get("order_supplies", True):
            _barrow_order(p, s, cfg, proposals)
    if rules_.get("link_feeders", True):
        _feeder_links(p, cfg, proposals)


def pile_links_line(s: dict) -> str:
    """The wheelbarrows and feeder links in a line for the digest; "" without
    a pile_links section."""
    p = pile_links(s)
    if p is None:
        return ""
    b = _d(p.get("barrows"))
    feeders = [r for r in _l(p.get("feeders")) if isinstance(r, dict)]
    linked = sum(1 for r in feeders if r.get("linked"))
    stone = [r for r in _l(p.get("stone_piles")) if isinstance(r, dict)]
    return (f"PILES wheelbarrows {_int(b.get('owned'))} owned, {_int(b.get('assigned'))} in piles, "
            f"{_int(b.get('free'))} free, piles want {_int(b.get('wanted'))} (AI's {_int(b.get('ai_wanted'))})"
            f" | AI stone piles {len(stone)}"
            f" | AI feeders {len(feeders)}: {linked} linked, {_int(p.get('unlinked'))} unlinked")

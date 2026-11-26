"""planner_leisure (0.105.82): soldiers short of what only time off gives.

B "Monastery", 23 Nov: 20-34% truly idle civilians kept all four squads on
constant training ("many idle hands": planner_military); 20 of 20 dwarves
missing drink and 13 of 13 merriment were soldiers, 28 miserable, dwarves
strangling dwarves. While a fifth of the soldiers badly miss these, the
squads take turns off instead.
"""

from __future__ import annotations

from digest import _d

__all__ = ["LEISURE_NEEDS", "COMPANY_NEEDS", "soldiers_short_of_leisure", "friends_counted", "squad_shortage",
           "company_short", "squad_mostly_short", "inside_few", "war_leisure_rule"]

# (BeWithFriends left out: it wants friends, not time off; 54 of 59 soldiers in happy A miss it)
# (0.105.97) ...unless the fort is unhappy (friends_counted): B, 23 Nov, 76 of
# 88 badly wanting friends, 37 of them soldiers, 40% unhappy, 29 killed by
# fellow citizens; friends are made where the others are, off duty
LEISURE_NEEDS = ("DrinkAlcohol", "MakeMerry", "Socialize", "PrayOrMeditate", "TakeItEasy")
# (0.105.97) what the recreation burrow gives a soldier off duty: the
# taverns, the temples, the others
COMPANY_NEEDS = ("BeWithFriends", "DrinkAlcohol", "PrayOrMeditate")


# (r6 c2) kept local: a positive count only (0 for none, a bool or a negative)
def _int(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


def _soldiers(s: dict) -> int:
    return _int(_d(s.get("dwarves")).get("in_squads"))


def _short_line(s: dict, cfg: dict, sol: int) -> float:
    return max(int(cfg.get("leisure_starved_soldiers", 3)), sol * float(cfg.get("leisure_starved_share", 0.2)))


def friends_counted(s: dict, cfg: dict) -> bool:
    """(0.105.97) Does BeWithFriends count as a soldier's leisure need? Only in
    a fort unhappy past `unhappy_wide_share` (a fifth): happy A had 54 of 59
    soldiers missing friends and nothing wrong; B (40% unhappy) lost 29 to
    fellow citizens."""
    from planner_society import unhappy_wide
    return unhappy_wide(s, cfg)


def soldiers_short_of_leisure(s: dict, cfg: dict) -> str:
    """(0.105.82) The leisure need most soldiers badly miss, when at least
    `leisure_starved_soldiers` (3) and `leisure_starved_share` (a fifth) of
    the soldiers do ("" otherwise, or with no per-soldier counts): their
    squads get turns off rather than all training for the idle civilians."""
    needs = _d(_d(s.get("needs")).get("needs"))
    sol = _soldiers(s)
    if not sol:
        return ""
    best, n = "", 0
    for k in LEISURE_NEEDS:
        b = _d(needs.get(k)).get("badly_soldiers")
        if isinstance(b, int) and not isinstance(b, bool) and b > n:
            best, n = k, b
    if n >= _short_line(s, cfg, sol):
        best_ok = best
    else:
        best_ok = ""
    # (0.105.97) friends too, in an unhappy fort, from their own share
    # (`leisure_friends_share`, a third of the soldiers)
    f = _int(_d(needs.get("BeWithFriends")).get("badly_soldiers"))
    if (f > (n if best_ok else 0) and f >= max(int(cfg.get("leisure_starved_soldiers", 3)),
                                               sol * float(cfg.get("leisure_friends_share", 1 / 3)))
            and friends_counted(s, cfg)):
        return "BeWithFriends"
    return best_ok


def squad_shortage(s: dict) -> dict:
    """(0.105.97) Each squad's members and how many badly miss friends, drink
    or prayer (`short`) and drink or prayer alone (`short_np`): the bridge's
    society.recreation.squads ({} from an older bridge). Keys are squad ids."""
    out = {}
    for k, v in _d(_d(_d(s.get("society")).get("recreation")).get("squads")).items():
        v = _d(v)
        try:
            out[int(k)] = {"n": _int(v.get("n")), "short": _int(v.get("short")), "short_np": _int(v.get("short_np"))}
        except (TypeError, ValueError):
            continue
    return out


def company_short(s: dict, cfg: dict) -> int:
    """(0.105.97) The soldiers badly missing friends, drink or prayer (friends
    only while friends_counted) when they are `leisure_starved_soldiers` (3)
    and `leisure_starved_share` (a fifth) of the soldiers, else 0. From the
    squads' own counts when the bridge gives them (one soldier counted once),
    else the most missing any one of those needs. While it is nonzero, at most
    half the squads train at a time, a squad most of whom are short rests a
    turn more, and off-duty soldiers get places in the recreation burrow."""
    sol = _soldiers(s)
    if not sol:
        return 0
    friends = friends_counted(s, cfg)
    sq = squad_shortage(s)
    if sq:
        n = sum(r["short"] if friends else r["short_np"] for r in sq.values())
    else:
        needs = _d(_d(s.get("needs")).get("needs"))
        n = max([_int(_d(needs.get(k)).get("badly_soldiers")) for k in COMPANY_NEEDS
                 if friends or k != "BeWithFriends"] or [0])
    return n if n >= _short_line(s, cfg, sol) else 0


def squad_mostly_short(s: dict, cfg: dict, sid) -> bool:
    """(0.105.97) Do most of squad `sid`'s members badly miss friends (while
    counted), drink or prayer? False without the bridge's squad counts."""
    r = squad_shortage(s).get(sid)
    if not r or not r["n"]:
        return False
    return 2 * (r["short"] if friends_counted(s, cfg) else r["short_np"]) > r["n"]




def inside_few(s: dict, cfg: dict, reach: list, threats: dict) -> list:
    """(0.105.83) The ids of the enemies in reach when they are a few
    (`inside_defence_max`, 6) and every one is already inside the fort (the
    gate scan's intruders_inside, the hunt's "inside" targets, thieves and
    interrupters inside: planner_holdfast._inside_ids), fliers and wild
    animals included, none a great danger, fire breather or building
    destroyer; [] otherwise. One squad goes at them whatever the Rules tab
    says (B's ravens, 23 Nov)."""
    from planner_holdfast import _inside_ids
    ids = [i for i in reach if i is not None]
    if not ids or len(ids) > int(cfg.get("inside_defence_max", 6)):
        return []
    inside = _inside_ids(s)
    for i in ids:
        t = threats.get(i)
        if (not isinstance(t, dict) or i not in inside or t.get("great_danger") or t.get("destroyer")
                or t.get("fire_breather")):
            return []
    return ids


def war_leisure_rule(s: dict, cfg: dict, proposals: list | None, memory=None) -> None:
    """(0.105.119 item35) A militant fort's soldiers get their months off too.

    A "War-hold" (Militarism +150), 25 Nov, y253 winter to y254 winter: 59
    of 86 citizens in 7 squads, every one on constant or staggered training
    all year; the rotation and 0.105.97's leisure turns never ran (both only
    under `train_rotate_below_militarism`, 50), and the recreation burrow
    takes soldiers only from a squad resting off duty: none, all year. 28-50%
    of the fort unhappy, "unmet needs" 63-69 citizens in the stress census;
    badly missing (soldiers of all): friends 43 of 52, prayer 29 of 33, art
    35 of 35, crafting 30 of 30. The other forts, rotating, 0-9%.

    So, in a militant fort while company_short (a fifth of the soldiers
    badly miss friends in an unhappy fort, drink or prayer), no threat can
    reach the dwarves and the soldiers aren't longing to train: one of the
    AI's squads in every `war_leisure_one_in` (3) rests a month off duty,
    the shortest first (most of its members short), each at most once in
    `war_leisure_again_days` (56). The reason says "another squad trains", so
    the month off is the rotation's own (planner_record books rested_at,
    planner_military leaves it off duty a month, then trains it again, and
    sends it back at once if enemies can reach the dwarves); while it rests,
    the recreation rule gives its soldiers places among the taverns and
    temples. At least two squads and 3 soldiers (the guard) keep training.
    Config keys read with defaults (PLANNER_CONFIG is pinned by r7 d6)."""
    if proposals is None or memory is None:
        return
    from planner_core import _traits, abs_tick, player_rules, reachable_threats, TICKS_PER_DAY, Proposal
    traits = _traits(s)
    mil_ = int(traits.get("militarism", 0) or 0)
    if mil_ < int(cfg.get("train_rotate_below_militarism", 50)):
        return                                        # the rotation's own turns run there
    if not player_rules(s).get("train_squads", True) or s.get("civ_alert"):
        return
    try:
        if reachable_threats(s, traits, cfg):
            return
    except Exception:  # noqa: BLE001  (a malformed threats section: no rests)
        return
    if int(_d(s.get("dwarves")).get("total") or 0) < int(cfg.get("train_min_citizens", 15)):
        return
    short = company_short(s, cfg)
    if not short:
        return
    # the soldiers longing to train keep training (planner_military's train_all)
    mtd = _d(_d(_d(s.get("needs")).get("needs")).get("MartialTraining"))
    mts = mtd.get("badly_soldiers")
    mt = _int(mts) if isinstance(mts, int) else _int(mtd.get("badly"))
    cit = max(1, int(_d(s.get("dwarves")).get("total") or 0))
    if mt >= max(5, cit * float(cfg.get("train_all_share", 0.15))):
        return
    mil = _d(s.get("military"))
    off = next((r for r in mil.get("routines") or [] if isinstance(r, str) and "off duty" in r.lower()), None)
    if not off:
        return
    squads = [q for q in mil.get("squads") or [] if isinstance(q, dict) and q.get("id") is not None]
    ai = (set(getattr(memory, "squads_trained", None) or []) | set(getattr(memory, "squads_made", None) or [])
          | {q.get("id") for q in squads if q.get("ai_uniform")})
    mine = [q for q in squads if q["id"] in ai and _int(q.get("members")) and not q.get("ai_orders")
            and not _int(q.get("orders")) and not q.get("sheltering")]
    if len(mine) < int(cfg.get("war_leisure_min_squads", 3)):
        return
    resting = [q for q in mine if "off duty" in str(q.get("routine") or "").lower()]
    training = [q for q in mine if q not in resting]
    now = abs_tick(s)
    book = getattr(memory, "war_leisure", None)
    if not isinstance(book, dict):
        book = {}
        try:
            memory.war_leisure = book
        except Exception:  # noqa: BLE001
            pass
    again = int(cfg.get("war_leisure_again_days", 56)) * TICKS_PER_DAY
    month = int(cfg.get("train_rotate_days", 28)) * TICKS_PER_DAY
    rested = set(getattr(memory, "squads_rested", None) or [])
    for q in resting:                                 # the month off begins when it is seen off duty
        t = book.get(str(q["id"]))
        if q["id"] in rested and not (isinstance(t, int) and 0 <= now - t < month):
            book[str(q["id"])] = now
    max_off = max(1, len(mine) // max(1, int(cfg.get("war_leisure_one_in", 3))))
    if len(resting) >= max_off or len(training) < 3:
        return
    friends = friends_counted(s, cfg)
    sq = squad_shortage(s)

    def share(q):
        r = sq.get(q["id"]) or {}
        return (r.get("short") if friends else r.get("short_np")) or 0

    def recent(q):
        t = book.get(str(q["id"]))
        return isinstance(t, int) and 0 <= now - t < again

    cands = sorted((q for q in training if squad_mostly_short(s, cfg, q["id"]) and not recent(q)),
                   key=lambda q: (-share(q) / max(1, _int(q.get("members"))), book.get(str(q["id"])) or 0, q["id"]))
    still = sum(_int(q.get("members")) for q in training)
    for q in cands:
        if still - _int(q.get("members")) < 3:
            continue
        n_tr = len(training) - 1
        proposals.append(Proposal(
            "war_leisure", {"type": "squad_routine", "squad_id": q["id"], "routine": off},
            f"{q.get('name') or 'a squad'} rests a month off duty while another squad trains ({n_tr} of "
            f"{len(mine)} squads train; Militarism {mil_} trains them all, but {short} soldiers badly miss "
            f"friends, drink or prayer, {share(q)} of its {_int(q.get('members'))}): its soldiers to the "
            "taverns and temples, back to training in a month (at once if enemies come)", 4))
        return

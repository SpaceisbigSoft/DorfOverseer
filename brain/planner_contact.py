"""(r10 p3) How much contact the fort has with the world: initial contact for
every fort, then the AI's choice by the fort's character and the situation.

The player, 22 Nov 00:51: "all forts should make at least some initial
contact with nearby towns/forts/etc, but then the AI should decide how much
contact and what type of contact they should have including raids. hermit
hold should make initial contacts but then only make contact with others
when the AI decides its fitting for the current situations".

  * initial contact (every fort and preset, the Hermit hold too): once a
    messenger holds the post, Make contact goes to the nearest sites people
    live in that the fort isn't in contact with (the missions report's
    `sites.nearest`: towns, hamlets, forts, halls, retreats, camps, towers of
    other civs), nearest first, at most `contact_initial_max`, those within
    `contact_initial_tiles` (and always the nearest one), one at a time,
    `contact_initial_gap_days` apart. The sender's own guards stay (the
    World screen never pressed under the player's window, one run at a
    time); never in a threat, a siege, an alarm or a crisis, never while a
    World screen of the player's is open;
  * the book (memory.world_seen["contacts"], kept in the save's working
    memory): per site its name, civ, what happened (sent, made: the site is
    in contact now, failed: DF said no or the AI gave up, tried: stopped,
    tried again) and why, initial or further, so nothing is repeated;
  * after it (`initial_done`), further contact by character: open (Outsiders
    >= contact_open_outsiders, Trade >= contact_open_trade, or Greed high with
    Trade not low: a merchant's fort) one more site every
    `contact_open_days` (half at Outsiders or Trade 100+); measured (the rest)
    one a year; closed (Outsiders <= contact_closed_outsiders: the Hermit
    hold) none as routine. Any fort, the closed one included, makes contact
    when the situation calls for it: a war to end (a site of a civ at war
    with the fort, unless the fort is aggressive or the Rules refuse peace),
    friends wanted (the fort was attacked lately or a hostile site is close,
    and it has fewer than contact_friends_min friends), or a needed trade (a
    strange mood waits for what the fort can't make, or food or drink is
    short, and no caravan came this year);
  * raids stay in brain/planner_raids.py (aggressive / reactive / timid by
    the sliders); the aggressive fort waits for initial contact before
    raiding anyone who didn't attack it (`initial_pending`).

Every choice and every hold says why in the planner's notes and the
proposal's reason (the journal). The Rules' switches stay the player's:
make_contact or send_messenger off and nothing is sent.
"""

from __future__ import annotations

from digest import _d, _l, game_text
from planner_core import PLANNER_CONFIG, TICKS_PER_DAY, TICKS_PER_YEAR, abs_tick, player_rules, _traits

__all__ = ["contact_book", "note_contacts", "contact_candidates", "initial_state", "initial_pending",
           "contact_stance", "contact_plan", "contact_hold", "last_sent_tick", "CONTACT_OPEN", "BOOK_MAX"]

CONTACT_OPEN = ("NoContact", "unknown")          # DF's site relation: not in contact (or never met)
HOSTILE = ("TotalWar", "Skirmishing")
BOOK_MAX = 20                                    # sites kept in the book at most (the oldest go first)
TRIES_MAX = 3                                    # stopped runs at one site before the AI gives up on it
FINAL = ("sent", "made", "failed")               # an initial contact that counts as done


from util import int_or_none as _int  # noqa: E402


from util import num_or_none as _num  # noqa: E402


def _trait(s: dict, k: str) -> float:
    return float(_num(_traits(s).get(k, 0)) or 0)


def contact_book(memory, create: bool = False) -> dict:
    """memory.world_seen["contacts"]: {"sites": {site id: entry}, "initial_done": tick or None}.
    An entry: n (name), c (civ), st (sent | made | failed | tried), k (initial | further), t (tick),
    why, tries, ot (the sender's outcome tick last read)."""
    ws = getattr(memory, "world_seen", None) if memory is not None else None
    if not isinstance(ws, dict):
        if not create or memory is None:
            return {"sites": {}}
        ws = memory.world_seen = {}
    b = ws.get("contacts")
    if not isinstance(b, dict):
        if not create:
            return {"sites": {}}
        b = ws["contacts"] = {}
    if not isinstance(b.get("sites"), dict):
        b["sites"] = {}
    return b


def last_sent_tick(memory) -> int | None:
    """The newest Make contact the book saw sent (any site), or None."""
    ts = [_int(_d(e).get("ot")) for e in contact_book(memory)["sites"].values()
          if _d(e).get("st") in ("sent", "made") and _int(_d(e).get("ot")) is not None]
    return max(ts) if ts else None


def _lived_in(row: dict) -> bool:
    from planner_raids import LIVED_IN
    t = row.get("type")
    return t is None or str(t) in LIVED_IN          # an older bridge gives no type: kept


def _sites(s: dict) -> list:
    return [x for x in _l(_d(_d(s.get("missions")).get("sites")).get("nearest"))
            if isinstance(x, dict) and _int(x.get("id")) is not None]


def _messenger_held(s: dict) -> bool:
    o = _d(_d(_d(s.get("offices")).get("offices")).get("MESSENGER"))
    return bool(_l(o.get("held")))


# --- the book -------------------------------------------------------------------------

def note_contacts(s: dict, memory, cfg: dict = PLANNER_CONFIG) -> None:
    """Bookkeeping before planning (planner_world.note_world): the sender's
    last Make contact outcome booked under its site, a site sent to and now
    in contact booked as made, and initial contact marked done once it is."""
    if memory is None:
        return
    book = contact_book(memory, create=True)
    sites = book["sites"]
    now = abs_tick(s)
    from planner_missions import last_of_goal, interrupted
    last = last_of_goal(_d(_d(s.get("missions")).get("send")), "make_contact")
    sid, t = _int(last.get("site_id")), _int(last.get("tick"))
    if sid is not None and t is not None:
        e = sites.get(str(sid))
        if not isinstance(e, dict) or (_int(e.get("ot")) or -1) < t:
            e = dict(e) if isinstance(e, dict) else {}
            row = next((x for x in _sites(s) if x["id"] == sid), {})
            e.setdefault("k", "initial" if book.get("initial_done") is None else "further")
            e["n"] = game_text(last.get("site") or row.get("name") or e.get("n") or f"site {sid}", 40)
            if _int(row.get("owner_civ")) is not None:
                e["c"] = row["owner_civ"]
            e["ot"], e["t"] = t, t
            res, reason = last.get("result"), last.get("reason")
            if res == "sent":
                e["st"], e["why"] = "sent", "the messenger was sent"
            elif reason in ("inaccessible", "unavailable"):
                e["st"], e["why"] = "failed", game_text(f"DF said no ({last.get('why') or reason})", 60)
            elif res in ("stopped", "error"):
                if not interrupted(last) and reason != "no_messenger":
                    e["tries"] = int(_int(e.get("tries")) or 0) + 1
                tries = int(_int(e.get("tries")) or 0)
                if tries >= TRIES_MAX:
                    e["st"], e["why"] = "failed", game_text(f"gave up after {tries} stopped tries "
                                                            f"({last.get('why') or reason})", 60)
                else:
                    e["st"], e["why"] = "tried", game_text(f"stopped ({last.get('why') or reason}); tried again", 60)
            else:
                e = None
            if e is not None:
                sites[str(sid)] = e
    # a site sent to that is in contact now: made
    for x in _sites(s):
        e = sites.get(str(x["id"]))
        if isinstance(e, dict) and e.get("st") in ("sent", "tried") and x.get("relation") not in CONTACT_OPEN:
            e["st"], e["why"] = "made", f"in contact now ({game_text(x.get('relation'), 20)})"
            e["t"] = now
    if len(sites) > BOOK_MAX:
        for k in sorted(sites, key=lambda k: _int(_d(sites[k]).get("t")) or 0)[:len(sites) - BOOK_MAX]:
            del sites[k]
    # initial contact done: the messenger home (held) and nothing left for it
    if book.get("initial_done") is None and _messenger_held(s) and isinstance(
            _d(_d(s.get("missions")).get("sites")).get("nearest"), list):
        st = initial_state(s, memory, cfg)
        if not st["candidates"] and _sites(s) and not _d(_d(_d(s.get("missions")).get("send")).get("running")):
            book["initial_done"] = now
            book["initial_words"] = (f"initial contact done: {st['done']} site(s) "
                                     + (f"({', '.join(st['names'][:4])})" if st["names"] else "")
                                     + "; further contact goes by the fort's character and the situation")


# --- the candidates -----------------------------------------------------------------------

def contact_candidates(s: dict, memory=None, cfg: dict = PLANNER_CONFIG) -> list:
    """The sites Make contact could go to now, nearest first: not in contact,
    people live there, reachable, DF never said no, not given up on, and not
    sent to lately (a site sent to and still not in contact a year later may
    be tried again)."""
    from planner_missions import unreachable_sites, unavailable_sites
    gone = unreachable_sites(s, memory) | unavailable_sites(s, "make_contact", memory)
    sites = contact_book(memory)["sites"]
    now = abs_tick(s)
    out = []
    for x in _sites(s):
        if x.get("relation") not in CONTACT_OPEN or x.get("inaccessible") or x["id"] in gone or not _lived_in(x):
            continue
        e = _d(sites.get(str(x["id"])))
        if e.get("st") == "failed":
            continue
        if e.get("st") == "sent" and 0 <= now - (_int(e.get("t")) or 0) < TICKS_PER_YEAR:
            continue
        out.append(x)
    return sorted(out, key=lambda x: (int(_int(x.get("dist")) if _int(x.get("dist")) is not None else 999), x["id"]))


def initial_state(s: dict, memory=None, cfg: dict = PLANNER_CONFIG) -> dict:
    """{done: initial contacts booked (sent, made or failed), cap, names,
    candidates: the sites initial contact still goes to, nearest first}."""
    book = contact_book(memory)
    cap = int(cfg.get("contact_initial_max", 4))
    near = int(cfg.get("contact_initial_tiles", 40))
    done = [e for e in book["sites"].values() if isinstance(e, dict) and e.get("k") == "initial"
            and e.get("st") in FINAL]
    names = [str(e.get("n")) for e in done if e.get("n")]
    left = max(0, cap - len(done))
    cands = []
    if book.get("initial_done") is None and left:
        booked = {k for k, e in book["sites"].items() if isinstance(e, dict) and e.get("st") in FINAL}
        pool = [x for x in contact_candidates(s, memory, cfg) if str(x["id"]) not in booked]
        within = [x for x in pool if (_int(x.get("dist")) or 0) <= near]
        if not within and pool and not done:
            within = pool[:1]                        # the nearest one, however far: at least some contact
        cands = within[:left]
    return {"done": len(done), "cap": cap, "names": names, "candidates": cands}


def initial_pending(s: dict, memory=None, cfg: dict = PLANNER_CONFIG) -> bool:
    """Initial contact still to make, and it can be made: the switches on, a
    messenger holds the post, a site waits."""
    rules = player_rules(s)
    if not (rules["make_contact"] and rules["send_messenger"]) or not _messenger_held(s):
        return False
    return bool(initial_state(s, memory, cfg)["candidates"])


# --- after initial contact: by character and the situation ----------------------------------

def contact_stance(s: dict, cfg: dict = PLANNER_CONFIG) -> tuple[str, str]:
    """(open | measured | closed, why in words), from Outsiders, Trade and Greed."""
    o, tr, g = _trait(s, "outsiders"), _trait(s, "trade"), _trait(s, "greed")
    if o <= cfg.get("contact_closed_outsiders", -100):
        return "closed", f"Outsiders {o:g}: a closed hold, contact only when the situation calls for it"
    if o >= cfg.get("contact_open_outsiders", 30):
        return "open", f"Outsiders {o:g}: a welcoming fort seeks out its neighbours"
    if tr >= cfg.get("contact_open_trade", 50):
        return "open", f"Trade {tr:g}: a trading fort seeks out partners"
    if g >= cfg.get("contact_open_greed", 60) and tr >= 0:
        return "open", f"Greed {g:g}: a grasping fort seeks out buyers"
    return "measured", f"Outsiders {o:g}, Trade {tr:g}: one new neighbour a year"


def _routine_days(s: dict, stance: str, cfg: dict) -> int | None:
    if stance == "open":
        d = int(cfg.get("contact_open_days", 56))
        return d // 2 if max(_trait(s, "outsiders"), _trait(s, "trade")) >= 100 else d
    if stance == "measured":
        return int(cfg.get("contact_measured_days", 336))
    return None


def _civ_names(s: dict) -> dict:
    return {_int(c.get("id")): game_text(c.get("name") or f"civ {c.get('id')}", 40)
            for c in _l(_d(s.get("world")).get("civs")) if isinstance(c, dict) and _int(c.get("id")) is not None}


def _hostile_civs(s: dict) -> set:
    return {_int(c.get("id")) for c in _l(_d(s.get("world")).get("civs"))
            if isinstance(c, dict) and (c.get("relation") in HOSTILE or c.get("hostile")) and _int(c.get("id")) is not None}


def _hostile_near(s: dict, cfg: dict) -> dict | None:
    """The nearest hostile site within raid_near_tiles (the missions report's
    sites and raid_sites), or None."""
    near = int(cfg.get("raid_near_tiles", 8))
    rows = [x for x in _sites(s) if x.get("relation") in HOSTILE]
    rows += [dict(r, id=r.get("site_id"), name=r.get("site")) for r in _l(_d(_d(s.get("missions")).get("raid_sites")).get("rows"))
             if isinstance(r, dict) and (r.get("hostile") or r.get("at_war"))]
    rows = [r for r in rows if _int(r.get("dist")) is not None and r["dist"] <= near]
    return min(rows, key=lambda r: r["dist"]) if rows else None


def _trade_need(s: dict, cfg: dict) -> str:
    """What the fort needs from a caravan now (a strange mood's material, food
    or drink short), "" when nothing pressing."""
    try:
        from planner_moods import mood_trade_wants
        mood = mood_trade_wants(s)
    except Exception:  # noqa: BLE001  (a read that fails is no need)
        mood = []
    if mood:
        return f"a strange mood waits for {game_text(str(_d(mood[0]).get('key') or 'a material'), 30).lower()}"
    try:
        from planner_trade import trade_wants
        dw = _d(s.get("dwarves"))
        wants = trade_wants(s, cfg, int(dw.get("citizens") or dw.get("total") or 0))
    except Exception:  # noqa: BLE001
        wants = []
    short = [w["key"].lower() for w in wants if isinstance(w, dict) and w.get("key") in ("FOOD", "DRINK")]
    return f"{' and '.join(short)} short" if short else ""


def _caravan_lately(s: dict, memory) -> bool:
    if any(not _d(c).get("hostile") for c in _l(_d(s.get("world")).get("caravans"))):
        return True
    ms = getattr(memory, "missions_seen", None) if memory is not None else None
    traders = _d(_d(_d(ms).get("raids")).get("traders"))
    now = abs_tick(s)
    return any(0 <= now - (_int(_d(v).get("last")) or -10 ** 9) < TICKS_PER_YEAR for v in traders.values())


def _situation(s: dict, cands: list, memory, cfg: dict) -> tuple[dict | None, str]:
    """(the site, why) the situation calls a messenger for, else (None, "")."""
    from planner_raids import raid_attackers, raid_friends, raid_stance
    names = _civ_names(s)
    hostile = _hostile_civs(s)
    stance = raid_stance(s, cfg)[0]
    # a war to end: a site of a civ at war with the fort that is not in contact
    if hostile and stance != "aggressive" and player_rules(s)["peace"] != "refuse":
        for x in cands:
            if _int(x.get("owner_civ")) in hostile:
                return x, f"a war with {names.get(x['owner_civ'], 'its civ')} to end: a messenger may open talks"
    friendly = [x for x in cands if _int(x.get("owner_civ")) not in hostile]
    if not friendly:
        return None, ""
    attackers = raid_attackers(s, memory, cfg)
    near = _hostile_near(s, cfg)
    friends = raid_friends(s, memory, {**cfg, "raid_friends_min": 0})
    if (attackers or near) and len(friends) < int(cfg.get("contact_friends_min", 2)):
        x = next((x for x in friendly if _int(x.get("owner_civ")) not in attackers), None)
        if x is not None:
            if attackers:
                cid, a = max(attackers.items(), key=lambda kv: kv[1]["year"])
                what = f"{game_text(a.get('name') or names.get(cid) or 'a civ', 40)} attacked the fort in y{a['year']}"
            else:
                what = f"a hostile site ({game_text(near.get('name') or 'a site', 40)}) is {near['dist']} tiles away"
            return x, f"{what} and the fort has {len(friends)} friend(s): it looks for more"
    need = _trade_need(s, cfg)
    if need and not _caravan_lately(s, memory):
        return friendly[0], f"{need} and no caravan came this year: a new trade partner is needed"
    return None, ""


def contact_plan(s: dict, memory=None, cfg: dict = PLANNER_CONFIG) -> dict:
    """What Make contact does now: {site, kind (initial | situation | routine),
    why, gap_days} or {site: None, held: why not}. The guards (switches, the
    messenger, threats) are the callers'."""
    st = initial_state(s, memory, cfg)
    book = contact_book(memory)
    if st["candidates"]:
        x = st["candidates"][0]
        return {"site": x, "kind": "initial", "gap_days": int(cfg.get("contact_initial_gap_days", 14)),
                "why": f"initial contact ({st['done'] + 1} of up to {st['cap']}): every fort makes itself known "
                       "to its nearest neighbours"}
    cands = contact_candidates(s, memory, cfg)
    if book.get("initial_done") is None and memory is not None and not cands:
        return {"site": None, "held": "initial contact: no site left to make contact with"}
    if not cands:
        return {"site": None, "held": "every nearby site the messenger can reach is in contact or said no"}
    stance, why_stance = contact_stance(s, cfg)
    x, why = _situation(s, cands, memory, cfg)
    if x is not None:
        return {"site": x, "kind": "situation", "why": why, "gap_days": int(cfg.get("contact_situation_days", 28))}
    days = _routine_days(s, stance, cfg)
    if days is None:
        return {"site": None, "held": f"{why_stance}: nothing calls for it now (no war to end, no attack or "
                                      "hostile site near while short of friends, no trade needed)"}
    return {"site": cands[0], "kind": "routine", "why": why_stance, "gap_days": days}


def contact_hold(s: dict, memory=None, cfg: dict = PLANNER_CONFIG) -> str:
    """Why no Make contact may go now for the situation (a threat, a siege,
    the alarm, a crisis, the player's World screen), "" when none."""
    from planner_core import reachable_threats
    if reachable_threats(s, _traits(s), cfg):
        return "a threat is near"
    if any(_d(e).get("active") for e in _l(_d(s.get("world")).get("sieges"))):
        return "a siege is on"
    if s.get("civ_alert") is True:
        return "the civilian alert is on"
    if _d(getattr(memory, "crisis", None)).get("why"):
        return "the fort is in crisis"
    ms = _d(s.get("missions"))
    if ms.get("screen") and not _d(_d(ms.get("send")).get("running")):
        return "a World screen is open (the player's): the AI never presses under it"
    return ""

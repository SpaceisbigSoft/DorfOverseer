"""(0.105.47, J17) The raid policy: whom the fort may attack, by its character.

The player, 14 Nov 17:47: "War-holds [should] potentially attack any
others, but still allow for some allies. Other fort types should still allow
for the option of raiding, but be less hostile and more reactionary, or if
some other hostile towns are setting up nearby be able to deal with that."

The policy is the AI's choice inside the Rules' `missions` = 'all'; the Army
tab's `raid_policy` (ai / aggressive / reactive / off, (0.105.48) the default) can force
it. With 'ai' the sliders decide (the presets just fall out of them):

  * aggressive (Militarism >= raid_aggressive_militarism, the War-hold): any
    civ's reachable site, hostile or not, but never a friend: its own civ
    (never in the lists), an ally, a civ with a peace pending or tribute
    agreed, one whose caravan is here or has traded with the fort, and at
    least raid_friends_min (Outsiders: one more when high, one fewer when
    very low) kept from the civs at peace with the most trade. The weakest
    site the squads clearly beat first (Greed high: the richest), then the
    nearest;
  * reactive (everyone else): (a) retaliation, a civ that attacked the fort
    (a siege, thieves, an ambush: DF's invasions of this site, the AI's
    grudge list) within raid_retaliate_years, at its nearest reachable site
    the squads clearly beat; (b) a threat close by, a hostile (or ownerless:
    bandits) site within raid_near_tiles, or one that appeared since the AI
    began watching within raid_new_tiles, removed before it grows. Never a
    civ at peace that hasn't attacked;
  * timid (Militarism <= raid_timid_militarism, the Monastery): (a) only with
    a sure win (raid_ratio_timid), (b) only within raid_timid_tiles;
  * off: no raid, pillage, tribute or conquest.

Every policy: one offensive mission at a time (the missions rule), a season
between two (raid_cooldown_days), the reserve kept (sendable_squads), the
matchup: the squads' power against the site's strength (its residents, its
type) at raid_ratio (+ Caution) or better. The target's `why` says plainly
why it was chosen; `policy` goes to the bridge, which allows a raid on a civ
that isn't hostile only for these reasons (lua/ai-bridge-actions.lua).

Pets (live 17:38: a raid squad waited at the map edge for a sheep kept in
an AI pasture and a peafowl): `pets_of_squads()` reads the missions
report's `pets` (lua/ai-raids.lua): a pet held in the AI's own zone is let
out for the trip (mission_pets release) and put back once home (restore);
a squad whose soldier's pet is held where the AI can't let it out (a cage,
a chain, the player's zone) stays home and the soldier is swapped out.
"""

from __future__ import annotations

from digest import _d, _l, game_text
from planner_core import PLANNER_CONFIG, TICKS_PER_DAY, abs_tick, player_rules, _traits

__all__ = ["raid_stance", "raid_friends", "raid_attackers", "contact_civs", "LIVED_IN", "site_strength", "squads_power", "raid_candidates",
           "raid_choice", "last_offensive_tick", "note_raids", "pets_of_squads", "stuck_pets", "releasable_pets",
           "pet_words", "restore_due", "RAID_POLICIES", "RAIDS_SWITCH", "SITE_WEIGHT"]

RAID_POLICIES = ("ai", "aggressive", "reactive", "off")
RAIDS_SWITCH = 'the Army tab\'s "Raids"'
HOSTILE = ("TotalWar", "Skirmishing")
OFFENSIVE = ("tribute", "raid", "pillage", "conquer")
# how much a site's people count, by its type (a dark fortress holds trolls and
# beasts, a camp a few bandits)
SITE_WEIGHT = {"DarkFortress": 1.5, "Fortress": 1.3, "MountainHalls": 1.3, "Town": 1.2, "ForestRetreat": 1.1,
               "Hamlet": 0.9, "Camp": 0.8, "LairShrine": 1.5, "Cave": 1.0, "Tower": 1.6, "ImportantLocation": 1.0}
SITE_WORDS = {"Camp": "camp", "DarkFortress": "dark fortress", "Fortress": "fortress", "MountainHalls": "hold",
              "Town": "town", "ForestRetreat": "forest retreat", "Hamlet": "hamlet", "LairShrine": "lair",
              "Cave": "cave", "Tower": "tower"}
SIGHTS_MAX = 300          # sites remembered (first seen) at most
# (0.105.48, K9) the site types people live in: the only ones raided (the
# audit: 1210 of this world's 1429 sites are monuments of unknown civs, and
# the aggressive rule sent the War-hold to a tomb). A Monument, a lair, a
# cave or an important location is never a raid's target.
LIVED_IN = ("Town", "Hamlet", "Fortress", "DarkFortress", "MountainHalls", "ForestRetreat", "Camp", "Tower")


from util import num_or_none as _num  # noqa: E402  (r6 c2) was a copy here


from util import int_or_none as _int  # noqa: E402  (r6 c2) was a copy here


def _trait(s: dict, k: str) -> float:
    v = _num(_traits(s).get(k, 0)) or 0
    return float(v)


def _world(s: dict) -> dict:
    return _d(s.get("world"))


def _seen(memory) -> dict:
    """memory.missions_seen["raids"] (read only here; note_raids writes it)."""
    ms = getattr(memory, "missions_seen", None) if memory is not None else None
    return _d(_d(ms).get("raids"))


# --- the stance ---------------------------------------------------------------------

def raid_stance(s: dict, cfg: dict = PLANNER_CONFIG) -> tuple[str, str]:
    """(aggressive | reactive | timid | off, why in words)."""
    rp = player_rules(s).get("raid_policy", "off")
    if rp == "off":
        return "off", f"{RAIDS_SWITCH} is off"
    if rp == "aggressive":
        return "aggressive", f"{RAIDS_SWITCH} is aggressive"
    if rp == "reactive":
        return "reactive", f"{RAIDS_SWITCH} strikes back only"
    m = _trait(s, "militarism")
    if m >= cfg.get("raid_aggressive_militarism", 100):
        return "aggressive", f"Militarism {m:g}: the fort attacks any but its friends"
    if m <= cfg.get("raid_timid_militarism", -50):
        return "timid", f"Militarism {m:g}: the fort strikes back only with a sure win"
    return "reactive", f"Militarism {m:g}: the fort strikes back and clears threats close by"


# --- friends and attackers ------------------------------------------------------------

def raid_friends(s: dict, memory=None, cfg: dict = PLANNER_CONFIG) -> dict:
    """civ id -> why it is a friend (never raided by the aggressive fort)."""
    w = _world(s)
    civs = [c for c in _l(w.get("civs")) if isinstance(c, dict) and _int(c.get("id")) is not None]
    out: dict = {}
    for c in civs:
        if c.get("allies"):
            out[c["id"]] = "an ally"
        elif c.get("peace_offered"):
            out[c["id"]] = "a peace pending"
        elif c.get("tribute") or c.get("relation") in ("AcceptingTribute", "OfferingTribute"):
            out[c["id"]] = "tribute agreed"
    for car in _l(w.get("caravans")):
        car = _d(car)
        if _int(car.get("civ_id")) is not None and not car.get("hostile") and car["civ_id"] not in out:
            out[car["civ_id"]] = "its caravan is here"
    traders = _d(_seen(memory).get("traders"))
    for k, v in traders.items():
        if str(k).lstrip("-").isdigit() and int(k) not in out:
            out[int(k)] = f"traded with ({int(_d(v).get('n') or 1)} caravan(s))"
    need = int(cfg.get("raid_friends_min", 2))
    o = _trait(s, "outsiders")
    need += 1 if o >= 50 else (-1 if o <= -100 else 0)
    need = max(1, need)
    if len(out) < need:
        sieges = {_int(_d(e).get("id")): int(_d(e).get("n") or 0) for e in _l(w.get("sieges"))}
        cands = [c for c in civs if c["id"] not in out and c.get("relation") not in HOSTILE
                 and not c.get("hostile") and not sieges.get(c["id"])]
        cands.sort(key=lambda c: (-int(_d(traders.get(str(c["id"]))).get("n") or 0),
                                  0 if c.get("relation") == "Peace" else 1, c["id"]))
        for c in cands[:need - len(out)]:
            out[c["id"]] = "kept as a friend (at peace, the most contact)"
    return out


def raid_attackers(s: dict, memory=None, cfg: dict = PLANNER_CONFIG) -> dict:
    """civ id -> {year, siege, name}: the civs that attacked the fort (DF's
    invasions of this site: sieges, thieves, ambushes; the grudge list)
    within raid_retaliate_years."""
    year = _int(_d(s.get("date")).get("year"))
    keep = int(cfg.get("raid_retaliate_years", 3))
    out: dict = {}

    def take(cid, y, siege, name):
        if cid is None or y is None or y < 0:
            return
        if year is not None and year - y > keep:
            return
        old = out.get(cid)
        if old is None or y > old["year"]:
            out[cid] = {"year": y, "siege": siege, "name": name or (old or {}).get("name")}
    for e in _l(_world(s).get("sieges")):
        e = _d(e)
        take(_int(e.get("id")), _int(e.get("last_year")), e.get("last_siege"), e.get("name"))
    ws = getattr(memory, "world_seen", None) if memory is not None else None
    for k, v in _d(_d(ws).get("grudges")).items():
        if str(k).lstrip("-").isdigit():
            take(int(k), _int(_d(v).get("last_year")), None, _d(v).get("name"))
    return out


def _attack_words(a: dict) -> str:
    kind = "the siege" if a.get("siege") is True else ("the thieves or ambush" if a.get("siege") is False
                                                       else "the attack")
    return f"{kind} of y{a['year']}"


# --- strength -------------------------------------------------------------------------

def site_strength(row: dict, cfg: dict = PLANNER_CONFIG) -> float:
    """A site's strength in squad-power units: base + per resident (capped),
    weighted by its type. Unknown residents: raid_unknown_pop. (0.105.48, K9)
    0 residents at a lived-in type is unknown too (DF's resident_count is
    first_calc_total_pop: maybe 0 for a site never loaded)."""
    pop = _int(row.get("pop"))
    if pop is None or (pop <= 0 and str(row.get("type") or "") in LIVED_IN):
        pop = int(cfg.get("raid_unknown_pop", 60))
    pop = min(max(0, pop), int(cfg.get("raid_resident_cap", 200)))
    w = SITE_WEIGHT.get(str(row.get("type") or ""), 1.0)
    return (float(cfg.get("raid_site_base", 4.0)) + float(cfg.get("raid_resident_power", 0.5)) * pop) * w


def squads_power(squads) -> float:
    return sum(float(_num(_d(_d(q).get("power")).get("power")) or 0) for q in squads or [])


def _need_ratio(s: dict, stance: str, cfg: dict) -> float:
    r = float(cfg.get("raid_ratio_timid", 3.0) if stance == "timid" else cfg.get("raid_ratio", 2.0))
    c = max(0.0, min(200.0, _trait(s, "caution")))
    return r + float(cfg.get("raid_ratio_caution", 0.5)) * c / 100


# --- the candidates ---------------------------------------------------------------------

def _site_words(row: dict) -> str:
    kind = SITE_WORDS.get(str(row.get("type") or ""), "site")
    return f"{game_text(row.get('site') or 'site ' + str(row.get('site_id')), 40)} ({kind})"


def _rows(s: dict, extra=None) -> tuple[list, bool]:
    """(the rows a raid could go to, known: the report gave raid_sites).
    raid_sites rows as raids; the targets list's offensive rows (hostile
    sites) keep their goal and borrow the residents of the same site."""
    ms = _d(s.get("missions"))
    rs = ms.get("raid_sites")
    known = isinstance(rs, dict) and isinstance(rs.get("rows"), list)
    by_site = {}
    out = []
    for r in _l(_d(rs).get("rows")):
        if isinstance(r, dict) and _int(r.get("site_id")) is not None:
            e = dict(r)
            e["goal"] = "raid"
            by_site[e["site_id"]] = e
            out.append(e)
    for t in extra or []:
        if not isinstance(t, dict) or _int(t.get("site_id")) is None:
            continue
        e = dict(t)
        b = by_site.get(e["site_id"])
        if b:
            for k in ("pop", "type", "bandit", "owner_id"):
                e.setdefault(k, b.get(k))
            if e["goal"] == "raid":
                out.remove(b)               # one row per site and goal
        out.append(e)
    return out, known


def _raidable(r: dict) -> bool:
    """(0.105.48, K9) A site people live in and not known to be empty."""
    if str(r.get("type") or "") not in LIVED_IN:
        return False
    pop = _int(r.get("pop"))
    return pop is None or pop > 0          # None: unknown (the bridge reads 0 as unknown); 0: an older bridge


def contact_civs(s: dict, memory=None) -> dict:
    """(0.105.48, K9) civ id -> the site the fort is making contact with: the
    site Make contact names now, the messenger's mission out, its last send
    within a year. Never raided (the audit: the War-hold was proposed to raid
    Peacemine, the site its messenger had just been sent to)."""
    from planner_core import TICKS_PER_YEAR
    ms = _d(s.get("missions"))
    civ_of: dict = {}
    for x in _l(_d(ms.get("sites")).get("nearest")):
        x = _d(x)
        if _int(x.get("id")) is not None and _int(x.get("owner_civ")) is not None:
            civ_of.setdefault(x["id"], set()).add(x["owner_civ"])
    for r in _l(_d(ms.get("raid_sites")).get("rows")):
        r = _d(r)
        if _int(r.get("site_id")) is not None:
            for k in ("civ_id", "owner_id"):
                if _int(r.get(k)) is not None:
                    civ_of.setdefault(r["site_id"], set()).add(r[k])
    sites: list = []
    try:
        from planner_world import _contact_site, _messenger_out
        c = _contact_site(s, memory)
        if c is not None:
            sites.append(c.get("id"))
        sites += [_d(c).get("site_id") for c in _messenger_out(ms)]
    except Exception:  # noqa: BLE001  (a missing part never opens a raid; the rest still counts)
        pass
    from planner_missions import last_of_goal
    last = last_of_goal(_d(ms.get("send")), "make_contact")
    t = _int(last.get("tick"))
    if t is not None and 0 <= abs_tick(s) - t < TICKS_PER_YEAR:
        sites.append(last.get("site_id"))
    out: dict = {}
    for sid in sites:
        for cid in civ_of.get(_int(sid), ()):
            out.setdefault(cid, sid)
    return out


def _civ_relation(s: dict, cid, row: dict | None = None):
    """DF's relation with a civ: the world report's civs, else the row's."""
    for c in _l(_world(s).get("civs")):
        if isinstance(c, dict) and _int(c.get("id")) == cid and c.get("relation"):
            return c.get("relation")
    return _d(row).get("relation")


def raid_candidates(s: dict, cfg: dict = PLANNER_CONFIG, memory=None, squads=None, extra=None) -> tuple[list, list, str]:
    """(candidates best first, words on what was passed over, the stance).
    A candidate: the row with goal, policy, why, need, ratio."""
    stance, why_stance = raid_stance(s, cfg)
    if stance == "off":
        return [], [why_stance], stance
    rows, known = _rows(s, extra)
    if squads is None:
        from planner_missions import sendable_squads
        squads = sendable_squads(s, cfg)[0]
    power = squads_power(squads)
    need_ratio = _need_ratio(s, stance, cfg)
    sights = _d(_seen(memory).get("sites"))
    base = _int(_seen(memory).get("since"))
    passed: list = []
    out: list = []

    def clear(r) -> tuple[bool, float, float]:
        need = site_strength(r, cfg)
        ratio = power / max(1.0, need)
        # (r9, audit A8 #23) no raid_sites (lua/ai-raids failed to load): the
        # site's strength isn't known, so it is never "clearly beaten" (before:
        # the matchup was skipped and a 0.67x squad passed)
        return known and ratio >= need_ratio, need, ratio
    attackers = raid_attackers(s, memory, cfg) if stance != "aggressive" else {}
    # (0.105.48, K9) only sites people live in; never the civ the messenger is making contact with
    if not known and rows:
        passed.append("the sites' sizes couldn't be read (no raid_sites): no raid until they can")
    empty = [r for r in rows if not _raidable(r)]
    rows = [r for r in rows if _raidable(r)]
    if empty:
        passed.append(f"{len(empty)} site(s) nobody lives in (monuments, lairs, empty) never raided")
    contact = contact_civs(s, memory)
    if contact:
        kept = [r for r in rows if _int(r.get("civ_id")) in contact or _int(r.get("owner_id")) in contact]
        rows = [r for r in rows if r not in kept]
        if kept:
            passed.append("the civ the fort is making contact with is never raided ("
                          + ", ".join(f"civ {k}" for k in list(contact)[:3]) + ")")
    if stance == "aggressive":
        friends = raid_friends(s, memory, cfg)
        greedy = _trait(s, "greed") >= cfg.get("raid_greed_rich", 60)
        for r in rows:
            cid = _int(r.get("civ_id"))
            if cid is not None and cid in friends:
                continue
            ok, need, ratio = clear(r)
            if not ok:
                passed.append(f"{_site_words(r)}: too strong ({ratio:.1f}x, {need_ratio:.1f}x wanted)")
                continue
            who = game_text(r.get("civ") or ("bandits" if r.get("bandit") else "nobody's"), 40)
            out.append({**r, "policy": "aggressive", "need": need, "ratio": ratio,
                        "why": (f"aggressive ({why_stance}): {'the richest' if greedy else 'the weakest'} reachable "
                                f"site of {who} the squads clearly beat ({ratio:.1f}x its strength)"
                                + (f"; friends kept: {len(friends)}" if friends else "")),
                        "_key": (-need if greedy else need)})
        from planner_missions import MISSION_GOALS
        order = {g: i for i, g in enumerate(MISSION_GOALS)}
        out.sort(key=lambda t: (order.get(t["goal"], 99), t["_key"], _int(t.get("dist")) or 10 ** 6, t["site_id"]))
        if friends:
            passed.append("friends never raided: " + ", ".join(
                f"civ {k} ({v})" for k, v in list(friends.items())[:4]))
    else:
        # (0.105.48, K9) every friend the aggressive fort keeps is kept here too: an
        # ally, a peace pending, tribute, its caravan here, a civ in the traders' book
        # (the audit: a reactive fort retaliated against a trade partner at peace)
        protected = raid_friends(s, memory, {**cfg, "raid_friends_min": 0})
        near = int(cfg.get("raid_timid_tiles" if stance == "timid" else "raid_near_tiles", 8))
        new_tiles = int(cfg.get("raid_new_tiles", 16))
        # (a) retaliation: each attacker's nearest site the squads clearly beat
        for cid, a in sorted(attackers.items(), key=lambda kv: -kv[1]["year"]):
            if cid in protected:
                passed.append(f"civ {cid} attacked the fort ({_attack_words(a)}) but {protected[cid]}: left alone")
                continue
            if cid in contact:
                continue
            # (0.105.48, K9) only while still at war (TotalWar or Skirmishing): a
            # civ the fort has made peace with since is left alone
            rel = _civ_relation(s, cid, next((r for r in rows if _int(r.get("civ_id")) == cid), None))
            if rel not in HOSTILE:
                passed.append(f"civ {cid} attacked the fort ({_attack_words(a)}) but is at "
                              f"{game_text(rel or 'an unknown standing', 20)} now: left alone")
                continue
            theirs = sorted([r for r in rows if _int(r.get("civ_id")) == cid and r["goal"] == "raid"],
                            key=lambda r: (_int(r.get("dist")) or 10 ** 6, r["site_id"]))
            for r in theirs:
                ok, need, ratio = clear(r)
                if ok:
                    out.append({**r, "policy": "retaliation", "need": need, "ratio": ratio, "_key": (0, r.get("dist") or 0),
                                "why": f"retaliation for {_attack_words(a)} by {game_text(r.get('civ') or a.get('name') or 'them', 40)}"
                                       f": their nearest reachable site the squads clearly beat ({ratio:.1f}x)"})
                    break
                passed.append(f"{_site_words(r)} of an attacker: too strong ({ratio:.1f}x, {need_ratio:.1f}x wanted)")
        # (b) a threat close by: a hostile or ownerless site near, or new within reach
        for r in rows:
            if r["goal"] != "raid":
                continue
            cid = _int(r.get("civ_id"))
            if cid is not None and (cid in protected or cid in attackers):
                continue
            if not (r.get("hostile") or r.get("at_war") or r.get("bandit")):
                continue
            d = _int(r.get("dist"))
            if d is None:
                continue
            first = _int(sights.get(str(r["site_id"])))
            new = base is not None and first is not None and first > base
            if d <= near:
                reason = f"{'a new ' if new else 'a '}{SITE_WORDS.get(str(r.get('type') or ''), 'site')} " \
                         f"{d} tile(s) away"
            elif new and stance != "timid" and d <= new_tiles:
                reason = f"a new {SITE_WORDS.get(str(r.get('type') or ''), 'site')} setting up {d} tiles away"
            else:
                continue
            ok, need, ratio = clear(r)
            if not ok:
                passed.append(f"{_site_words(r)}, {reason}: too strong ({ratio:.1f}x, {need_ratio:.1f}x wanted)")
                continue
            who = game_text(r.get("civ") or "bandits", 40)
            stand = "at war" if r.get("at_war") else ("hostile" if r.get("hostile") else "nobody's friend")
            out.append({**r, "policy": "threat", "need": need, "ratio": ratio, "_key": (1, d),
                        "why": f"{reason} ({who}, {stand}): removed before it grows ({ratio:.1f}x its strength)"})
        out.sort(key=lambda t: (t["_key"], t["site_id"]))
        if not out and not attackers:
            passed.append(f"{why_stance}; no civ attacked the fort in the last {cfg.get('raid_retaliate_years', 3)} "
                          "years and no hostile site is close: no raid")
    for t in out:
        t.pop("_key", None)
    return out, passed, stance


def last_offensive_tick(s: dict, memory=None):
    """The newest offensive mission the AI sent: the sender's runs and the
    book (note_raids)."""
    best = _int(_seen(memory).get("last"))
    by = _d(_d(_d(s.get("missions")).get("send")).get("last_by_goal"))
    for g in OFFENSIVE:
        o = _d(by.get(g))
        t = _int(o.get("tick"))
        if o.get("result") == "sent" and t is not None and (best is None or t > best):
            best = t
    return best


def raid_choice(s: dict, cfg: dict = PLANNER_CONFIG, memory=None, squads=None, extra=None):
    """(the best candidate or None, words): the cooldown first."""
    last = last_offensive_tick(s, memory)
    cd = int(cfg.get("raid_cooldown_days", 84)) * TICKS_PER_DAY
    if last is not None and 0 <= abs_tick(s) - last < cd:
        days = (abs_tick(s) - last) // TICKS_PER_DAY
        stance = raid_stance(s, cfg)[0]
        return None, [f"the last attack went {days} day(s) ago: one a season ({stance})"]
    cands, passed, _ = raid_candidates(s, cfg, memory, squads, extra)
    return (cands[0] if cands else None), passed


# --- bookkeeping (planner.note_cycle, through note_missions) -------------------------------

def note_raids(s: dict, memory) -> None:
    """memory.missions_seen["raids"]: since (when the AI began watching the
    sites), sites (site id -> first seen), traders (civ id -> {n, last}),
    present (the caravans' civs here last cycle), last (the newest
    offensive mission sent)."""
    if memory is None:
        return
    ms = getattr(memory, "missions_seen", None)
    if not isinstance(ms, dict):
        ms = memory.missions_seen = {}
    r = ms.get("raids")
    if not isinstance(r, dict):
        r = ms["raids"] = {}
    now = abs_tick(s)
    rs = _d(_d(s.get("missions")).get("raid_sites"))
    if isinstance(rs.get("rows"), list):
        if not isinstance(r.get("since"), int):
            r["since"] = now
        sites = r.get("sites") if isinstance(r.get("sites"), dict) else {}
        for row in rs["rows"]:
            sid = _int(_d(row).get("site_id"))
            if sid is not None and str(sid) not in sites:
                sites[str(sid)] = now
        if len(sites) > SIGHTS_MAX:
            for k in sorted(sites, key=lambda k: sites[k])[:len(sites) - SIGHTS_MAX]:
                del sites[k]
        r["sites"] = sites
    w = _world(s)
    if "world" not in _d(s.get("_errors")) and isinstance(s.get("world"), dict):
        here = sorted({_d(c).get("civ_id") for c in _l(w.get("caravans"))
                       if _int(_d(c).get("civ_id")) is not None and not _d(c).get("hostile")})
        before = set(_l(r.get("present")))
        traders = r.get("traders") if isinstance(r.get("traders"), dict) else {}
        for cid in here:
            if cid not in before:
                t = _d(traders.get(str(cid)))
                traders[str(cid)] = {"n": int(t.get("n") or 0) + 1, "last": now}
        r["traders"] = traders
        r["present"] = here
    last = last_offensive_tick(s, None)
    if last is not None and (not isinstance(r.get("last"), int) or last > r["last"]):
        r["last"] = last


# --- pets ----------------------------------------------------------------------------------

def _pets(s: dict) -> dict:
    return _d(_d(s.get("missions")).get("pets"))


def pets_of_squads(s: dict, squad_ids) -> list:
    ids = set(squad_ids or [])
    return [p for p in _l(_pets(s).get("held")) if isinstance(p, dict) and p.get("squad_id") in ids]


def _releasable(p: dict) -> bool:
    return p.get("held") in ("pasture", "zone") and p.get("ai") is True and _int(p.get("pet_id")) is not None


def releasable_pets(s: dict, squad_ids) -> list:
    return [p for p in pets_of_squads(s, squad_ids) if _releasable(p)]


def stuck_pets(s: dict, squad_ids) -> list:
    """The pets the AI can't let out (a cage, a chain, the player's zone)."""
    return [p for p in pets_of_squads(s, squad_ids) if not _releasable(p)]


HELD_WORDS = {"pasture": "kept in a pasture", "zone": "kept in a zone", "cage": "in a cage", "chain": "chained"}


def pet_words(p: dict) -> str:
    where = HELD_WORDS.get(str(p.get("held")), "held")
    if p.get("held") in ("pasture", "zone"):
        where += " of the AI's" if p.get("ai") else " of yours"
    return f"its {game_text(p.get('pet') or 'pet', 24)} {where}"


def restore_due(s: dict, cfg: dict = PLANNER_CONFIG) -> list:
    """The booked pets ready to go back (home, held nowhere) and booked long
    enough ago."""
    days = int(cfg.get("raid_pet_restore_days", 2))
    now = abs_tick(s)
    return [e for e in _l(_pets(s).get("book")) if isinstance(e, dict) and e.get("state") == "ready"
            and _int(e.get("tick")) is not None and now - e["tick"] >= days * TICKS_PER_DAY]


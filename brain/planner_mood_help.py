"""planner_mood_help (0.105.47, J1): what the strange moods need from the
rest of the fort, read from the bridge's `mood_help` section
(lua/ai-mood-help.lua): DF's job cancels (an order whose jobs DF keeps
cancelling is a failed route, not one on its way), the webs a weaver can
reach (silk), and the moods' tiles outside the shelter while the alarm is up.

Why (I7a, the 11-14 Nov run, forts A-F): 54 moods failed. 49 timed out
(cloth 36: silk 20, plant 10, yarn 6; bone or leather never fetched 4;
rough gems 4; sand 1; a macabre mood that never claimed a shop 1) and 5 were
cancelled "Forbidden area" by the AI's own civilian alarm. `_mood_make`
treated an order "already queued" as handled, so the AI waited on weave,
shear, spin and sand orders DF cancelled more than 1,000 times; silk had no
route at all ("silk comes from webs or caravans", and no caravan trade ran),
while remove_webs took 20,000-36,000 webs a fort.

planner_moods calls `dead_order`, `usable_thread`, `silk_route`, the
free-items memo and the trade words; planner.py calls `mood_shelter_rule`
and `note_mood_help` (record), planner_industry `webs_hold`.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (LIMIT_EXEMPT, STEER_PROTECTED, PLANNER_CONFIG, Proposal, TICKS_PER_DAY, _has_shop,
                          abs_tick, mood_kind, mood_on_hand)

__all__ = ["mood_want", "MOOD_FIBRES", "THREAD_PART_OK", "CANCEL_MATCH", "dead_order", "usable_thread", "released_since", "webs_reach", "silk_route", "silk_wanted", "webs_hold",
           "mood_shelter_rule", "free_items_sig", "free_items_skip", "hospital_none_skip", "note_mood_help", "TRADE_IF", "request_detail"]

# a gathering mood's tiles put in the shelter: a life on it, no action slot to wait for
LIMIT_EXEMPT.add("mood_shelter")
STEER_PROTECTED.add("mood_shelter")

# --- (0.105.112 item3) one reading of what a mood request wants --------------------
#
# B, 24 Nov 22:28-22:40: Sigun's secretive mood (a gem cutter's) wanted 1 yarn
# cloth first and 1 plant cloth fourth; `mood` read the fibre from the
# request's flags in one order, `mood_hospital` from them in another
# (`_fibre_of`), and the thread branch in a third; each acted on its own
# reading. Every rule now reads a request through mood_want.

MOOD_FIBRES = ("silk", "yarn", "plant")
THREAD_WHOLE = 15000
THREAD_PART_OK = 13500        # (item4's THREAD_SET_OUT_MIN) a thread mood takes thread this full
_MAT_FIBRE = (("silk", "silk"), ("wool", "yarn"), ("hair", "yarn"), ("yarn", "yarn"))


def mood_want(x: dict) -> dict:
    """What a mood request (the bridge's `moods.list[].missing[]`, from DF's
    job_items: item type, material, flags1-3) asks for, read one way for
    every rule: {what: 'cloth' | 'thread' | a mood_kind, fibres: the fibres
    the request names in DF's flags (silk / yarn / plant; from its material
    when the flags name none, e.g. "cave spider silk"), fibre: the one fibre
    to set out or make ('any' when none is named), part_ok: a part-used
    thread does (DF's min_dimension under a whole thread, or not reported)}."""
    x = _d(x)
    item = str(x.get("item") or "").upper()
    what = "cloth" if item == "CLOTH" else "thread" if item == "THREAD" else mood_kind(x)
    flags = set(str(f) for f in _l(x.get("flags")))
    fibres = tuple(f for f in MOOD_FIBRES if f in flags)
    if not fibres and what in ("cloth", "thread") and x.get("material"):
        mat = str(x.get("material")).lower()
        fibres = tuple(dict.fromkeys(k for w, k in _MAT_FIBRE if w in mat)) or ("plant",)
    md = x.get("min_dim")
    md = md if isinstance(md, int) and not isinstance(md, bool) else None
    return {"what": what, "fibres": fibres, "fibre": fibres[0] if fibres else "any",
            "part_ok": what == "thread" and (md is None or md <= THREAD_PART_OK)}


# (0.105.47) the caravans: no trade deal ran in any fort all run (I7a), so the
# notes never promise a purchase, only one if a trade happens
TRADE_IF = "if a caravan trade happens"

# a recipe -> the words of its DF job name (lower case) and, for the weaves,
# of the thread's kind (in the job's name or its cancel reason)
CANCEL_MATCH = {
    "weave_silk_cloth": (("weave",), ("silk",)),
    "weave_yarn_cloth": (("weave",), ("yarn", "wool")),
    "weave_plant_cloth": (("weave",), ("plant", "fiber", "fibre")),
    "shear_creature": (("shear",), ()),
    "spin_thread": (("spin",), ()),
    "collect_sand": (("collect sand",), ()),
    "collect_webs": (("collect web",), ()),
    "process_plants": (("process plant",), ()),
    "tan_hide": (("tan ",), ()),
    "smelt_ore": (("smelt",), ()),
    "make_charcoal": (("charcoal",), ()),
    "coke_bituminous": (("coke",), ()),
    "coke_lignite": (("coke",), ()),
    "raw_green_glass": (("glass",), ()),
    "cut_gems": (("cut ",), ()),
    "stone_blocks": (("block",), ()),
}
# a cancel reason that says something is missing (not an interruption, a
# tantrum or a fight): the order can't go on as it stands
LACK_WORDS = ("needs", "need ", "no ", "could not", "cannot", "can't", "unable", "not enough")


def _lacks(why: str) -> bool:
    w = why.lower()
    return any(w.startswith(x) or f" {x}" in w for x in LACK_WORDS) and "interrupted" not in w


def _cancels(s: dict) -> list:
    return [c for c in _l(_d(s.get("mood_help")).get("cancels")) if isinstance(c, dict)]


WEAVE_FIBRE = {"weave_plant_cloth": "plant", "weave_silk_cloth": "silk", "weave_yarn_cloth": "yarn"}


def _lack_cancels(s: dict, recipe: str) -> list:
    """The bridge's cancel rows of this recipe's jobs for something missing."""
    m = CANCEL_MATCH.get(recipe)
    if not m:
        return []
    jobs, kinds = m
    out = []
    for c in _cancels(s):
        job, reason = str(c.get("job") or "").lower(), str(c.get("why") or "")
        if not any(j in job for j in jobs) or not _lacks(reason):
            continue
        if kinds and not any(k in job or k in reason.lower() for k in kinds):
            continue
        out.append(c)
    return out


def dead_order(s: dict, recipe: str, cfg: dict | None = None) -> str | None:
    """Why an order of this recipe is a failed route, in words (None: it
    isn't): its jobs were cancelled `mood_dead_cancels` times or more lately
    for something missing (I7a: "Needs 1 unused collected yarn thread",
    "No creature", "Needs hair/wool", "Need valid, active sand collection
    zone")."""
    cfg = cfg or PLANNER_CONFIG
    fibre = WEAVE_FIBRE.get(recipe)
    if fibre and released_since(s, fibre, recipe):
        return None                  # (item2) the cancels were for the hospital's thread, set out since
    n, why = 0, ""
    for c in _lack_cancels(s, recipe):
        n += int(c.get("n") or 1)
        why = why or str(c.get("why") or "")
    if n >= int(cfg.get("mood_dead_cancels", 2)):
        return f"DF cancels the {recipe.replace('_', ' ')} jobs: \"{why}\" ({n} times lately)"
    return None


def usable_thread(s: dict, cfg: dict | None = None) -> dict:
    """The bridge's thread by kind, a kind counted 0 while its weaving is
    cancelled for want of thread (I7a: F's 6 yarn thread and B's 5, counted
    for years, "unused collected yarn thread" DF would not weave)."""
    th = {k: int(v or 0) for k, v in _d(_d(s.get("supplies")).get("thread_kinds")).items()}
    for k in list(th):
        d = dead_order(s, f"weave_{k}_cloth", cfg)
        if d and "thread" in d.lower():
            th[k] = 0
    return th


def released_since(s: dict, fibre: str, recipe: str) -> bool:
    """(item2) The hospital's thread of this fibre was set out for a mood
    (the bridge's `mood_help.hospital_hold.released`, a tick) after the last
    of the recipe's jobs DF cancelled for want of thread: the cancels were for
    the thread the hospital held, and the thread set out is woven
    (dead_order, and so usable_thread, don't count that weave as failed)."""
    rel = _d(_d(_d(s.get("mood_help")).get("hospital_hold")).get("released"))
    at = [v for k, v in rel.items() if k in (fibre, "any") and isinstance(v, int) and not isinstance(v, bool)]
    if not at:
        return False
    ticks = [int(c["tick"]) for c in _lack_cancels(s, recipe) if isinstance(c.get("tick"), int)]
    return max(at) > max(ticks, default=-1)


def webs_reach(s: dict) -> int | None:
    """Webs a Loom's weaver can walk to (None: not reported)."""
    w = _d(_d(s.get("mood_help")).get("webs"))
    v = w.get("reach")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def silk_route(s: dict, cfg: dict | None = None) -> bool:
    """Silk thread can be made here: a Loom, webs a weaver reaches, and the
    collecting not cancelled as failing."""
    return (_has_shop(_d(s.get("buildings")), "Loom") and int(webs_reach(s) or 0) > 0
            and not dead_order(s, "collect_webs", cfg))


def _silk_request(x: dict) -> bool:
    w = mood_want(x)
    return w["what"] in ("cloth", "thread") and "silk" in w["fibres"]


def silk_wanted(s: dict, cfg: dict | None = None) -> str:
    """Why the fort wants silk now ('' if not): a crafting mood waits on silk
    cloth or thread it doesn't have within reach, or the silk cloth reserve
    is short with no silk thread to weave."""
    cfg = cfg or PLANNER_CONFIG
    for m in _l(_d(s.get("moods")).get("list")):
        if not isinstance(m, dict) or not m.get("craft"):
            continue
        for x in _l(m.get("missing")):
            if isinstance(x, dict) and _silk_request(x) and mood_on_hand(x) is not True:
                return f"{m.get('name') or 'a dwarf'}'s mood waits on silk"
    su = _d(s.get("supplies"))
    ck = su.get("cloth_kinds")
    want = int(cfg.get("reserve_silk_cloth") or 0)          # (0.105.51) silk on its own
    if isinstance(ck, dict) and want > 0:
        have = int(ck.get("silk") or 0)
        th = usable_thread(s, cfg)
        if have <= want and not th.get("silk"):
            return f"the silk cloth kept for moods is {have} of {want}"
    return ""


def webs_hold(s: dict, cfg: dict | None = None) -> str:
    """remove_webs (and clear_webs) wait while silk is wanted and the webs a
    weaver can reach are no more than `mood_webs_keep` ('' if they needn't);
    the reason in words."""
    cfg = cfg or PLANNER_CONFIG
    why = silk_wanted(s, cfg)
    if not why:
        return ""
    reach = webs_reach(s)
    keep = int(cfg.get("mood_webs_keep", 50))
    if reach is not None and reach > keep * 4:
        return ""                      # plenty within reach: the far ones may go
    return (f"{why}: the spider webs stay (silk thread is collected from them at the Loom; "
            f"{reach if reach is not None else 'an unknown number'} within a weaver's reach, {keep} kept at least)")


# --- the alarm and the moods ---------------------------------------------------------


def mood_shelter_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """(I7a 3) While the alarm is up (or evil weather keeps the civilians in
    the AI shelter), a crafting mood still gathering gets its workshop and the
    tiles of the items it needs put in the shelter burrow: five moods were
    cancelled "Forbidden area" within 0-2 days of the alarm (F's evil cloud,
    cavern beasts in A and F, C's fire), each a certain loss; the threat a
    remote one. The shelter is drawn with them anyway (ai-society
    fill_shelter); this covers a mood that began after it was drawn."""
    sh = _d(_d(s.get("mood_help")).get("shelter"))
    out = sh.get("outside")
    if not (isinstance(out, int) and out > 0):
        return
    kept_in = False
    try:
        from planner_weather import keep_in_active
        kept_in = bool(keep_in_active(memory)) if memory is not None else False
    except Exception:                    # noqa: BLE001  (an older planner)
        kept_in = False
    if s.get("civ_alert") is not True and not kept_in:
        return
    who = [str(m.get("name") or "a dwarf") for m in _l(_d(s.get("moods")).get("list"))
           if isinstance(m, dict) and m.get("craft") and m.get("workshop")]
    proposals.append(Proposal("mood_shelter", {"type": "mood_shelter"},
                              f"{', '.join(who[:3]) or 'a dwarf'} in a strange mood still gathers while the "
                              + ("alarm" if s.get("civ_alert") is True else "evil weather")
                              + f" keeps the civilians in the shelter: {out} tile(s) of its workshop and "
                              "materials put inside (a mood kept from them fails for certain; the threat may never "
                              "come)", 0))


# --- mood_free_items: not asked again while nothing changed ---------------------------


def free_items_sig(missing: list) -> str:
    """The counts a mood's free-items call depends on, as one string."""
    bits = []
    for x in missing:
        av = _d(_d(x).get("avail"))
        bits.append("/".join(str(int(av.get(k) or 0)) for k in ("forbidden", "forbidden_reach", "dump", "reach")))
    return ";".join(bits)


def free_items_skip(memory, unit_id, missing: list) -> bool:
    """mood_free_items answered "nothing forbidden" for these very counts:
    not proposed again until they change (I7a: up to 7 rejections a mood)."""
    if memory is None or unit_id is None:
        return False
    seen = _d(_d(getattr(memory, "mood_help", None)).get("free_none")).get(str(unit_id))
    return seen is not None and seen == free_items_sig(missing)


def _hospital_sig(s: dict) -> str:
    h = _d(_d(s.get("supplies")).get("hospital"))
    return "|".join(f"{k}:{sorted(_d(h.get(k)).items())}" for k in ("cloth_kinds", "thread_kinds"))


def hospital_none_skip(s: dict, memory, give: str, fibre: str) -> bool:
    """(0.105.112 item3) hospital_release answered "nothing of that kind"
    for this give (cloth / thread) and fibre while the hospital's counts were
    as they are now: not asked again until they change."""
    if memory is None:
        return False
    seen = _d(_d(getattr(memory, "mood_help", None)).get("hosp_none")).get(f"{give}:{fibre}")
    return seen is not None and seen == _hospital_sig(s)


def note_mood_help(p, r: dict, state: dict, memory, now) -> None:
    """record(): a mood_free_items call that found nothing forbidden keeps the
    counts it saw; a workshop built past the cap for a mood is remembered
    (one a mood)."""
    if memory is None:
        return
    a = _d(getattr(p, "action", None))
    mh = dict(_d(getattr(memory, "mood_help", None)))
    if a.get("type") == "mood_free_items" and a.get("unit_id") is not None:
        uid = str(a["unit_id"])
        none = dict(_d(mh.get("free_none")))
        if _d(r).get("ok") is not True and "nothing forbidden" in str(_d(r).get("error") or ""):
            for m in _l(_d(state.get("moods")).get("list")):
                if isinstance(m, dict) and str(m.get("unit_id")) == uid:
                    none[uid] = free_items_sig([x for x in _l(m.get("missing")) if isinstance(x, dict)])
        elif _d(r).get("ok") is True:
            none.pop(uid, None)
        mh["free_none"] = none
    if getattr(p, "rule", "") == "mood_hospital" and a.get("type") == "hospital_release" and not a.get("restore"):
        hn = dict(_d(mh.get("hosp_none")))
        give = "thread" if a.get("thread") else "cloth"
        key = f"{give}:{a.get('kind') or 'any'}"
        if _d(r).get("ok") is not True and "nothing of that kind" in str(_d(r).get("error") or ""):
            hn[key] = _hospital_sig(state)
        elif _d(r).get("ok") is True:
            hn.pop(key, None)
        mh["hosp_none"] = hn
    if getattr(p, "rule", "") == "mood" and a.get("type") == "start_project" and a.get("mood_unit") is not None:
        if _d(r).get("ok") is not False:
            cap = dict(_d(mh.get("cap_built")))
            cap[str(a["mood_unit"])] = now if isinstance(now, int) else 0
            mh["cap_built"] = cap
    # (0.105.51) an animal sent to the butcher for the leather reserve: one a fortnight
    if getattr(p, "rule", "") == "mood_reserve" and a.get("type") == "slaughter_one" and _d(r).get("ok") is True:
        mh["reserve_slaughter"] = now if isinstance(now, int) else 0
    # the moods gone are forgotten
    live = {str(m.get("unit_id")) for m in _l(_d(state.get("moods")).get("list")) if isinstance(m, dict)}
    if live:
        for k in ("free_none", "cap_built"):
            if isinstance(mh.get(k), dict):
                mh[k] = {u: v for u, v in mh[k].items() if u in live}
    memory.mood_help = mh


# --- the stalled mood's detail -------------------------------------------------------


def request_detail(x: dict) -> str:
    """(I7a 7) For a stalled mood: the request's flags as DF holds them
    (showmood's view) and where the counted items lie."""
    flags = [str(f) for f in _l(_d(x).get("flags"))]
    bits = []
    if flags:
        bits.append("DF's flags: " + ", ".join(flags[:8]))
    if x.get("material"):
        bits.append(f"material {x.get('material')}")
    spots = [sp for sp in _l(_d(_d(x).get("avail")).get("spots")) if isinstance(sp, dict)]
    if spots:
        where = []
        for sp in spots[:3]:
            w = f"x{sp.get('x')} y{sp.get('y')} z{sp.get('z')} {sp.get('at') or ''}".strip()
            if sp.get("standing") and sp.get("standing") != "free":
                w += f", {sp.get('standing')}"
            w += ", in walk" if sp.get("reach") else ", out of walk"
            where.append(w)
        bits.append("counted at " + "; ".join(where))
    return "; ".join(bits)

"""(0.105.41, item 11) Syndromes beyond infection, and miasma.

Syndromes (the bridge's `syndromes` section, lua/ai-syndromes.lua): each
citizen with an active syndrome (from a forgotten beast's breath, dust or
blood, giant cave spider venom, evil rain or cloud, something eaten or
drunk), by name, how long, its routes, its deadly effects and where it came
from (the material that carries it); the citizens whose bodies carry a
contact syndrome's material (DF tracks it from feet to floor and floor to
feet: they spread it), and the fort's floors' syndrome spatter (walked in
slices). The rule (_syndrome_rule):

  * says who has what, from where, and what it does (a few names, the rest
    counted); an ingested one of unknown source: the food, drink or water;
  * the carriers kept apart (quarantine_syndromes: kept in the AI's
    hospital burrow as patients are, with its drink, food and guards, for
    `syndrome_quarantine_days` after last seen carrying), while the hospital
    burrow's own switch is on;
  * the syndrome spatter cleaned off the carriers, their things and the
    fort's floors (clean_contaminants; only the syndrome materials). The
    first call in a fort is a trial (a dry run that counts), as the world
    cleanup's are.

The Rules switch `syndrome_care` (on by default): off, neither is done and
the quarantine is emptied.

Miasma (the bridge's `miasma` section): the Miasma flows indoors and near
where the dwarves live, the worst spots, and what rots there. The rule
(_miasma_rule), past `miasma_min_tiles` where the dwarves live (the
`living` count: indoors, in the fort's built-up areas, no cavern tile):

  * says where and what rots (the fort's own dead are the burial rules':
    the tombs and coffins, unforbid_dead; said, not touched here);
  * the rotting bodies, remains and rotten food lying loose near it marked
    for the garbage dump (clear_miasma), only with a dump zone under the
    sky; without one, one placed outside (place_surface dump);
  * with refuse piles but none under the sky (rot in an indoor pile fills
    the fort with miasma), a refuse pile placed outside (the player's
    indoor pile is left as it is, and said).

Without either section (an older bridge, the fixtures) nothing here
proposes or says anything.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import AGENDA_THEMES, PLANNER_CONFIG, TICKS_PER_DAY, Proposal, abs_tick, player_rules

__all__ = ["SYNDROME_CONFIG", "SOURCE_WORDS", "source_words", "syndromes_report", "miasma_report",
           "_syndrome_rule", "_miasma_rule", "note_syndromes", "syndrome_line"]

SYNDROME_CONFIG = {
    "syndrome_notes_max": 4,                         # afflicted citizens named in the notes (the rest counted)
    "syndrome_clean_min_tiles": 1,                   # syndrome spatter tiles in the fort's areas that ask a clean
    "syndrome_clean_cooldown_ticks": TICKS_PER_DAY,
    "syndrome_quarantine_days": 7,                   # a carrier kept in the hospital burrow this long after last seen carrying
    "syndrome_quarantine_max": 20,
    "syndrome_quarantine_cooldown_ticks": TICKS_PER_DAY // 2,
    "miasma_min_tiles": 3,                           # miasma tiles where the dwarves live before the rule speaks
    "miasma_clear_max": 50,                          # rotting things marked for the dump a call
    "miasma_clear_cooldown_ticks": 2 * TICKS_PER_DAY,
    "miasma_dump_cooldown_ticks": 7 * TICKS_PER_DAY,
    "miasma_refuse_cooldown_ticks": 7 * TICKS_PER_DAY,
}
for _k, _v in SYNDROME_CONFIG.items():
    PLANNER_CONFIG.setdefault(_k, _v)
for _k, _t in (("syndrome_clean", "clean off what spreads sickness"), ("syndrome_quarantine", "keep the sick apart"),
               ("miasma_clear", "clear what rots indoors"), ("miasma_dump", "clear what rots indoors"),
               ("miasma_refuse", "clear what rots indoors")):
    AGENDA_THEMES.setdefault(_k, _t)

SOURCE_WORDS = {
    "forgotten_beast": "a forgotten beast (its breath, dust or blood)",
    "cave_spider": "giant cave spider venom",
    "evil_weather": "evil rain or cloud",
    "night_creature": "a night creature, demon or titan",
    "creature": "a creature",
    "plant": "a plant (eaten or drunk)",
    "mineral": "a mineral",
}


def source_words(row: dict) -> str:
    """Where a syndrome came from, in words."""
    kind = row.get("source")
    what = row.get("source_what")
    if kind in SOURCE_WORDS:
        w = SOURCE_WORDS[kind]
        if what and kind in ("creature", "mineral", "plant", "forgotten_beast"):
            w += f" ({what})"
        return w
    routes = _l(row.get("routes"))
    if routes == ["ingested"]:
        return "something eaten or drunk (the food, the drink or the water)"
    return "a source not found yet"


def syndromes_report(s: dict) -> dict | None:
    sec = _d(s.get("syndromes"))
    if sec.get("error") or not isinstance(sec.get("list"), list):
        return None
    return sec


def miasma_report(s: dict) -> dict | None:
    m = _d(s.get("miasma"))
    if m.get("error") or not isinstance(m.get("tiles"), int):
        return None
    return m


def _int(v) -> int:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _seen(memory) -> dict:
    if memory is None:
        return {}
    if not isinstance(getattr(memory, "syndromes_seen", None), dict):
        memory.syndromes_seen = {}
    return memory.syndromes_seen


def _row_words(r: dict) -> str:
    syns = [x for x in _l(r.get("syndromes")) if isinstance(x, dict)]
    parts = []
    for x in syns[:3]:
        t = str(x.get("name") or "a syndrome")
        days = x.get("days")
        if isinstance(days, int):
            t += f" for {days} day{'s' if days != 1 else ''}"
        t += ", from " + source_words(x)
        routes = [str(v) for v in _l(x.get("routes"))]
        if routes:
            t += " (by " + " or ".join(routes) + ")"
        if x.get("deadly"):
            bad = [str(e).lower().replace("_", " ") for e in _l(x.get("effects"))]
            t += ": deadly" + (" (" + ", ".join(bad[:4]) + ")" if bad else "")
        parts.append(t)
    text = f"{r.get('name') or r.get('id')}: " + ("; ".join(parts) if parts else "no syndrome yet")
    if r.get("carrier"):
        text += "; carries " + ", ".join(str(m) for m in _l(r.get("carries"))[:3]) + " on their body"
    if r.get("quarantined"):
        text += " (kept in the hospital)"
    return text


def _syndrome_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None, rules: dict | None = None) -> None:
    """Who has what syndrome and from where; the carriers kept apart and the
    syndrome spatter cleaned (see the module)."""
    sec = syndromes_report(s)
    if sec is None:
        return
    rules = rules or player_rules(s)
    rows = [r for r in _l(sec.get("list")) if isinstance(r, dict)]
    afflicted, deadly = _int(sec.get("afflicted")), _int(sec.get("deadly"))
    carriers, quarantined = _int(sec.get("carriers")), _int(sec.get("quarantined"))
    floors = _d(sec.get("floors"))
    tiles = _int(floors.get("tiles"))
    if afflicted:
        names = sorted(_d(sec.get("by_name")).items(), key=lambda kv: (-_int(kv[1]), str(kv[0])))
        text = f"{afflicted} citizen{'s have' if afflicted != 1 else ' has'} an active syndrome"
        if names:
            text += " (" + ", ".join(f"{k} {v}" for k, v in names[:3]) + ")"
        if deadly:
            text += f"; {deadly} with deadly effects"
        notes.append(text)
        shown = [r for r in rows if _l(r.get("syndromes"))]
        shown.sort(key=lambda r: (not any(_d(x).get("deadly") for x in _l(r.get("syndromes"))), str(r.get("name"))))
        for r in shown[:cfg["syndrome_notes_max"]]:
            notes.append(_row_words(r))
    if carriers or tiles:
        mats = sorted(_d(floors.get("materials")).items(), key=lambda kv: -_int(kv[1]))
        carried = sorted({str(m) for r in rows for m in _l(r.get("carries"))})
        what = ", ".join(carried[:3] or [k for k, _ in mats[:3]]) or "a syndrome's material"
        notes.append(f"{what} spreads sickness by touch: {carriers} citizen(s) carry it on their bodies, "
                     f"{tiles} floor tile(s) in the fort hold it")
    soldiers = _int(sec.get("soldier_carriers"))
    if soldiers:                                   # (fix5) the hospital burrow doesn't hold squad members
        notes.append(f"{soldiers} of the carriers are in a squad: soldiers aren't kept in the hospital burrow, so "
                     "they aren't kept apart (the clean still takes it off them)")
    if not rules.get("syndrome_care", True):
        if quarantined and proposals is not None:
            proposals.append(Proposal("syndrome_quarantine", {"type": "quarantine_syndromes", "release": True},
                                      f"syndrome care is switched off in the Rules: the {quarantined} kept apart "
                                      "let out", 3))
        if carriers or tiles:
            notes.append("syndrome care is off in the Rules: the carriers aren't kept apart and nothing is cleaned")
        return
    if proposals is None:
        return
    keepable = max(0, carriers - _int(sec.get("soldier_carriers")))     # (fix5) soldiers aren't held
    if keepable or quarantined:
        if not rules.get("hospital_burrow", True):
            if carriers:
                notes.append(f"{carriers} carrier(s) of a contact syndrome walk the fort: the hospital burrow is off "
                             "in the Rules, so nobody is kept apart")
        else:
            proposals.append(Proposal("syndrome_quarantine",
                                      {"type": "quarantine_syndromes", "days": cfg["syndrome_quarantine_days"],
                                       "max": cfg["syndrome_quarantine_max"]},
                                      (f"{keepable} citizen(s) carry a contact syndrome on their bodies: kept in the "
                                       f"hospital burrow {cfg['syndrome_quarantine_days']} days after last seen "
                                       "carrying it" if keepable else
                                       f"{quarantined} kept apart: those clean again a while let out"), 3))
    if carriers or tiles >= cfg["syndrome_clean_min_tiles"]:
        a = {"type": "clean_contaminants"}
        trial = not _seen(memory).get("dry")
        if trial:
            a["dry_run"] = True
        proposals.append(Proposal("syndrome_clean", a,
                                  ("a trial (counts, removes nothing): " if trial else "")
                                  + f"the syndrome's material cleaned off {carriers} citizen(s) and their things and "
                                    f"{tiles} floor tile(s) of the fort (blood, mud and the rest left)", 3))


def note_syndromes(p, r: dict, memory, now: int) -> None:
    """After a clean: the trial marked done (the real calls follow), the
    counts kept."""
    if getattr(p, "action", {}).get("type") != "clean_contaminants" or memory is None:
        return
    r = _d(r)
    seen = _seen(memory)
    if p.action.get("dry_run"):
        if r.get("ok") is True:
            seen["dry"] = now
    elif r.get("ok") is True:
        seen["cleaned"] = _int(seen.get("cleaned")) + _int(r.get("unit_spatter")) + _int(r.get("tile_events"))
        seen["last"] = now


def _has(proposals: list, action: dict) -> bool:
    return any(p.action == action for p in proposals)


def _miasma_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """Miasma indoors: where, what rots, and what the AI does (see the module)."""
    m = miasma_report(s)
    if m is None:
        return
    indoor, living = _int(m.get("indoor")), _int(m.get("living"))
    if living < cfg["miasma_min_tiles"]:        # (fix5) where the dwarves live: the caverns' or far-off rot is no one's to haul
        return
    src = _d(m.get("sources"))
    spots = [x for x in _l(m.get("spots")) if isinstance(x, dict)]
    text = f"miasma on {indoor} tile(s) indoors" + (f", {living} where the dwarves live" if living else "")
    if spots:
        w = spots[0]
        text += f"; worst at x{w.get('x')} y{w.get('y')} z{w.get('z')}"
    parts = [f"{_int(src.get(k))} {words}" for k, words in (("own_dead", "of the fort's own dead"),
                                                             ("corpse", "bodies or parts"), ("remains", "remains"),
                                                             ("food", "rotten food")) if _int(src.get(k))]
    text += ": rotting there " + ", ".join(parts) if parts else ": nothing rotting found near it (it drifts in)"
    notes.append(text)
    if _int(src.get("own_dead")):
        notes.append(f"{_int(src.get('own_dead'))} of the fort's own dead rot near the miasma: the burial rules give "
                     "them tombs (the AI doesn't dump its own)")
    kept = _d(m.get("kept"))
    if proposals is None:
        return
    b = _d(s.get("buildings"))
    clearing = _d(b.get("clearing"))
    markable = _int(m.get("markable"))
    if markable:
        if _int(m.get("dump_outside")):
            proposals.append(Proposal("miasma_clear", {"type": "clear_miasma", "max": cfg["miasma_clear_max"]},
                                      f"{markable} rotting thing(s) lie loose near the miasma indoors: marked for the "
                                      "garbage dump outside", 4))
        elif not clearing.get("dump"):
            a = {"type": "place_surface", "kind": "dump"}
            if not _has(proposals, a):
                proposals.append(Proposal("miasma_dump", a,
                                          f"{markable} rotting thing(s) make miasma indoors and the fort has no "
                                          "garbage dump under the sky: make one outside", 4))
    refuse = [x for x in _l(b.get("refuse_list")) if isinstance(x, dict)]
    indoor_piles = [x for x in refuse if x.get("outside") is False]
    if refuse and len(indoor_piles) == len(refuse) and not clearing.get("refuse"):
        a = {"type": "place_surface", "kind": "refuse"}
        if not _has(proposals, a):
            proposals.append(Proposal("miasma_refuse", a,
                                      f"every refuse pile ({len(refuse)}) is indoors, where rot makes miasma: a refuse "
                                      "pile put outside (the indoor one is left as it is)", 5))
    if _int(kept.get("in_pile")):
        notes.append(f"{_int(kept.get('in_pile'))} rotting thing(s) near the miasma lie in a stockpile: left in it "
                     "(a pile's contents are its owner's; an indoor refuse pile is the likely source)")


def syndrome_line(s: dict) -> str:
    """One line for the digest: syndromes, carriers, miasma ("" when none)."""
    sec, m = syndromes_report(s), miasma_report(s)
    parts = []
    if sec is not None and (_int(sec.get("afflicted")) or _int(sec.get("carriers"))):
        parts.append(f"syndromes {_int(sec.get('afflicted'))} (deadly {_int(sec.get('deadly'))}), "
                     f"carriers {_int(sec.get('carriers'))}, kept apart {_int(sec.get('quarantined'))}")
    if m is not None and _int(m.get("indoor")):
        parts.append(f"miasma indoors {_int(m.get('indoor'))} tiles")
    return ("Sickness: " + "; ".join(parts)) if parts else ""

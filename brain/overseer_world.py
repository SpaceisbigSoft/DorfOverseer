"""The overseer's memory of the world: the day's row, the atlas and the
chronicle (remember_world), the world facts and the culture pushed to the
game, and the learned payload. Split from overseer.py (r7 d1); overseer
re-exports every name. What it uses from overseer is looked up there at
call time (_ov, _late).
"""

from __future__ import annotations

import hashlib
import json
from bridge import Bridge, BridgeError  # noqa: F401  (Bridge: the annotations)
from dfhack import DFHackError
from planner import PLANNER_CONFIG, TICKS_PER_YEAR, abs_tick
import planner_stuck
import atlas
import calibrate
import chronicle
import defence
import learning
import masterplan
import leanings
import temperament
import memstore
import outcomes
import phases
import timeline
from culture import explain, new_history, pick_stone, profile_from, style_guide, update_eras
from quirks import describe as describe_quirks
from quirks import update as update_quirks
from weights import choose_all
from culture import note_events as culture_events
from digest import _d, _l, normalize

__all__ = ["STYLE_AREAS", "remember_world", "world_facts", "survey_site", "culture_update", "push_culture",
           "learned_payload", "push_learned"]

_ov = None     # the overseer module: set by overseer.py as it imports this part (its own
               # module object, also when it runs as the main script)


def _late(name: str):
    """A call-time forwarder to overseer.<name> (the one there now: a test's patch, too)."""
    def call(*a, **kw):
        return getattr(_ov, name)(*a, **kw)
    call.__name__ = call.__qualname__ = name
    return call


defer_act = _late("defer_act")
journal = _late("journal")
say = _late("say")


STYLE_AREAS = ("halls", "finish", "statues", "materials", "worship")


def _style_choices(memory) -> dict:
    ch = memory.culture.get("choices") if isinstance(memory.culture, dict) else None
    return {a: ch[a] for a in STYLE_AREAS if a in ch} if isinstance(ch, dict) else {}


def _note_adjust(state: dict, memory, journal_entry: dict | None, cfg: dict) -> None:
    """A strategist review that raised a target opens an outcome entry for it."""
    adj = (journal_entry or {}).get("adjust") if isinstance(journal_entry, dict) else None
    for k, kind in (("drink_per_dwarf", "drink_target"), ("meals_per_dwarf", "meal_target")):
        v = (adj or {}).get(k)
        if isinstance(v, (int, float)) and v != cfg.get(k):
            outcomes.open_entry(state, memory, kind, f"{k.replace('_', ' ')} {cfg.get(k)} -> {v}", "strategist",
                                expect="up" if v > cfg.get(k, 0) else "down")


def remember_world(state: dict, memory, events: list[dict], key: str, cfg: dict,
                   learned_now: list[str] | None = None, bridge=None) -> None:
    """Memory, part two: the day's row of numbers, the atlas (survey, registry,
    entrances, where things happened) and the chronicle. Scripts only, no tokens."""
    now = abs_tick(state)
    year = state["date"]["year"]
    if not (memory.chronicle or {}).get("entries"):
        chronicle.add(memory, state, "founded", "the AI overseer began keeping this fort's memory")
    chronicle.rewind(memory, year)                  # an older save: forget what hasn't happened yet
    # (0.104.86) the newest finished season, not how many: memory keeps 24, so
    # once full the count stood still and seasons.csv stopped (Enxah: at y70)
    seasons_before = _newest_season(memory)
    finished = timeline.record(state, memory, events, cfg)
    try:
        pj = _d(state.get("projects"))
        _ov.LAST_CYCLE.clear()
        _ov.LAST_CYCLE.update({"fort": key, **outcomes.measure(state),
                           # (0.100.1) how long the report froze the game, by section
                           "report_timing": state.get("_timing") if isinstance(state.get("_timing"), dict) else None,
                           "wealth": state.get("wealth") if isinstance(state.get("wealth"), int) else None,
                           "threats": _d(state.get("others_on_map")).get("threats_that_can_reach_dwarves"),
                           "projects_open": len(pj.get("open") or []), "projects_finished": pj.get("finished"),
                           "agenda": (memory.agenda or [])[:3],
                           "stuck": planner_stuck.soak_summary(memory),   # (0.105.45) things past their timeout
                           # the needs most dwarves are distracted by (name: count)
                           "needs": dict(sorted(((k, int(_d(v).get("distracted") or 0))
                                                 for k, v in _d(_d(state.get("needs")).get("needs")).items()),
                                                key=lambda kv: -kv[1])[:5])})
    except Exception:  # noqa: BLE001  (the soak row is only a log)
        pass
    if finished:
        memstore.log_day(key, finished, timeline.FIELDS)
    seasons = memory.timeline.get("seasons") or []
    if _newest_season(memory) != seasons_before:
        memstore.log_seasons(key, seasons, timeline.season_name)
    surveyed = atlas.survey_due(state, memory)
    if surveyed:
        for line in atlas.survey(state, memory):        # (this notes the entrances too)
            say(f"Atlas: {line}")
            chronicle.add(memory, state, "found" if "found" in line else "registry", line)
    else:
        for line in atlas.note_entrances(state, memory):
            say(f"Atlas: {line}")
            chronicle.add(memory, state, "registry", line)
    if surveyed or not masterplan.has_plan(memory) or masterplan.needs_redraw(memory):
        site = survey_site(bridge, memory)
        s = normalize(state)
        if site and "settings" not in s["_errors"]:
            traits = _d(s["settings"].get("traits"))
            for line in masterplan.ensure(state, memory, site, traits,
                                          profile_from(traits, memory.culture or new_history())):
                say(f"Plan: {line}")
                chronicle.add(memory, state, "plan", line)
    for line in atlas.note_registry(state, memory):
        chronicle.add(memory, state, "built", line)
    atlas.note_events(state, memory, events)
    atlas.consolidate(memory, now)
    change = phases.update(state, memory, events)
    if change:
        say(f"Phase: {change}")
        chronicle.add(memory, state, "phase", change)
    for line in defence.judge_sieges(state, memory):
        say(f"Defence: {line}")
        chronicle.add(memory, state, "siege", line)
    for line in masterplan.apply_quirks(memory):
        say(f"Plan: {line}")
        chronicle.add(memory, state, "plan", line)
    for line in learned_now or []:
        if "lesson" in line:
            chronicle.add(memory, state, "learned", line)
    chronicle.consolidate(memory, year)


def world_facts(state: dict, memory) -> dict:
    """Facts from the atlas and the phases that quirks can test: caverns
    reached, citizens killed inside the fort (away from the gates) during a
    siege, and years since the last such death."""
    now = abs_tick(state)
    a = memory.atlas if isinstance(memory.atlas, dict) else {}
    layers = (a.get("survey") or {}).get("layers") or []
    f = {"caverns_reached": sum(1 for l in layers if isinstance(l, dict)
                                and str(l.get("name", "")).startswith("Cavern")
                                and (l.get("found") or l.get("discovered")))}
    spans = phases.siege_spans(memory, now)
    inside = [e for e in a.get("events") or [] if isinstance(e, dict) and e.get("k") == "death"
              and not str(e.get("near") or "").startswith("entrance:")
              and any(s <= (e.get("t") or -1) <= t for s, t in spans)]
    f["deaths_inside_in_siege"] = len(inside)
    # (0.103, site and story quirks) the land and the fort's own hard times
    st = normalize(state)
    bodies = [b for b in _l(_d(st.get("water")).get("bodies")) if isinstance(b, dict)]
    if bodies:
        f["surface_water_tiles"] = sum(int(b.get("tiles") or 0) for b in bodies if b.get("kind") == "surface")
    cr = _d(st.get("crossings"))
    if "crossings" in cr:
        f["crossings_built"] = sum(1 for c in _l(cr.get("mine")) if isinstance(c, dict) and c.get("built"))
        f["crossings_possible"] = len(_l(cr.get("crossings")))
    f["freezes"] = 1 if getattr(memory, "climate_freezes", False) else 0
    om = _d(st.get("others_on_map"))
    if isinstance(om.get("tame_animals"), int):
        f["tame_animals"] = om["tame_animals"]
    dw = _d(st.get("dwarves"))
    if "children" in dw:
        f["children"] = int(dw.get("children") or 0)
    if "legendary" in dw:
        f["legendary"] = int(dw.get("legendary") or 0)
    # (0.103.11) Forge-born and Communal: the forges, magma, beds for everyone
    bl = _d(st.get("buildings"))
    if "workshops" in bl:
        places = {**_d(bl.get("workshops")), **_d(bl.get("furnaces"))}
        f["magma_forges"] = int(places.get("MagmaForge") or 0)
        f["forges"] = int(places.get("MetalsmithsForge") or 0) + f["magma_forges"]
        if isinstance(_d(bl.get("other")).get("Bed"), int) and int(dw.get("total") or 0) >= 10:
            f["beds_per_dwarf"] = round(_d(bl.get("other"))["Bed"] / max(1, int(dw.get("total") or 1)), 2)
    # (0.103.15) Gem-mad and Nobles' Pride
    sk = _d(st.get("stocks"))
    if "rough_gems" in sk or "cut_gems" in sk:
        f["cut_gems"] = int(sk.get("cut_gems") or 0)
        f["gems"] = int(sk.get("rough_gems") or 0) + f["cut_gems"]
    if "workshops" in bl:
        f["jewelers"] = int(_d(bl.get("workshops")).get("Jewelers") or 0)
    if isinstance(st.get("nobles"), list):
        f["nobles"] = len({str(n.get("position")) for n in st["nobles"] if isinstance(n, dict) and n.get("position")})
    stones = [x for x in _l(st.get("stone_types")) if isinstance(x, dict) and isinstance(x.get("count"), (int, float))]
    if stones and sum(x["count"] for x in stones) >= 20:        # (0.103.18) One Stone
        f["top_stone_share"] = round(max(x["count"] for x in stones) / sum(x["count"] for x in stones), 2)
    # (0.103.19) Waste Not: wood and usable stone a dwarf (a poor site)
    sk2 = _d(st.get("stocks"))
    if "wood" in sk2 and "boulders" in sk2 and int(dw.get("total") or 0) >= 10:
        f["materials_pd"] = round((int(sk2.get("wood") or 0) + int(sk2.get("boulders") or 0)) / int(dw["total"]), 1)
    # (0.103.19) Sky-reachers: the share of citizens out under the sky,
    # smoothed over the days (a slow average kept in the fort's culture)
    md = _d(_d(st.get("map")).get("dwarves"))
    if isinstance(md.get("outside"), int) and int(md.get("citizens") or 0) >= 10 and isinstance(memory.culture, dict):
        share = md["outside"] / md["citizens"]
        avg = memory.culture.get("surface_share_avg")
        avg = share if not isinstance(avg, (int, float)) else avg * 0.97 + share * 0.03
        memory.culture["surface_share_avg"] = round(avg, 3)
        f["surface_share"] = round(avg, 2)
    mg = _d(_d(st.get("water")).get("magma"))
    if "tiles" in mg:
        f["magma_tiles"] = int(mg.get("tiles") or 0)
    dead = _d(st.get("dead"))
    if "ghosts" in dead:
        f["ghosts"] = int(dead.get("ghosts") or 0)
    # (0.105.0) the sieges on the game's own record (the grudge list) for Grudge-keepers
    try:
        from planner_world import grudge_facts
        f.update(grudge_facts(st, memory))
    except Exception:  # noqa: BLE001
        pass
    civs = [c for c in _l(_d(st.get("diplomacy")).get("civs")) if isinstance(c, dict)]
    if civs:
        # (r2 h8) DF's diplomacy_state_type says "TotalWar" (Peace, TotalWar, NoContact,
        # AcceptingTribute, OfferingTribute, Skirmishing): "War" alone never comes
        f["goblin_wars"] = sum(1 for c in civs if c.get("race") == "GOBLIN"
                               and str(c.get("relation")) in ("War", "TotalWar"))
        f["elf_peace"] = 1 if any(c.get("race") == "ELF" and str(c.get("relation")) == "Peace" for c in civs) else 0
    dp = _d(st.get("diplomacy"))
    ty = memory.tree_year if isinstance(getattr(memory, "tree_year", None), dict) else {}
    if isinstance(dp.get("trees_removed"), int) and isinstance(dp.get("tree_cap"), int) and dp["tree_cap"] > 0 \
            and isinstance(ty.get("base"), int):
        f["tree_quota_share"] = round((dp["trees_removed"] - ty["base"]) / dp["tree_cap"], 2)
    tl = memory.timeline if isinstance(getattr(memory, "timeline", None), dict) else {}
    dry = [x.get("season") for x in _l(tl.get("seasons")) if isinstance(x, dict)
           and isinstance(_d(x.get("avg")).get("drink_pd"), (int, float)) and _d(x.get("avg"))["drink_pd"] < 0.5]
    # years only from before the seasons kept (a year rolls up seasons still listed)
    kept = [x.get("season") for x in _l(tl.get("seasons")) if isinstance(x, dict) and isinstance(x.get("season"), int)]
    first_year = (min(kept) // 4) if kept else None
    dry_years = [x.get("year") for x in _l(tl.get("years")) if isinstance(x, dict)
                 and (first_year is None or (isinstance(x.get("year"), int) and x["year"] < first_year))
                 and isinstance(_d(x.get("avg")).get("drink_pd"), (int, float)) and _d(x.get("avg"))["drink_pd"] < 0.5]
    f["dry_seasons"] = len(dry) + 2 * len(dry_years)
    done = [x for x in _l(tl.get("seasons")) if isinstance(x, dict) and isinstance(_d(x.get("avg")).get("drink_pd"), (int, float))]
    if done:
        f["drink_pd_season"] = _d(done[-1].get("avg"))["drink_pd"]
    locs = _d(_d(st.get("locations")).get("count"))
    if "locations" in st:
        f["libraries"] = int(locs.get("LIBRARY") or 0)
        if isinstance(memory.atlas, dict):
            if f["libraries"]:
                memory.atlas.setdefault("library_since", now)
            else:
                memory.atlas.pop("library_since", None)
            since = memory.atlas.get("library_since")
            if isinstance(since, int) and since <= now:
                f["library_years"] = (now - since) // TICKS_PER_YEAR
    seasons = [d for d in dry if isinstance(d, int)]
    if seasons:
        f["years_since_dry"] = max(0, (now // 1200 // 84 - max(seasons)) // 4)
    # (kept in the atlas: located events fold into clusters after a year)
    if isinstance(memory.atlas, dict):
        if inside:
            memory.atlas["last_inside_death"] = max(e["t"] for e in inside)
        last = memory.atlas.get("last_inside_death")
        if isinstance(last, int):
            if last > now:
                memory.atlas.pop("last_inside_death", None)    # an older save
            else:
                f["years_since_inside_death"] = (now - last) // TICKS_PER_YEAR
    return f


def survey_site(bridge, memory) -> dict | None:
    """The bridge's survey (the main stairs, soil, the fort's heart), kept with
    the atlas's survey; asked for at most once a season (atlas.survey_due), or
    until the master plan is drawn."""
    sv = (memory.atlas or {}).get("survey") or {}
    site = sv.get("site") if isinstance(sv.get("site"), dict) else None
    fresh = site is not None and site.get("tick") == sv.get("tick")
    # (0.104.82) a survey from before the stairwell count: asked again once
    if fresh and "stairwells" not in site and not site.get("asked_stairwells") and site.get("stairs"):
        fresh = False
    if fresh or bridge is None or not hasattr(bridge, "survey"):
        return site if site and not site.get("error") else None
    def keep(s):
        if isinstance(memory.atlas, dict) and isinstance(memory.atlas.get("survey"), dict):
            memory.atlas["survey"]["site"] = s
    try:
        r = bridge.survey()
    except (BridgeError, DFHackError, OSError, ValueError) as e:
        keep({"tick": sv.get("tick"), "error": str(e)[:200]})   # an older bridge: ask again next season
        return None
    if not isinstance(r, dict) or not r.get("ok"):
        keep({"tick": sv.get("tick"), "error": "the survey failed"})
        return None
    site = {k: r.get(k) for k in ("stairs", "stairwells", "soil", "citizen_elevation", "elevation_offset") if k in r}
    site["tick"] = sv.get("tick")
    if "stairwells" not in site:
        site["asked_stairwells"] = True      # an older bridge: not asked again this season
    keep(site)
    return site


def culture_update(state: dict, memory, events: list[dict], key: str) -> None:
    """History shapes the fort's culture; a changed style starts a new era."""
    if not memory.culture:
        memory.culture = new_history()
    # what you turned down leans the weights engine away from it
    memory.culture["learned"] = learning.engine_bonuses(memory)
    # how each defence design held up in sieges, here and in your other forts
    memory.culture["design"] = defence.engine_bonuses(memory)
    # (0.105.15) a siege for culture is one phases confirmed (3+ invaders),
    # not DF's invasion record of a lone thief
    year = (state.get("date") or {}).get("year")
    seen = [e for e in events if not (isinstance(e, dict) and e.get("kind") == "invasion")]
    seen += [{"kind": "invasion", "year": year}] * phases.take_new_sieges(memory)
    for change in culture_events(memory.culture, seen):
        say(f"Culture: {change}")
        journal({"kind": "culture", "fort": key, "change": change})
        chronicle.add(memory, state, "siege" if "siege" in change else "beast", change)
    s = normalize(state)
    if "settings" in s["_errors"]:
        return
    traits = _d(s["settings"].get("traits"))
    # the fort's own seed: settles close calls the same way every time
    memory.culture.setdefault("seed", key)
    # (0.95) its own leanings (drawn once from the seed) and the site's (read
    # again from each full report), leaning the style engine beyond the sliders
    for change in leanings.update(memory.culture, state):
        say(f"Culture: {change}")
        journal({"kind": "culture", "fort": key, "leaning": change})
    # how often a promising defence design is tried instead of the best-known (Caution)
    memory.culture["explore"] = defence.explore(traits, state["date"]["year"])
    profile = profile_from(traits, memory.culture)
    # remember each area's choice: it's kept until something clearly beats it
    memory.culture["choices"] = {a: c["id"] for a, c in choose_all(traits, memory.culture).items()}
    era = update_eras(memory.culture, profile, state["date"]["year"])
    if era:
        say(f"Culture: a new era begins: {era}")
        journal({"kind": "culture", "fort": key, "era": era, "year": state["date"]["year"]})
        chronicle.add(memory, state, "era", f"a new era began: {era}")
        for line in masterplan.new_era(memory, len(memory.culture.get("eras") or []), profile, traits):
            say(f"Plan: {line}")
            chronicle.add(memory, state, "plan", line)
    stocks = s["stocks"] if "stocks" not in s["_errors"] else None
    for change in update_quirks(memory.culture, traits, stocks, state["date"], world_facts(state, memory)):
        say(f"Culture: {change}")
        journal({"kind": "culture", "fort": key, "quirk": change, "year": state["date"]["year"]})
        chronicle.add(memory, state, "quirk", change)


def push_culture(bridge: Bridge, state: dict, memory) -> None:
    """Copy the culture into the save (for the panel's Culture page), only when
    it changed. Display only; nothing in the game reads it."""
    s = normalize(state)
    if "settings" in s["_errors"] or not memory.culture:
        return
    traits = _d(s["settings"].get("traits"))
    profile = profile_from(traits, memory.culture)
    stones = s.get("stone_types") if isinstance(s.get("stone_types"), list) else []
    stone = pick_stone(stones, profile["palette"])
    payload = {"profile": profile,
               "guide": style_guide(profile, stone and stone.get("name"), memory.culture),
               "stone": stone and stone.get("name"),
               "eras": [{"year": e["year"], "title": e["title"]} for e in memory.culture.get("eras", [])],
               "beasts_slain": len(memory.culture.get("beasts_slain", [])),
               "sieges": memory.culture.get("sieges", 0),
               "choices": [{k: c[k] for k in ("name", "choice", "why", "by_ai", "later")}
                           for c in explain(traits, memory.culture)],
               "quirks": [{k: q[k] for k in ("name", "since", "why", "does", "fade")}
                          for q in describe_quirks(memory.culture)],
               "plan": masterplan.lines(memory),
               "phase": phases.line(memory),
               "effects": temperament.effects(s),       # (0.94) the panel's "Now:" line per slider
               "leanings": leanings.panel(memory.culture)}   # (0.95) its "Leans:" line
    try:      # (D0) the fort's design language, for the Culture page (only when it has one)
        import design as _design
        dl = _design.lines(memory.culture)
        if dl:
            payload["design"] = list(dl)[:6]
    except Exception:  # noqa: BLE001  (only words for the panel)
        pass
    # (0.97.1, B9) a short hash is kept, not the whole payload (it was stored
    # in the memory, and could push the save's memory past its budget)
    fingerprint = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    if fingerprint == memory.culture_pushed:
        return
    def done(r, err):
        # (also when refused, e.g. by an older bridge: don't ask again every cycle)
        if err is None and (r.get("ok") or r.get("rejected")):
            memory.culture_pushed = fingerprint

    defer_act(bridge, {"type": "set_culture", "culture": payload}, done)   # (0.105.40) with the next call


def learned_payload(state: dict, memory) -> dict:
    """What the AI has learned, for the panel (Culture tab, Shift-V)."""
    now = abs_tick(state)
    return {"prefs": [{k: d[k] for k in ("text", "weight", "lesson", "inherited", "how", "effect")}
                      for d in learning.describe(memory, now)][:12],
            "tuned": [{"name": c["name"], "value": c["value"], "default": c["default"], "why": c["why"],
                       "date": c["date"]} for c in calibrate.describe(memory, PLANNER_CONFIG)],
            "verdicts": outcomes.summary_lines(memory, 6),
            "waiting": outcomes.waiting_lines(memory, 4),
            "lessons": (defence.lesson_lines(memory, 3) + outcomes.lessons(memory))[:6],
            "log": learning.log_lines(memory, 6),
            "trends": (timeline.trend_lines(memory, 4) + calibrate.evidence(memory))[:6],
            "places": atlas.notable(memory, 4),
            "story": chronicle.lines(memory, 4)}


def push_learned(bridge: Bridge, state: dict, memory) -> None:
    """Copy what the AI has learned into the save for the panel, only when it changed."""
    payload = learned_payload(state, memory)
    fingerprint = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()   # (B9)
    seen = memory.learning.get("pushed") if isinstance(memory.learning, dict) else None
    if fingerprint == seen:
        return
    def done(r, err):
        if err is None and (r.get("ok") or r.get("rejected")):   # (an older bridge refuses it: don't ask every cycle)
            memory.learning["pushed"] = fingerprint

    defer_act(bridge, {"type": "set_learned", "learned": payload}, done)   # (0.105.40) with the next call


def _newest_season(memory) -> int | None:
    """The newest finished season the memory's timeline holds, or None."""
    ss = [s.get("season") for s in ((getattr(memory, "timeline", None) or {}).get("seasons") or [])
          if isinstance(s, dict) and isinstance(s.get("season"), int)]
    return max(ss) if ss else None

"""The season's character decision (14.3, step 1).

Even at the lowest token setting the strategist makes one decision a season
that shows in the fort: it picks from a short menu drawn from the identity
map, and names the season in the chronicle. The scripts keep the fort alive;
this is the judgement they can't make (Design Notes, 3f).

    due(state, memory)                 -> True once each game season
    menu_text()                        -> the menu, for the review's instructions
    check(obj)                         -> (choice dict | None, rejected reasons)
    apply(choice, state, memory)       -> what changed, in words (one line each)

A choice lasts the season (SEASON_TICKS). It is kept in the fort's culture
(saved with the fort) as `season_choice`; the planner reads it:
  raise:<level>   that optional level +3 in the build ladder this season
  focus:<area>    the season's bounded planner adjustments (they expire with
                  the strategist's own after a season)
  name            the next statue garden's name (used once)
"""

from __future__ import annotations

import re

from digest import _d, game_text

SEASON_TICKS = 3 * 28 * 1200
SEASONS = ("spring", "summer", "autumn", "winter")
RAISE_BONUS = 3.0

# levels the ladder chooses among (planner.LADDER_BASE)
RAISE = ("tavern", "library", "temple", "garden", "great hall", "memorial", "barracks", "archery", "jail")
# a season's push, as planner adjustments (multipliers of today's value, or a set value), within
# planner.ADJUST_BOUNDS
FOCUS = {
    "drink": ({"drink_per_dwarf": 1.5}, "brew more: a third more drink kept this season"),
    "food": ({"meals_per_dwarf": 1.5}, "cook more: half again the meals kept this season"),
    "building_stone": ({"blocks_per_dwarf": 1.5}, "cut more blocks this season"),
    "timber": ({"wood_per_dwarf": 1.5}, "fell more trees this season"),
    "crafts": ({"idle_share": 0.67}, "idle hands carve crafts sooner this season"),
}
NAME_RE = re.compile(r"^[A-Za-z' ]{3,40}$")
LINE_MAX = 140


def season_key(state: dict) -> str | None:
    d = _d(state.get("date"))
    if not isinstance(d.get("year"), int) or d.get("season") not in SEASONS:
        return None
    return f"{d['year']}-{d['season']}"


def due(state: dict, memory) -> bool:
    """One character decision a game season."""
    key = season_key(state)
    c = getattr(memory, "culture", None)
    return key is not None and not (isinstance(c, dict) and c.get("season_done") == key)


RETRY_TICKS = 7 * 1200


def wait(memory, now: int) -> None:
    """A season review that couldn't run (no budget, no connection): a week's wait."""
    if not isinstance(getattr(memory, "culture", None), dict):
        memory.culture = {}
    memory.culture["season_retry"] = now + RETRY_TICKS


def waiting(memory, now: int) -> bool:
    c = getattr(memory, "culture", None)
    t = c.get("season_retry") if isinstance(c, dict) else None
    return isinstance(t, int) and 0 <= t - now <= RETRY_TICKS


def menu_text() -> str:
    return (
        "SEASON: also make this season's CHARACTER DECISION, true to the fort's personality, quirks and story:\n"
        "\"season\":{\"choice\":..,\"name\":<optional, 3-40 letters: the next statue garden>,"
        "\"line\":<the chronicle's sentence for this season, max 140 chars>,\"why\":<short>}\n"
        "choice: raise:<" + "|".join(RAISE) + "> (that hall first this season), focus:<"
        + "|".join(FOCUS) + "> (the season's push), or keep.")


def check(obj) -> tuple[dict | None, list[str]]:
    """The model's "season" object, checked; never trusted."""
    rej: list[str] = []
    if not isinstance(obj, dict):
        return None, ["season: missing or not an object"]
    choice = obj.get("choice")
    ok_choices = {f"raise:{k}" for k in RAISE} | {f"focus:{k}" for k in FOCUS} | {"keep"}
    if choice not in ok_choices:
        return None, [f"season: unknown choice {choice!r}"]
    out = {"choice": choice}
    name = obj.get("name")
    if name is not None:
        if isinstance(name, str) and NAME_RE.match(name.strip()):
            out["name"] = " ".join(name.split())
        else:
            rej.append("season: name must be 3-40 letters, spaces or apostrophes")
    line = obj.get("line")
    if isinstance(line, str) and line.strip():
        out["line"] = game_text(" ".join(line.split()), LINE_MAX)
    why = obj.get("why")
    if isinstance(why, str) and why.strip():
        out["why"] = game_text(" ".join(why.split()), 160)
    return out, rej


def apply(choice: dict, state: dict, memory, adjust: dict | None = None) -> list[str]:
    """Keep the choice for the season; return what changed in words. `adjust`
    is the planner's current adjustment table (a focus multiplies today's value)."""
    from planner import ADJUST_BOUNDS, PLANNER_CONFIG, abs_tick
    if not isinstance(memory.culture, dict):
        memory.culture = {}
    now = abs_tick(state)
    key = season_key(state)
    c = memory.culture
    c["season_done"] = key
    kept = {"choice": choice["choice"], "until": now + SEASON_TICKS, "season": key}
    said = []
    kind, _, what = choice["choice"].partition(":")
    if kind == "raise":
        said.append(f"this season the {what} comes first among the halls")
    elif kind == "focus":
        bundle, words = FOCUS[what]
        cur = dict(PLANNER_CONFIG, **{k: v for k, v in (adjust or {}).items() if k in ADJUST_BOUNDS})
        new = {}
        for k, mult in bundle.items():
            lo, hi = ADJUST_BOUNDS[k]
            new[k] = round(max(lo, min(hi, float(cur.get(k, lo)) * mult)), 2)
        kept["adjust"] = new
        memory.adjust.update(new)
        if isinstance(memory.adjust_at, dict):
            memory.adjust_at.update({k: now for k in new})      # they last a season, as the strategist's do
        said.append(words + " (" + ", ".join(f"{k} {v:g}" for k, v in new.items()) + ")")
    else:
        said.append("the fort keeps to its ways this season")
    if choice.get("name"):
        c["set_piece_name"] = choice["name"]
        said.append(f"the next statue garden will be {choice['name']}")
    if choice.get("why"):
        kept["why"] = choice["why"]
    c["season_choice"] = kept
    return said


def active(memory, now: int) -> dict:
    """The season's choice while it lasts, else {}."""
    c = getattr(memory, "culture", None)
    sc = c.get("season_choice") if isinstance(c, dict) else None
    if isinstance(sc, dict) and isinstance(sc.get("until"), int) and now < sc["until"]:
        return sc
    return {}


def raised(memory, now: int) -> str | None:
    ch = str(active(memory, now).get("choice") or "")
    return ch.split(":", 1)[1] if ch.startswith("raise:") else None


# ---------------------------------------------------------------------------
# (0.104.3) The scripted choice: forts without tokens (or whose AI review
# couldn't run by mid-season) still make the season's character decision,
# from the same menu, by rule: what most of the fort is missing, pushed by
# the sliders, the quirks and the fort's own leanings. The AI's job becomes
# choosing better than this (14.3's comparison runs get their baseline).
# ---------------------------------------------------------------------------

AI_GRACE_TICKS = 14 * 1200        # the AI's review has two weeks of the season to choose; then the script does
KEEP_BELOW = 0.12                 # no option scoring this much: the fort keeps to its ways

# the needs each option answers (the bridge's `needs` report)
RAISE_NEEDS = {
    "tavern": ("BeWithFriends", "MakeMerry", "Socialize", "HearEloquence"),
    "library": ("LearnSomething", "ThinkAbstractly"),
    "temple": ("PrayOrMeditate",),
    "garden": ("AdmireArt", "BeExtravagant"),
    "barracks": ("MartialTraining", "Fight"),
}
FOCUS_NEEDS = {"drink": ("DrinkAlcohol",), "food": ("EatGoodMeal",), "crafts": ("CraftObject", "BeCreative")}
# (slider, weight per +100)
SLIDERS = {
    "raise:tavern": (("welfare", 0.15), ("outsiders", 0.1)), "raise:library": (("welfare", 0.1), ("craftsmanship", 0.1)),
    "raise:temple": (("piety", 0.2),), "raise:garden": (("grandeur", 0.2),), "raise:great hall": (("grandeur", 0.2),),
    "raise:memorial": (("piety", 0.1), ("grandeur", 0.1)), "raise:barracks": (("militarism", 0.2),),
    "raise:archery": (("militarism", 0.15),), "raise:jail": (("justice", 0.2),),
    "focus:crafts": (("craftsmanship", 0.15), ("trade", 0.1)), "focus:drink": (("welfare", 0.05),),
    "focus:food": (("welfare", 0.05),), "focus:timber": (("surface", 0.1),), "focus:building_stone": (("industriousness", 0.1),),
}
# quirks (culture ids) that lean the fort toward an option
QUIRKS = {
    "mead_hall": (("raise:tavern", 0.15), ("focus:drink", 0.1)), "thirst_scarred": (("focus:drink", 0.2),),
    "scholars_hold": (("raise:library", 0.2),), "ancestor_halls": (("raise:memorial", 0.2),),
    "haunted": (("raise:memorial", 0.15),), "superstitious": (("raise:temple", 0.15),),
    "legend_proud": (("raise:garden", 0.1), ("raise:great hall", 0.1)), "living_walls": (("raise:garden", 0.1),),
    "goblin_haunted": (("raise:barracks", 0.15), ("raise:archery", 0.1)), "grudge_keepers": (("raise:barracks", 0.1),),
    "merchant_princes": (("focus:crafts", 0.15),), "gem_mad": (("focus:crafts", 0.1),),
    "waste_not": (("focus:timber", 0.1), ("focus:building_stone", 0.1)), "forge_born": (("focus:building_stone", 0.05),),
    "frozen_hold": (("focus:food", 0.1),),
}
WORDS = {
    "raise:tavern": "a tavern to drink and talk in", "raise:library": "a library", "raise:temple": "a temple",
    "raise:garden": "a statue garden", "raise:great hall": "a great hall", "raise:memorial": "a memorial to its dead",
    "raise:barracks": "barracks to train in", "raise:archery": "an archery range", "raise:jail": "a jail",
    "focus:drink": "brewing", "focus:food": "the kitchens", "focus:crafts": "crafts",
    "focus:timber": "felling timber", "focus:building_stone": "cutting stone", "keep": "its old ways",
}


NEED_WORDS = {"tavern": "company and merriment", "library": "learning", "temple": "prayer",
              "garden": "art and finery", "barracks": "training and a fight",
              "drink": "a drink", "food": "a good meal", "crafts": "making things"}
SHORT_WORDS = {"drink": "drink", "food": "meals", "timber": "wood", "building_stone": "blocks"}


def ai_gave_up(state: dict, memory) -> bool:
    """The AI had two weeks of this season and made no choice."""
    d = _d(state.get("date"))
    tick = d.get("tick")
    return isinstance(tick, int) and tick % SEASON_TICKS >= AI_GRACE_TICKS


def _share(s: dict, names, pop: int) -> float:
    n = _d(_d(s.get("needs")).get("needs"))
    return max([int(_d(n.get(k)).get("distracted") or 0) for k in names] or [0]) / max(1, pop)


def score_options(state: dict, memory, cfg: dict | None = None) -> dict:
    """Each menu option's score for this fort this season, with its reason."""
    from planner import PLANNER_CONFIG, level_refused
    cfg = cfg or PLANNER_CONFIG
    s = state
    pop = int(_d(s.get("dwarves")).get("total") or 0)
    traits = _d(_d(s.get("settings")).get("traits"))
    culture = getattr(memory, "culture", None)
    culture = culture if isinstance(culture, dict) else {}
    lean = {}
    try:
        from leanings import totals
        lean = totals(culture)
    except Exception:  # noqa: BLE001
        pass
    held = set(_d(culture.get("quirks")))
    st = _d(s.get("stocks"))
    loc = _d(_d(s.get("locations")).get("count"))
    out: dict = {}

    def add(opt, v, why):
        cur = out.setdefault(opt, [0.0, []])
        cur[0] += v
        if why:
            cur[1].append(why)

    for kind, needs in RAISE_NEEDS.items():
        sh = _share(s, needs, pop)
        if sh > 0:
            add(f"raise:{kind}", sh * 0.6, f"{round(sh * 100)}% of the dwarves long for {NEED_WORDS[kind]}")
    have = {"tavern": loc.get("INN_TAVERN"), "library": loc.get("LIBRARY"), "temple": loc.get("TEMPLE")}
    for kind, n in have.items():
        if n:
            add(f"raise:{kind}", -0.15 * min(2, int(n)), None)        # one stands already: less pressing
    dead = _d(s.get("dead"))
    ghosts = int(dead.get("ghosts") or 0)
    if ghosts or dead.get("unburied"):
        add("raise:memorial", 0.1 + 0.05 * ghosts, f"{ghosts} ghost(s) walk the fort" if ghosts else "the dead wait")
    if pop >= 60:
        add("raise:great hall", 0.05, None)
    for opt, needs in FOCUS_NEEDS.items():
        sh = _share(s, needs, pop)
        if sh > 0:
            add(f"focus:{opt}", sh * 0.4, f"{round(sh * 100)}% of the dwarves long for {NEED_WORDS[opt]}")
    if pop:
        for key, stock, per in (("drink", "drink", "drink_per_dwarf"), ("food", "prepared_meals", "meals_per_dwarf"),
                                ("timber", "wood", "wood_per_dwarf"), ("building_stone", "blocks", "blocks_per_dwarf")):
            want = float(cfg.get(per) or 0) * pop
            have_n = float(st.get(stock) or 0)
            if want > 0 and have_n < want:
                short = 1 - have_n / want
                add(f"focus:{key}", short * 0.5, f"{SHORT_WORDS[key]} short: {int(have_n)} of {int(want)}")
    for opt, pushes in SLIDERS.items():
        for slider, w in pushes:
            v = (traits.get(slider, 0) or 0) + 0.5 * (lean.get(slider, 0) or 0)
            if v:
                add(opt, w * v / 100, None)
    for q, pushes in QUIRKS.items():
        if q in held:
            for opt, w in pushes:
                add(opt, w, f"the fort is {q.replace('_', ' ')}")
    # what may not be built anyway is no choice
    for opt in list(out):
        kind, _, what = opt.partition(":")
        if kind == "raise" and (what not in RAISE or level_refused(s, what, cfg)):
            out.pop(opt)
    return {k: (round(v[0], 3), v[1]) for k, v in out.items()}


def pick(state: dict, memory, cfg: dict | None = None) -> dict:
    """The script's choice for this season, in the same shape as the AI's."""
    import hashlib
    scores = score_options(state, memory, cfg)
    key = season_key(state) or ""
    fort = str(_d(state.get("fort")).get("site_id") or "")

    def tie(opt):          # a small tie-breaker of this fort's own (two default forts choose apart)
        return int(hashlib.sha256(f"{fort}|{key}|{opt}".encode()).hexdigest()[:4], 16) / 65535 * 0.02

    best = max(scores, key=lambda o: scores[o][0] + tie(o), default=None)
    d = _d(state.get("date"))
    when = f"{str(d.get('season') or '').capitalize()} of {d.get('year')}"
    if best is None or scores[best][0] < KEEP_BELOW:
        return {"choice": "keep", "why": "nothing presses this season",
                "line": f"{when}: the fort kept to its old ways.", "by": "script"}
    why = "; ".join(scores[best][1][:2]) or "the fort's leanings"
    kind, _, what = best.partition(":")
    line = (f"{when}: the fort set its heart on {WORDS[best]}." if kind == "raise"
            else f"{when}: the fort turned its hands to {WORDS[best]}.")
    return {"choice": best, "why": game_text(why, 160), "line": game_text(line, LINE_MAX), "by": "script"}

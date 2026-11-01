"""The fort's temperament in words (phase 14.1, 0.94): what each slider is
doing in this fort right now, for the panel's "Now:" line under the selected
slider. One place that lists every slider's direct effects, so the panel, the
docs and the tests agree with the planner (the numbers come from the planner's
own functions). Style leanings (the weights engine) are named per slider from
choices.json; the Culture page shows what they chose.

    effects(state, cfg) -> {trait id: "what it does now"}
"""

from __future__ import annotations

from planner import (PLANNER_CONFIG, cistern_pop, factor, gatherers, growth_mode, jail_plan, keeps_treasures,
                     mining_plan, noble_room_kinds, outsider_orders, petition_lean, room_size, soldier_share, spare_mechanisms,
                     stone_tidiness, tavern_factor, trade_margin_for, woodcutters, _traits, player_rules)
from weights import data as choices_data

AREA_WORDS = {"halls": "hall shape", "finish": "finish", "statues": "statues", "materials": "stone",
              "defence": "gate design", "traps": "traps", "level_doors": "level doors",
              "worship": "temples", "layout": "the plan's pattern"}


def style_leanings(tid: str) -> str:
    """The style areas this slider leans (from choices.json), in words."""
    out = []
    for area_id, area in choices_data()["areas"].items():
        if any(abs(o.get("sliders", {}).get(tid, 0)) >= 0.2 for o in area["options"].values()):
            out.append(AREA_WORDS.get(area_id, area_id))
    return ", ".join(out)


def _pct(x: float) -> str:
    return f"{round(x * 100):g}%"


def _x(f: float) -> str:
    return f"x{f:.2g}"


def effects(state: dict, cfg: dict | None = None) -> dict:
    cfg = cfg or PLANNER_CONFIG
    t = _traits(state)
    v = lambda k: t.get(k, 0)                                     # noqa: E731
    out = {}

    share = soldier_share(state, cfg)
    mil = [f"{_pct(share)} of citizens in squads"]
    if v("militarism") >= cfg["train_rotate_below_militarism"]:
        mil.append("everyone trains, barracks early")
    elif v("militarism") <= -50:
        mil.append("no squad training")
    if v("militarism") >= 30:
        mil.append("mercenaries may stay")
    if v("militarism") >= cfg["archery_more_militarism"]:
        mil.append("barracks and ranges grow with the army")      # (0.104.161)
    out["militarism"] = "; ".join(mil)

    mode, n = growth_mode(state, cfg)
    rules_ = player_rules(state)
    if rules_["fort_goal"] == "maintain":
        out["growth"] = "Maintain (Rules tab): held at the size it had, Growth set aside"
    else:
        out["growth"] = ("no population cap" if mode == "uncapped" else
                         f"no newcomers; a dwarf sent away every {n} days" if mode == "shrink" else
                         f"population target {n}")
    # (0.97) one control: Growth (or Maintain) is the target; the Rules switch
    # only says whether DF's own cap is set to it
    out["growth"] += "; DF's cap set to it" if rules_["set_pop_cap"] else "; DF's cap left to you"

    w = v("welfare")
    out["welfare"] = (f"{'lavish' if w >= 50 else 'easy' if w <= -50 else 'fine'} meals; hospital "
                      f"{_x(factor(t, 'welfare'))}, tavern {_x(tavern_factor(t))}" + ("; no tailor" if w < -50 else ""))
    out["stockpile"] = f"food, drink, wood and block reserves {_x(factor(t, 'stockpile'))}"
    out["agriculture"] = ("no farms (hunt and gather)" if v("agriculture") <= -100
                          else f"farm size {_x(factor(t, 'agriculture'))}")
    h = v("husbandry")
    out["husbandry"] = (f"pastures {_x(max(1.0, factor(t, 'husbandry')))}; "
                        + ("nestboxes on" if h >= 0 else "no nestboxes")
                        + ("; big herds culled" if h <= 0 else "; herds kept"))
    out["size"] = f"bedrooms {room_size(t)}x{room_size(t)}"
    sp = max(-100, min(100, v("spacing")))
    out["spacing"] = (f"corridors {0 if sp <= 0 else int(10 * sp / 100)}-{int(25 + (sp if sp < 0 else 0) * 0.17)} tiles"
                      + ("; wider gaps between rooms" if sp >= 50 else ""))
    tidy = stone_tidiness(t, cfg)
    out["industriousness"] = ((f"stone cleared past {tidy[0]} loose (storage up to {tidy[1]} tiles)" if tidy
                               else "stone left where it's dug")
                              + f"; idle work from {_pct(0.25 / factor(t, 'industriousness'))} idle")
    craft = v("craftsmanship")
    out["craftsmanship"] = ("metal furniture when bars are spare" if craft >= 50 or v("grandeur") >= 50
                            else "stone furniture") + (f"; style: {style_leanings('craftsmanship')}")
    g = v("grandeur")
    out["grandeur"] = (("statue gardens every " + f"{cfg['garden_every_years'] / factor(t, 'grandeur'):.1f} years"
                        if g > 0 or craft > 0 else "no statue gardens")
                       + f"; style: {style_leanings('grandeur')}")
    out["surface"] = (("a walled keep above the way in" if v("surface") >= cfg["keep_surface_min"]
                       else "no keep (from +50)")
                      + f"; woodcutters {woodcutters(t, False)}, gatherers {gatherers(t, False)}")
    mp = mining_plan(t, cfg)
    out["mining"] = (("only the levels it needs; " if mp["need_only"] else "")
                     + (f"veins mined while bars < {mp['bars_below']}, {mp['vein_tiles']} tiles at a time"
                        if mp["veins"] else "no ore veins mined (metal by trade)")
                     + f"; quarries of {mp['quarry']}")
    kinds = noble_room_kinds(t)
    out["deference"] = (("mandates ignored" if v("deference") < -50 else "mandates obeyed")
                        + "; nobles given " + (", ".join(k.replace("dining", "dining room") for k in kinds)
                                               if kinds else "no rooms")
                        + ("; suites dug early" if v("deference") >= 50 else ""))
    out["caution"] = (("alarm for any danger within 10 levels" if v("caution") >= 100 else "alarm for dangers that can reach us")
                      + f"; defence trials {_pct(max(0.0, min(0.35, 0.15 - 0.0015 * v('caution'))))} a year")
    out["fortification"] = ("fortified doors on every level" if v("fortification") >= 70
                            else f"style: {style_leanings('fortification')}")
    # (0.104.161) temple petitions declined at a low leaning; more temples as a devout fort grows
    temple_lean = petition_lean({"loc": "TEMPLE"}, t)[0]
    out["piety"] = ("temple petitions declined" if temple_lean <= cfg["petition_decline_lean"]
                    else "grand temple petitions agreed" if v("piety") > 0 else "temple petitions agreed") \
        + ("; more temples as it grows" if v("piety") >= cfg["temple_more_piety"]
           else "; temples by need only") + f"; style: {style_leanings('piety')}"
    out["trade"] = f"crafts kept to sell: {2 * factor(t, 'trade'):.1f} per dwarf"
    oo = outsider_orders(t)
    out["outsiders"] = ("no residents or new citizens" if oo["closed"] else
                        "guests welcome (performers, scholars, refugees)" if oo["guests"] else
                        "guests asked about; hunters and mercenaries by Militarism") \
        + f"; tavern {_x(2 ** (v('outsiders') / 200))}"
    out["greed"] = (f"gives {trade_margin_for(t, cfg):g}x what it gets in trade"
                    + ("; gems and precious metal kept home" if keeps_treasures(t) else ""))
    cp = cistern_pop(t, cfg)
    sm = spare_mechanisms(t)
    out["engineering"] = ((f"a cistern from {cp} dwarves" if cp else "no cistern")
                          + (f"; {sm} mechanisms kept spare" if sm else "")
                          + f"; style: {style_leanings('engineering') or 'none'}")
    out["verticality"] = f"style only for now: {style_leanings('verticality') or 'none'} (acts when the plan is drawn)"
    jp = jail_plan(t, cfg, 100)
    out["justice"] = ((f"a jail from {jp['min_dwarves']} dwarves, {jp['cells']} cells per 100"
                       + ("; a prison as it grows" if v("justice") >= cfg["prison_justice_at"] else "")) if jp
                      else "no jail: the sheriff beats or lets go")
    return out

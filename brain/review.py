"""One strategist review, start to finish: decide whether one is due, check the
token budget, ask Claude, check the answer, and turn it into proposals that go
through the same safety limits as the local planner's.

Kept separate from overseer.py so it can be tested without a game or a network.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from culture import apply_style, explain, layout_style, new_history, pick_stone, profile_from, style_guide
from quirks import describe as describe_quirks
from digest import _d, normalize
import calibrate
import learning
import memstore
from planner import PLANNER_CONFIG, TICKS_PER_DAY, Memory, Proposal, abs_tick, level_refused
from strategist import check_answer, detect, instructions, review_message, shown_rules
import chronicle
import season as season_mod
from tokens import TokenBank, ai_plan, budget_settings, event_review_allowed, routine_due, routine_interval_ticks

CHARS_PER_TOKEN = 2.5            # measured on fort digests with the current tokenizer
EXPECTED_ANSWER_TOKENS = 400     # the bank is charged what's actually used
PENDING_KIND_DAYS = 3            # an event still counts for an event review this long
MAX_PENDING_EVENTS = 40


@dataclass
class ReviewOutcome:
    proposals: list = field(default_factory=list)
    journal: dict | None = None      # what to write to the decision log, if anything
    say: list = field(default_factory=list)


def snapshot(state: dict) -> dict:
    """The small slice of a report that event detection compares next cycle."""
    s = normalize(state)
    o, dw = s["others_on_map"], _d(s.get("dwarves"))
    return {"others_on_map": {"threats_that_can_reach_dwarves": o.get("threats_that_can_reach_dwarves", 0),
                              "merchants": o.get("merchants", 0)},
            "dwarves": {"stress": _d(dw.get("stress")), "total": dw.get("total", 0)}}


def compact_event(e: dict) -> dict:
    return {k: e.get(k) for k in ("kind", "topic", "own_civ", "animal", "hostile") if e.get(k) is not None}


def note_events(state: dict, memory: Memory, bank: TokenBank | None, events: list[dict]) -> list[str]:
    """Every cycle: remember events for the next review, detect big ones, top up
    the bank for them. Returns the kinds detected this cycle."""
    if "date" in normalize(state)["_errors"]:
        # (0.105.26) no date: events wait for the next cycle, nothing is topped up on a made-up y0 tick
        memory.pending_events = (memory.pending_events + [compact_event(e) for e in events])[-MAX_PENDING_EVENTS:]
        return []
    now = abs_tick(state)
    memory.pending_events = (memory.pending_events + [compact_event(e) for e in events])[-MAX_PENDING_EVENTS:]
    kinds = detect(memory.prev_snapshot or None, state, events)
    memory.prev_snapshot = snapshot(state)
    memory.pending_kinds = [k for k in memory.pending_kinds
                            if 0 <= now - k.get("tick", 0) < PENDING_KIND_DAYS * TICKS_PER_DAY]
    for k in kinds:
        st = state.get("settings")
        if bank is not None and isinstance(st, dict) and ("token_bank_max" in st or "ai_frequency" in st):
            bank.top_up(k, now, budget_settings(st))
        if k not in {p["kind"] for p in memory.pending_kinds}:
            memory.pending_kinds.append({"kind": k, "tick": now})
    return kinds


TOKEN_RATIO_RANGE = (0.5, 4.0)


def token_ratio(memory) -> float:
    """(0.104.89) What a call really costs against the estimate, learned (1 at first)."""
    r = getattr(memory, "token_ratio", None)
    return r if isinstance(r, (int, float)) and TOKEN_RATIO_RANGE[0] <= r <= TOKEN_RATIO_RANGE[1] else 1.0


def learn_token_ratio(memory, used: int, estimate: int) -> None:
    if not used or not estimate:
        return
    seen = max(TOKEN_RATIO_RANGE[0], min(TOKEN_RATIO_RANGE[1], used / estimate))
    memory.token_ratio = round(0.7 * token_ratio(memory) + 0.3 * seen, 3)


def apply_steer(memory, steer: list, now: int) -> list[str]:
    """(0.104.89) The strategist's raises (a week) and holds (its days) into memory."""
    if not isinstance(getattr(memory, "steer", None), dict):
        memory.steer = {}
    out = []
    for s in steer or []:
        days = 7 if s["type"] == "raise" else int(s.get("days") or 7)
        memory.steer[s["rule"]] = {"mode": s["type"], "until": now + days * TICKS_PER_DAY, "why": s.get("why") or ""}
        out.append(f"{s['type']} {s['rule']} for {days} day(s)" + (f": {s['why']}" if s.get("why") else ""))
    return out


def maybe_review(state: dict, memory: Memory, bank: TokenBank, backend, bridge_info: dict,
                 planner_notes: list[str], today=None, proposals: list | None = None) -> ReviewOutcome:
    """Run a strategist review if one is due and affordable."""
    out = ReviewOutcome()
    s = normalize(state)
    if ("settings" in s["_errors"]
            or ("token_bank_max" not in s["settings"] and "ai_frequency" not in s["settings"])):
        out.say.append("AI review skipped: the AI settings couldn't be read from the game")
        return out
    if "date" in s["_errors"]:
        # (0.105.26) a review on a made-up y0 date would schedule, bank and pick the season wrongly
        out.say.append("AI review skipped: the game's date couldn't be read")
        return out
    settings = budget_settings(s["settings"])
    now = abs_tick(state)
    plan = ai_plan(settings)                     # how often, how long (the two AI sliders)
    bank.accrue(now, settings)

    kinds = [k["kind"] for k in memory.pending_kinds]
    # (0.103.20) one character decision a season, at any setting: the review
    # that makes it may come early (the lowest setting reviews rarely)
    season_due = season_mod.due(state, memory) and not season_mod.waiting(memory, now)
    if kinds and event_review_allowed(bank, now, plan):
        reason, important = "event: " + ", ".join(kinds), True
    elif routine_due(bank, now, plan) or season_due:
        reason, important = ("season" if season_due else "routine"), False
    else:
        return out

    # (metal gear needs a named metal; the planner orders that itself)
    recipes = {r for r in (bridge_info.get("recipes") or []) if not str(r).startswith("metal_")}
    tools = set(bridge_info.get("tools") or [])
    my_orders = {o["id"] for o in s["orders"] if o.get("by_ai") and isinstance(o.get("id"), int)}
    build = {k: bridge_info.get(k) or [] for k in ("level_kinds", "stockpiles", "workshops")}
    build["digging_ids"] = [p.get("id") for p in s["projects"].get("open") or []
                            if isinstance(p, dict) and p.get("phase") == "dig"]
    history = memory.culture or new_history()
    traits = _d(s["settings"].get("traits"))
    profile = profile_from(traits, history)
    build["memorials"] = profile["memorials"]
    loc = s.get("locations") if isinstance(s.get("locations"), dict) else {}
    build["temple_allowed"] = not _d(loc.get("count")).get("TEMPLE") and "locations" not in s["_errors"]
    stone = pick_stone(s.get("stone_types") if isinstance(s.get("stone_types"), list) else [], profile["palette"])
    eras = history.get("eras") or []
    culture = {"profile": profile, "guide": style_guide(profile, stone and stone.get("name"), history),
               "stone": stone and stone.get("name"), "era": eras[-1]["title"] if eras else None,
               "choices": explain(traits, history), "quirks": describe_quirks(history),
               # what the player turned down, and the targets that tuned themselves
               "learned": learning.brief(memory),
               "tuned": [f"{c['key']}={c['value']} (from {c['default']}: {c['why']})"
                         for c in calibrate.describe(memory, PLANNER_CONFIG)] + calibrate.evidence(memory)[:2],
               # the fort's memory: trends, notable places, the latest of its story
               "memory": memstore.brief(memory)}
    instr = instructions(sorted(recipes), sorted(tools), build, season_menu=season_due)
    from planner import player_rules
    lockout = None
    try:      # (0.105.26) the visitor lockout after a heist or a visitor's killing (memory, not the report)
        from planner_visitors import heist_lockout
        last = heist_lockout(s, memory, PLANNER_CONFIG)
        if last:
            days = int(PLANNER_CONFIG.get("heist_lockout_days") or 0) - (now - last[0]) // TICKS_PER_DAY
            lockout = (f"VISITORS KEPT OUT after a heist or a visitor's killing ({len(memory.heists)} on record, "
                       f"last {(now - last[0]) // TICKS_PER_DAY} days ago): about {max(1, days)} more day(s)")
    except Exception:  # noqa: BLE001  (only words for the review)
        pass
    msg = review_message(state, reason, planner_notes, memory.recent_actions, memory.adjust,
                         memory.pending_events, culture, news=plan["news"],
                         proposals=proposals, steer=getattr(memory, "steer", None),
                         wants=getattr(memory, "strategist_wants", None), rules=player_rules(s), lockout=lockout)
    think = plan["thinking_events"] if important else plan["thinking_routine"]
    effort = {"model": plan["model_events"] if important else plan["model_routine"],
              "thinking": think, "answer_tokens": plan["answer_tokens"]}
    raw_estimate = (int((len(instr) + len(msg)) / CHARS_PER_TOKEN)
                    + min(EXPECTED_ANSWER_TOKENS, plan["answer_tokens"]) + think)
    # (0.104.89) corrected by what the calls really cost (14.0's audit: about
    # twice the old estimate)
    estimate = int(raw_estimate * token_ratio(memory))
    ok, why = bank.can_spend(estimate, settings, is_event=important, today=today)
    if not ok:
        # Try again tomorrow (game time) rather than every cycle.
        if not important:
            bank.last_routine_tick = now - routine_interval_ticks(plan) + TICKS_PER_DAY
        if season_due:
            season_mod.wait(memory, now)        # the season's decision: tried again in a week, not every cycle
        out.say.append(f"AI review ({reason}) skipped: {why}")
        out.journal = {"kind": "review_skipped", "reason": reason, "why": why, "estimate": estimate}
        return out

    # Mark it as done before asking, so a failure doesn't cause a retry storm.
    if important:
        bank.event_reviews.append(now)
    else:
        bank.last_routine_tick = now
    try:
        reply = backend.ask(instr, msg, important=important, effort=effort)
    except Exception as e:  # noqa: BLE001 - any connection problem: log it, carry on with the planner
        if not important:
            bank.last_routine_tick = now - routine_interval_ticks(plan) + TICKS_PER_DAY
        if season_due:
            season_mod.wait(memory, now)
        out.say.append(f"AI review ({reason}) failed: {type(e).__name__}: {str(e)[:200]}")
        out.journal = {"kind": "review_failed", "reason": reason, "error": f"{type(e).__name__}: {e}"[:500]}
        return out

    used = reply.budget_tokens
    bank.spend(used, now, reason, today=today)
    learn_token_ratio(memory, used, raw_estimate)
    answer = check_answer(reply.text, recipes, tools, my_orders, build,
                          shown=shown_rules(proposals, memory.recent_actions))
    # (0.104.89) its raises and holds of the planner's rules, and what it wants to see
    steer_lines = apply_steer(memory, answer.steer, now)
    memory.strategist_wants = list(answer.want)

    actions = []
    for a in answer.actions:
        # (0.97) the Rules tab's level switches, the Maintain goal and Mining
        # -100 hold for the strategist's levels as for the planner's
        why = level_refused(s, a.get("kind")) if a["type"] == "start_project" else None
        if why:
            answer.rejected.append(f"start_project {a.get('kind')}: {why}")
            continue
        if a["type"] == "set_style":
            # The style lives with the overseer (and is copied into the save);
            # nothing in the game changes now.
            if not memory.culture:
                memory.culture = new_history()
            apply_style(memory.culture, {k: v for k, v in a.items() if k != "type"}, traits)
            actions.append(a)
            continue
        if a["type"] == "start_project":
            a = dict(a, style=layout_style(profile_from(traits, memory.culture or new_history())))
        if a["type"] == "civ_alert" and not a["on"] and s.get("civ_alert") and not memory.ai_alert_raised:
            answer.rejected.append("civ_alert off: the player raised this alert; the AI won't lower it")
            continue
        actions.append(a)
        # A new level from the strategist shares the planner's building limits.
        rule = "build" if a["type"] == "start_project" else "strategist"
        out.proposals.append(Proposal(rule, a, f"strategist: {answer.note or 'no reason given'}",
                                      1, a["type"] == "work_order"))
    memory.adjust.update(answer.adjust)
    if isinstance(memory.adjust_at, dict):            # (0.97.1) each lasts a season from now
        memory.adjust_at.update({k: now for k in answer.adjust})
    season_said = []
    if season_due:
        if answer.season is None:
            # nothing chosen: the fort keeps to its ways; asked again next season
            answer.season = {"choice": "keep", "why": "no character decision in the reply"}
        season_said = season_mod.apply(answer.season, state, memory, memory.adjust)
        line = answer.season.get("line")
        chronicle.add(memory, state, "season", line or "; ".join(season_said))
    memory.pending_events = []
    memory.pending_kinds = []

    out.say.append(f"AI review ({reason}, {reply.model}, thinking {plan['effort_word'].lower()}): {used:,} tokens, "
                   f"{int(bank.balance):,} left. {answer.note}")
    for line in season_said:
        out.say.append(f"  Season: {line}" + (f" ({answer.season['why']})" if answer.season.get("why") else ""))
    if season_due and answer.season.get("line"):
        out.say.append(f"  Chronicle: {answer.season['line']}")
    if answer.adjust:
        out.say.append(f"  AI adjusted the planner: {answer.adjust}")
    for line in steer_lines:
        out.say.append(f"  AI steers: {line}")
    for r in answer.rejected:
        out.say.append(f"  AI suggestion thrown out: {r}")
    out.journal = {"kind": "review", "reason": reason, "model": reply.model, "tokens": used,
                   "usage": {"in": reply.input_tokens, "out": reply.output_tokens,
                             "cache_write": reply.cache_write_tokens, "cache_read": reply.cache_read_tokens},
                   "note": answer.note, "adjust": answer.adjust, "actions": actions,
                   "steer": answer.steer, "want": answer.want,
                   "season": answer.season if season_due else None,
                   "rejected": answer.rejected, "bank_left": int(bank.balance)}
    return out

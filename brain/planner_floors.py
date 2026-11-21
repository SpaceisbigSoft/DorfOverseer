"""(layout B) Hallway-first floors: the floor hint on every new level, at send time.

From this version a new level is cut into its rooms and each goes into the
next free slot along a floor's 3-wide main hall (lua/ai-builder-floors.lua);
a level the floor cannot take is placed as before. Which floors a level is
offered, on which hall and by what grammar (gaps, runs, turns) is the
`floor` key of its start_project: masterplan_floors.hint(memory, action, s,
traits, cfg) computes it (the master plan's floor table and
floor_grammar.grammar).

floor_action (applied by the overseer to the action it sends, after
planner_shopslots.shop_level_action, so plan()'s proposals, the journal,
planner.record and masterplan.note_result keep the proposal's own action
and no plan snapshot moves) puts that hint on every start_project, whoever
proposed it (a rule, the strategist). A dict or False (classic on purpose)
is passed on; None, a missing masterplan_floors or any error leaves the
action without a `floor` key, and the builder then makes its own plain
hint. The Rules switch (settings `floor_layout` = "classic") turns it off.
(r3 g3) The hint sent goes on the level's journal line beside its action,
as `floor_hint` (journal_hint), so the journal shows the floors offered.

floor_outcome and not_on_floor_words are the journal line's words for the
builder's answer: the floor a level went onto, or why it did not.
"""

from __future__ import annotations

from digest import _d
from planner_config import PLANNER_CONFIG

NOT_ON_FLOOR_MAX = 120       # characters of the builder's reasons in the outcome words


def _traits_of(s: dict) -> dict:
    """The sliders as the planner reads them (planner_core._traits); none
    for a state without readable settings."""
    try:
        from planner_core import _traits      # here: planner_core is heavy, and only a level needs it
        return _d(_traits(s))
    except Exception:  # noqa: BLE001
        return {}


# (r3 g3) the floor hint floor_action last put on a level, for the journal line
# that follows the send (journal_hint); taken there, cleared by every call
LAST_SENT: dict = {}


def floor_action(action: dict, s: dict, memory, cfg: dict = PLANNER_CONFIG) -> dict:
    """The start_project as sent to the bridge: a copy with `floor` set from
    masterplan_floors.hint (a dict, or False). Any other action, a level that
    already has `floor`, a fort at "classic", a hint of None, or an error:
    the action as it is (the same object). Never raises. (r3 g3) The hint
    set is kept in LAST_SENT for journal_hint."""
    LAST_SENT.clear()
    try:
        if not isinstance(action, dict) or action.get("type") != "start_project" \
                or not isinstance(action.get("kind"), str) or "floor" in action:
            return action
        s = s if isinstance(s, dict) else {}
        if _d(s.get("settings")).get("floor_layout") == "classic":
            return action
        import masterplan_floors      # group B11's; without it the builder's own default stands
        h = masterplan_floors.hint(memory, action, s, _traits_of(s), cfg if isinstance(cfg, dict) else PLANNER_CONFIG)
        if h is not False and not isinstance(h, dict):
            return action
        b = dict(action)
        b["floor"] = h
        LAST_SENT.update({"type": action.get("type"), "kind": action.get("kind"), "floor": h})
        return b
    except Exception:  # noqa: BLE001  (the builder's own default stands)
        return action


def journal_hint(action: dict, cfg: dict = PLANNER_CONFIG) -> dict:
    """(r3 g3) The journal line's extra key for the send just made:
    {"floor_hint": <the hint floor_action put on it (a dict, or False)>}, so
    the journal, the ledger and seen.py see the floors a level was offered.
    The line's `action` stays the proposal's own (as planner.record and
    masterplan.note_result have it). {} when no hint was sent for this
    action (another action, one with its own `floor`, a dry run's line) or
    the switch r3g3_journal_floor_hint is off. Takes the hint: a second call
    gets {}. Never raises."""
    try:
        sent = dict(LAST_SENT)
        LAST_SENT.clear()
        if not sent or not isinstance(action, dict) or "floor" in action \
                or not _d(cfg).get("r3g3_journal_floor_hint", True):
            return {}
        if action.get("type") != sent.get("type") or action.get("kind") != sent.get("kind"):
            return {}
        return {"floor_hint": sent.get("floor")}
    except Exception:  # noqa: BLE001
        return {}


def _whole(v):
    """A whole number out of the answer, or None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        return None
    return int(v)


def floor_outcome(result: dict) -> str | None:
    """The outcome words of a start_project that went onto a floor ("done: on
    floor #3 (elevation 12), along the east hall, 39 tiles of new hall", and
    ", a new floor"); None when the answer has no `floor` dict. Never raises."""
    try:
        f = result.get("floor") if isinstance(result, dict) else None
        if not isinstance(f, dict):
            return None
        fid, elev = _whole(f.get("id")), _whole(f.get("elevation"))
        if elev is None:
            elev = _whole(result.get("elevation"))
        out = "done: on " + (f"floor #{fid}" if fid is not None else "a floor")
        if elev is not None:
            out += f" (elevation {elev})"
        arm = f.get("arm")
        if isinstance(arm, str) and arm.strip():
            out += f", along the {arm.strip()[:24]} hall"
        new = _whole(f.get("hall_new"))
        if new is not None:
            out += (f", {new} tile{'' if new == 1 else 's'} of new hall" if new > 0 else ", no new hall")
        if f.get("new_floor") is True:
            out += ", a new floor"
        return out
    except Exception:  # noqa: BLE001
        return None


def not_on_floor_words(result: dict) -> str:
    """" (not on a floor: <why>)" for an answer with `not_on_floor` (hallway
    mode was on and the level went the classic way), the reasons cut to
    NOT_ON_FLOOR_MAX characters; "" otherwise. Never raises."""
    try:
        why = result.get("not_on_floor") if isinstance(result, dict) else None
        if not isinstance(why, str):
            return ""
        why = " ".join(why.split())
        if not why:
            return ""
        if len(why) > NOT_ON_FLOOR_MAX:
            why = why[:NOT_ON_FLOOR_MAX - 3].rstrip() + "..."
        return f" (not on a floor: {why})"
    except Exception:  # noqa: BLE001
        return ""

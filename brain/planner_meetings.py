"""(0.105.47) Meetings opened by the AI.

The 8-13 Nov run answered no meeting in six forts: DF queues a diplomat's or
the liaison's meeting behind its purple diplomacy light (the bridge's
`meetings.popups`, the pulse's `meeting_waiting`) and opens the meeting
screen only when someone clicks it. The AI noted "a meeting waits to be
shown in DF ... the game runs on meanwhile" and nobody clicked; the popup ran
out and the diplomats "left unhappy" (gamelogs: 21-93 a fort). answer_meeting
needs the screen open, so it never ran.

Now the overseer's main loop opens it (the bridge's `open_meeting`, lua/
ai-meeting-open.lua) under the same rules as its meeting answers: autopilot,
an unattended run (nobody at the game: the keeper or --unattended), not
halted, not held by the keeper's pin, no stop file, no meeting or trade screen
already open, and at most once every `meeting_open_every_s`. A player at the
game is never interrupted: the light is theirs to click then.
"""

from __future__ import annotations

from digest import _d
from planner_config import PLANNER_CONFIG

__all__ = ["MEETING_OPEN_EVERY_S", "meeting_open_due", "meeting_open_said", "meeting_reopen_wait"]

MEETING_OPEN_EVERY_S = float(PLANNER_CONFIG.get("meeting_open_every_s", 60))   # (0.105.47) a light clicked at most this often


def meeting_open_due(status: dict, autopilot: bool, unattended: bool, halted: bool, held_pin, stopped: bool,
                     since_last: float, every: float = MEETING_OPEN_EVERY_S) -> bool:
    """Whether the main loop clicks the diplomacy light now. `status` is the
    bridge's pulse (`meeting_waiting`, `meeting`, `trade_open`, `in_fort`)."""
    st = _d(status)
    if not (autopilot and unattended and st.get("in_fort")):
        return False
    if halted or held_pin or stopped:
        return False
    if st.get("meeting") or st.get("trade_open") or st.get("saving"):
        return False
    try:
        waiting = int(st.get("meeting_waiting") or 0)
    except (TypeError, ValueError):
        waiting = 0
    return waiting > 0 and since_last >= every


def meeting_reopen_wait() -> float:
    """After the overseer left a meeting screen it couldn't answer, how long
    (real seconds) before the light is clicked again: each opening holds the
    game still until the 2-minute leave, so a meeting the AI can't answer is
    not reopened every minute."""
    return float(PLANNER_CONFIG.get("meeting_reopen_after_s", 1800))


def meeting_open_said(r: dict) -> str | None:
    """The keeper log's line for an open_meeting answer (None: nothing worth saying)."""
    r = _d(r)
    if r.get("clicking"):
        how = {"picture": "found by its picture", "shown": "where it was shown"}.get(str(r.get("via")), "")
        return (f"Unattended: a meeting waited behind DF's diplomacy light ({r.get('popups') or 1} waiting): "
                f"the AI clicked the light ({how}) to open it and answer it.")
    if r.get("rejected"):
        return f"Unattended: a meeting waits in DF and the AI couldn't open it: {r.get('error')}"
    return None

"""Co-pilot answer ids (brain/overseer.py proposal_id): an answer given in the
game is kept under the question's id, so the id must stay the same from one
cycle to the next, across a restart and across versions, while the fort's size
changes the request.

    python tests/test_copilot_ids.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import overseer  # noqa: E402
from planner import Proposal  # noqa: E402
import test_overseer as T  # noqa: E402   (its fakes; its tests don't run here)

test = T.test          # (the overseer tests' reset before each: memory, journal, printed lines)


@test("ids are pinned: the same question gets the same id as in every earlier version (answers saved in forts)")
def _():
    # An answer waiting in a live fort's save is matched by these: a change to
    # proposal_id (the keys, the hash, the rule in it) would drop every answer
    cases = [("build", {"type": "start_project", "kind": "bedrooms", "rooms": 32, "room_size": 3}, "bca9e057"),
             ("tools", {"type": "tool", "name": "autochop", "enabled": False}, "b0c2ef0d"),
             ("farms", {"type": "farm_plots", "tiles": 30, "dig": True}, "e231bacd"),
             ("squad", {"type": "create_squad", "squad_id": 3, "size": 10}, "3fcb3c68")]
    for rule, action, want in cases:
        got = overseer.proposal_id(Proposal(rule, action, "any reason", 3))
        assert got == want, (rule, action, got)


@test("ids: sizes, counts, the reason and the key order don't change the id; what is asked does")
def _():
    pid = lambda rule, a: overseer.proposal_id(Proposal(rule, a, "why", 3))        # noqa: E731
    base = pid("build", {"type": "start_project", "kind": "bedrooms", "rooms": 32, "room_size": 3})
    assert pid("build", {"room_size": 4, "rooms": 40, "kind": "bedrooms", "type": "start_project"}) == base
    assert overseer.proposal_id(Proposal("build", {"type": "start_project", "kind": "bedrooms", "rooms": 8},
                                         "another reason", 1)) == base
    assert pid("build", {"type": "start_project", "kind": "dining", "rooms": 32}) != base         # another level
    assert pid("tombs_ghosts", {"type": "start_project", "kind": "bedrooms", "rooms": 32}) != base  # another rule
    assert pid("squad", {"type": "create_squad", "squad_id": 3}) != pid("squad", {"type": "create_squad", "squad_id": 4})


@test("co-pilot: a Yes given under the id asked is acted on after migrants change the request")
def _():
    b = T.young("copilot")
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    first = b.reports[-1]["pending"]
    assert len(first) == 1 and "bedrooms" in first[0]["text"], first
    assert "start_project" not in T.kinds(b)                                       # asked, not done
    b._state["dwarves"]["total"] += 40                                            # migrants: more rooms wanted
    b.advance(1)
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    again = [p for p in b.reports[-1]["pending"] if "bedrooms" in p["text"]]
    assert [p["id"] for p in again] == [first[0]["id"]], (first, again)          # the same question
    assert again[0]["text"] != first[0]["text"], "(the request did change)"
    b.decisions[first[0]["id"]] = "yes"                                           # answered in the game
    b.advance(1)
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    started = [a for a in b.acted if a["type"] == "start_project"]
    assert [a["kind"] for a in started] == ["bedrooms"], started
    assert not [p for p in b.reports[-1]["pending"] if "bedrooms" in p["text"]], b.reports[-1]["pending"]


if __name__ == "__main__":
    finish()

"""(r4 merge) The player spends no extra money: a subscription rate-limit event saying
pay-as-you-go "extra usage" is in play drops the call at once and turns the AI off for
the longest back-off.

    python tests/test_r4_overage.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
import backends as BK  # noqa: E402
import review as RV  # noqa: E402
from planner import Memory, PLANNER_CONFIG  # noqa: E402


@dataclass
class RateLimitInfo:
    status: str
    rate_limit_type: str | None = None
    overage_status: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class RateLimitEvent:
    rate_limit_info: RateLimitInfo


@test("extra usage in play: the overage window, a reached limit with overage allowed, or the raw flag")
def _():
    assert BK._overage_event(RateLimitEvent(RateLimitInfo("allowed", rate_limit_type="overage")))
    assert BK._overage_event(RateLimitEvent(RateLimitInfo("rejected", "five_hour", overage_status="allowed")))
    assert BK._overage_event(RateLimitEvent(RateLimitInfo("rejected", "five_hour", overage_status="allowed_warning")))
    assert BK._overage_event(RateLimitEvent(RateLimitInfo("allowed", raw={"isUsingOverage": True})))


@test("no extra usage: a warning, a plain reached limit, overage refused or off")
def _():
    assert not BK._overage_event(RateLimitEvent(RateLimitInfo("allowed_warning", "five_hour")))
    assert not BK._overage_event(RateLimitEvent(RateLimitInfo("rejected", "seven_day")))
    assert not BK._overage_event(RateLimitEvent(RateLimitInfo("rejected", "five_hour", overage_status="rejected")))
    assert not BK._overage_event(object())


@test("an overage failure backs off for the longest wait and is marked in the record")
def _():
    m = Memory()
    bo = RV.note_failure(m, 1000, BK.RateLimited("extra usage", overage=True))
    assert bo["wait_days"] == PLANNER_CONFIG["r4k2_backoff_max_days"] and bo["overage"] is True, bo
    m2 = Memory()
    bo2 = RV.note_failure(m2, 1000, BK.RateLimited("limit"))
    assert bo2["wait_days"] < bo["wait_days"] and bo2["overage"] is False, bo2


@test("the subscription backend drops the call at the event (source)")
def _():
    src = (ROOT / "brain" / "backends.py").read_text(encoding="utf-8")
    i = src.index("elif _overage_event(msg):")
    assert "raise RateLimited(" in src[i:i + 700] and "overage=True" in src[i:i + 700]


finish()

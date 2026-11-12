"""(item10) Training benches: a skill cap on the AI's second workshop of a kind.

The `benches` report (lua/ai-benches.lua): for each kind the AI may cap
(carpenters, masons, craftsdwarfs, jewellers, clothiers, leatherworks,
bowyers, mechanics), the AI's own built workshops of it (those standing in
its projects' areas; every other workshop is the player's and is never
touched), oldest first, each with its skill range (`max_level`, `min_level`),
named workers, jobs, and `capped` (the cap is the AI's); and `skills`: the
skill ratings of the citizens holding the kind's labour, best first.

  * bench_caps: two or more of the AI's own of a kind, none capped yet, at
    least `bench_learners_min` workers below `bench_training_max_level` and
    one at or above it: the newest untouched one gets that max skill level,
    so novices learn there and the masters work the oldest (the good one);
  * bench_caps release: the cap lifted again when nobody under it holds the
    labour any more (the bench would stand idle) or the AI is down to one
    workshop of the kind.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import AGENDA_THEMES, Proposal

__all__ = ["_bench_caps_rule", "BENCH_SKILL_WORDS"]

AGENDA_THEMES.update({"bench_caps": "training benches for the novices"})

# df.skill_rating's words for the levels the cap is likely set at
BENCH_SKILL_WORDS = {1: "Novice", 2: "Adequate", 3: "Competent", 4: "Skilled", 5: "Proficient", 6: "Talented",
                     7: "Adept", 8: "Expert", 9: "Professional", 10: "Accomplished", 11: "Great", 12: "Master"}


def _untouched(shop: dict) -> bool:
    return not shop.get("max_level") and not shop.get("min_level") and not shop.get("workers")


def _bench_caps_rule(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    b = _d(s.get("benches"))
    if not b or "error" in b:
        return
    level = int(cfg["bench_training_max_level"])
    word = BENCH_SKILL_WORDS.get(level, str(level))
    for kind, k in sorted(_d(b.get("kinds")).items()):
        k = _d(k)
        shops = [x for x in _l(k.get("shops")) if isinstance(x, dict)]
        skills = [int(r) for r in _l(k.get("skills")) if isinstance(r, (int, float)) and not isinstance(r, bool)]
        learners = sum(1 for r in skills if r < level)
        masters = len(skills) - learners
        capped = [x for x in shops if x.get("capped")]
        if capped:
            if learners == 0 or len(shops) < 2:
                why = ("nobody holding the labour is below the cap any more" if learners == 0
                       else "the AI is down to one workshop of the kind")
                proposals.append(Proposal("bench_caps", {"type": "bench_caps", "kind": kind, "release": True},
                                          f"the {kind} training bench ({word} and under): {why}: lift the cap", 4))
            continue
        if len(shops) < 2 or not any(_untouched(x) for x in shops[1:]):
            continue
        if learners >= cfg["bench_learners_min"] and masters >= 1:
            proposals.append(Proposal("bench_caps", {"type": "bench_caps", "kind": kind, "level": level},
                                      f"{len(shops)} {kind} workshops of the AI's, {learners} worker(s) below "
                                      f"{word} and {masters} at or above: the newest becomes a training bench "
                                      f"(skill {word} and under), the masters work the oldest", 6))

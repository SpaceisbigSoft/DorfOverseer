"""(r4 k1, audit A7 B1/B2) What the strategist may hold and raise, judged by
what a rule IS and what it DOES rather than by hand-kept name lists (those
fell fifteen versions behind: 208 survival/defence rules could be held for
84 days, a dozen kill/open/slaughter rules could have their pacing removed).

Holds (B1): a rule hold_classes classes survival or defence is never held,
whatever its name; nor one in the planner's protected sets (steer_protected,
strategist.HOLD_PROTECTED); nor a rule in no class (hold_classes' own rule:
unknown is survival, never held by mistake). `build` keeps its two-week hold
(strategist.BUILD_HOLD_MAX_DAYS): the whole level ladder, and its survival
levels are judged one by one in planner.select (hold_applies).

Raises (B2): a raise puts a rule first and skips its cooldown. A rule whose
proposals take an action of a kind in RAISE_NEVER (kill or squad orders,
hunts, missions, expulsions, gates, levers, hatches and entrances, trade, the
butcher, convictions and prisoners, the cavern seal opened, lures, kill
zones) is never raised. The rule -> action kinds table is read from every
`Proposal(` in brain/ (raise_rule_kinds, an AST scan, cached), so a rule added
later is covered by what it does; the review adds the kinds of the proposals
it saw; and planner.select checks every raised proposal's own action
(raise_applies), so a rule the scan could not read is still never raised.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

# action kind -> words; a kind always refused for a raise
RAISE_NEVER = {
    # kill orders, hunts and missions (squad_orders: unless it only calls a squad back)
    "squad_orders": "a squad order", "squad_station": "a squad posted", "guard_gate": "a squad at a gate",
    "archer_post": "archers posted", "hunt_send": "a hunt", "hunters": "hunters sent",
    "send_mission": "a mission", "mission_way": "a mission", "mission_pets": "a mission",
    # expulsions
    "expel_dwarf": "an expulsion",
    # gates, levers, hatches, entrances
    "open_gates": "gates opened", "close_threatened_gates": "gates shut", "pull_gate": "a gate lever pulled",
    "clear_gate": "a gate cleared", "unstick_gate": "a gate forced", "link_lever": "a lever linked",
    "place_gate_lever": "a gate lever", "arm_gates": "the gates armed", "free_gate_jobs": "gate jobs freed",
    "open_entrance": "an entrance opened", "cut_entrance": "an entrance cut (hatches)",
    "way_out_open": "a way out opened", "close_world": "the fort shut",
    # trade
    "trade_deal": "a trade", "call_trader": "a trader called", "open_trade": "trade opened",
    "close_trade": "trade closed", "bring_goods": "goods to the depot",
    "unload_depot": "the depot unloaded (trade)",           # (r4 W5)
    # the butcher
    "slaughter_one": "the butcher", "herd_targets": "the butcher's targets",
    # convictions and prisoners
    "convict": "a conviction", "release_prisoners": "prisoners released", "pit_prisoners": "prisoners to the pit",
    "make_pit": "a prisoner pit", "killer_cell": "a killer's cell",
    "cleanup_units": "units removed",
    # lures and kill zones
    "build_lure": "a lure", "lure_open": "a lure opened", "build_killzone": "a kill zone",
}


def raise_never_why(action) -> str | None:
    """Why a raise may not speed this action, or None. Flags count: a squad
    order that only clears (a recall) is fine; the cavern seal only when it
    opens; the autobutcher only switched on."""
    if not isinstance(action, dict):
        return None
    t = action.get("type")
    if t == "squad_orders" and action.get("clear") is True and not action.get("kill"):
        return None
    if t == "hunters" and action.get("stop") is True:
        return None                 # the hunters called in
    if t == "seal_cavern":
        return "the cavern seal opened" if action.get("open") else None
    if t == "tool":
        return "the butcher" if action.get("name") == "autobutcher" and action.get("enabled") else None
    return RAISE_NEVER.get(t) if isinstance(t, str) else None


# ---------------------------------------------------------------- the scan

_UNKNOWN = object()


def _const(node):
    return node.value if isinstance(node, ast.Constant) else _UNKNOWN


def _dict_of(node) -> dict | None:
    """A dict literal's constant keys -> constant values (_UNKNOWN for the rest)."""
    if not isinstance(node, ast.Dict):
        return None
    out = {}
    for k, v in zip(node.keys, node.values):
        if k is not None and isinstance(k, ast.Constant) and isinstance(k.value, str):
            out[k.value] = _const(v)
    return out


def _scan_why(d: dict) -> str | None:
    """raise_never_why for a dict read from source: a flag that is not a
    constant counts against (never raised by mistake)."""
    t = d.get("type")
    if not isinstance(t, str):
        return None
    if t == "squad_orders":
        return None if d.get("clear") is True and "kill" not in d else RAISE_NEVER[t]
    if t == "hunters":
        return None if d.get("stop") is True else RAISE_NEVER[t]
    if t == "seal_cavern":
        return None if d.get("open", False) in (False, None, 0) else "the cavern seal opened"
    if t == "tool":
        n, e = d.get("name"), d.get("enabled")
        return "the butcher" if n == "autobutcher" and e not in (False, None, 0) else None
    return RAISE_NEVER.get(t)


def _dicts_in(expr, assigns: dict, depth: int = 0) -> list:
    """Every dict literal the action expression may be built from: literals
    inside it, and (two levels) what its names are assigned in the function."""
    out = []
    for n in ast.walk(expr):
        if isinstance(n, ast.Dict):
            out.append(n)
        elif isinstance(n, ast.Name) and depth < 2:
            for v in assigns.get(n.id, ()):
                out += _dicts_in(v, assigns, depth + 1)
    return out


def _rule_names(node):
    """('exact', name) or ('pattern', regex) or None for a rule expression."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return "exact", node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(re.escape(str(v.value)))
            else:
                parts.append(r"[a-z0-9_]+")
        return "pattern", "^" + "".join(parts) + "$"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        l, r = _rule_names(node.left), _rule_names(node.right)
        lp = re.escape(l[1]) if l and l[0] == "exact" else r"[a-z0-9_]+"
        rp = re.escape(r[1]) if r and r[0] == "exact" else r"[a-z0-9_]+"
        return "pattern", "^" + lp + rp + "$"
    return None


class _Sub(ast.NodeTransformer):
    def __init__(self, sub):
        self.sub = sub

    def visit_Name(self, node):
        return self.sub.get(node.id, node)


def _subst(expr, sub: dict):
    """A copy of the expression with the helper's parameters replaced by a
    caller's arguments; an f-string of constants folds to a constant."""
    import copy
    e = _Sub(sub).visit(copy.deepcopy(expr))
    if isinstance(e, ast.JoinedStr):
        parts = []
        for v in e.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            elif isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Constant) and v.conversion == -1 \
                    and v.format_spec is None:
                parts.append(str(v.value.value))
            else:
                return e
        return ast.Constant("".join(parts))
    return e


def _module_consts(tree) -> dict:
    out = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = n.value.value
    return out


def scan_source(text: str) -> tuple[dict, list]:
    """The rules one module's Proposal( calls name and the refused kinds of
    their actions: ({rule: {words}}, [(regex, {words})]). Every rule found is
    in the dict (an empty set when nothing refused)."""
    tree = ast.parse(text)
    consts = _module_consts(tree)
    exact: dict = {}
    patterns: list = []

    def record(r, a, assigns):
        if isinstance(r, ast.Name) and r.id in consts:
            r = ast.Constant(consts[r.id])
        names = _rule_names(r)
        if names is None:
            return
        words = set()
        for d in (_dicts_in(a, assigns) if a is not None else []):
            w = _scan_why(_dict_of(d) or {})
            if w:
                words.add(w)
        if names[0] == "exact":
            exact.setdefault(names[1], set()).update(words)
        elif words:
            patterns.append((names[1], words))

    def visit(fn):
        assigns: dict = {}
        for n in ast.walk(fn):
            if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                for t in targets:
                    if isinstance(t, ast.Name) and n.value is not None:
                        assigns.setdefault(t.id, []).append(n.value)
        params = []
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params = [x.arg for x in fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs]
        for n in ast.walk(fn):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            if (f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None) != "Proposal":
                continue
            args = list(n.args)
            kw = {k.arg: k.value for k in n.keywords}
            r = args[0] if args else kw.get("rule")
            a = args[1] if len(args) > 1 else kw.get("action")
            if r is None:
                continue
            record(r, a, assigns)
            # (a helper such as cleanup's propose(kind, action)) its callers' arguments
            used = {x.id for e in (r, a) if e is not None for x in ast.walk(e) if isinstance(x, ast.Name)}
            if not (used & set(params)):
                continue
            for c in ast.walk(tree):
                if not (isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == fn.name):
                    continue
                sub = dict(zip(params, c.args))
                sub.update({k.arg: k.value for k in c.keywords if k.arg})
                r2, a2 = _subst(r, sub), (_subst(a, sub) if a is not None else None)
                record(r2, a2, assigns)

    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit(fn)
    visit(ast.Module(body=[s for s in tree.body if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                                      ast.ClassDef))], type_ignores=[]))
    return exact, patterns


_CACHE: tuple | None = None
BRAIN = Path(__file__).resolve().parent


def raise_rule_kinds() -> tuple[dict, list]:
    """The scan of every brain/*.py with a Proposal( in it, once a process."""
    global _CACHE
    if _CACHE is None:
        exact, patterns = {}, []
        for f in sorted(BRAIN.glob("*.py")):
            try:
                text = f.read_text(encoding="utf-8")
                if "Proposal(" not in text:
                    continue
                e, p = scan_source(text)
            except Exception:  # noqa: BLE001  (a module that won't parse: the select check still holds)
                continue
            for k, v in e.items():
                exact.setdefault(k, set()).update(v)
            patterns += p
        _CACHE = (exact, patterns)
    return _CACHE


def raise_refused(rule, seen_actions=()) -> str | None:
    """Why the strategist may not raise this rule, or None. `seen_actions`:
    actions the rule was seen to propose (this review's proposals)."""
    if not isinstance(rule, str):
        return "not a rule"
    try:
        from strategist import RAISE_FORBIDDEN
    except Exception:  # noqa: BLE001
        RAISE_FORBIDDEN = set()
    if rule in RAISE_FORBIDDEN:
        return "paced by its wait"
    words = set()
    for a in seen_actions or ():
        w = raise_never_why(a)
        if w:
            words.add(w)
    exact, patterns = raise_rule_kinds()
    words |= exact.get(rule, set())
    for rx, w in patterns:
        if re.match(rx, rule):
            words |= w
    if words:
        return "its steps are " + ", ".join(sorted(words))
    return None


def hold_refused(rule) -> str | None:
    """Why the strategist may not hold this rule, or None (B1)."""
    if not isinstance(rule, str):
        return "not a rule"
    try:
        from planner_core import steer_protected
        if steer_protected(rule):
            return "a guard the fort's safety needs"
    except Exception:  # noqa: BLE001
        pass
    try:
        from strategist import HOLD_PROTECTED
        if rule in HOLD_PROTECTED:
            return "protected"
    except Exception:  # noqa: BLE001
        pass
    if rule == "build":
        return None          # two weeks at most (strategist.BUILD_HOLD_MAX_DAYS); its levels judged in select
    import hold_classes
    c = hold_classes.rule_class(rule)
    if c in (hold_classes.SURVIVAL, hold_classes.DEFENCE):
        return f"a {c} rule"
    if c is None:
        return "a rule in no class (kept as survival)"
    return None


def hold_applies(p) -> bool:
    """planner.select: a strategist's hold of the rule holds this proposal.
    Only an expansion step waits (a waterworks' floodgate shut, a survival
    level of the build ladder in a crisis's recovery go on)."""
    rule = getattr(p, "rule", None)
    if hold_refused(rule) and rule != "build":
        return False
    if rule == "build":
        return not _urgent(p)
    import hold_classes
    try:
        return hold_classes.step_class(p) == hold_classes.EXPANSION
    except Exception:  # noqa: BLE001  (never hold by mistake)
        return False


def _urgent(p) -> bool:
    a = getattr(p, "action", None)
    a = a if isinstance(a, dict) else {}
    import hold_classes
    return bool(a.get("urgent")) or any(a.get(k) for k in hold_classes.SAFE_FLAGS)


def raise_applies(p) -> bool:
    """planner.select: a strategist's raise speeds this proposal (B2)."""
    return raise_never_why(getattr(p, "action", None)) is None and raise_refused(getattr(p, "rule", None)) is None

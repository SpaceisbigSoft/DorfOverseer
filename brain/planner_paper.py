"""(item9) Paper for the library: from plants when the kiln's parchment chain
can't make it, and scrolls and codices once the library has its paper.

The library keeps "paper" (DF's location screen: blank writing materials in
its chests); its scribes (planner_health _staff_rule) and visiting scholars
write on them. The kiln chain (planner_industry _kiln_rules) makes parchment
from limestone and fresh hides and binds any sheet into a blank quire at a
Craftsdwarf's workshop. This rule is the plant route, one step a cycle:

  * press_paper   slurry pressed into a sheet (a screw press)
  * make_papyrus  papyrus sedge made into a sheet (its workshop)
  * make_slurry   a plant with a paper-slurry product milled into slurry (a
                  quern or millstone), only when the game can press it, and
                  only while food and drink are well in hand, keeping
                  `paper_plants_keep` of them
  (then the kiln rule binds the sheets into quires, as it does parchment)

A missing workshop (a quern, a screw press, ...) is built when no other
workshops project is under way (rule paper_shop).

Once the library has the paper it wants: blank scrolls (a sheet and scroll
rollers; up to `paper_scrolls_keep`, keeping `paper_scroll_sheets_spare`
sheets for quires) and codices (a written quire bound with a book binding,
up to `paper_codex_batch` an order); the rollers and bindings carved of wood
at the carpenter's first.

The bridge's `paper` section (lua/ai-paper.lua) names each kind's reaction
as the game has it (the vanilla codes are remembered, not read: a reaction
of the right shape stands in), the workshops it is made at and its free
inputs. Without the section (an older bridge, a failed one) nothing here
runs.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (AGENDA_THEMES, BUILDABLE_SHOPS, Proposal, _has_shop, _location, _location_short, _workshops_busy,
                          food_per_dwarf, queued, young_fort)

__all__ = ["PAPER_RECIPES", "KILN_PAPER", "DEFAULT_SHOPS", "paper_section", "paper_need", "_paper_rule"]

PAPER_RECIPES = ("make_slurry", "press_paper", "make_papyrus", "make_scroll", "bind_codex",
                 "wooden_scroll_rollers", "wooden_book_binding")
KILN_PAPER = ("make_quicklime", "make_milk_of_lime", "make_parchment", "make_quire")
# where each is made when the report doesn't say (vanilla, from memory: needs an in-game look)
DEFAULT_SHOPS = {"slurry": ("Quern", "Millstone"), "press": ("ScrewPress",), "papyrus": ("Farmers",),
                 "scroll": ("Craftsdwarfs",), "codex": ("Craftsdwarfs",)}
AGENDA_THEMES["paper"] = AGENDA_THEMES["paper_shop"] = "paper for the library"

SHOP_WORDS = {"ScrewPress": "a screw press", "Quern": "a quern", "Millstone": "a millstone",
              "Farmers": "a farmer's workshop", "Craftsdwarfs": "a craftsdwarf's workshop"}


def paper_section(s: dict) -> dict | None:
    """The bridge's paper section, or None (an older bridge, a failed one)."""
    p = s.get("paper")
    return p if isinstance(p, dict) and isinstance(p.get("reactions"), dict) else None


def _rx(paper: dict, kind: str) -> dict | None:
    e = _d(paper["reactions"].get(kind))
    return e if isinstance(e.get("code"), str) and e.get("code") else None


def _shops(e: dict, kind: str) -> tuple:
    named = tuple(x for x in _l(e.get("shops")) if isinstance(x, str))
    return named or DEFAULT_SHOPS[kind]


def _at(b: dict, shops: tuple) -> str | None:
    return next((x for x in shops if _has_shop(b, x)), None)


def paper_need(s: dict, paper: dict | None) -> tuple[int, int, int]:
    """(have, want, still to make) of the library's paper: what it wants less
    what it keeps and the blank quires and scrolls already made (on their way
    to its chests). (0, 0, 0) without a library or a shortfall."""
    lib = _location(s, "LIBRARY")
    short = _location_short(lib, ("paper",)).get("paper") if lib else None
    if not short:
        return 0, 0, 0
    h, w = short
    p = paper or {}
    blank = max(int(p.get("quires_blank") or 0), int(_d(s.get("supplies")).get("blank_quires") or 0))
    blank += int(p.get("scrolls_blank") or 0)
    return h, w, max(0, w - h - blank)


def _order(proposals: list, recipe: str, amount: int, why: str) -> None:
    proposals.append(Proposal("paper", {"type": "work_order", "recipe": recipe, "amount": max(1, int(amount))},
                              why, 6, True))


def _shop_missing(s: dict, cfg: dict, proposals: list, notes: list, shops: tuple, why: str) -> None:
    """A workshop for a paper step: built (the first buildable one) when no
    workshops project is under way, else said."""
    build = next((x for x in shops if x in BUILDABLE_SHOPS), None)
    words = " or ".join(SHOP_WORDS.get(x, x) for x in shops)
    if build is None:
        notes.append(f"{why} needs {words}, which the AI can't build: the paper waits")
        return
    open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
    if _workshops_busy(open_):
        notes.append(f"{why} waits for {words} (another workshops project is under way)")
        return
    proposals.append(Proposal("paper_shop", {"type": "start_project", "kind": "workshops", "shops": [build]},
                              f"{why}: build {SHOP_WORDS.get(build, build)}", 6))


def _paper_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    paper = paper_section(s)
    lib = _location(s, "LIBRARY")
    if paper is None or lib is None or young_fort(s, cfg):
        return
    # one step a cycle: nothing while a paper or kiln-chain order waits, or the
    # kiln rule proposed one this cycle
    if queued(s, set(PAPER_RECIPES) | set(KILN_PAPER)):
        return
    if any(_d(p.action).get("recipe") in KILN_PAPER for p in proposals if p.rule == "kiln"):
        return
    b = _d(s.get("buildings"))
    sup = _d(s.get("supplies"))
    sheets = max(int(sup.get("sheets") or 0), int(paper.get("sheets") or 0))
    batch = int(cfg["paper_batch"])
    have, want, need = paper_need(s, paper)
    _scholar_note(s, lib, notes, memory)
    if need > 0:
        if sheets > 0:
            return      # the kiln rule binds them into quires
        _plant_route(s, cfg, paper, b, need, have, want, batch, proposals, notes)
        return
    if want and have < want:
        return          # the blank ones made wait to be carried to the library
    _extras(s, cfg, paper, b, sheets, proposals, notes)


def _plant_route(s, cfg, paper, b, need, have, want, batch, proposals, notes) -> None:
    lack = f"the library has {have} of {want} sheets of paper"
    press, papyrus, slurry = _rx(paper, "press"), _rx(paper, "papyrus"), _rx(paper, "slurry")
    # 1. slurry already made: pressed
    if press and int(press.get("inputs") or 0) > 0:
        shops = _shops(press, "press")
        if _at(b, shops):
            n = min(int(press["inputs"]), need, batch)
            _order(proposals, "press_paper", n, f"{lack}: press {n} sheet(s) of paper from slurry")
        else:
            _shop_missing(s, cfg, proposals, notes, shops, f"{lack}; {press['inputs']} slurry to press")
        return
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 0))
    from planner_farms import drink_below_target
    fed = food_per_dwarf(s) >= cfg["paper_food_per_dwarf_min"] and not drink_below_target(s, citizens, cfg)
    if not fed:
        if (papyrus and int(papyrus.get("inputs") or 0)) or (slurry and int(slurry.get("inputs") or 0)):
            notes.append(f"{lack}: paper from plants waits until food and drink are well in hand")
        return
    keep = int(cfg["paper_plants_keep"])
    # 2. papyrus sedge: a sheet straight away
    if papyrus and int(papyrus.get("inputs") or 0) > keep:
        shops = _shops(papyrus, "papyrus")
        if _at(b, shops):
            n = min(int(papyrus["inputs"]) - keep, need, batch)
            _order(proposals, "make_papyrus", n, f"{lack}: make {n} papyrus sheet(s) from papyrus sedge")
        else:
            _shop_missing(s, cfg, proposals, notes, shops, f"{lack}; papyrus sedge to make into sheets")
        return
    # 3. plants milled into slurry, only when the game can press it
    if slurry and int(slurry.get("inputs") or 0) > keep:
        if not press:
            notes.append(f"{lack}: the game has no reaction pressing slurry into paper (a mod?): no slurry made")
            return
        shops = _shops(slurry, "slurry")
        press_shops = _shops(press, "press")
        if not _at(b, shops):
            _shop_missing(s, cfg, proposals, notes, shops, f"{lack}; plants to mill into paper slurry")
        elif not _at(b, press_shops):
            _shop_missing(s, cfg, proposals, notes, press_shops, f"{lack}; the paper slurry is pressed into sheets")
        else:
            n = min(int(slurry["inputs"]) - keep, need, batch)
            _order(proposals, "make_slurry", n, f"{lack}: mill {n} plant(s) into paper slurry (then pressed into sheets)")
        return
    if not (papyrus or slurry):
        notes.append(f"{lack}: the game has no plant paper reactions; parchment (the kiln chain) is the only route")
    else:
        notes.append(f"{lack}: no papyrus sedge or plants for paper slurry in stock (more than {keep} kept); "
                     "parchment (the kiln chain) or the caravans meanwhile")


def _extras(s, cfg, paper, b, sheets, proposals, notes) -> None:
    """The library has its paper: blank scrolls from spare sheets, codices
    from written quires."""
    wood = int(_d(s.get("stocks")).get("wood") or 0)
    scroll, codex = _rx(paper, "scroll"), _rx(paper, "codex")
    spare = sheets - int(cfg["paper_scroll_sheets_spare"])
    blank_scrolls = int(paper.get("scrolls_blank") or 0)
    if scroll and spare > 0 and blank_scrolls < int(cfg["paper_scrolls_keep"]):
        rollers = int(paper.get("rollers") or 0)
        if rollers == 0:
            if _has_shop(b, "Carpenters") and wood >= cfg["paper_wood_min"]:
                n = min(spare, int(cfg["paper_scrolls_keep"]) - blank_scrolls, 2)
                _order(proposals, "wooden_scroll_rollers", n,
                       f"{sheets} sheets spare and the library has its paper: carve {n} scroll roller(s) for scrolls")
                return
        else:
            shops = _shops(scroll, "scroll")
            if _at(b, shops):
                n = min(rollers, spare, int(cfg["paper_scrolls_keep"]) - blank_scrolls, int(cfg["paper_batch"]))
                _order(proposals, "make_scroll", n, f"{sheets} sheets spare and the library has its paper: "
                                                    f"roll {n} blank scroll(s) for its scribes and scholars")
                return
    written = int(paper.get("quires_written") or 0)
    if codex and written > 0:
        bindings = int(paper.get("bindings") or 0)
        if bindings == 0:
            if _has_shop(b, "Carpenters") and wood >= cfg["paper_wood_min"]:
                n = min(written, int(cfg["paper_codex_batch"]))
                _order(proposals, "wooden_book_binding", n,
                       f"{written} written quire(s) lie loose: carve {n} book binding(s) to bind them into codices")
        else:
            shops = _shops(codex, "codex")
            if _at(b, shops):
                n = min(written, bindings, int(cfg["paper_codex_batch"]))
                _order(proposals, "bind_codex", n, f"{written} written quire(s): bind {n} into codices "
                                                   "(kept and worth more in the library)")


def _scholar_note(s: dict, lib: dict, notes: list, memory) -> None:
    """Visiting scholars write in a library open to visitors. One the player
    shut is theirs (never changed); said once a plan."""
    flags = lib.get("flags")
    if not isinstance(flags, list) or "VISITORS_ALLOWED" in flags:
        return
    mine = set(getattr(memory, "locations_closed", None) or []) if memory is not None else set()
    if lib.get("id") in mine:
        return          # the AI's own shut (planner_visitors): it says so itself
    notes.append("the library is shut to visitors (not by the AI): visiting scholars can't come to write there; "
                 "its scribes still do")

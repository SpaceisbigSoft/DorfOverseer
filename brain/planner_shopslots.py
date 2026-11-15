"""(0.105.54, layout option A part 2) Workshops grouped onto shared levels.

Nearly every new workshop started a workshops level of its own (fort B: 20
of 25 workshop levels held one shop, ~250 dug tiles each, ~18 tiles apart).
The builder (lua/ai-builder-projects.lua join_workshop_level) now puts a
start_project of kind 'workshops' into a standing AI workshops level first:
a free room of a level of the shop's industry, else that level extended,
else the same in a level of another industry; only then a new level.

shop_level_action (applied by the overseer to the action it sends, so
plan()'s proposals stay as they were) tells the builder, for every
workshops level any rule proposed (the industry, the bottleneck's second
shops, paper, moods, needs, ...), what a NEW level should be planned for: the fort's next likely shops
(`spare_for`: the requested shops' industry-mates the fort has neither
standing nor coming, then the basic chain), WORKSHOP_LEVEL_MIN to
WORKSHOP_LEVEL_MAX rooms in all (`spare`: the empty rooms beyond the
shops). A level a placement custom put somewhere on purpose (field
kitchens: by the farms) may only join a level in its band (`join: "band"`).
The keys a rule set itself are kept.
"""

from __future__ import annotations

from digest import _d, _l

WORKSHOP_LEVEL_MIN = 4       # rooms a new workshops level is planned with, at least
WORKSHOP_LEVEL_MAX = 6       # and at most (shops past it still get their own rooms)
URGENT_LEVEL_MAX = 4         # a mood's (urgent) level: little more digging before its shop

# The industries (as the builder's WORKSHOP_GROUPS, lua/ai-builder-projects.lua),
# each in the order a fort usually wants its shops.
WORKSHOP_GROUP_ORDER = {
    "smithing": ["Smelter", "MetalsmithsForge", "WoodFurnace", "Kiln", "GlassFurnace"],
    "crafts": ["Craftsdwarfs", "Masons", "Mechanics", "Jewelers", "Carpenters", "Bowyers"],
    "food": ["Kitchen", "Still", "Butchers", "Tanners", "Farmers", "Fishery", "Quern", "Millstone", "ScrewPress"],
    "cloth": ["Loom", "Clothiers", "Leatherworks"],
    "soap": ["Ashery", "SoapMaker"],
}
WORKSHOP_GROUPS = {shop: g for g, shops in WORKSHOP_GROUP_ORDER.items() for shop in shops}
# what a fort's chain wants after its own industry's shops
CHAIN_ORDER = ["Carpenters", "Masons", "Craftsdwarfs", "Mechanics", "Kitchen", "Still", "Farmers",
               "Butchers", "Tanners", "Leatherworks", "Loom", "Clothiers", "Smelter", "MetalsmithsForge",
               "WoodFurnace", "Jewelers", "Ashery", "SoapMaker", "Kiln"]
# placement customs a level keeps (it may join only a level in its plan's band)
BAND_CUSTOMS = ("field_kitchens",)


def _fort_shops(s: dict) -> set:
    """The shops the fort has standing, and those an open workshops level is building."""
    b = _d(s.get("buildings"))
    have = {k for k, v in {**_d(b.get("workshops")), **_d(b.get("furnaces"))}.items()
            if isinstance(v, int) and v > 0}
    for p in _l(_d(s.get("projects")).get("open")):
        if isinstance(p, dict) and p.get("kind") == "workshops":
            have |= {x for x in _l(_d(p.get("summary")).get("workshops")) if isinstance(x, str)}
    return have


def next_shops(shops: list, have: set) -> list:
    """The fort's next likely shops after `shops`: their industries' shops in
    order, then the basic chain; none the fort has or is building."""
    out = []
    groups = []
    for x in shops:
        g = WORKSHOP_GROUPS.get(x)
        if g and g not in groups:
            groups.append(g)
    for name in [n for g in groups for n in WORKSHOP_GROUP_ORDER[g]] + CHAIN_ORDER:
        if name not in shops and name not in have and name not in out:
            out.append(name)
    return out


def level_plan(shops: list, have: set, urgent: bool = False) -> dict:
    """The spare rooms a new level of these shops is planned with:
    {"spare": n, "spare_for": [names]} (the names may be fewer than n)."""
    top = URGENT_LEVEL_MAX if urgent else WORKSHOP_LEVEL_MAX
    nxt = next_shops(shops, have)
    total = max(len(shops), min(top, max(WORKSHOP_LEVEL_MIN, len(shops) + len(nxt))))
    spare = max(0, min(8, total - len(shops), 12 - len(shops)))
    return {"spare": spare, "spare_for": nxt[:spare]}


def shop_level_action(action: dict, s: dict) -> dict:
    """The start_project of kind workshops as sent to the bridge: with the
    spare rooms a new level is planned with and a placement custom's band
    (module docstring). Any other action, or one that already says, comes
    back as it is. Never raises."""
    try:
        if not isinstance(action, dict) or action.get("type") != "start_project" \
                or action.get("kind") != "workshops":
            return action
        shops = [x for x in _l(action.get("shops")) if isinstance(x, str)]
        if not shops:
            return action
        b = dict(action)
        if "spare" not in b and "spare_for" not in b:
            b.update(level_plan(shops, _fort_shops(s if isinstance(s, dict) else {}), action.get("urgent") is True))
        if "join" not in b and isinstance(b.get("plan"), dict) \
                and set(_l(b.get("customs"))) & set(BAND_CUSTOMS):
            b["join"] = "band"
        return b
    except Exception:  # noqa: BLE001  (the builder's own defaults stand)
        return action

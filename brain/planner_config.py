"""planner_config: the planner's tuning numbers (PLANNER_CONFIG), split out of
planner_core in 0.105.25 (13c). Every rule reads them as `cfg[...]`; select()
reads `<rule>_cooldown_ticks` by the rule's name (default rule_cooldown_ticks).
planner_core re-exports PLANNER_CONFIG, so `from planner_core import PLANNER_CONFIG`
works as before."""

__all__ = ["PLANNER_CONFIG", "DISPOSAL_ACTION_MAX"]

# (0.105.27 fixes) The most items one disposal action (unforbid_items,
# mark_melt, mark_dump, empty_dump) may take a call: the bridge refuses a
# bigger max (lua/ai-bridge-actions.lua DISPOSAL_MAX, lua/ai-disposal.lua
# MAX_CAP, both 500; tests/test_disposal_fixes.py checks the three agree).
# _disposal_rules caps every disposal max here.
DISPOSAL_ACTION_MAX = 500

# (r7 d6) The tuning numbers live in themed parts, applied here in their old order
# (the dict is the same: keys, values and key order). __import__ so this module's
# names stay what they were (PLANNER_CONFIG, DISPOSAL_ACTION_MAX). A new block goes
# below these lines, just before the (layout B) block, which stays the last.
PLANNER_CONFIG = dict(__import__("planner_config_base").PART)
PLANNER_CONFIG.update(__import__("planner_config_society").PART)
PLANNER_CONFIG.update(__import__("planner_config_works").PART)
PLANNER_CONFIG.update(__import__("planner_config_features").PART)
PLANNER_CONFIG.update(__import__("planner_config_rounds").PART)


# (layout B) hallway-first floors (brain/floor_grammar.py, brain/masterplan_floors.py, brain/planner_floor_notes.py; lua/ai-floorplan.lua)
PLANNER_CONFIG.update({
    "floor_gap": 1,                       # rock between two rooms on a hall
    "floor_gap_wide": 50,                 # Spacing at or past this: one more
    "floor_gap_far": 100,                 # Spacing at or past this: two more
    "floor_tight_spacing": -50,           # Spacing at or below: no lead, no gap between kinds
    "floor_kind_gap": 1,                  # extra rock between two kinds of room; +2 at floor_gap_wide, +4 at floor_gap_far
    "floor_lead": 2,                      # hall between the stair and the first room; +2 at floor_gap_wide, +4 at floor_gap_far
    "floor_run": 30,                      # a hall's straight run, Verticality between the two bars
    "floor_run_deep": 20,                 # Verticality 40+
    "floor_run_very_deep": 14,            # Verticality 100+
    "floor_run_flat": 44,                 # Verticality -40 or lower
    "floor_run_very_flat": 60,            # Verticality -100 or lower
    "floor_run_dogleg": 0.6,              # x the run for a dog-leg fort (Fortification 50+)
    "floor_run_aspect": 1.25,             # x for the language's `long`, / for `wide`
    "floor_run_min": 10,                  # a hall is begun, or turned, only where this many columns are free
    "floor_run_room": 0.15,               # + this share for each Room size step (50, 100), - for each below (-50, -100)
    "floor_arms_deep": 1,                 # halls out of one stair, Verticality 40+
    "floor_arms": 2,                      # ...between
    "floor_arms_flat": 4,                 # ...Verticality -40 or lower
    "floor_node_grandeur": 60,            # Grandeur at or past this (or style scale 130+): a 5x5 square where a hall turns
    "floor_axial_grandeur": 40,           # Grandeur at or past this: a grand hall may close a hall's end
    "floor_pile_small": 5,                # a workshop's pile room, Room size -50 or lower
    "floor_pile": 5,                      # ...between
    "floor_pile_large": 7,                # ...Room size 50+
    "floor_piles_new": 1,                 # pile rooms dug with one workshop request
    "floor_piles_stock": 50,              # Stockpile at or past this: one more
    "floor_elevs_max": 4,                 # floors offered for one level
    "floor_full_retry_days": 28,          # a full floor is offered again after this long
    "floor_note_days": 3,                 # a fallback is said in the planner's notes for this many days after it happened
})




An AI overseer that runs a Dwarf Fortress fort through DFHack while you watch: a Python brain, a Lua bridge inside the game, a free local planner and an optional AI strategist. Built for DF 53.17 and DFHack 53.17-r1. Setup: `docs/setup-guide.md`.

## What's in 0.105.41

This version covers the game systems a long-running fort needs that the AI didn't handle yet:

- **Nobles:** the monarch, the capital and land titles are recognised; rooms below the value a title demands get statues, smoothing and engraving.
- **Logistics:** wheelbarrows for stone piles, feeder piles linked to their workshops, and traffic zones on the AI's levels to help pathing.
- **Food and land:** hunting when it's safe, butchery and tanning, fruit picking, more varied meals, farms on cavern soil, cavern logging and a protected grove.
- **Defence:** carved fortifications and ballistae at the gates of fortified forts, marksdwarves posted in sieges, caravans guarded and dangerous wildlife hunted.
- **Prisoners and undead:** caged prisoners kept or put in a pit (your Rules choice); squads pulled back from overwhelming undead sieges.
- **Hazards and health:** spilt magma, cave-ins, frozen water sources and heat; illnesses quarantined; rot moved away from living areas.
- **The world outside:** peace offers answered by a Rules choice; mountainhome export bans respected.
- **Crafts:** paper, scrolls and codices for the library; training workshops for novices; leather armour when metal is short; artifacts shown on pedestals and in display cases behind doors.

Each new behaviour has a switch on the Rules or Army tab. Every check DF might not support is guarded, so it fails quietly rather than crashing.

Also included: everything since the previous delivery (0.105.32-0.105.40), such as the fort-ending gaps (adamantine and the underworld, evil weather, fire breathers, insane dwarves, hauling, food storage, alloys), the whole-map water survey, missions and performance work.

**Status:** built and tested offline (178 test files); not yet seen running in the game. After installing, run `python brain\selftest.py` and watch the first reports.

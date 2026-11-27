"""(F4) The ai-bridge version this Python code was released with.

Bumped with BRIDGE_VERSION: the release's one find-replace of the quoted
version (lua/*.lua, lua/gui/*.lua, tests/test_bridge_memory.py and this
file); tests/test_f4_read_guard.py fails when it differs from
lua/ai-bridge.lua's BRIDGE_VERSION. Bridge.state() compares every full
report's bridge_version (and its stale parts, when the report lists them)
with it: on a mismatch the Lua was reloaded but this Python was not (the
keepers restart it), so nothing is acted on until the keeper is restarted.
"""

EXPECTED_BRIDGE_VERSION = "0.105.135"

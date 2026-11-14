"""(0.105.42) No corner-only touch: a new dig may not meet open space only at a
corner (dwarves, water and creatures pass a diagonal; no door closes it).

    python tests/test_corner_gap.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402
from lupa.lua53 import LuaRuntime  # noqa: E402

SRC = (ROOT / "lua" / "ai-builder-sites.lua").read_text(encoding="utf-8")
FN = re.search(r"\nfunction corner_gap\(.*?\nend\n", SRC, re.S).group(0)

HELP = r"""
function grid(rows)   -- '#' rock, '.' open (not ours), 'D' ours
  local g = {}
  for y, r in ipairs(rows) do for x = 1, #r do g[x .. ',' .. y] = r:sub(x, x) end end
  local function at(x, y) return g[x .. ',' .. y] or '#' end
  local dug = function(x, y) return at(x, y) == 'D' end
  local open = function(x, y) return at(x, y) == '.' end
  local each = function(fn)
    for k, v in pairs(g) do
      if v == 'D' then
        local x, y = k:match('(%-?%d+),(%-?%d+)')
        if not fn(tonumber(x), tonumber(y)) then return false end
      end
    end
    return true
  end
  local ok, w = corner_gap(dug, open, each)
  if ok then return 'ok' end
  return w.x .. ',' .. w.y
end
"""

lua = LuaRuntime()
lua.execute(FN)
lua.execute(HELP)
grid = lua.globals().grid


def g(*rows):
    return grid(lua.table_from({i + 1: r for i, r in enumerate(rows)}))


@test("a room meeting a corridor only at a corner is refused")
def _():
    assert g("#####",
             "#DD##",
             "#DD##",
             "###..",
             "#####") == "4,4"


@test("a room joined edge to edge is fine, even with a corner beside the join")
def _():
    assert g("#####",
             "#DD.#",
             "#DD..",
             "#####") == "ok"


@test("plain rock all round is fine")
def _():
    assert g("####", "#DD#", "#DD#", "####") == "ok"


@test("a corner with one open tile between is not a corner-only touch")
def _():
    assert g("#####",
             "#DD.#",
             "#DD.#",
             "###.#") == "ok"


@test("check_site runs the corner check")
def _():
    body = SRC[SRC.index("function check_site("):SRC.index("function corner_gap(")]
    assert "corner_gap(" in body


finish()

"""(r5 p5) The control panel (lua/gui/ai-overseer.lua) built for real, on a
stub of DFHack's gui and gui.widgets, in place of tests that cut the page's
source text with regexes (frame = {t = t + 18, l = 76, w = 40} and the like).

    window(settings)         the OverseerWindow made as DFHack makes it: every
                             page's init run, its widgets kept with their attrs
    widgets(page)            [Widget]: view_id, kind, row, l, w, label, label_width,
                             options, initial_option (the frames' t as the page sets it)
    find(page, view_id)      that widget (one only)
    refresh(page, settings)  the page's refresh(): {view_id: the value setOption got}
    change(page, view_id, v) its on_change(v): the window's set_field calls [(field, value)]
    overlaps(page)           pairs of widgets on one row whose columns cross

The stub widgets know nothing of drawing: a widget's width is its frame's w,
else its label or text's length (an unsized Label). The page names are the
classes': TraitPage (by group), AIPage, RulesPage, MilitaryPage, NeedsPage,
CulturePage, CameraPage. The settings module is the real one on
tests/test_preset.py's stub DFHack.

Not a test file itself (run_all runs test_*.py only).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
GUI_PATH = ROOT / "lua" / "gui" / "ai-overseer.lua"

STUB = r"""
local gui_src, part_srcs = ...
local G = {}
local function defclass(cls, parent)
  cls = cls or {}
  cls.__index = cls
  cls._parent = parent
  cls._attrs = {}
  cls.ATTRS = function(arg)
    if type(arg) == 'table' then for k, v in pairs(arg) do cls._attrs[k] = v end end
    return cls
  end
  setmetatable(cls, {__index = parent, __call = function(c, attrs)
    local o = setmetatable({}, c)
    local chain = {}
    local k = c
    while k do table.insert(chain, 1, k); k = k._parent end
    for _, kk in ipairs(chain) do
      for a, v in pairs(kk._attrs or {}) do if o[a] == nil and v ~= G.DEFAULT_NIL then o[a] = v end end
    end
    for a, v in pairs(attrs or {}) do o[a] = v end
    o.subviews = {}
    local given = attrs and attrs.subviews
    if given then o.subviews = {}; o:addviews(given) end
    for _, kk in ipairs(chain) do
      local init = rawget(kk, 'init')
      if init then init(o, attrs or {}) end
    end
    return o
  end})
  return cls
end
G.DEFAULT_NIL = setmetatable({}, {__tostring = function() return 'DEFAULT_NIL' end})
G.log = {options = {}}

local View = defclass(nil, nil)
View._kind = 'View'
function View:addviews(list)
  for _, v in ipairs(list or {}) do
    table.insert(self.subviews, v)
    if v.view_id then self.subviews[v.view_id] = v end
    for _, sub in ipairs(v.subviews or {}) do       -- DFHack: named views below are reachable too
      if sub.view_id and self.subviews[sub.view_id] == nil then self.subviews[sub.view_id] = sub end
    end
  end
end
function View:callback(name, ...)
  local args = table.pack(...)
  return function(...) return self[name](self, table.unpack(args, 1, args.n), ...) end
end
function View:updateLayout() end
function View:setOption(v, call)
  self.option = v
  G.log.options[self.view_id or '?'] = v
end
function View:setText(t) self.text = t end
function View:setChoices(c) self.choices = c end
function View:getChoices() return self.choices or {} end
function View:getSelectedChoice() return nil end
function View:setSelected(i) self.selected = i end
function View:getSelected() return self.selected or 1 end
function View:getSelectedPage() return self.subviews[self:getSelected()] end
function View:getOptionValue() return self.option end
function View:show() return self end
function View:raise() return self end

local widgets = {}
for _, name in ipairs({'Panel', 'Window', 'Label', 'CycleHotkeyLabel', 'ToggleHotkeyLabel', 'HotkeyLabel',
                       'TabBar', 'Pages', 'Divider', 'EditField', 'Slider', 'RangeSlider', 'List',
                       'FilteredList', 'WrappedLabel', 'TooltipLabel', 'ResizingPanel', 'Scrollbar',
                       'BannerPanel', 'TextButton', 'ConfigureButton'}) do
  local c = defclass(nil, View)
  c._kind = name
  widgets[name] = c
end
local gui = {ZScreen = defclass(nil, View), FramedScreen = defclass(nil, View)}
local dialogs = {showYesNoPrompt = function() end, showInputPrompt = function() end,
                 showMessage = function() end, showListPrompt = function() end}

function G.load(S, extra)
  local env = setmetatable({}, {__index = _G})
  env.defclass = defclass
  env.DEFAULT_NIL = G.DEFAULT_NIL
  env.dfhack_flags = {module = true}
  env.PART_SOURCES = part_srcs     -- (r9) the hub's parts (lua/gui/ai-overseer-<part>.lua), as their texts
  env.dfhack = setmetatable({utf2df = function(x) return x end, getTickCount = function() return 0 end},
                            {__index = S.dfhack})   -- the settings' stub: its persistence
  for _, c in ipairs({'COLOR_GREY', 'COLOR_WHITE', 'COLOR_LIGHTCYAN', 'COLOR_LIGHTRED', 'COLOR_YELLOW',
                      'COLOR_LIGHTGREEN', 'COLOR_GREEN', 'COLOR_RED', 'COLOR_CYAN', 'COLOR_DARKGREY',
                      'COLOR_LIGHTBLUE', 'COLOR_BROWN', 'COLOR_MAGENTA', 'COLOR_LIGHTMAGENTA', 'COLOR_BLUE',
                      'COLOR_BLACK'}) do env[c] = c end
  env.require = function(n)
    if n == 'gui' then return gui end
    if n == 'gui.widgets' then return widgets end
    if n == 'gui.dialogs' then return dialogs end
    error('unexpected require ' .. n)
  end
  env.reqscript = function(n)
    if n == 'ai-overseer-settings' then return S end
    if extra and extra[n] then return extra[n] end
    error('no ' .. n .. ' here')
  end
  assert(load(gui_src, 'gui/ai-overseer', 't', env))()
  return env
end
function G.kind(w) return w._kind end
return G
"""


@dataclass
class Widget:
    view_id: str | None
    kind: str
    row: int | None
    l: int | None
    w: int | None
    label: str | None
    label_width: int | None
    options: list = field(default_factory=list)
    initial_option: object = None
    text: str | None = None
    raw: object = None


_S: dict = {}


def _boot():
    if "G" not in _S:
        try:
            import lupa.lua53  # noqa: F401
        except ImportError:
            from harness import skip
            skip("needs the lupa package (pip install lupa)")
        import test_preset as TP          # its stub DFHack and the real settings module
        _S["TP"] = TP
        _S["LUA"] = TP.LUA
        from lua_modules_util import LUA_DIR, split_parts      # (r9) the panel is a hub and parts
        parts = TP.LUA.table_from({n: (LUA_DIR / (n + ".lua")).read_text(encoding="utf-8")
                                   for n in split_parts("gui/ai-overseer.lua")})
        _S["G"] = TP.LUA.execute(STUB, GUI_PATH.read_text(encoding="utf-8"), parts)
    return _S["LUA"], _S["G"], _S["TP"]


def settings_module():
    L, G, TP = _boot()
    return TP.H.settings()


def window(saved=None, extra=None, saving=False):
    """The window as the player opens it, on settings saved as `saved` (a dict; None: a new fort).
    saving=False: its persist() only counts (win.persisted); True: the window's own (it saves)."""
    L, G, TP = _boot()
    TP.reset()
    if saved is not None:
        TP.H.persist["ai-overseer/settings"] = TP.t(saved)
    S = TP.H.settings()
    env = G.load(S, TP.t(extra) if extra else None)
    win = env.OverseerWindow(L.table())
    if not saving:
        win.persist = L.eval("function(self) self.persisted = (self.persisted or 0) + 1 end")
    _S["env"], _S["S"] = env, S
    return win


def pages(win):
    p = win.subviews.pages
    return [p.subviews[i] for i in range(1, len(p.subviews) + 1)]


def page(win, name):
    """A page by class name ('RulesPage'), or a trait page by its group's name."""
    env = _S["env"]
    for pg in pages(win):
        mt = _S["LUA"].eval("getmetatable")(pg)
        if name in env and _S["LUA"].eval("rawequal")(mt, env[name]):
            return pg
        if pg.group is not None and pg.group.name == name:
            return pg
    raise KeyError(name)


def _text(t):
    L = _S["LUA"]
    if t is None:
        return None
    if L.eval("type")(t) == "string":
        return t
    if L.eval("type")(t) == "table":
        parts = []
        for i in range(1, len(t) + 1):
            x = t[i]
            if L.eval("type")(x) == "table":
                v = x.text
                parts.append(v if isinstance(v, str) else "")
            elif isinstance(x, str):
                parts.append(x)
        return "".join(parts)
    return None


def _num(v):
    return int(v) if isinstance(v, (int, float)) else None


def widgets(pg):
    L, G, _ = _boot()
    out = []
    for i in range(1, len(pg.subviews) + 1):
        v = pg.subviews[i]
        fr = v.frame
        opts = []
        if v.options is not None:
            for j in range(1, len(v.options) + 1):
                o = v.options[j]
                opts.append((o.label, o.value) if L.eval("type")(o) == "table" else (o, o))
        label = v.label if isinstance(v.label, str) else None
        text = _text(v.text)
        w = _num(fr.w) if fr is not None else None
        out.append(Widget(view_id=v.view_id, kind=G.kind(v), row=_num(fr.t) if fr is not None else None,
                          l=_num(fr.l) if fr is not None else None, w=w, label=label,
                          label_width=_num(v.label_width), options=opts, initial_option=v.initial_option,
                          text=text, raw=v))
    return out


def find(pg, view_id) -> Widget:
    got = [w for w in widgets(pg) if w.view_id == view_id]
    assert len(got) == 1, (view_id, len(got))
    return got[0]


def width(w: Widget) -> int:
    if w.w is not None:
        return w.w
    return len(w.label or w.text or "")


def overlaps(pg):
    ws = [w for w in widgets(pg) if w.row is not None and w.l is not None]
    bad = []
    for i, a in enumerate(ws):
        for b in ws[i + 1:]:
            if a.row == b.row and a.l < b.l + width(b) and b.l < a.l + width(a):
                bad.append((a.view_id or a.label or a.text, b.view_id or b.label or b.text, a.row))
    return bad


def refresh(pg, saved=None):
    """pg:refresh() on the window's settings (with `saved` merged over them):
    {view_id: what setOption was given}."""
    L, G, TP = _boot()
    if saved:
        for k, v in saved.items():
            pg.panel.settings[k] = TP.t(v)
    G.log.options = L.table()
    pg.refresh(pg)
    return {k: G.log.options[k] for k in G.log.options.keys()}


def change(pg, view_id, value):
    """The widget's on_change(value): what the window's set_field was given, [(field, value)]."""
    L, G, TP = _boot()
    seen = L.table()
    win = pg.panel
    old = win.set_field
    win.set_field = L.eval("function(seen) return function(self, f, v) table.insert(seen, {f, v}) end end")(seen)
    try:
        find(pg, view_id).raw.on_change(TP.t(value) if isinstance(value, (dict, list)) else value)
    finally:
        win.set_field = old
    return [(seen[i][1], seen[i][2]) for i in range(1, len(seen) + 1)]


def visible_rows(win) -> int:
    """The rows a page shows: the window's height less its frame (2), the tabs (3) and the foot (9)."""
    return int(win.frame.h) - 2 - 3 - 9


def inner_width(win) -> int:
    return int(win.frame.w) - 2


def culture_lines(win, culture) -> list[str]:
    """The Culture page's text for a saved culture (a dict), as refresh() writes it."""
    L, G, TP = _boot()
    TP.H.persist["ai-overseer/culture"] = TP.t(culture)
    pg = page(win, "CulturePage")
    pg.learned = False
    pg.refresh(pg)
    t = pg.subviews.text.text_to_wrap
    return [t[i] for i in range(1, len(t) + 1)]


def control(page_name, view_id, field=None, values=(), default=None, kind=None, pad=0, saved=None, fit=True):
    """The common check of one control, on a window opened on `saved`: its kind; its label
    within label_width; inside the window (118 columns); the widest choice beside the label
    (+pad; fit=False: not checked); each of `values` chosen goes to set_field(field, v) and a refresh with it shows it;
    on a new fort (and a refresh with the field unset) it shows `default`; nothing on its page
    overlaps. Returns the Widget."""
    win = window(saved)
    pg = page(win, page_name)
    w = find(pg, view_id)
    if kind is not None:
        assert w.kind == kind, (view_id, w.kind)
    assert w.label and w.label_width and len(w.label) <= w.label_width, w
    assert w.l + width(w) <= inner_width(win) - 2, w
    if w.options and fit:
        longest = max(len(str(n)) for n, _ in w.options)
        assert w.label_width + longest + pad <= w.w, (view_id, w.label_width, longest, w.w)
    field = field or view_id
    for v in values:
        assert change(pg, view_id, v) == [(field, v)], (view_id, v, change(pg, view_id, v))
        assert refresh(pg, {field: v}).get(view_id) == v, (view_id, v, refresh(pg, {field: v}).get(view_id))
    if default is not None:
        fresh = window()
        assert find(page(fresh, page_name), view_id).initial_option == default, (view_id, "new fort")
        got = refresh(page(fresh, page_name)).get(view_id)
        assert got == default, (view_id, "refreshed on a new fort", got)
    assert overlaps(pg) == [], overlaps(pg)
    return w


def rule_switch(key, page_name, default=True, fit=True):
    """A Rules on/off switch end to end, in place of its source lines (`key = true,` in the
    defaults, `'key',` in the switches' list, `key = s.key,` in for_ai, the view and its
    setOption): the settings' default, kept through sanitize and for_ai either way, an
    older save (unset) reads the default; the window's toggle sets it and shows it."""
    S = settings_module()
    L, G, TP = _boot()
    d = S.defaults()
    assert d[key] is default and S.for_ai(d)[key] is default, (key, d[key], S.for_ai(d)[key])
    for v in (not default, default):
        s = S.defaults()
        s[key] = v
        assert S.sanitize(s)[key] is v and S.for_ai(S.sanitize(s))[key] is v, (key, v)
    old = S.defaults()
    old[key] = None
    assert S.sanitize(old)[key] is default, (key, "an older save")
    return control(page_name, key, kind="ToggleHotkeyLabel", values=[not default, default], default=default, fit=fit)

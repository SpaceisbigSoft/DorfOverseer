-- (0.105.47) Where the screen buttons the AI clicks are, kept for every save
-- on this PC, not only the save the player showed them in.
--
-- Why: DF has no key for the depot's Trade button, the trade screen's Trade
-- button or the meeting screen's answers, so the AI clicks them where the
-- player showed it once (probe_trade.py --here-depot / --here,
-- probe_meeting.py --here). Those places were kept in the save's site data
-- only, so every new fort started without them: the 8-13 Nov run (six new
-- forts of 11 Nov) never opened the trade screen (`trade.trader.can_open`
-- false, "can't open the trade screen" Needs you 14-35 times a fort) though
-- the October forts had traded end to end.
--
-- Now a button is looked up in this order: the save's site data (shown in
-- this save), this PC's file dfhack-config/ai-overseer/screen-buttons.json
-- (shown in any save of this DF folder, or a guess that worked here), then
-- the AI's own guess (DEFAULTS, `default = true`). A guess that fails its
-- check RETIRE_AFTER times (or once, badly) is retired in the file and the
-- old Needs you comes back; a guess that works is written to the file as a
-- known place. The window's grid is the same in all six DF folders
-- (prefs/init.txt: INTERFACE_SCALING_TO_DESIRED_GRID 170 x 64), and every
-- place is kept from the edge it sits by, so a resized window still finds it.
--@ module = true

local U = reqscript('ai-util')

FILE = dfhack.getDFPath() .. '/dfhack-config/ai-overseer/screen-buttons.json'
RETIRE_AFTER = 2           -- a guess that failed this many times is no longer tried

-- (0.105.47) The AI's own guesses, from its October clicks on this PC that
-- worked (logs/runs 23-24 Oct: open_trade at x94/x73/x60 y15 on windows
-- 170/149/136 tiles wide, the trade screen's Trade pressed at x72 y64 and
-- x66 y60 on the last two, the merchants answering): the depot sheet's
-- Trade button 76 tiles from the right edge on row 15 (inside the button
-- column DFHack's own move-goods overlay covers, 70-96 from the right, just
-- below its Move goods button, rows 11-13); the trade screen's Trade button
-- 2 left of the centre, 2 rows above the bottom. Nothing is known of the
-- meeting screen's buttons yet: none is guessed.
DEFAULTS = {
    ['ai-overseer/trade-buttons'] = {
        Depot = {anchor = 'right-top', rx = 76, ty = 15, default = true},
        Trade = {anchor = 'centre-bottom', dx = -2, dy = 2, default = true},
    },
}

local function copy(t)
    local o = {}
    for k, v in pairs(t or {}) do o[k] = type(v) == 'table' and copy(v) or v end
    return o
end

-- The file: {buttons = {[key] = {[name] = place}}, misses = {[key] = {[name] = n}},
-- retired = {[key] = {[name] = why}}}
function read_file()
    local ok, d = pcall(function() return require('json').decode_file(FILE) end)
    if not ok or type(d) ~= 'table' then d = {} end
    d.buttons = type(d.buttons) == 'table' and d.buttons or {}
    d.misses = type(d.misses) == 'table' and d.misses or {}
    d.retired = type(d.retired) == 'table' and d.retired or {}
    return d
end

function write_file(d)
    return pcall(function()
        pcall(function() dfhack.filesystem.mkdir_recursive(dfhack.getDFPath() .. '/dfhack-config/ai-overseer') end)
        require('json').encode_file(d, FILE)
    end)
end

-- Pure: the buttons of a group, merged: the save's over the PC's over the
-- guesses not retired. Each place says where it came from (`from`).
function merge(site, pc, defaults, retired)
    local out = {}
    for name, b in pairs(defaults or {}) do
        if not (retired and retired[name]) then
            out[name] = copy(b); out[name].from = 'guess'; out[name].default = true
        end
    end
    for name, b in pairs(pc or {}) do
        if type(b) == 'table' then out[name] = copy(b); out[name].from = 'pc'; out[name].default = nil end
    end
    for name, b in pairs(site or {}) do
        if type(b) == 'table' then out[name] = copy(b); out[name].from = 'save'; out[name].default = nil end
    end
    return out
end

function get(key)
    local f = read_file()
    return merge(U.site_get(key, {}), f.buttons[key], DEFAULTS[key], f.retired[key])
end

-- A place the player showed (or a guess that worked): kept for every save here.
function share(key, name, place)
    local f = read_file()
    f.buttons[key] = type(f.buttons[key]) == 'table' and f.buttons[key] or {}
    local p = copy(place)
    p.default, p.from = nil, nil
    f.buttons[key][name] = p
    if type(f.misses[key]) == 'table' then f.misses[key][name] = nil end
    write_file(f)
    return p
end

-- A guess that failed its check: counted; retired after RETIRE_AFTER (at
-- once with `now`). Returns whether it is retired now.
function miss(key, name, why, now)
    local f = read_file()
    f.misses[key] = type(f.misses[key]) == 'table' and f.misses[key] or {}
    local n = (tonumber(f.misses[key][name]) or 0) + 1
    f.misses[key][name] = n
    local gone = now == true or n >= RETIRE_AFTER
    if gone then
        f.retired[key] = type(f.retired[key]) == 'table' and f.retired[key] or {}
        f.retired[key][name] = tostring(why or 'failed'):sub(1, 160)
    end
    write_file(f)
    return gone
end

-- Where a place is on the screen now (anchors as ai-trade and ai-diplomacy
-- keep them): right-top {rx, ty}, centre-bottom {dx, dy}, left-top {x, y},
-- else centre {dx, dy}.
function at(b, dimx, dimy)
    if b.anchor == 'right-top' then return dimx - b.rx, b.ty end
    if b.anchor == 'centre-bottom' then return dimx // 2 + b.dx, dimy - b.dy end
    if b.anchor == 'left-top' then return b.x, b.y end
    return dimx // 2 + (b.dx or 0), dimy // 2 + (b.dy or 0)
end

-- Pure: a place on the screen at all.
function on_screen(x, y, dimx, dimy)
    return type(x) == 'number' and type(y) == 'number' and x >= 0 and y >= 0 and x < dimx and y < dimy
end

-- (0.105.47 review) A guessed button is pressed only where the screen reads
-- its word: the trade screen's Seize and Offer sit by its Trade button, and a
-- seize turns the caravan's civilisation hostile for good. The rows round the
-- guessed tile (y-1..y+1, WORD_SPAN tiles each side) are read with
-- dfhack.screen.readTile; a tile with no character (TrueType text reads as
-- nothing) makes the text unreadable, and then nothing is pressed. A word
-- counts when the guessed tile is on it or within WORD_PAD of its ends (the
-- label inside its button); a forbidden word there wins over the right one.
WORD_SPAN = 12
WORD_PAD = 3
FORBIDDEN_WORDS = {'Seize', 'Offer'}

-- The text round (x, y): {rows = {...}, col = the guessed tile's place in a
-- row (1-based)}, or nil when unreadable.
function text_near(x, y, span)
    span = span or WORD_SPAN
    local gps = df.global.gps
    local x0 = math.max(0, x - span)
    local rows = {}
    for yy = math.max(0, y - 1), math.min(gps.dimy - 1, y + 1) do
        local chars = {}
        for xx = x0, math.min(gps.dimx - 1, x + span) do
            local ok, t = pcall(function() return dfhack.screen.readTile(xx, yy) end)
            local ch = ok and t and tonumber(t.ch) or nil
            if ch == nil then return nil end
            table.insert(chars, (ch >= 32 and ch < 127) and string.char(ch) or ' ')
        end
        table.insert(rows, table.concat(chars))
    end
    return {rows = rows, col = x - x0 + 1}
end

local function covers(row, word, col)
    local from = 1
    while true do
        local a, b = row:find(word, from, true)
        if not a then return false end
        if col >= a - WORD_PAD and col <= b + WORD_PAD then return true end
        from = b + 1
    end
end

-- Pure: 'ok' (the word at the guessed tile, no forbidden one there),
-- 'forbidden' (Seize or Offer there; the word returned too), 'missing'
-- (readable, the word not there), 'unreadable' (nil, or nothing but blanks).
function judge(text, word)
    if type(text) ~= 'table' or type(text.rows) ~= 'table' or #text.rows == 0 then return 'unreadable' end
    if not table.concat(text.rows, '\n'):find('%S') then return 'unreadable' end
    local col = tonumber(text.col) or 1
    for _, w in ipairs(FORBIDDEN_WORDS) do
        for _, row in ipairs(text.rows) do
            if covers(row, w, col) then return 'forbidden', w end
        end
    end
    for _, row in ipairs(text.rows) do
        if covers(row, word, col) then return 'ok' end
    end
    return 'missing'
end

-- The check before a guessed press: verdict, the forbidden word, the text read.
function check_word(x, y, word)
    local text = text_near(x, y)
    local v, w = judge(text, word)
    return v, w, text
end

-- (r2 h5) A button found by its label, when the AI's guess of its place is
-- wrong. The 14-15 Nov run's only depot click (F, 00:51:04, x74 y15 on a
-- 150-wide window) opened no trade screen and the guess was retired at once;
-- the 15-16 Nov run never tried again in any fort (`can_open` false, the
-- "can't open the trade screen" Needs you 3-38 times a fort): no trade deal in
-- six forts. The same screens' text was read fine for the meetings (14
-- liaison meetings answered by the words on the screen), so a button is
-- looked for by its word where the guess misses.

-- Pure: where `word` stands alone in `rows` (strings): {col, row} (1-based),
-- never inside a longer word ("Trader"), never followed by one of
-- `not_before`'s words ("Trade depot", the sheet's title), never preceded by
-- one of `not_after`'s.
function label_hits(rows, word, not_before, not_after)
    local hits = {}
    for r, row in ipairs(rows or {}) do
        local from = 1
        while true do
            local a, b = row:find(word, from, true)
            if not a then break end
            local prev = a > 1 and row:sub(a - 1, a - 1) or ' '
            local nxt = row:sub(b + 1, b + 1)
            local ok = not prev:match('%w') and not nxt:match('%w')
            if ok and not_before then
                local w = row:sub(b + 1):match('^ ?(%a+)')
                if w and not_before[w:lower()] then ok = false end
            end
            if ok and not_after then
                local w = row:sub(1, a - 1):match('(%a+) ?$')
                if w and not_after[w:lower()] then ok = false end
            end
            if ok then table.insert(hits, {a, r}) end
            from = b + 1
        end
    end
    return hits
end

-- The screen's text in a box, one string a row; nil and 'unreadable' when a
-- tile can't be read (TrueType), so nothing is clicked blind; nil and 'blank'
-- when the box holds nothing but blanks (not drawn yet: tried again later).
function rows_in(x0, y0, x1, y1)
    local rows = {}
    local any = false
    for yy = y0, y1 do
        local chars = {}
        for xx = x0, x1 do
            local ok, t = pcall(function() return dfhack.screen.readTile(xx, yy) end)
            local ch = ok and t and tonumber(t.ch) or nil
            if ch == nil then return nil, 'unreadable' end
            if ch > 32 and ch < 127 then any = true end
            table.insert(chars, (ch >= 32 and ch < 127) and string.char(ch) or ' ')
        end
        table.insert(rows, table.concat(chars))
    end
    if not any then return nil, 'blank' end
    return rows
end

-- Where `word` stands as a label in the box {x0, y0, x1, y1} of the screen,
-- nearest (nx, ny) first: a list of {x, y} (the label's middle tile), and
-- 'found', 'none', 'blank' or 'unreadable'. With `forbid`, a label that judge() finds
-- by a forbidden word (Seize, Offer) is left out.
function find_label(word, box, near, opts)
    opts = opts or {}
    local gps = df.global.gps
    local x0, y0 = math.max(0, box[1]), math.max(0, box[2])
    local x1, y1 = math.min(gps.dimx - 1, box[3]), math.min(gps.dimy - 1, box[4])
    if x1 < x0 or y1 < y0 then return {}, 'none' end
    local rows, why = rows_in(x0, y0, x1, y1)
    if not rows then return {}, why or 'unreadable' end
    local out = {}
    for _, h in ipairs(label_hits(rows, word, opts.not_before, opts.not_after)) do
        local x, y = x0 + h[1] - 1 + #word // 2, y0 + h[2] - 1
        local keep = true
        if opts.forbid then
            local v = judge(text_near(x, y), word)
            keep = v == 'ok'
        end
        if keep then table.insert(out, {x = x, y = y}) end
    end
    local nx, ny = near and near[1] or x0, near and near[2] or y0
    table.sort(out, function(a, b)
        local da = math.abs(a.x - nx) + 3 * math.abs(a.y - ny)
        local db = math.abs(b.x - nx) + 3 * math.abs(b.y - ny)
        if da ~= db then return da < db end
        return a.y < b.y or (a.y == b.y and a.x < b.x)
    end)
    return out, #out > 0 and 'found' or 'none', rows
end

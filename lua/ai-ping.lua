-- ai-ping: reports basic game info as one line of JSON.
-- Used by brain/check_connection.py to prove the Python side can read the game.
--
-- Run in-game (DFHack console or launcher):   ai-ping
-- Run from outside:                           dfhack-run ai-ping
--@ module = true

local json = require('json')

local BRIDGE_VERSION = '0.1.0'

function get_info()
    local info = {
        bridge = 'ai-ping',
        bridge_version = BRIDGE_VERSION,
        dfhack_version = dfhack.getDFHackVersion(),
        df_version = dfhack.getDFVersion(),
        world_loaded = dfhack.isWorldLoaded(),
        map_loaded = dfhack.isMapLoaded(),
    }

    if dfhack.isMapLoaded() then
        info.citizens = #dfhack.units.getCitizens()
        info.year = df.global.cur_year
        info.year_tick = df.global.cur_year_tick
    end

    return info
end

if dfhack_flags.module then
    return
end

print(json.encode(get_info(), {pretty = false}))

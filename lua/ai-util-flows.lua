-- ai-util-flows: df.global.flows (fire, smoke, mist, miasma, clouds...)
-- walked once a report and grouped by type (flows_by_type, flows_where).
--
-- (r9) A part of ai-util, not a script of its own: ai-util.lua loads it into
-- its own environment, so every name here is reqscript('ai-util').name and
-- the helpers defined there and in the parts before it are in reach.

if not PARTS then qerror('ai-util-flows is a part of ai-util; run ai-util') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-util-flows'] = '0.105.130'   -- (0.105.26) bumped with BRIDGE_VERSION

-- --- (0.105.46, I6) the flows, walked once a report ------------------------------------
--
-- df.global.flows (fire, smoke, mist, miasma, clouds...) was walked whole by
-- the threats' fire and cloud reads and the miasma report, each reading every
-- flow's type, density and place. Now one walk a report groups them by type
-- (REPORT_CTX, as citizens()); each reader takes only the types it wants, in
-- the game's order. Outside a report: a walk each call, as before.
function flows_by_type()
    return report_memo('flows_by_type', function()
        local by = {}
        local i = 0
        for _, f in ipairs(df.global.flows) do
            i = i + 1
            local t = f.type
            if t ~= nil then
                local l = by[t]
                if not l then l = {}; by[t] = l end
                l[#l + 1] = {i, f}
            end
        end
        return by
    end)
end

-- The flows whose type `want(type)` says yes to (asked once per type present), in the game's order
function flows_where(want)
    local by = flows_by_type() or {}
    local picked = {}
    for t, l in pairs(by) do
        local ok, yes = pcall(want, t)
        if ok and yes then
            for _, e in ipairs(l) do picked[#picked + 1] = e end
        end
    end
    table.sort(picked, function(a, b) return a[1] < b[1] end)
    local out = {}
    for k, e in ipairs(picked) do out[k] = e[2] end
    return out
end

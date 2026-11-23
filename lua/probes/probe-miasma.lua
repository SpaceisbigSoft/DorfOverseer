-- probe-miasma: ai-syndromes' own miasma report (what rots near the worst
-- spots, why each is kept or markable) and clear_miasma as a dry run. READ ONLY.
local json = require('json')
local S = reqscript('ai-syndromes')
local out = {}
local ok, r = pcall(S.miasma_report)
out.report = ok and r or tostring(r)
if ok and type(r) == 'table' then
    r.items = nil
end
local okc, c = pcall(S.clear_miasma, {max = 50}, true)
out.dry_run = okc and c or tostring(c)
print(json.encode(out))

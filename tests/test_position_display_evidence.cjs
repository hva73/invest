const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const window = { MarketUI: { slot: () => '' } };
const source = fs.readFileSync(require.resolve('../static/position-ui.js'), 'utf8');
vm.runInNewContext(source, { window });
window.PositionUI.setup({ escape: String, formatTime: String });

function panel(asOf, assessedAt) {
  const item = {
    position: { position_id: 'p1', portfolio_id: 'depot', as_of: asOf },
    assessment: { risk_level: 'low', assessed_at: assessedAt },
    assessment_status: 'BEHOLD',
    orders: [],
  };
  return window.PositionUI.panel({
    groups: [{ portfolio: { name: 'Depot' }, positions: [item] }],
    count: 1,
  });
}

const malformed = panel('ugyldig dato', 'ugyldig vurderingstid');
assert.match(malformed, /Pr\. Ikke oplyst</);
assert.match(malformed, /Vurderet Ikke oplyst</);

const valid = panel('2026-07-01T23:05:00Z', '2026-01-02T04:15:00+03:00');
assert.match(valid, /Pr\. 02\.07\.2026,? 01\.05</);
assert.match(valid, /Vurderet 02\.01\.2026,? 02\.15</);

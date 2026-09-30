const { test, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
const React = require('react');
const { create } = require('react-test-renderer');
const { act } = React;
global.IS_REACT_ACT_ENVIRONMENT = true;
require.extensions['.tsx'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS },
}).outputText, filename);
const { BolMarket } = require('../components/BolMarket.tsx');
const { BolEanPreview } = require('../components/BolEanPreview.tsx');
const { BolSnapshots } = require('../components/BolSnapshots.tsx');
let tree;
const originalFetch = global.fetch;
afterEach(() => { if (tree) act(() => tree.unmount()); global.fetch = originalFetch; });
const cheap = { offerId: '1', retailerId: '0', price: 10, bestOffer: false, fulfilmentMethod: 'FBR',
  ultimateOrderTime: '23:59', minDeliveryDate: '2026-10-01', maxDeliveryDate: '2026-10-02' };
const best = { ...cheap, offerId: '2', price: 15, bestOffer: true, fulfilmentMethod: 'FBB' };
const market = { source: 'bol Retailer API', api_version: 'v10', country: 'NL', condition: 'NEW',
  started_at: '2026-09-30T12:00:00Z', measured_at: '2026-09-30T12:00:01Z', status: 'complete', warnings: [],
  offers: [cheap, best], derived: { offer_count: 2, unique_seller_count: 1, price_min: 10, price_max: 15,
    lowest_offer: cheap, best_offers: [best], observed_offer_count: 2, observed_unique_seller_count: 1 } };
const preview = { ean: '4006381333931', preview_id: 'a'.repeat(43), source: 'bol Retailer API v10',
  fetched_at: market.measured_at, status: 'complete', catalog: { title: 'Product', published: true },
  ratings: { count: 5, average: 4 }, warnings: [], market };
function mount(value = market) { act(() => { tree = create(React.createElement(BolMarket, { market: value })); }); }
function text() { return JSON.stringify(tree.toJSON()); }
function fields() { return tree.root.findAllByType('dd'); }

test('shows offer and seller counts separately, with cheapest and official best separately', () => {
  mount();
  assert.equal(fields()[1].children.join(''), '1');
  assert.equal(fields()[2].children.join(''), '2');
  assert.match(text(), /Laagste aanbieding/);
  assert.match(text(), /Beste aanbieding volgens bol/);
  assert.match(text(), /10,00/);
  assert.match(text(), /15,00/);
  assert.match(text(), /FBB/); assert.match(text(), /FBR/);
  assert.match(text(), /23:59/); assert.match(text(), /2026-10-02/);
});

test('shows source, freshness and derived attribution without score integration', () => {
  mount();
  assert.match(text(), /bol Retailer API/); assert.match(text(), /v10/);
  assert.match(text(), /Ouderdom bij weergave/);
  assert.match(text(), /ProductRadar-telling/);
  assert.match(text(), /Opportunity Score en Decision Engine niet aan/);
});

test('partial data hides total counts and price range even if supplied incorrectly', () => {
  mount({ ...market, status: 'partial', warnings: ['Pagina 2 kon niet worden opgehaald.'] });
  assert.equal(fields()[0].children.join(''), 'Onbekend');
  assert.equal(fields()[1].children.join(''), 'Onbekend');
  assert.equal(fields()[2].children.join(''), 'Onbekend');
  assert.match(text(), /geen volledige markttotalen/);
  assert.match(text(), /Pagina 2/);
});

test('unavailable data never presents zero competition', () => {
  mount({ ...market, status: 'unavailable', offers: [], derived: { ...market.derived,
    offer_count: null, unique_seller_count: null, observed_offer_count: 0, observed_unique_seller_count: 0 } });
  assert.equal(fields()[1].children.join(''), 'Onbekend');
  assert.equal(fields()[2].children.join(''), 'Onbekend');
  assert.match(text(), /betekent niet dat er geen concurrentie is/);
});

test('complete explicit empty result has zero offers but no fabricated price or best offer', () => {
  mount({ ...market, offers: [], derived: { ...market.derived, offer_count: 0, unique_seller_count: 0,
    price_min: null, price_max: null, lowest_offer: null, best_offers: [] } });
  assert.equal(fields()[0].children.join(''), 'Onbekend');
  assert.equal(fields()[1].children.join(''), '0');
  assert.equal(fields()[2].children.join(''), '0');
  assert.equal(fields()[4].children.join(''), 'Niet beschikbaar');
});

test('legacy snapshots without market data show absence rather than zero', () => {
  act(() => { tree = create(React.createElement(BolMarket, {})); });
  assert.match(text(), /Geen marktmeting opgeslagen/);
  assert.equal(tree.root.findAllByType('dd').length, 0);
});

test('offer text is escaped and missing delivery metadata is explicit', () => {
  const offer = { ...cheap, retailerId: '<script>danger</script>', fulfilmentMethod: null, minDeliveryDate: null, maxDeliveryDate: null, ultimateOrderTime: null };
  mount({ ...market, offers: [offer], derived: { ...market.derived, lowest_offer: offer } });
  assert.equal(tree.root.findAllByType('script').length, 0);
  assert.match(text(), /onbekend/);
});

test('EAN preview displays market measurement without automatic POST', async () => {
  const calls = [];
  global.fetch = async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => preview }; };
  act(() => { tree = create(React.createElement(BolEanPreview, { api: '/api' })); });
  act(() => tree.root.findByType('input').props.onChange({ target: { value: preview.ean } }));
  await act(async () => tree.root.findByType('form').props.onSubmit({ preventDefault() {} }));
  assert.equal(calls.length, 1); assert.equal(calls[0].options.method, undefined);
  assert.equal(tree.root.findAllByProps({ 'aria-label': 'Bol marktmeting' }).length, 1);
});

test('saving keeps server receipt only and displays persisted market data', async () => {
  const calls = [];
  global.fetch = async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => ({ id: 1, saved_at: preview.fetched_at, preview }) }; };
  act(() => { tree = create(React.createElement(BolSnapshots, { api: '/api', ean: preview.ean, previewId: preview.preview_id })); });
  await act(async () => tree.root.findAllByType('button')[0].props.onClick());
  assert.deepEqual(JSON.parse(calls[0].options.body), { preview_id: preview.preview_id });
  assert.equal(tree.root.findAllByProps({ 'aria-label': 'Bol marktmeting' }).length, 1);
  assert.match(text(), /ProductRadar-telling/);
});

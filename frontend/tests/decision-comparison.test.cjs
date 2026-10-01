const { test, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
const React = require('react');
const { create } = require('react-test-renderer');
const { renderToStaticMarkup } = require('react-dom/server');
const { act } = React;
global.IS_REACT_ACT_ENVIRONMENT = true;
require.extensions['.tsx'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS },
}).outputText, filename);
const { ComparisonView, DecisionComparison, score } = require('../components/DecisionComparison.tsx');
const { DecisionEvaluation } = require('../components/DecisionEvaluation.tsx');
const cases = require('../../backend/tests/fixtures/comparison_scenarios.json');
const clone = value => JSON.parse(JSON.stringify(value));
let tree;
const originalFetch = global.fetch;
afterEach(() => { if (tree) act(() => tree.unmount()); tree = undefined; global.fetch = originalFetch; });
function mount(type, props) { act(() => { tree = create(React.createElement(type, props)); }); }
function text() { return JSON.stringify(tree.toJSON()); }

for (const { scenario, comparison } of cases) {
  test(`renders actual engine acceptance comparison: ${scenario}`, () => {
    mount(ComparisonView, { comparison });
    const v1 = tree.root.findByProps({ 'aria-label': 'Decision Engine v1' });
    const v2 = tree.root.findByProps({ 'aria-label': 'Decision Engine v2' });
    assert.equal(v1.findByType('strong').children.join(''), score(comparison.analysis_v1.opportunity_score));
    assert.equal(v2.findByType('strong').children.join(''), score(comparison.analysis_v2.opportunity_score));
    assert.match(text(), new RegExp(comparison.analysis_v2.verdict));
    assert.ok(text().includes(comparison.primary_reason.text));
    assert.match(text(), /V1 blijft de standaard/);
  });
}

test('stale market price is historical and blocks definitive-score messaging', () => {
  mount(ComparisonView, { comparison: cases[4].comparison });
  assert.match(text(), /Marktdata ouder dan 24 uur/);
  assert.match(text(), /Historische prijsrange — geen actuele prijs/);
  assert.match(text(), /Geen definitieve actuele Opportunity Score/);
  assert.doesNotMatch(text(), /Prijsrange in opgeslagen meting \(maximaal 24 uur oud\)/);
});

test('provenance labels never claim sales estimates are official sales', () => {
  mount(ComparisonView, { comparison: cases[0].comparison });
  assert.match(text(), /Officiële bol-meting/);
  assert.match(text(), /Handmatig \/ geïmporteerd/);
  assert.match(text(), /Door ProductRadar berekend/);
  assert.match(text(), /Schatting — geen gemeten verkoopcijfer/);
  assert.match(text(), /geen gemeten verkopen/);
  assert.match(text(), /Bron- en invoerdatum zijn onbekend/);
});

test('missing values show unknown; legitimate zero stays zero', () => {
  const c = clone(cases[0].comparison);
  c.analysis_v2.opportunity_score = null;
  c.analysis_v2.subscores.demand = null;
  c.analysis_v2.subscores.competition = 0;
  c.market.price_min = null; c.market.price_max = null;
  mount(ComparisonView, { comparison: c });
  assert.match(text(), /Onbekend/); assert.match(text(), /0\/100/);
  assert.match(text(), /Onbekend is geen nul/);
  assert.equal(score(null), 'Onbekend'); assert.equal(score(0), '0/100');
});

test('safeguards drivers confidence and missing financial inputs are visible', () => {
  mount(ComparisonView, { comparison: cases[4].comparison });
  assert.match(text(), /Data Confidence/);
  assert.match(text(), /Veiligheidsgrenzen en caps/);
  assert.match(text(), /Kritieke ontbrekende gegevens/);
  assert.match(text(), /Een cap vult een ontbrekende score niet in/);
  assert.match(text(), /Positieve v2-drivers/);
  assert.match(text(), /Negatieve v2-drivers/);
  assert.match(text(), /Hoger betekent meer risico/);
});

test('loading comparison requires explicit action and makes only a no-store GET', async () => {
  const calls = [];
  global.fetch = async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => cases[0].comparison }; };
  mount(DecisionComparison, { productId: 1, api: '/api' });
  assert.equal(calls.length, 0);
  await act(async () => tree.root.findByType('button').props.onClick());
  assert.deepEqual(calls, [{ url: '/api/comparison/products/1', options: { cache: 'no-store' } }]);
  assert.match(text(), /Kansrijk/);
});

test('network or malformed-response errors allow retry without fake scores', async () => {
  global.fetch = async () => { throw new Error('Sensitive transport detail'); };
  mount(DecisionComparison, { productId: 1, api: '/api' });
  await act(async () => tree.root.findByType('button').props.onClick());
  assert.match(text(), /Vergelijking niet beschikbaar/);
  assert.doesNotMatch(text(), /Sensitive/);
  assert.equal(tree.root.findByType('button').props.disabled, false);
  global.fetch = async () => ({ ok: true, json: async () => ({}) });
  await act(async () => tree.root.findByType('button').props.onClick());
  assert.equal(tree.root.findAllByProps({ 'aria-label': 'Decision Engine v2' }).length, 0);
});

test('switching products ignores late responses and clears old analysis', async () => {
  let resolve;
  global.fetch = () => new Promise(r => { resolve = r; });
  mount(DecisionComparison, { productId: 1, api: '/api' });
  let pending;
  act(() => { pending = tree.root.findByType('button').props.onClick(); });
  act(() => tree.update(React.createElement(DecisionComparison, { productId: 2, api: '/api' })));
  await act(async () => { resolve({ ok: true, json: async () => cases[0].comparison }); await pending; });
  assert.equal(tree.root.findAllByProps({ 'aria-label': 'Decision Engine v2' }).length, 0);
});

test('evaluation preserves API order and shows per-product failure without sorting by v2', async () => {
  const a = clone(cases[0].comparison), b = clone(cases[4].comparison);
  a.product.id = 20; b.product.id = 10;
  const calls = [];
  global.fetch = async (url, options) => { calls.push({url,options}); return { ok: true, json: async () => ({
    items: [b,a,{ product:{id:30,name:'Onleesbaar'},error:'Vergelijking niet beschikbaar.' }],
    total:3,offset:0,limit:25,next_offset:null,evaluated_at:a.evaluated_at,
  }) }; };
  mount(DecisionEvaluation, {api:'/api'});
  assert.equal(calls.length,0);
  await act(async () => tree.root.findByType('button').props.onClick());
  assert.deepEqual(tree.root.findAllByType('a').map(a => a.props.href), ['/products/10','/products/20','/products/30']);
  assert.match(text(), /geen v2-rangschikking/);
  assert.match(text(), /Geen definitieve actuele score/);
  assert.match(text(), /Vergelijking niet beschikbaar/);
  assert.equal(calls[0].options.method, undefined);
});

test('evaluation pagination uses saved products and maintains no-store GET requests', async () => {
  const calls = [];
  global.fetch = async (url, options) => { calls.push({url,options}); return {ok:true,json:async()=>({items:[],total:26,offset:calls.length===1?0:25,limit:25,next_offset:calls.length===1?25:null,evaluated_at:'2026-10-01'})}; };
  mount(DecisionEvaluation, {api:'/api'});
  await act(async () => tree.root.findByType('button').props.onClick());
  await act(async () => tree.root.findAllByType('button').find(b => b.children.join('')==='Volgende pagina').props.onClick());
  assert.equal(calls[1].url, '/api/comparison/products?offset=25&limit=25');
  assert.equal(calls[1].options.cache, 'no-store');
});

test('source text is escaped and cannot inject HTML', () => {
  const c=clone(cases[0].comparison);
  c.primary_reason.text='<script>alert(1)</script>';
  const html=renderToStaticMarkup(React.createElement(ComparisonView,{comparison:c}));
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(!html.includes('<script>'));
});

const { test, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
const React = require('react');
const { create } = require('react-test-renderer');
const { act } = React;
global.IS_REACT_ACT_ENVIRONMENT = true;
require.extensions['.tsx'] = (module, filename) => {
  module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS },
  }).outputText, filename);
};
const { BolEanPreview } = require('../components/BolEanPreview.tsx');
let tree;
const originalFetch = global.fetch;
afterEach(() => { if (tree) act(() => tree.unmount()); global.fetch = originalFetch; });
const sample = {
  ean: '4006381333931', source: 'bol Retailer API v10', fetched_at: '2026-09-25T12:00:00Z', language: 'nl',
  catalog: { title: '<script>Testproduct</script>', brand: null, classification_id: '123', published: true, enrichment: 2 },
  ratings: { count: 4, average: 4, distribution: [] }, warnings: [],
};
function mount() { act(() => { tree = create(React.createElement(BolEanPreview, { api: '/api' })); }); }
function input(value) { act(() => tree.root.findByType('input').props.onChange({ target: { value } })); }
async function submit() { await act(async () => tree.root.findByType('form').props.onSubmit({ preventDefault() {} })); }

test('EAN preview only fetches read-only endpoint and renders data as text', async () => {
  const calls = [];
  global.fetch = async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => sample }; };
  mount(); input(sample.ean); await submit();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/bol/ean-preview/4006381333931');
  assert.equal(calls[0].options.cache, 'no-store');
  assert.equal(calls[0].options.method, undefined);
  assert.equal(tree.root.findAllByType('script').length, 0);
  assert.match(JSON.stringify(tree.toJSON()), /Ophalen slaat niets automatisch op/);
  input('0000000000000');
  assert.equal(tree.root.findAllByProps({ role: 'status' }).length, 0);
});

test('invalid EAN is rejected before a network request', async () => {
  global.fetch = async () => { throw new Error('must not call'); };
  mount(); input('123'); await submit();
  assert.match(tree.root.findByProps({ role: 'alert' }).children.join(''), /13 cijfers/);
});

test('missing backend configuration is displayed without a preview', async () => {
  global.fetch = async () => ({ ok: false, json: async () => ({ detail: 'Bol is nog niet ingesteld.' }) });
  mount(); input(sample.ean); await submit();
  assert.match(tree.root.findByProps({ role: 'alert' }).children.join(''), /niet ingesteld/);
  assert.equal(tree.root.findAllByProps({ role: 'status' }).length, 0);
});

test('partial preview shows unavailable ratings and warning', async () => {
  global.fetch = async () => ({ ok: true, json: async () => ({ ...sample, ratings: null, warnings: ['Beoordelingen niet beschikbaar.'] }) });
  mount(); input(sample.ean); await submit();
  assert.match(tree.root.findByProps({ role: 'alert' }).children.join(''), /niet beschikbaar/);
  assert.match(JSON.stringify(tree.toJSON()), /Testproduct/);
});

test('duplicate submissions are blocked and state recovers', async () => {
  let resolve, requests = 0;
  global.fetch = () => { requests++; return new Promise(r => { resolve = r; }); };
  mount(); input(sample.ean);
  let first;
  act(() => {
    const handler = tree.root.findByType('form').props.onSubmit;
    first = handler({ preventDefault() {} }); handler({ preventDefault() {} });
  });
  assert.equal(requests, 1);
  assert.equal(tree.root.findByType('input').props.disabled, true);
  await act(async () => { resolve({ ok: true, json: async () => sample }); await first; });
  assert.equal(tree.root.findByType('input').props.disabled, false);
});

test('network errors show a readable message and restore controls', async () => {
  global.fetch = async () => { throw new TypeError('Failed to fetch'); };
  mount(); input(sample.ean); await submit();
  assert.match(tree.root.findByProps({ role: 'alert' }).children.join(''), /backend is niet bereikbaar/);
  assert.equal(tree.root.findByType('input').props.disabled, false);
});

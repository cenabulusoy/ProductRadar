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
const { BolSnapshots } = require('../components/BolSnapshots.tsx');
const { BolEanPreview } = require('../components/BolEanPreview.tsx');
let tree;
const originalFetch = global.fetch;
afterEach(() => { if (tree) act(() => tree.unmount()); global.fetch = originalFetch; });
const preview = {
  preview_id: 'a'.repeat(43), ean: '4006381333931', source: 'bol Retailer API v10', api_version: 'v10',
  fetched_at: '2026-09-25T12:00:00Z', status: 'complete', bol_product_id: null,
  catalog: { title: '<script>Title</script>', brand: null, published: null },
  ratings: { count: 4, average: 4 }, warnings: [],
};
const stored = { id: 1, saved_at: '2026-09-25T12:01:00Z', preview };
function mount(props = {}) {
  act(() => { tree = create(React.createElement(BolSnapshots, { api: '/api', ean: preview.ean, previewId: preview.preview_id, ...props })); });
}
function buttons() { return tree.root.findAllByType('button'); }
async function click(index) { await act(async () => buttons()[index].props.onClick()); }

test('save is explicit and sends only the server receipt, renders provenance and freshness', async () => {
  const calls = [];
  global.fetch = async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => stored }; };
  mount();
  assert.equal(calls.length, 0);
  await click(0);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/bol/snapshots');
  assert.equal(calls[0].options.method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].options.body), { preview_id: preview.preview_id });
  assert.equal(buttons()[0].props.disabled, true);
  assert.match(JSON.stringify(tree.toJSON()), /Handmatige velden, CSV-data en scores zijn ongewijzigd/);
  assert.match(JSON.stringify(tree.toJSON()), /Ouderdom bij weergave/);
  assert.match(JSON.stringify(tree.toJSON()), /bol Retailer API v10/);
  assert.equal(tree.root.findAllByType('script').length, 0);
});

test('double click performs one save and disables actions while pending', async () => {
  let resolve, count = 0;
  global.fetch = () => { count++; return new Promise(r => { resolve = r; }); };
  mount();
  let pending;
  act(() => { const save = buttons()[0].props.onClick; pending = save(); save(); });
  assert.equal(count, 1);
  assert.ok(buttons().every(button => button.props.disabled));
  await act(async () => { resolve({ ok: true, json: async () => stored }); await pending; });
  assert.equal(buttons()[1].props.disabled, false);
});

test('expired preview displays error and never claims success', async () => {
  global.fetch = async () => ({ ok: false, json: async () => ({ detail: 'Dit voorbeeld is verlopen. Haal eerst een nieuw voorbeeld op.' }) });
  mount(); await click(0);
  assert.match(tree.root.findByProps({ role: 'alert' }).children.join(''), /verlopen/);
  assert.equal(tree.root.findAllByProps({ role: 'status' }).length, 0);
  assert.equal(buttons()[0].props.disabled, false);
});

test('network failure permits retry with the same receipt', async () => {
  const bodies = [];
  global.fetch = async (_, options) => { bodies.push(options.body); if (bodies.length === 1) throw new TypeError('offline'); return { ok: true, json: async () => stored }; };
  mount(); await click(0);
  assert.match(tree.root.findByProps({ role: 'alert' }).children.join(''), /niet bereikbaar/);
  await click(0);
  assert.equal(bodies[0], bodies[1]);
  assert.equal(tree.root.findAllByProps({ role: 'alert' }).length, 0);
});

test('history is available without credentials or a fresh preview and makes only a GET', async () => {
  const calls = [];
  global.fetch = async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => ({ snapshots: [stored] }) }; };
  mount({ previewId: undefined });
  assert.equal(buttons().length, 1);
  assert.equal(calls.length, 0);
  await click(0);
  assert.equal(calls[0].url, '/api/bol/products/4006381333931/snapshots');
  assert.equal(calls[0].options.method, undefined);
  assert.match(JSON.stringify(tree.toJSON()), /nieuwste meting eerst/);
});

test('empty history and invalid EAN are handled', async () => {
  global.fetch = async () => ({ ok: true, json: async () => ({ snapshots: [] }) });
  mount({ previewId: undefined }); await click(0);
  assert.match(JSON.stringify(tree.toJSON()), /Nog geen snapshots/);
  act(() => tree.update(React.createElement(BolSnapshots, { api: '/api', ean: '123' })));
  assert.equal(tree.toJSON(), null);
});

test('partial snapshot keeps warnings and never invents zero ratings', async () => {
  global.fetch = async () => ({ ok: true, json: async () => ({ ...stored,
    preview: { ...preview, status: 'partial', ratings: null, warnings: ['Beoordelingen niet beschikbaar.'] } }) });
  mount(); await click(0);
  const view = JSON.stringify(tree.toJSON());
  assert.match(view, /Gedeeltelijke meting/);
  assert.match(view, /Niet beschikbaar/);
  assert.match(view, /Beoordelingen niet beschikbaar/);
});

test('malformed error response restores controls', async () => {
  global.fetch = async () => ({ ok: false, json: async () => { throw new Error('not JSON'); } });
  mount(); await click(0);
  assert.match(tree.root.findByProps({ role: 'alert' }).children.join(''), /tijdelijk niet beschikbaar/);
  assert.equal(buttons()[0].props.disabled, false);
});

test('changing EAN removes the old preview save action and history', async () => {
  global.fetch = async () => ({ ok: true, json: async () => preview });
  act(() => { tree = create(React.createElement(BolEanPreview, { api: '/api' })); });
  act(() => tree.root.findByType('input').props.onChange({ target: { value: preview.ean } }));
  await act(async () => tree.root.findByType('form').props.onSubmit({ preventDefault() {} }));
  assert.ok(buttons().some(button => button.children.join('').includes('als snapshot opslaan')));
  act(() => tree.root.findByType('input').props.onChange({ target: { value: '0000000000000' } }));
  assert.ok(!buttons().some(button => button.children.join('').includes('als snapshot opslaan')));
});

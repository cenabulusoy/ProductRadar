const { test, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
const React = require('react');
const { create } = require('react-test-renderer');
const { act } = React;
global.IS_REACT_ACT_ENVIRONMENT = true;

require.extensions['.tsx'] = (module, filename) => {
  const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS },
  });
  module._compile(compiled.outputText, filename);
};
const { CsvImport } = require('../components/CsvImport.tsx');
const originalFetch = global.fetch;
let tree;
afterEach(() => { if (tree) act(() => tree.unmount()); global.fetch = originalFetch; });

const sample = { filename: 'products.csv', product_count: 8, preview: [
  { name: '<script>Product</script>', category: 'Test', brand: 'Brand', ean: '00123', sale_price: 20, purchase_price: 10 },
] };
const response = (body, ok = true) => ({ ok, json: async () => body });
function mount() {
  const calls = [];
  let refreshed = 0;
  global.fetch = async (url, options) => {
    calls.push({ url, file: options.body.get('file') });
    return response(url.endsWith('/preview') ? sample : { message: '1 producten geïmporteerd, 0 overgeslagen' });
  };
  act(() => { tree = create(React.createElement(CsvImport, {
    api: '/api', onImported: async () => { refreshed++; },
  })); });
  return { calls, refreshed: () => refreshed };
}
function button(label) { return tree.root.findAllByType('button').find(b => b.children.join('') === label); }
async function select(file = new File(['content'], 'products.csv', { type: 'text/csv' })) {
  const target = { files: [file], value: 'products.csv' };
  await act(async () => { tree.root.findByType('input').props.onChange({ target }); });
  assert.equal(target.value, '');
  return file;
}
async function click(label) { await act(async () => { button(label).props.onClick(); }); }

test('selection only previews, displays count, filename and literal product text', async () => {
  const state = mount();
  await select();
  assert.deepEqual(state.calls.map(c => c.url), ['/api/products/import/preview']);
  const rendered = JSON.stringify(tree.toJSON());
  assert.match(rendered, /products.csv/);
  assert.match(rendered, /8/);
  assert.match(rendered, /<script>Product<\/script>/);
  assert.equal(tree.root.findAllByType('script').length, 0);
  assert.ok(button('Definitief importeren'));
  assert.equal(state.refreshed(), 0);
});

test('cancel makes no import request and supports selecting the same file again', async () => {
  const state = mount();
  const file = await select();
  await click('Annuleren');
  assert.equal(state.calls.length, 1);
  assert.equal(button('Definitief importeren'), undefined);
  await select(file);
  assert.equal(state.calls.length, 2);
  assert.ok(button('Definitief importeren'));
});

test('confirmation sends the exact previewed file and refreshes products once', async () => {
  const state = mount();
  const file = await select();
  await click('Definitief importeren');
  assert.equal(state.calls[1].url, '/api/products/import');
  assert.equal(state.calls[1].file, file);
  assert.equal(state.refreshed(), 1);
  assert.equal(button('Definitief importeren'), undefined);
  assert.match(JSON.stringify(tree.toJSON()), /1 producten geïmporteerd/);
});

test('double confirmation is blocked while importing', async () => {
  mount();
  await select();
  let resolve;
  let requests = 0;
  global.fetch = () => { requests++; return new Promise(r => { resolve = r; }); };
  const confirm = button('Definitief importeren').props.onClick;
  await act(async () => { confirm(); confirm(); });
  assert.equal(requests, 1);
  assert.equal(button('Importeren…').props.disabled, true);
  assert.equal(button('Annuleren').props.disabled, true);
  assert.equal(tree.root.findByType('input').props.disabled, true);
  await act(async () => { resolve(response({ message: 'Klaar' })); });
});

test('invalid preview clears the previous file and prevents confirmation', async () => {
  mount();
  await select();
  global.fetch = async () => response({ detail: 'Regel 2: ongeldige numerieke waarde' }, false);
  await select(new File(['bad'], 'invalid.csv'));
  assert.equal(button('Definitief importeren'), undefined);
  assert.match(tree.root.findByProps({ role: 'alert' }).children.join(''), /Regel 2/);
});

test('import failure shows backend error and retains preview for retry', async () => {
  const state = mount();
  await select();
  global.fetch = async () => response({ detail: 'Import mislukt' }, false);
  await click('Definitief importeren');
  assert.ok(button('Definitief importeren'));
  assert.equal(state.refreshed(), 0);
  assert.match(tree.root.findByProps({ role: 'alert' }).children.join(''), /Import mislukt/);
});

test('non-JSON server failure is readable and leaves no confirmation', async () => {
  mount();
  global.fetch = async () => ({ ok: false, json: async () => { throw new Error('HTML'); } });
  await select();
  assert.match(tree.root.findByProps({ role: 'alert' }).children.join(''), /verbinding/);
  assert.equal(button('Definitief importeren'), undefined);
});

test('network error restores file selection', async () => {
  mount();
  global.fetch = async () => { throw new Error('Netwerk niet bereikbaar'); };
  await select();
  assert.match(tree.root.findByProps({ role: 'alert' }).children.join(''), /Netwerk/);
  assert.equal(button('CSV kiezen').props.disabled, false);
});

test('replacement file is previewed and becomes the file imported', async () => {
  const state = mount();
  await select();
  const replacement = await select(new File(['replacement'], 'replacement.csv'));
  await click('Definitief importeren');
  assert.equal(state.calls[2].file, replacement);
});

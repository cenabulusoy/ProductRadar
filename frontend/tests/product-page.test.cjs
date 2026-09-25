const { test, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');

require.extensions['.tsx'] = (module, filename) => {
  const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS },
  });
  module._compile(compiled.outputText, filename);
};
const ProductPage = require('../app/products/[id]/page.tsx').default;
const originalFetch = global.fetch;
afterEach(() => { global.fetch = originalFetch; });

test('product page waits for async params and fetches fresh product details', async () => {
  const product = { id: 42, name: 'Testproduct' };
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({ url, options });
    return { ok: true, json: async () => product };
  };
  let resolveParams;
  const pending = ProductPage({ params: new Promise(resolve => { resolveParams = resolve; }) });
  assert.equal(calls.length, 0);
  resolveParams({ id: '42' });
  const element = await pending;
  assert.equal(calls.length, 1);
  assert.ok(calls[0].url.endsWith('/products/42'));
  assert.equal(calls[0].options.cache, 'no-store');
  assert.equal(element.props.product, product);
});

test('product page preserves backend failure handling', async () => {
  global.fetch = async () => ({ ok: false });
  await assert.rejects(ProductPage({ params: Promise.resolve({ id: '999' }) }), /Product niet gevonden/);
});

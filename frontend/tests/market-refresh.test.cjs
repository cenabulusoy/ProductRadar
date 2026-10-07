const {test,afterEach}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),ts=require('typescript'),React=require('react'),{create}=require('react-test-renderer');
const {act}=React;global.IS_REACT_ACT_ENVIRONMENT=true;
for(const ext of ['.ts','.tsx'])require.extensions[ext]=(m,f)=>m._compile(ts.transpileModule(fs.readFileSync(f,'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS}}).outputText,f);
const {MarketRefresh}=require('../components/MarketRefresh.tsx'),{FreshnessView}=require('../components/MarketFreshness.tsx');
const {ComparisonView,DecisionComparison}=require('../components/DecisionComparison.tsx');
const comparison=require('../../backend/tests/fixtures/comparison_scenarios.json')[0].comparison;
const market={...comparison.market,freshness:'current',age_hours:3};
const body={product_id:1,can_refresh:true,identity_notice:null,market,history:[market]};
let tree;const originalFetch=global.fetch;
afterEach(()=>{if(tree)act(()=>tree.unmount());tree=undefined;global.fetch=originalFetch;});
async function mount(type=MarketRefresh,props={productId:1,api:'/api'}){await act(async()=>{tree=create(React.createElement(type,props));});}
function text(){return JSON.stringify(tree.toJSON());}
function button(label){return tree.root.findAllByType('button').find(b=>b.children.join('')===label);}
const ok=(value)=>({ok:true,json:async()=>value});
for(const [status,label] of [['current','Actueel'],['stale','Verversen aanbevolen'],['historical','Historische marktmeting'],['missing','Geen marktmeting'],['incomplete','Laatste meting onvolledig'],['error','Laatste meting mislukt']]){
 test('renders backend freshness bucket '+status,async()=>{
  await mount(FreshnessView,{market:{...market,freshness:status,age_hours:status==='missing'?null:38}});assert.match(text(),new RegExp(label));assert.match(text(),/door ProductRadar afgeleid/);
  if(status!=='current')assert.match(text(),/voordat v2/);
 });
}
test('GET status on load, no refresh without EAN and no fake mutation',async()=>{
 const calls=[];global.fetch=async(url,options)=>{calls.push({url,options});return ok({...body,can_refresh:false,identity_notice:'Een geldige EAN/productidentiteit is eerst nodig.'});};
 await mount();assert.equal(calls.length,1);assert.equal(calls[0].options.cache,'no-store');assert.equal(button('Markt verversen'),undefined);assert.match(text(),/EAN\/productidentiteit/);
});
test('explicit successful refresh reloads stored offers, source and comparison callback',async()=>{
 const calls=[];let reload=0;global.fetch=async(url,options)=>{calls.push({url,options});return ok(options.method==='POST'?{refresh:{outcome:'saved'}}:body);};
 await mount(MarketRefresh,{productId:1,api:'/api',onReload:()=>reload++});assert.equal(calls.length,1);
 await act(async()=>button('Markt verversen').props.onClick());assert.equal(calls.length,3);assert.equal(calls[1].options.method,'POST');assert.match(JSON.parse(calls[1].options.body).request_id,/^[a-f0-9-]{36}$/);
 assert.ok(calls[2].url.endsWith('/market-status'));assert.equal(reload,1);assert.match(text(),/Nieuwe marktmeting opgeslagen/);assert.match(text(),/Actuele prijsrange/);assert.match(text(),/Unieke verkopers/);assert.match(text(),/geen verkoopvolume/);
});
test('double concurrent click sends one refresh and hides old current price while pending',async()=>{
 let resolve,count=0;global.fetch=async(url,options)=>{if(options.method==='POST'){count++;return new Promise(r=>{resolve=r;});}return ok(body);};
 await mount();const click=button('Markt verversen').props.onClick;let pending;act(()=>{pending=click();click();});
 assert.equal(count,1);assert.doesNotMatch(text(),/Actuele prijsrange/);assert.match(text(),/refresh is bezig/);
 await act(async()=>{resolve(ok({refresh:{outcome:'saved'}}));await pending;});
});
test('failed latest never presents previous measurement as current',async()=>{
 let posted=false;const failed={...body,market:{...market,freshness:'error',reason:'latest_measurement_failed',price_min:null,price_max:null,offer_count:null,unique_seller_count:null},history:[market]};
 global.fetch=async(url,options)=>{if(options.method==='POST'){posted=true;return ok({refresh:{outcome:'failed',message:'Bol vraagt om te wachten.'}});}return ok(posted?failed:body);};
 await mount();await act(async()=>button('Markt verversen').props.onClick());assert.match(text(),/Bol vraagt om te wachten/);assert.doesNotMatch(text(),/Actuele prijsrange/);assert.match(text(),/Historische contextprijs/);assert.match(text(),/geen geselecteerde actuele prijs/);
});
test('network failure does not restore old current display or leak details',async()=>{
 global.fetch=async(url,options)=>{if(options.method==='POST')throw new Error('sensitive network transport');return ok(body);};
 await mount();await act(async()=>button('Markt verversen').props.onClick());assert.match(text(),/Verbinding met refresh onderbroken/);assert.doesNotMatch(text(),/sensitive network transport|Actuele prijsrange/);
});
test('retry after uncertain network result reuses idempotency key',async()=>{
 const keys=[];global.fetch=async(url,options)=>{if(options.method==='POST'){keys.push(JSON.parse(options.body).request_id);if(keys.length===1)throw new Error('transport');return ok({refresh:{outcome:'saved'}});}return ok(body);};
 await mount();await act(async()=>button('Markt verversen').props.onClick());await act(async()=>button('Markt verversen').props.onClick());assert.equal(keys.length,2);assert.equal(keys[0],keys[1]);
});
test('409 concurrent conflict is understandable and reloads stored status',async()=>{
 global.fetch=async(url,options)=>options.method==='POST'?{ok:false,status:409}:ok({...body,market:{...market,freshness:'error',reason:'refresh_in_progress'}});
 await mount();await act(async()=>button('Markt verversen').props.onClick());assert.match(text(),/loopt al een refresh/);
});
test('late refresh response cannot overwrite another product',async()=>{
 let resolve;global.fetch=async(url,options)=>options.method==='POST'?new Promise(r=>{resolve=r;}):ok({...body,product_id:url.includes('/2/')?2:1});
 await mount();let pending;act(()=>{pending=button('Markt verversen').props.onClick();});
 await act(async()=>tree.update(React.createElement(MarketRefresh,{productId:2,api:'/api'})));
 await act(async()=>{resolve(ok({refresh:{outcome:'saved'}}));await pending;});assert.doesNotMatch(text(),/Nieuwe marktmeting opgeslagen/);
});
test('comparison reload revision fetches saved v2 and hides previous analysis while refreshing',async()=>{
 let count=0;global.fetch=async()=>{count++;return ok(comparison);};
 await mount(DecisionComparison,{productId:1,api:'/api',refreshRevision:0});assert.equal(count,0);
 await act(async()=>tree.update(React.createElement(DecisionComparison,{productId:1,api:'/api',refreshRevision:1})));assert.equal(count,1);
 await act(async()=>tree.update(React.createElement(DecisionComparison,{productId:1,api:'/api',refreshRevision:1,refreshing:true})));assert.match(text(),/tijdelijk verborgen/);assert.doesNotMatch(text(),/Vergelijking Decision Engine v1 en v2/);
 await act(async()=>tree.update(React.createElement(DecisionComparison,{productId:1,api:'/api',refreshRevision:1,refreshing:false})));assert.equal(count,1);assert.doesNotMatch(text(),/Vergelijking Decision Engine v1 en v2/);
 await act(async()=>tree.update(React.createElement(DecisionComparison,{productId:1,api:'/api',refreshRevision:2})));assert.equal(count,2);
});
test('comparison clearly explains latest failed data and shows unknown rather than zero',async()=>{
 const c=structuredClone(comparison);Object.assign(c.market,{freshness:'error',reason:'latest_measurement_failed',price_min:null,price_max:null,offer_count:null,unique_seller_count:null});c.analysis_v2.opportunity_score=null;
 await mount(ComparisonView,{comparison:c});assert.match(text(),/Laatste meting mislukt/);assert.match(text(),/Geen definitieve actuele Opportunity Score/);assert.match(text(),/Onbekend/);assert.match(text(),/Schatting — geen gemeten verkoopcijfer/);
});

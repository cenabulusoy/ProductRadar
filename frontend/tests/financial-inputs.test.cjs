const {test,afterEach}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),ts=require('typescript'),React=require('react');
const {create}=require('react-test-renderer');
const {act}=React;
global.IS_REACT_ACT_ENVIRONMENT=true;
for(const ext of ['.ts','.tsx']) require.extensions[ext]=(module,file)=>module._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS}}).outputText,file);
const {blankDraft,buildProfile,loadDraft}=require('../lib/financial-form.ts');
const {FinancialEditor,FinancialPreview}=require('../components/FinancialEditor.tsx');
let tree;const originalFetch=global.fetch;
afterEach(()=>{if(tree)act(()=>tree.unmount());tree=undefined;global.fetch=originalFetch;});
const provenance={kind:'manual_or_imported',source:'Bevestigde testinvoer',recorded_at:'2026-01-01T12:00:00Z'};
function entry(d,key,amount){Object.assign(d.entries[key],{amount,basis:'effective',source:provenance.source,recorded:'2026-01-01T12:00:00'});}
function mount(type=FinancialEditor,props={productId:1,api:'/api'}){act(()=>{tree=create(React.createElement(type,props));});}
function button(label){return tree.root.findAllByType('button').find(b=>b.children.join('')===label);}
function visible(){return JSON.stringify(tree.toJSON());}
const data={saved:null,history:[],suggestions:[{field:'purchase_cost',value:0}]};
const fin={price_selection:{selected_gross_price:null,reason:'market_older_than_24_hours',market_reference:{status:'unavailable'}},base:{revenue_excluding_vat:null,contribution_per_unit:null,contribution_margin_percent:null,inventory_roi_percent:null,missing_inputs:['sales_vat_rate']},stress:{sale_price_including_vat:null,contribution_per_unit:null}};
test('blank inputs do not guess VAT, fees or confirm legacy values',()=>{
 const d=blankDraft(),p=buildProfile(d);assert.equal(d.flat,'');assert.equal(d.entries.sales_vat_rate.amount,'');
 assert.deepEqual(p.financial,{currency:'EUR',scenario_mode:'conservative'});assert.deepEqual(p.breakdown,{});
});
test('decimal zero, unknown amount, tax deductibility and provenance round-trip',()=>{
 const d=blankDraft();entry(d,'purchase_cost','0');entry(d,'inbound_cost','');d.entries.inbound_cost.kind='estimated';
 d.entries.purchase_cost.importRef='csv-123';d.entries.purchase_cost.basis='inclusive';d.entries.purchase_cost.vat='0';d.entries.purchase_cost.recoverable='false';
 const p=buildProfile(d);assert.equal(p.breakdown.purchase_cost.amount,'0');assert.equal(p.breakdown.inbound_cost.amount,null);
 assert.equal(p.breakdown.purchase_cost.input_vat_recoverable,false);assert.equal(p.breakdown.inbound_cost.provenance.kind,'estimated');
 assert.equal(p.references['breakdown.purchase_cost'].import_reference,'csv-123');
 const loaded=loadDraft(p);assert.equal(loaded.entries.purchase_cost.amount,'0');assert.equal(loaded.entries.inbound_cost.amount,'');assert.equal(loaded.entries.purchase_cost.recoverable,'false');
});
test('fixed and variable commission remain separate and tariff is explicit',()=>{
 const d=blankDraft();entry(d,'fixed_fee','1');entry(d,'commission','10');
 let p=buildProfile(d);assert.equal(p.financial.commission.fixed_fee.amount,'1');assert.equal(p.financial.commission.variable_rate_percent,'10');assert.equal(p.financial.commission.flat_tariff_confirmed,null);
 d.flat='false';d.from='10';d.to='30';p=buildProfile(d);assert.equal(p.financial.commission.flat_tariff_confirmed,false);assert.equal(p.financial.commission.valid_to_gross_price,'30');
});
test('unconfirmed source/date and invalid date are refused before requesting preview',()=>{
 const d=blankDraft();d.entries.planned_sale_price.amount='30';assert.throws(()=>buildProfile(d),/bron en datum/);
 entry(d,'planned_sale_price','30');d.entries.planned_sale_price.recorded='invalid';assert.throws(()=>buildProfile(d),/Ongeldige datum/);
});
test('official measurement keeps snapshot reference and does not label estimates official',()=>{
 const d=blankDraft();entry(d,'planned_sale_price','24.2');Object.assign(d.entries.planned_sale_price,{basis:'inclusive',kind:'official_measured',snapshotRef:'9'});
 const p=buildProfile(d);assert.equal(p.financial.planned_sale_price.provenance.snapshot_id,9);assert.equal(p.references['financial.planned_sale_price'].snapshot_id,9);
});
test('unknown preview stays unknown and contribution is not presented as net profit',()=>{
 mount(FinancialPreview,{financial:fin});assert.match(visible(),/Onbekend/);assert.match(visible(),/24 uur/);assert.match(visible(),/Bijdrage is geen nettowinst/);assert.match(visible(),/sales_vat_rate/);
});
test('editor starts without requests and legacy proposal requires explicit source/date',async()=>{
 const calls=[];global.fetch=async(url,options)=>{calls.push({url,options});return{ok:true,json:async()=>data};};
 mount();assert.equal(calls.length,0);await act(async()=>button('Financiële invoer laden').props.onClick());assert.equal(calls[0].options.cache,'no-store');
 act(()=>button('Gebruik bedrag als voorstel').props.onClick());assert.equal(tree.root.findByProps({'aria-label':'Inkoopprijs'}).props.value,'0');
 await act(async()=>button('Bereken live preview').props.onClick());assert.equal(calls.length,1);assert.match(visible(),/bron en datum/);assert.match(visible(),/V1 blijft de standaard/);
});
test('preview does not save; explicit confirmation saves exact preview and version',async()=>{
 const calls=[];global.fetch=async(url,options)=>{calls.push({url,options});return{ok:true,json:async()=>options.method==='POST'?(url.endsWith('/preview')?{preview_id:'receipt',financial:fin,proposals:{}}:{version:1,saved_at:'2026-01-01'}):data};};
 mount();await act(async()=>button('Financiële invoer laden').props.onClick());await act(async()=>button('Bereken live preview').props.onClick());
 assert.equal(calls.length,2);assert.equal(button('Bevestig en sla financiële versie op').props.disabled,true);
 act(()=>tree.root.findByProps({type:'checkbox'}).props.onChange({target:{checked:true}}));
 await act(async()=>button('Bevestig en sla financiële versie op').props.onClick());const payload=JSON.parse(calls[2].options.body);
 assert.equal(payload.confirmed,true);assert.equal(payload.expected_version,0);assert.equal(payload.preview_id,'receipt');assert.deepEqual(payload.profile,JSON.parse(calls[1].options.body).profile);
 assert.match(visible(),/versie 1 opgeslagen/);assert.match(visible(),/Versiehistorie/);
});
test('editing invalidates preview and confirmation',async()=>{
 global.fetch=async(url)=>({ok:true,json:async()=>url.endsWith('/preview')?{preview_id:'receipt',financial:fin,proposals:{}}:data});
 mount();await act(async()=>button('Financiële invoer laden').props.onClick());await act(async()=>button('Bereken live preview').props.onClick());
 act(()=>tree.root.findByProps({'aria-label':'Geplande verkoopprijs'}).props.onChange({target:{value:'30'}}));
 assert.equal(button('Bevestig en sla financiële versie op'),undefined);assert.doesNotMatch(visible(),/Live preview/);
});
test('network details are hidden and conflict requires reloading',async()=>{
 global.fetch=async()=>({ok:false,status:409});mount();await act(async()=>button('Financiële invoer laden').props.onClick());assert.match(visible(),/Laad de nieuwste versie/);
 global.fetch=async()=>{throw new Error('secret transport value');};await act(async()=>button('Financiële invoer laden').props.onClick());assert.doesNotMatch(visible(),/secret transport value/);
});
test('switching product ignores a pending old load response',async()=>{
 let resolve;global.fetch=()=>new Promise(r=>{resolve=r;});mount();
 let pending;act(()=>{pending=button('Financiële invoer laden').props.onClick();});
 act(()=>tree.update(React.createElement(FinancialEditor,{productId:2,api:'/api'})));
 await act(async()=>{resolve({ok:true,json:async()=>data});await pending;});
 assert.equal(button('Bereken live preview'),undefined);assert.equal(button('Financiële invoer laden').props.disabled,false);
});
test('double save sends one request while pending',async()=>{
 let resolve,postCount=0;
 global.fetch=async(url,options)=>{if(options.method==='POST'&&!url.endsWith('/preview')){postCount++;return new Promise(r=>{resolve=r;});}return{ok:true,json:async()=>url.endsWith('/preview')?{preview_id:'receipt',financial:fin,proposals:{}}:data};};
 mount();await act(async()=>button('Financiële invoer laden').props.onClick());await act(async()=>button('Bereken live preview').props.onClick());act(()=>tree.root.findByProps({type:'checkbox'}).props.onChange({target:{checked:true}}));
 const handler=button('Bevestig en sla financiële versie op').props.onClick;let pending;act(()=>{pending=handler();handler();});assert.equal(postCount,1);
 await act(async()=>{resolve({ok:true,json:async()=>({version:1,saved_at:'2026-01-01'})});await pending;});assert.match(visible(),/versie 1 opgeslagen/);
});
test('derived total proposal invalidates receipt and still requires source and date',async()=>{
 global.fetch=async(url)=>({ok:true,json:async()=>url.endsWith('/preview')?{preview_id:'receipt',financial:fin,proposals:{landed_purchase_cost:{amount:'5'}}}:data});
 mount();await act(async()=>button('Financiële invoer laden').props.onClick());await act(async()=>button('Bereken live preview').props.onClick());act(()=>button('Neem totaal als voorstel over').props.onClick());
 assert.equal(tree.root.findByProps({'aria-label':'Bevestigde landed inkoopkosten (totaal)'}).props.value,'5');assert.equal(button('Bevestig en sla financiële versie op'),undefined);
 assert.equal(tree.root.findByProps({'aria-label':'Herkomst Bevestigde landed inkoopkosten (totaal)'}).props.value,'derived');
 await act(async()=>button('Bereken live preview').props.onClick());assert.match(visible(),/bron en datum/);
});

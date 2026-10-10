"use client";
import { useEffect,useRef,useState } from "react";
import { ProvenanceLegend } from "./DecisionComparison";
type Context={id:number;name:string;parameters:Record<string,unknown>;watched:{id:number;ean:string}[];last_run:{status:string;started_at:string;completed_at:string|null;lease_expired?:boolean}|null};
type Change=Record<string,unknown>;
type History={points:{id:number|null;measured_at:string;payload:{status:string;list_status:string;position:number|null;preview?:{ratings?:{count:number}|null}}}[];
  demand_evidence:{rating_history:string;market_measurements:number;rating_measurements:number;actual_sales_evidence:null;comparison:Change;rating_growth:Change|null;notice:string;seller_trend_available:boolean;price_trend_available:boolean}};
const API=process.env.NEXT_PUBLIC_API_URL??"http://localhost:8000/api";
export function change(value:unknown){return value==null?'Onbekend':value===false?'Geen verandering':value===true?'Verandering gemeten':typeof value==='number'?`${value>0?'+':''}${Number(value.toFixed(4))}`:String(value);}
const labels:Record<string,string>={rating_count_delta:'Ratingaantal Δ',rating_growth_per_day:'Ratinggroei per dag',rating_growth_per_30_days:'Ratinggroei per 30 dagen',seller_count_delta:'Unieke verkopers Δ',offer_count_delta:'Aanbiedingen Δ',relevant_price_delta:'Relevante prijs Δ',price_min_delta:'Laagste prijs Δ',price_max_delta:'Hoogste prijs Δ',best_offer_changed:'Beste aanbieding gewisseld',list_position_delta:'Contextgebonden lijstpositie Δ (positief = hoger positienummer)',fulfilment_changed:'Fulfilment gewijzigd',delivery_changed:'Levertermijn gewijzigd'};
const reasons:Record<string,string>={no_previous_comparable_measurement:'Nog geen vorige vergelijkbare meting',different_identity_or_context:'Andere productidentiteit of zoekcontext',conflicting_product_identity:'Conflicterende bol-productidentiteit',invalid_timestamp:'Meetmoment ongeldig',non_positive_interval:'Geen positief meetinterval',comparable_context:'Dezelfde zoekcontext en een positief interval',missing_or_incomplete_ratings:'Ratings ontbreken of zijn onvolledig',missing_or_incomplete_market:'Marktmeting ontbreekt of is onvolledig',interval_outside_14_60_days:'Interval ligt buiten 14–60 dagen',rating_count_decreased:'Ratingaantal gedaald; geen groeisignaal',not_observed_or_failed_in_this_page_context:'Niet waargenomen of lijstmeting onvolledig/mislukt',non_positive_list_interval:'Geen nieuw vergelijkbaar lijstmeetmoment'};
export function DiscoveryHistory({history}:{history:History}){
 const e=history.demand_evidence,g=e.rating_growth;
 return <section className="panel"><h3>Historische metingen · geen actuele prijs</h3>
  <p>Ratinghistorie: {e.rating_history} · {e.rating_measurements} ratingmeetpunten · {e.market_measurements} complete marktmeetpunten.</p>
  <p>Verkoperstrend: {e.seller_trend_available?'beschikbaar':'onbekend'} · Prijstrend: {e.price_trend_available?'beschikbaar':'onbekend'} · Werkelijke verkopen: onbekend. Geen Demand Score of verkoopschatting.</p>
  <p>{e.notice}</p>
  {g&&<p>{change(g.rating_count_delta)} ratings in {change(g.interval_days)} dagen · derived demand signal; geen verkopen.</p>}
  <h4>Verandering sinds vorige vergelijkbare meting · derived</h4>
  <p>Vergelijkingsstatus: {reasons[String(e.comparison.reason)]??'Onbekend'} · Interval: {change(e.comparison.interval_days)} dagen.</p>
  {!!e.comparison.metric_reasons&&<p>Ontbrekend vergelijkingsbewijs: {Object.values(e.comparison.metric_reasons as Record<string,string>).map(r=>reasons[r]??'Onbekend').join('; ')||'Geen aanvullende beperkingen'}</p>}
  <dl>{Object.keys(labels).map(k=><div key={k}><dt>{labels[k]}</dt><dd>{change(e.comparison[k])}</dd></div>)}</dl>
  <p>Onbekend betekent onvoldoende vergelijkbaar bewijs; nul betekent gemeten geen verschil. Niet waargenomen op één lijstpagina betekent geen gemeten positiedaling of verdwenen verkoop.</p>
  <table className="comparison-table"><thead><tr><th>Meetmoment</th><th>Status</th><th>Lijstwaarneming</th><th>Contextpositie</th><th>Ratings</th></tr></thead><tbody>{history.points.map((p,i)=><tr key={p.id??'pending'+i}><td>{p.measured_at}</td><td>{p.payload.status}</td><td>{p.payload.list_status}</td><td>{change(p.payload.position)}</td><td>{p.payload.preview?.ratings?.count??'Onbekend'}</td></tr>)}</tbody></table>
  <details><summary>Volledige bronmetingen en provenance</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(history.points,null,2)}</pre></details><ProvenanceLegend/>
 </section>;
}

export function DiscoveryMonitoring({api=API,candidateId}:{api?:string;candidateId?:number}){
 const [items,setItems]=useState<Context[]>([]),[selected,setSelected]=useState(''),[name,setName]=useState(''),[term,setTerm]=useState(''),[category,setCategory]=useState('');
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[history,setHistory]=useState<History|null>(null);
 const lock=useRef(false),request=useRef<{context:string;id:string}|null>(null),generation=useRef(0);
 useEffect(()=>{generation.current++;setHistory(null);},[candidateId,api]);
 useEffect(()=>()=>{generation.current++;},[]);
 async function call(path:string,body?:unknown){
  let r:Response;try{r=await fetch(api+'/discovery/monitoring'+path,{cache:'no-store',...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});}catch{throw new Error('Verbinding onderbroken. Dezelfde meetaanvraag kan veilig opnieuw worden verstuurd.');}
  let value;try{value=await r.json();}catch{throw new Error('Monitoring gaf een onverwacht antwoord. Laad de meetstatus opnieuw.');}if(!r.ok)throw new Error(typeof value.detail==='string'?value.detail:'Monitoring niet beschikbaar.');return value;
 }
 async function load(){const result=await call('/contexts');setItems(result.items);return result.items as Context[];}
 async function action(fn:()=>Promise<void>){if(lock.current)return;lock.current=true;setBusy(true);setError('');try{await fn();}catch(e){setError(e instanceof Error?e.message:'Monitoring niet beschikbaar.');}finally{lock.current=false;setBusy(false);}}
 useEffect(()=>{void action(async()=>{await load();});},[api]);
 const ctx=items.find(x=>String(x.id)===selected);
 async function readHistory(id:number){const current=generation.current;const result=await call(`/contexts/${selected}/candidates/${id}/history`);if(current===generation.current)setHistory(result);}
 return <section className="panel"><h2>Discovery-watchlist en historie</h2><p>Handmatige metingen, maximaal vijf kandidaten per vaste NL/RELEVANCE/pagina-1-context. Geen scheduler.</p>
  <fieldset disabled={busy}><legend>Vaste zoekcontext bewaren</legend>
   <label>Naam <input value={name} onChange={e=>setName(e.target.value)} maxLength={100}/></label><label>Zoekterm <input value={term} onChange={e=>setTerm(e.target.value)} maxLength={50}/></label><label>Of categorie-ID <input value={category} onChange={e=>setCategory(e.target.value)} maxLength={11}/></label>
   <button disabled={!name.trim()||!term.trim()&&!category.trim()} onClick={()=>action(async()=>{const r=await call('/contexts',{name:name.trim(),search_term:term.trim()||null,category_id:category.trim()||null});await load();setSelected(String(r.id));setHistory(null);setNotice('Zoekcontext opgeslagen; nog geen bol-aanvraag.');})}>Context bewaren</button>
  </fieldset>
  <label>Monitoringcontext <select disabled={busy} value={selected} onChange={e=>{setSelected(e.target.value);setHistory(null);generation.current++;}}><option value="">Kies context</option>{items.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
  {ctx&&<><p>Exacte context: {JSON.stringify(ctx.parameters)}</p><p>Laatste run: {ctx.last_run?`${ctx.last_run.started_at} · ${ctx.last_run.status}`:'Nog geen meting'}</p>
   {candidateId&&<button disabled={busy} onClick={()=>action(async()=>{await call(`/contexts/${ctx.id}/watchlist`,{candidate_id:candidateId,followed:true});await load();setNotice('Kandidaat gevolgd; geen live call.');})}>Geselecteerde kandidaat volgen</button>}
   <ul>{ctx.watched.map(x=><li key={x.id}>EAN {x.ean} <button disabled={busy} onClick={()=>action(()=>readHistory(x.id))}>Historie bekijken</button> <button disabled={busy} onClick={()=>action(async()=>{await call(`/contexts/${ctx.id}/watchlist`,{candidate_id:x.id,followed:false});await load();setHistory(null);})}>Niet meer volgen</button></li>)}</ul>
   <button disabled={busy||!ctx.watched.length} onClick={()=>action(async()=>{if(!request.current||request.current.context!==selected)request.current={context:selected,id:crypto.randomUUID()};setHistory(null);const r=await call(`/contexts/${ctx.id}/runs`,{request_id:request.current.id});request.current=null;await load();setNotice(`Meetrun ${r.status}; ${r.watched_count??0} kandidaten. Historie blijft behouden.`);})}>Opnieuw meten</button>
   <button disabled={busy} onClick={()=>action(async()=>{await load();})}>Meetstatus opnieuw laden</button>
   {(ctx.last_run?.lease_expired||ctx.last_run?.status==='interrupted')&&<><p>De meetlease van 75 minuten is verlopen. Eerdere historie blijft behouden; deze onderbreking levert geen gemeten verandering.</p><button disabled={busy} onClick={()=>{request.current=null;setNotice('Nieuwe aanvraag voorbereid. Klik expliciet op Opnieuw meten.');}}>Nieuwe aanvraag voorbereiden</button></>}
  </>}
  {busy&&<p role="status">Monitoringaanvraag bezig…</p>}{error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
  {!candidateId&&<p>Open een kandidaatdetail om deze aan de gekozen context toe te voegen.</p>}
  {history&&<DiscoveryHistory history={history}/>}
 </section>;
}

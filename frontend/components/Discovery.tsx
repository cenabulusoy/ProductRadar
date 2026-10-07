"use client";
import { useEffect, useRef, useState } from "react";
import { ProvenanceLegend } from "./DecisionComparison";
import { FreshnessView } from "./MarketFreshness";

type Signal = { value: unknown; provenance: {kind: string; source: string; recorded_at: string} | null };
type Candidate = {id:number;ean:string|null;title:string|null;brand:string|null;category:string|null;
  sources:string[];status:string;reasons:string[];missing:string[];evidence_quality:number;
  quality_notice:string;financial_notice:string;last_measured_at:string|null;catalog_classification_id?:string|null;
  signals:Record<string,Signal>;market:Parameters<typeof FreshnessView>[0]['market'];
  market_history:Parameters<typeof FreshnessView>[0]['market'][];};
const API=process.env.NEXT_PUBLIC_API_URL??"http://localhost:8000/api";
export const unknown=(value:unknown)=>value==null?"Onbekend":String(value);
const labels:Record<string,string>={product_identity:'Productidentiteit',title:'Titel',brand:'Merk',search_category:'Zoekcategorie',catalog:'Catalogus',rating_distribution:'Ratingverdeling',rating_average:'Gemiddelde rating',rating_count:'Aantal ratings',visibility:'Zoekzichtbaarheid',ranking_impressions:'Ranking en impressies',white_spots:'White Spots (beta)',sales_volume:'Verkoopvolume',rating_growth:'Ratinggroei',offers:'Officiële aanbiedingen'};

export function CandidateView({item}:{item:Candidate}) {
  return <section className="panel"><h2>{unknown(item.title)}</h2><p>EAN: {unknown(item.ean)} · Merk: {unknown(item.brand)} · Categorie: {unknown(item.category)}</p>
    <p>Catalogus-GPC: {unknown(item.catalog_classification_id)} — andere classificatie dan de zoekcategorie.</p>
    <strong>{item.financial_notice}</strong><p>{item.status} — {item.reasons.join(" ")}</p>
    <p>Bewijsdekking {item.evidence_quality}/100 · derived · {item.quality_notice}</p>
    <p>Bronnen: {item.sources.join(", ")} · Laatst gemeten: {unknown(item.last_measured_at)}</p>
    <FreshnessView market={item.market}/>
    {item.market.usable_for_current_analysis&&<><p>Actuele bol-prijsrange: {unknown(item.market.price_min)}–{unknown(item.market.price_max)} · relevante aanbieding: {unknown(item.market.relevant_price)} · official_measured</p>
      <p>Unieke verkopers: {unknown(item.market.unique_seller_count)} · Aanbiedingen: {unknown(item.market.offer_count)} · derived</p>
      <p>Fulfilment: {unknown(item.market.relevant_offer?.fulfilmentMethod)} · Levering: {unknown(item.market.relevant_offer?.minDeliveryDate)}–{unknown(item.market.relevant_offer?.maxDeliveryDate)}</p></>}
    <h3>Vraag-, concurrentie- en marktprijs-signalen</h3><p>Vraag: zichtbaarheid en ratings zijn aanwijzingen. Concurrentie: unieke verkopers en aanbiedingen zijn aparte tellingen. Marktprijs: officiële aanbiedingen. Bewijskwaliteit: afgeleide dekking en freshness.</p>
    <dl>{Object.entries(item.signals).map(([key,s])=><div key={key}><dt>{labels[key]??key}</dt><dd>{s.value==null?"Onbekend":JSON.stringify(s.value)} · {s.provenance?`${s.provenance.kind} · ${s.provenance.source} · ${s.provenance.recorded_at}`:"Geen bewijsbron"}</dd></div>)}</dl>
    <p>Lijstpositie is zoekzichtbaarheid binnen één context; geen verkoopvolume. Ratings zijn geen verkopen. Geschatte vraag wordt in deze sprint niet berekend.</p>
    <p>Ontbrekend: {item.missing.join(", ")}</p>
    {!!item.market_history?.length&&<details><summary>Markthistorie — context, geen actuele prijs</summary>{item.market_history.map((m,i)=><p key={i}>{unknown(m.measured_at)} · {m.freshness} · contextprijs {unknown(m.relevant_price)}</p>)}</details>}
    <ProvenanceLegend/>
  </section>;
}

export function Discovery({api=API}:{api?:string}) {
  const [items,setItems]=useState<Candidate[]>([]),[total,setTotal]=useState(0),[offset,setOffset]=useState(0);
  const [selected,setSelected]=useState<Candidate|null>(null),[query,setQuery]=useState(""),[queryCategory,setQueryCategory]=useState("");
  const [filters,setFilters]=useState<Record<string,string>>({}),[busy,setBusy]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState("");
  const [promotion,setPromotion]=useState(""),[capability,setCapability]=useState("Toegang niet geverifieerd");
  const lock=useRef(false),generation=useRef(0);
  useEffect(()=>()=>{generation.current++;},[]);
  async function request(path:string,body?:unknown) {
    let r:Response;
    try{r=await fetch(api+path,{cache:"no-store",...(body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{})});}
    catch{throw new Error("Verbinding met Discovery onderbroken. Laad opgeslagen kandidaten opnieuw.");}
    if(!r.ok) {let message="Discovery niet beschikbaar. Probeer opnieuw."; try {const b=await r.json();if(typeof b.detail==="string")message=b.detail;}catch{} throw new Error(message);}
    return r.json();
  }
  async function load(page=0) {
    const params=new URLSearchParams({...Object.fromEntries(Object.entries(filters).filter(([,v])=>v!=="")),offset:String(page),limit:"25"});
    const result=await request("/discovery/candidates?"+params);setItems(result.items);setTotal(result.total);setOffset(page);
  }
  async function action(fn:()=>Promise<void>) {
    if(lock.current)return;lock.current=true;setBusy(true);setError("");const current=generation.current;
    try{await fn();}catch(e){if(current===generation.current)setError(e instanceof Error?e.message:"Discovery niet beschikbaar.");}
    finally{lock.current=false;if(current===generation.current)setBusy(false);}
  }
  useEffect(()=>{void action(async()=>{await load();const c=await request("/discovery/capabilities");setCapability(c.white_spots.status+" — "+c.white_spots.reason);});},[api]);
  const filter=(name:string,value:string)=>setFilters(old=>({...old,[name]:value}));
  return <section className="panel"><h1>Product Discovery</h1>
    <p>Kandidaten om verder te onderzoeken. V1 blijft standaard; geen Opportunity Score of inkoopadvies.</p>
    <p>White Spots (beta): {capability}</p>
    <fieldset disabled={busy}><legend>Nieuwe kandidaten zoeken · maximaal één bol-lijstpagina</legend>
      <label>Zoekterm <input value={query} onChange={e=>setQuery(e.target.value)} maxLength={50}/></label>
      <label>Of categorie-ID <input value={queryCategory} onChange={e=>setQueryCategory(e.target.value)} maxLength={11}/></label>
      <button type="button" disabled={!query.trim()&&!queryCategory.trim()} onClick={()=>action(async()=>{const result=await request("/discovery/collect",{search_term:query.trim()||null,category_id:queryCategory.trim()||null});setNotice(`${result.saved_candidates} kandidaten opgeslagen · ${result.status}. ${result.notice}`);setSelected(null);await load();})}>Kandidaten ophalen en opslaan</button>
    </fieldset>
    <fieldset disabled={busy}><legend>Filter opgeslagen kandidaten</legend>
      {[['category','Categorie-ID'],['max_sellers','Maximaal unieke verkopers'],['min_price','Minimum actuele prijs'],['max_price','Maximum actuele prijs'],['min_quality','Minimum bewijsdekking']].map(([name,label])=><label key={name}>{label} <input type={name==='category'?'text':'number'} min="0" value={filters[name]??""} onChange={e=>filter(name,e.target.value)}/></label>)}
      <label>Bron <select value={filters.source??""} onChange={e=>filter('source',e.target.value)}><option value="">Alle</option><option value="bol_product_list">bol Product List</option><option value="bol_ean_preview">bol EAN-preview</option></select></label>
      <label>Marktstatus <select value={filters.freshness??""} onChange={e=>filter('freshness',e.target.value)}><option value="">Alle</option>{['current','stale','historical','missing','incomplete','error'].map(x=><option key={x}>{x}</option>)}</select></label>
      <label>Sortering <select value={filters.sort??'discovered'} onChange={e=>filter('sort',e.target.value)}><option value="discovered">Ontdekt op</option><option value="quality">Bewijsdekking</option><option value="sellers">Actuele unieke verkopers (onbekend laatst)</option></select></label>
      <button onClick={()=>action(()=>load())}>Filters toepassen</button>
    </fieldset>
    {busy&&<p role="status">Aanvraag bezig…</p>}{error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
    <p>{total} kandidaten · Prijs- en verkopersfilters sluiten onbekende/verouderde marktdata uit.</p>
    <div className="comparison-table-wrap"><table className="comparison-table"><caption>Onderzoekskandidaten — geen verkoopvolume</caption><thead><tr>{['Product','Categorie','Actuele marktprijs','Verkopers / aanbiedingen','Ratings','Zichtbaarheid','Bewijs / marktstatus','Reden / bron'].map(x=><th key={x}>{x}</th>)}</tr></thead>
      <tbody>{items.map(x=><tr key={x.id}><td><button disabled={busy} onClick={()=>action(async()=>{setPromotion("");setSelected(await request(`/discovery/candidates/${x.id}`));})}>{unknown(x.title)}</button><br/>{unknown(x.ean)}</td><td>{unknown(x.category)}</td>
      <td>{x.market.usable_for_current_analysis?unknown(x.market.relevant_price):"Onbekend — geen actuele prijs"}</td><td>{x.market.usable_for_current_analysis?`${unknown(x.market.unique_seller_count)} / ${unknown(x.market.offer_count)} · derived`:"Onbekend"}</td>
      <td>{unknown(x.signals.rating_average.value)} / {unknown(x.signals.rating_count.value)} · derived</td><td>{x.signals.visibility.value==null?"Onbekend":"Lijstpositie beschikbaar · derived"}</td>
      <td>{x.evidence_quality}/100 · derived<br/>{x.market.freshness}</td><td>{x.reasons.join(" ")}<br/>{x.sources.join(", ")}</td></tr>)}</tbody></table></div>
    {!items.length&&!busy&&<p>Geen kandidaten. Zoek expliciet op een productterm of categorie; er loopt geen automatische crawl.</p>}
    <button disabled={busy||offset===0} onClick={()=>action(()=>load(Math.max(0,offset-25)))}>Vorige</button><button disabled={busy||offset+25>=total} onClick={()=>action(()=>load(offset+25))}>Volgende</button>
    {selected&&<><CandidateView item={selected}/><button disabled={busy||!selected.ean} onClick={()=>action(async()=>{const id=selected.id;setSelected(null);setNotice("Nieuwe meting ophalen; vorige metingen blijven historie.");const next=await request(`/discovery/candidates/${id}/measure`,{});setSelected(next);setNotice(next.market.usable_for_current_analysis?"Nieuwe meting opgeslagen.":"Nieuwe meting niet volledig bruikbaar; geen actuele marktprijs.");await load(offset);})}>Catalogus, ratings en markt meten</button>
      <button disabled={busy} onClick={()=>action(async()=>{const p=await request(`/discovery/candidates/${selected.id}/promotion-preview`);setPromotion(p.notice+` Bestaande producten: ${p.existing_product_ids.join(', ')||'geen'}.`);})}>Promotie bekijken — niets toevoegen</button>{promotion&&<p>{promotion}</p>}</>}
    <ProvenanceLegend/>
  </section>;
}

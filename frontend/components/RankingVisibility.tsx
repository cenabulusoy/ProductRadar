"use client";
import {useEffect,useRef,useState} from "react";
type Measurement={id:number;ean:string;report_date:string;retrieved_at:string;country:null;language:string;requested_type:string|null;status:string;has_next_page:boolean;
 records:{official:{rank:number;impressions:number;wasSponsored:boolean;searchTerm:string|null;categoryId:string|null};derived:{context_type:string|null}}[];
 provenance:{kind:string;source:string;api_version:string;endpoint:string}};
export function VisibilityMeasurement({value}:{value:Measurement}){
 return <section className="panel"><h3>Rankings en impressies · zichtbaarheid</h3>
  <p>EAN {value.ean} · Verslagdatum {value.report_date} · Opgehaald {value.retrieved_at}</p>
  <p>Land: onbekend — endpoint bevat geen landveld. Taal: {value.language}.</p>
  <p>{value.provenance.kind} · {value.provenance.source} · {value.provenance.api_version} · {value.provenance.endpoint}</p>
  <p>Status: {value.status} · Pagina 1{value.has_next_page?' — vervolgpagina beschikbaar; niet opgehaald.':' — geen vervolgpagina.'}</p>
  {!value.records.length?<p>Geen rankingrecords voor deze verslagdatum/context. Dit bewijst geen nul zichtbaarheid of ontbrekende accounttoegang.</p>:
   <table className="comparison-table"><thead><tr><th>Context (derived)</th><th>Zoekterm / categorie</th><th>Rank</th><th>Impressies</th><th>Sponsored</th></tr></thead><tbody>
    {value.records.map((r,i)=><tr key={i}><td>{r.derived.context_type??'Onbekend'}</td><td>{r.official.searchTerm??'Onbekend'} / {r.official.categoryId??'Onbekend'}</td><td>{r.official.rank}</td><td>{r.official.impressions}</td><td>{r.official.wasSponsored?'Gesponsord':'Niet gesponsord'}</td></tr>)}
   </tbody></table>}
  <p>Zichtbaarheid op de verslagdatum; geen vraag, verkoopvolume, Demand Score of huidige Product List-positie.</p>
 </section>;
}
export function RankingVisibility({api,ean}:{api:string;ean:string}){
 const [items,setItems]=useState<Measurement[]>([]),[day,setDay]=useState(''),[latest,setLatest]=useState(''),[type,setType]=useState('');
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 const lock=useRef(false),generation=useRef(0),request=useRef<{key:string;id:string}|null>(null);
 useEffect(()=>{let active=true;generation.current++;request.current=null;setItems([]);setDay('');setError('');setBusy(false);lock.current=false;
  fetch(`${api}/discovery/rankings/${ean}`,{cache:'no-store'}).then(async r=>{if(!r.ok)throw new Error();return r.json();}).then(v=>{if(active){setItems(v.items);setLatest(v.latest_allowed_date);setDay(v.latest_allowed_date);}}).catch(()=>{if(active)setError('Opgeslagen zichtbaarheid niet beschikbaar.');});
  return()=>{active=false;generation.current++;};},[api,ean]);
 async function measure(){
  if(lock.current)return;lock.current=true;setBusy(true);setError('');const g=generation.current;
  const key=JSON.stringify([api,ean,day,type]);if(request.current?.key!==key)request.current={key,id:crypto.randomUUID()};
  try{
   const r=await fetch(`${api}/discovery/rankings`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ean,report_date:day,context_type:type||null,request_id:request.current.id})});
   if(!r.ok){let text='Rankings niet beschikbaar.';try{const b=await r.json();if(typeof b.detail==='string')text=b.detail;}catch{}throw new Error(text);}
   const value=await r.json();if(g===generation.current){setItems(old=>[value,...old.filter(x=>x.id!==value.id)]);request.current=null;}
  }catch(e){if(g===generation.current)setError(e instanceof Error?e.message:'Verbinding onderbroken; dezelfde aanvraag kan opnieuw worden verstuurd.');}
  finally{if(g===generation.current){lock.current=false;setBusy(false);}}
 }
 return <section className="panel"><h2>Zichtbaarheid · afzonderlijke bol-bron</h2><p>Openen leest alleen opgeslagen metingen. Ophalen gebeurt uitsluitend na een klik, maximaal één pagina.</p>
  <label>Verslagdatum <input type="date" max={latest} value={day} disabled={busy} onChange={e=>setDay(e.target.value)}/></label>
  <label>Context <select value={type} disabled={busy} onChange={e=>setType(e.target.value)}><option value="">SEARCH en BROWSE</option><option>SEARCH</option><option>BROWSE</option></select></label>
  <button disabled={busy||!day} onClick={measure}>Zichtbaarheid ophalen · één pagina</button>
  {busy&&<p role="status">Zichtbaarheid ophalen…</p>}{error&&<p role="alert">{error}</p>}
  {!items.length&&!busy&&<p>Geen opgeslagen rankingmeting; waarden blijven onbekend.</p>}
  {items.map(value=><VisibilityMeasurement key={value.id} value={value}/>)}
 </section>;
}

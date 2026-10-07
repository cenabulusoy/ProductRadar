"use client";
import {useEffect,useRef,useState} from "react";
import {FreshnessView} from "./MarketFreshness";
import type {Freshness} from "./MarketFreshness";
const API=process.env.NEXT_PUBLIC_API_URL??"http://localhost:8000/api";
type Status={product_id:number;can_refresh:boolean;identity_notice:string|null;market:Freshness;history:Freshness[]};
function value(n:number|string|null|undefined){return n==null?"Onbekend":Number(n).toLocaleString("nl-NL",{maximumFractionDigits:2});}
export function MarketRefresh({productId,api=API,onReload,onRefreshing}:{productId:number;api?:string;onReload?:()=>void;onRefreshing?:(busy:boolean)=>void}){
  const [data,setData]=useState<Status|null>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState("");
  const request=useRef(0),active=useRef(false),pendingKey=useRef<string|null>(null);
  async function read(){const r=await fetch(`${api}/products/${productId}/market-status`,{cache:"no-store"});if(!r.ok)throw new Error();const body=await r.json();if(body.product_id!==productId||!body.market||!Array.isArray(body.history))throw new Error();return body as Status;}
  useEffect(()=>{const id=++request.current;active.current=false;pendingKey.current=null;onRefreshing?.(false);setData(null);setBusy(false);setMessage("");read().then(d=>{if(id===request.current)setData(d);}).catch(()=>{if(id===request.current)setMessage("Marktstatus niet beschikbaar. Probeer opnieuw te laden.");});return()=>{request.current++;};},[productId,api]);
  async function load(){const id=++request.current;setMessage("");try{const d=await read();if(id===request.current){setData(d);onReload?.();}}catch{if(id===request.current)setMessage("Marktstatus niet beschikbaar. Probeer opnieuw.");}}
  async function refresh(){
    if(active.current||!data?.can_refresh)return;
    active.current=true;setBusy(true);setMessage("Nieuwe bol-marktmeting ophalen…");const id=++request.current;
    // Immediately hide previous current data while an explicit new attempt runs.
    setData(d=>d?{...d,market:{...d.market,freshness:"error",reason:"refresh_in_progress",usable_for_current_analysis:false,price_min:null,price_max:null,relevant_price:null,offer_count:null,unique_seller_count:null}}:null);
    onRefreshing?.(true);
    try{
      const key=pendingKey.current??crypto.randomUUID();pendingKey.current=key;
      const r=await fetch(`${api}/products/${productId}/market-refresh`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({request_id:key})});
      if(id!==request.current)return;
      let text="Refresh niet bevestigd. De vorige meting is niet opnieuw actueel verklaard.";
      if(r.ok){const body=await r.json();pendingKey.current=null;text=body.refresh?.outcome==="saved"?"Nieuwe marktmeting opgeslagen.":body.refresh?.message??"Laatste meting onvolledig of mislukt.";}
      else if(r.status===409){pendingKey.current=null;text="Voor deze EAN loopt al een refresh. Laad de status later opnieuw.";}
      else if(r.status===400)text="Een geldige EAN is eerst nodig.";
      else if(r.status===503)text="Refreshopslag of bol-configuratie niet beschikbaar. Controleer de lokale instellingen.";
      if(id!==request.current)return;
      const saved=await read();if(id===request.current){setData(saved);setMessage(text);onReload?.();}
    }catch{if(id===request.current)setMessage("Verbinding met refresh onderbroken. Laad de status opnieuw; oude data is niet opnieuw actueel verklaard.");}
    finally{if(id===request.current){active.current=false;setBusy(false);onRefreshing?.(false);}}
  }
  const market=data?.market,context=market&&["current","stale","historical"].includes(market.freshness);
  return <section className="panel market-refresh"><h2>Bol-marktstatus en verversen</h2><p>V1 blijft standaard. Verversen haalt officiële bol-data op en bewaart een nieuwe snapshot; handmatige prijzen en financiële profielen veranderen niet.</p>
    {market&&<FreshnessView market={market}/>}{message&&<p role="status">{message}</p>}
    <button type="button" disabled={busy} onClick={load}>Marktstatus opnieuw laden</button>{data?.can_refresh?<button type="button" disabled={busy} onClick={refresh}>{busy?"Markt verversen…":"Markt verversen"}</button>:data&&<p>{data.identity_notice}</p>}
    {context&&<><p>{market.freshness==="current"?"Actuele prijsrange":"Historische prijsrange — geen actuele prijs"}: {value(market.price_min)} – {value(market.price_max)} EUR. Relevante aanbieding: {value(market.relevant_price)} EUR.</p>
      <p>Unieke verkopers: {value(market.unique_seller_count)} · Aanbiedingen: {value(market.offer_count)}. Tellingen en prijsselectie: door ProductRadar afgeleid; aanbiedingsprijzen: officiële bol-data, geen verkoopvolume.</p>
      {market.relevant_offer&&<p>Fulfilment: {market.relevant_offer.fulfilmentMethod??"Onbekend"} · Levering: {market.relevant_offer.minDeliveryDate??"Onbekend"} – {market.relevant_offer.maxDeliveryDate??"Onbekend"}.</p>}</>}
    {data&&<details><summary>Opgeslagen markthistorie ({data.history.length})</summary><p>Historische context, geen fallback voor een actuele beoordeling.</p>{data.history.map(m=><div key={m.snapshot_id}><FreshnessView market={m} contextOnly/>{["current","stale","historical"].includes(m.freshness)&&<p>Historische contextprijs: {value(m.price_min)} – {value(m.price_max)} EUR.</p>}</div>)}</details>}
  </section>;
}

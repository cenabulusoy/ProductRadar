"use client";

export type Freshness = {
  freshness:string; reason:string; age_hours:number|null; measured_at:string|null;
  snapshot_id:number|null; source:string|null; api_version:string|null;
  usable_for_current_analysis:boolean; freshness_kind:string; price_min:number|null; price_max:number|null;
  offer_count:number|null; unique_seller_count:number|null; relevant_price?:string|null;
  as_of?:string; relevant_offer?:{fulfilmentMethod?:string|null;minDeliveryDate?:string|null;maxDeliveryDate?:string|null}|null;
};
export function FreshnessView({market,contextOnly=false}:{market:Freshness;contextOnly?:boolean}) {
  const titles:Record<string,string>={current:"Actueel",stale:"Verversen aanbevolen",historical:"Historische marktmeting",missing:"Geen marktmeting",incomplete:"Laatste meting onvolledig",error:"Laatste meting mislukt of ongeldig"};
  const age=market.age_hours==null?"Ouderdom onbekend":market.age_hours<=72?`${market.age_hours.toLocaleString('nl-NL',{maximumFractionDigits:1})} uur oud`:`${(market.age_hours/24).toLocaleString('nl-NL',{maximumFractionDigits:1})} dagen oud`;
  return <section aria-label="Marktstatus"><p><strong>{contextOnly?"Historische context — geen geselecteerde actuele prijs":titles[market.freshness]??"Marktstatus onbekend"}</strong> — {age}</p>
    {market.freshness!=="current"&&<p role="status">Geen bruikbare huidige marktprijs. Marktdata moet worden vernieuwd voordat v2 een actuele definitieve beoordeling kan geven. Oudere complete metingen worden niet als fallback gebruikt.</p>}
    {market.reason==="refresh_in_progress"&&<p>Een refresh is bezig; de vorige meting is voorlopig alleen historie.</p>}
    {market.reason==="refresh_interrupted"&&<p>De laatste refresh is onderbroken. Start expliciet een nieuwe aanvraag.</p>}
    <p>Ouderdom en freshness: door ProductRadar afgeleid, bepaald door de backend op {market.as_of??"het uitleesmoment"}. Meet-/pogingmoment: {market.measured_at??"Onbekend"}. Bron: {market.source??"Onbekend"} {market.api_version??""} · Snapshot {market.snapshot_id??"onbekend"}.</p>
  </section>;
}

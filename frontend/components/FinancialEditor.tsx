"use client";
import { useEffect, useRef, useState } from "react";
import { blankDraft, buildProfile, fields, loadDraft } from "../lib/financial-form";
import type { Draft, Entry } from "../lib/financial-form";

const API=process.env.NEXT_PUBLIC_API_URL??"http://localhost:8000/api";
const priceReasons:Record<string,string>={planned_price_not_above_market:"De geplande verkoopprijs ligt niet boven de relevante bol-prijs.",lowest_bol_best_offer:"De laagste officiële beste aanbieding is lager dan de geplande prijs.",lowest_offer_fallback:"Zonder officiële beste aanbieding wordt de laagste relevante aanbieding gebruikt.",market_older_than_24_hours:"De marktmeting is ouder dan 24 uur; er is geen actuele conservatieve prijs.",missing_market_snapshot:"Er is geen opgeslagen marktmeting.",invalid_market_snapshot:"De marktmeting is niet betrouwbaar te gebruiken.",market_incomplete_or_wrong_segment:"De marktmeting is onvolledig of past niet bij NL / NEW.",market_has_no_offers:"Er zijn geen bruikbare aanbiedingen in de marktmeting.",planned_price_or_vat_basis_missing:"De geplande prijs of btw-basis ontbreekt."};
function metric(v:any, unit="EUR") { return v==null ? "Onbekend" : `${Number(v).toLocaleString("nl-NL",{maximumFractionDigits:2})} ${unit}`; }
export function FinancialPreview({financial}:{financial:any}) {
  const base=financial.base,stress=financial.stress;
  return <section aria-label="Financial Engine v2 preview"><h3>Live preview · bijdrage na opgenomen kosten</h3>
    <p>Conservatieve prijs: {metric(financial.price_selection.selected_gross_price)} · {priceReasons[financial.price_selection.reason]??"Prijsselectie onbekend."}</p>
    {financial.price_selection.selected_from&&<p>Gekozen bron: {financial.price_selection.selected_from==="planned_sale_price"?"Expliciet ingevoerde geplande verkoopprijs":"Officiële bol-meting"}. Prijsselectie: door ProductRadar afgeleid.</p>}
    {financial.price_selection.market_reference.provenance&&<p>Marktbron: {financial.price_selection.market_reference.provenance.source} · Meetmoment: {financial.price_selection.market_reference.provenance.recorded_at} · Snapshot {financial.price_selection.market_reference.snapshot_id}. Oudere metingen zijn historische gegevens, geen actuele marktprijs.</p>}
    {financial.price_selection.market_reference.status!=="usable" && <p role="status">Geen volledige marktprijs van maximaal 24 uur oud. Het conservatieve scenario blijft onbekend; verversing gebeurt hier niet automatisch.</p>}
    <dl className="financial-preview-grid">{[["Omzet excl. btw",base.revenue_excluding_vat,"EUR"],["Bijdrage per stuk",base.contribution_per_unit,"EUR"],["Contributiemarge",base.contribution_margin_percent,"%"],["Voorraad-ROI",base.inventory_roi_percent,"%"],["Stressprijs (-10%)",stress.sale_price_including_vat,"EUR"],["Stressbijdrage (+10% operationele kosten)",stress.contribution_per_unit,"EUR"]].map(([label,value,unit])=><div key={label}><dt>{label}</dt><dd>{metric(value,unit)}</dd></div>)}</dl>
    <p>Bijdrage is geen nettowinst als niet alle overhead is opgenomen. Ontbrekende kosten worden niet nul.</p>
    {!!base.missing_inputs.length && <p>Nog onbekend: {base.missing_inputs.join(", ")}</p>}
  </section>;
}
export function FinancialEditor({productId,api=API}:{productId:number;api?:string}) {
  const [open,setOpen]=useState(false),[draft,setDraft]=useState<Draft>(blankDraft),[version,setVersion]=useState(0);
  const [suggestions,setSuggestions]=useState<any[]>([]),[history,setHistory]=useState<any[]>([]),[preview,setPreview]=useState<any>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(""),[message,setMessage]=useState(""),[confirmed,setConfirmed]=useState(false);
  const epoch=useRef(0),inFlight=useRef(false);
  useEffect(()=>{epoch.current++;setOpen(false);setDraft(blankDraft());setVersion(0);setPreview(null);setHistory([]);setSuggestions([]);setConfirmed(false);setError("");setMessage("");setBusy(false);inFlight.current=false;return()=>{epoch.current++;};},[productId,api]);
  function change(key:string,patch:Partial<Entry>) { epoch.current++;setDraft(d=>({...d,entries:{...d.entries,[key]:{...d.entries[key],...patch}}}));setPreview(null);setConfirmed(false);setMessage(""); }
  async function request(url:string,options?:RequestInit) { let r:Response; try { r=await fetch(url,{cache:"no-store",...options}); } catch { throw new Error("Verbinding mislukt. Probeer opnieuw."); } if(!r.ok) { if(r.status===409) throw new Error("Invoer is gewijzigd of een preview is achterhaald. Laad de nieuwste versie en bekijk je wijzigingen opnieuw."); throw new Error("Controleer invoer, brongegevens, datums en kostentotalen. Probeer opnieuw."); } return r.json(); }
  async function load(versionToView?:number) {
    if(inFlight.current)return;inFlight.current=true;setBusy(true);setError("");const id=++epoch.current;
    try {const body=await request(`${api}/products/${productId}/financial-inputs${versionToView ? `?version=${versionToView}`:""}`);
      if(id!==epoch.current)return;
      if(versionToView) {setMessage(`Historische versie ${versionToView}: ${body.saved.saved_at}. Deze historische versie is alleen ter inzage.`);setHistory(body.history);return;}
      setDraft(body.saved ? loadDraft(body.saved.profile):blankDraft());setVersion(body.saved?.version??0);setSuggestions(body.suggestions);setHistory(body.history);setPreview(null);setConfirmed(false);setOpen(true);
    }catch(e){if(id===epoch.current)setError(e instanceof Error?e.message:"Laden mislukt.");}finally{inFlight.current=false;if(id===epoch.current)setBusy(false);}
  }
  async function calculate() {
    if(inFlight.current)return;inFlight.current=true;setBusy(true);setError("");setPreview(null);setConfirmed(false);const id=++epoch.current;
    try {const profile=buildProfile(draft);const result=await request(`${api}/products/${productId}/financial-inputs/preview`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({profile,expected_version:version})});if(id===epoch.current)setPreview({...result,profile});}
    catch(e){if(id===epoch.current)setError(e instanceof Error?e.message:"Preview mislukt.");}finally{inFlight.current=false;if(id===epoch.current)setBusy(false);}
  }
  async function save() {
    if(!preview || !confirmed || inFlight.current)return;inFlight.current=true;setBusy(true);setError("");const id=++epoch.current;
    try {const saved=await request(`${api}/products/${productId}/financial-inputs`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({profile:preview.profile,expected_version:version,preview_id:preview.preview_id,confirmed:true})});
      if(id!==epoch.current)return;setVersion(saved.version);setPreview(null);setConfirmed(false);setHistory(h=>[{version:saved.version,saved_at:saved.saved_at},...h]);setMessage(`Financiële versie ${saved.version} opgeslagen. Laad de v1/v2-vergelijking opnieuw om deze invoer te gebruiken.`);
    }catch(e){if(id===epoch.current)setError(e instanceof Error?e.message:"Opslaan mislukt.");}finally{inFlight.current=false;if(id===epoch.current)setBusy(false);}
  }
  return <section className="panel financial-editor"><h2>Financiële invoer v2</h2><p>V1 blijft de standaard. Deze afzonderlijke invoer verandert geen bestaande productvelden of CSV-data.</p>
    <button type="button" disabled={busy} onClick={()=>load()}>Financiële invoer laden</button>{error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
    {open&&<><p>Huidige versie: {version||"Nog niet opgeslagen"}. Leeg betekent onbekend; vul nul alleen in als dat expliciet klopt.</p>
      {!!suggestions.length&&<details><summary>Voorstellen uit bestaande invoer — nog niet bevestigd</summary><p>Geen btw of commissie wordt geraden. Gebruik van een bedrag is slechts een voorstel; bevestig daarna basis, herkomst en datum.</p>{suggestions.map(s=><p key={s.field}>{fields.find(f=>f.key===s.field)?.label}: {metric(s.value)} <button type="button" disabled={busy} onClick={()=>change(s.field,{amount:s.value==null?"":String(s.value)})}>Gebruik bedrag als voorstel</button></p>)}</details>}
      {["Inkoop","Belasting","Verkoop","bol-kosten","Logistiek","Overige kosten"].map(group=><fieldset key={group} disabled={busy}><legend>{group}</legend>
        {group==="Inkoop"&&<p>Landed totaal bevat inkoop én inbound. Onderdelen zijn een uitsplitsing, geen extra aftrekposten. Bij een gewijzigde uitsplitsing moet je het totaal opnieuw bevestigen; maak het oude totaal eerst leeg om een nieuw voorstel te berekenen.</p>}
        {group==="Logistiek"&&<p>Logistiek totaal bevat verzending, verpakking en handling; geen dubbele aftrek.</p>}
        {fields.filter(f=>f.group===group).map(f=>{const e=draft.entries[f.key];return <details key={f.key} className="financial-input-row"><summary>{f.label}: {e.amount===""?"Onbekend":e.amount}</summary>
          <label>{f.label}<input aria-label={f.label} type="number" min={f.type==="price"?"0.0001":"0"} max={f.type==="rate"||f.type==="commission"?100:1000000000} step="0.0001" value={e.amount} onChange={ev=>change(f.key,{amount:ev.target.value})}/></label>
          {f.type!=="rate"&&<label>Btw-basis<select aria-label={`Btw-basis ${f.label}`} value={e.basis} onChange={ev=>change(f.key,{basis:ev.target.value,vat:"",recoverable:""})}><option value="">Onbekend</option><option value="inclusive">Inclusief btw</option><option value="exclusive">Exclusief btw</option>{f.type!=="price"&&<option value="effective">Economische kosten, belasting al verwerkt</option>}</select></label>}
          {f.type!=="rate"&&f.type!=="price"&&e.basis!=="effective"&&<><label>Btw op kosten (%)<input aria-label={`Btw op kosten ${f.label}`} type="number" min="0" max="100" step="0.0001" value={e.vat} onChange={ev=>change(f.key,{vat:ev.target.value})}/></label><label>Voorbelasting aftrekbaar<select aria-label={`Aftrekbaar ${f.label}`} value={e.recoverable} onChange={ev=>change(f.key,{recoverable:ev.target.value})}><option value="">Onbekend</option><option value="true">Ja</option><option value="false">Nee</option></select></label></>}
          <label>Herkomst<select aria-label={`Herkomst ${f.label}`} value={e.kind} onChange={ev=>change(f.key,{kind:ev.target.value})}><option value="manual_or_imported">Handmatig / geïmporteerd</option><option value="estimated">Schatting</option><option value="derived">Afgeleid / berekend</option><option value="official_measured">Officiële meting (geverifieerde bol-prijs vereist)</option></select></label>
          <label>Bron / beschrijving<input aria-label={`Bron ${f.label}`} maxLength={200} value={e.source} onChange={ev=>change(f.key,{source:ev.target.value})}/></label>
          <label>Invoer- / meetdatum<input aria-label={`Datum ${f.label}`} type="datetime-local" step="1" value={e.recorded} onChange={ev=>change(f.key,{recorded:ev.target.value})}/></label>
          <label>Importreferentie (optioneel)<input aria-label={`Importreferentie ${f.label}`} value={e.importRef} onChange={ev=>change(f.key,{importRef:ev.target.value})}/></label>
          <label>Snapshotreferentie (optioneel)<input aria-label={`Snapshotreferentie ${f.label}`} type="number" min="1" step="1" value={e.snapshotRef} onChange={ev=>change(f.key,{snapshotRef:ev.target.value})}/></label>
        </details>;})}
        {group==="bol-kosten"&&<><label>Tarief voor basis én stressprijs<select aria-label="Commissietarief bevestigd" value={draft.flat} onChange={ev=>{epoch.current++;setDraft(d=>({...d,flat:ev.target.value}));setPreview(null);setConfirmed(false);}}><option value="">Nog niet bevestigd</option><option value="true">Vast percentage en vast bedrag gelden in dit scenario</option><option value="false">Alleen binnen onderstaande bruto prijsrange</option></select></label><label>Geldig vanaf bruto prijs<input aria-label="Commissie vanaf" type="number" min="0" step="0.0001" value={draft.from} onChange={ev=>{setDraft(d=>({...d,from:ev.target.value}));setPreview(null);setConfirmed(false);}}/></label><label>Geldig tot bruto prijs<input aria-label="Commissie tot" type="number" min="0" step="0.0001" value={draft.to} onChange={ev=>{setDraft(d=>({...d,to:ev.target.value}));setPreview(null);setConfirmed(false);}}/></label></>}
      </fieldset>)}
      <button type="button" disabled={busy} onClick={calculate}>Bereken live preview</button>
      {preview&&<><FinancialPreview financial={preview.financial}/>{Object.entries(preview.proposals).map(([key,value]:[string,any])=>value.amount==null?null:<p key={key}>Afgeleid totaalvoorstel {fields.find(f=>f.key===key)?.label}: {metric(value.amount)} <button type="button" disabled={busy} onClick={()=>change(key,{amount:value.amount,basis:"effective",vat:"",recoverable:"",kind:"derived",source:"",recorded:""})}>Neem totaal als voorstel over</button> — vul daarna bron en datum in en bevestig opnieuw.</p>)}
        <label><input type="checkbox" checked={confirmed} disabled={busy} onChange={ev=>setConfirmed(ev.target.checked)}/>Ik bevestig de ingevoerde waarden, btw-behandeling, brongegevens en de getoonde preview.</label>
        <button type="button" disabled={busy||!confirmed} onClick={save}>Bevestig en sla financiële versie op</button>
      </>}
      <details><summary>Versiehistorie ({history.length})</summary>{history.map(h=><p key={h.version}>Versie {h.version} · {h.saved_at}</p>)}<p>Historische versies blijven bewaard en zijn via de read-only versie-API opvraagbaar.</p></details>
    </>}
  </section>;
}

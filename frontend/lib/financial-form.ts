export type Entry = { amount: string; basis: string; vat: string; recoverable: string; kind: string; source: string; recorded: string; importRef: string; snapshotRef: string };
export type Draft = { entries: Record<string, Entry>; flat: string; from: string; to: string };
export const fields = [
  {key:"purchase_cost",label:"Inkoopprijs",group:"Inkoop",type:"cost",breakdown:true},
  {key:"inbound_cost",label:"Inboundkosten per stuk",group:"Inkoop",type:"cost",breakdown:true},
  {key:"landed_purchase_cost",label:"Bevestigde landed inkoopkosten (totaal)",group:"Inkoop",type:"cost"},
  {key:"sales_vat_rate",label:"Btw-tarief verkoop (%)",group:"Belasting",type:"rate"},
  {key:"planned_sale_price",label:"Geplande verkoopprijs",group:"Verkoop",type:"price"},
  {key:"fixed_fee",label:"Vaste bol-commissie per stuk",group:"bol-kosten",type:"cost"},
  {key:"commission",label:"Variabele bol-commissie (%)",group:"bol-kosten",type:"commission"},
  {key:"shipping_cost",label:"Verzending per stuk",group:"Logistiek",type:"cost",breakdown:true},
  {key:"packaging_cost",label:"Verpakking per stuk",group:"Logistiek",type:"cost",breakdown:true},
  {key:"handling_cost",label:"Overige fulfilment/handling per stuk",group:"Logistiek",type:"cost",breakdown:true},
  {key:"fulfilment_cost",label:"Bevestigde logistieke kosten (totaal)",group:"Logistiek",type:"cost"},
  {key:"advertising_cost",label:"Advertentiekosten per stuk",group:"Overige kosten",type:"cost"},
  {key:"returns_loss_reserve",label:"Retour-/verliesreserve per stuk",group:"Overige kosten",type:"cost"},
  {key:"other_allocated_cost",label:"Overige toegerekende kosten per stuk",group:"Overige kosten",type:"cost"},
] as const;
export function blankEntry(): Entry { return {amount:"",basis:"",vat:"",recoverable:"",kind:"manual_or_imported",source:"",recorded:"",importRef:"",snapshotRef:""}; }
export function blankDraft(): Draft { return {entries:Object.fromEntries(fields.map(f=>[f.key,blankEntry()])),flat:"",from:"",to:""}; }
function dateLocal(value:string) { const d=new Date(value); return Number.isNaN(d.getTime()) ? "" : new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,19); }
function pathFor(f: typeof fields[number]) { return "breakdown" in f ? `breakdown.${f.key}` : (f.key==="fixed_fee" ? "financial.commission.fixed_fee" : `financial.${f.key}`); }
export function loadDraft(profile:any): Draft {
  const draft=blankDraft();
  for(const f of fields) {
    const item="breakdown" in f ? profile.breakdown?.[f.key] : f.key==="fixed_fee" ? profile.financial?.commission?.fixed_fee : profile.financial?.[f.key];
    if(!item) continue;
    const ref=profile.references?.[pathFor(f)] ?? {};
    draft.entries[f.key]={amount:String((f.type==="rate" ? item.value : f.type==="commission" ? item.variable_rate_percent : item.amount) ?? ""),
      basis:(f.type==="commission" ? item.variable_fee_vat_basis : item.vat_basis) ?? "", vat:String((f.type==="commission" ? item.variable_fee_vat_rate_percent : item.vat_rate_percent) ?? ""),
      recoverable:(f.type==="commission" ? item.variable_fee_input_vat_recoverable : item.input_vat_recoverable)==null ? "" : String(f.type==="commission" ? item.variable_fee_input_vat_recoverable : item.input_vat_recoverable),
      kind:item.provenance.kind,source:item.provenance.source,recorded:dateLocal(item.provenance.recorded_at),importRef:ref.import_reference ?? "",snapshotRef:String(item.provenance.snapshot_id ?? ref.snapshot_id ?? "")};
  }
  const c=profile.financial?.commission;
  if(c) { draft.flat=c.flat_tariff_confirmed==null ? "" : String(c.flat_tariff_confirmed); draft.from=String(c.valid_from_gross_price ?? ""); draft.to=String(c.valid_to_gross_price ?? ""); }
  return draft;
}
export function buildProfile(draft:Draft) {
  const financial:any={currency:"EUR",scenario_mode:"conservative"},breakdown:any={},references:any={};
  const num=(s:string)=>s==="" ? null : s; // Decimal strings avoid precision loss; blank never becomes zero.
  const boolean=(s:string)=>s==="" ? null : s==="true";
  for(const f of fields) {
    const entry=draft.entries[f.key];
    if(entry.amount==="" && !entry.source && !entry.recorded) continue;
    if(!entry.source.trim() || !entry.recorded) throw new Error(`Vul bron en datum in voor ${f.label}.`);
    const d=new Date(entry.recorded);
    if(Number.isNaN(d.getTime())) throw new Error(`Ongeldige datum voor ${f.label}.`);
    const provenance:any={kind:entry.kind,source:entry.source.trim(),recorded_at:d.toISOString()};
    if(entry.snapshotRef) provenance.snapshot_id=Number(entry.snapshotRef);
    let item:any;
    if(f.type==="rate") item={value:num(entry.amount),provenance};
    else if(f.type==="commission") item={variable_rate_percent:num(entry.amount),variable_fee_vat_basis:entry.basis||null,
      variable_fee_vat_rate_percent:num(entry.vat),variable_fee_input_vat_recoverable:boolean(entry.recoverable),
      flat_tariff_confirmed:boolean(draft.flat),valid_from_gross_price:num(draft.from),valid_to_gross_price:num(draft.to),provenance};
    else item={amount:num(entry.amount),vat_basis:entry.basis||null,provenance,...(f.type==="cost" ? {vat_rate_percent:num(entry.vat),input_vat_recoverable:boolean(entry.recoverable)} : {})};
    if("breakdown" in f) breakdown[f.key]=item;
    else if(f.key==="fixed_fee") { financial.commission={...(financial.commission??{}),fixed_fee:item}; }
    else if(f.key==="commission") financial.commission={...(financial.commission??{}),...item};
    else financial[f.key]=item;
    if(entry.importRef || entry.snapshotRef) references[pathFor(f)]={import_reference:entry.importRef||null,snapshot_id:entry.snapshotRef ? Number(entry.snapshotRef):null};
  }
  if(financial.commission && !financial.commission.provenance) throw new Error("Vul ook bron en datum van het bol-commissietarief in.");
  return {schema_version:"1",financial,breakdown,references};
}

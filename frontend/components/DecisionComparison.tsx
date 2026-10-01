"use client";

import { useEffect, useRef, useState } from "react";
import type { Comparison } from "../lib/comparison-types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";
const labels: Record<string, string> = {
  "financial.sale_price": "Geschikte verkoopprijs en btw-basis",
  "financial.sales_vat_rate": "Btw-tarief",
  "financial.landed_purchase_cost": "Volledige inkoopkosten en btw-behandeling",
  "financial.fulfilment_cost": "Fulfilment, verzending en verpakking",
  "financial.advertising_cost": "Advertentiekosten",
  "financial.returns_loss_reserve": "Retour- en verliesreserve",
  "financial.other_allocated_cost": "Overige toegerekende kosten",
  "financial.commission": "Volledige vaste en variabele commissie",
  "financial.commission_tariff_not_confirmed_for_price": "Commissietarief voor dit prijsscenario",
  product_identity: "Geldige opgeslagen bol-productidentiteit",
  conflicting_product_identity: "Overeenkomende productidentiteit",
  current_complete_market_price: "Volledige marktprijsmeting van maximaal 24 uur oud",
  complete_market_offers: "Volledig opgehaalde aanbiedingen",
  positive_landed_cost_for_roi: "Onderbouwde positieve inkoopkosten voor voorraad-ROI",
  current_financial_evidence: "Actuele financiële brongegevens",
};
const kinds: Record<string, string> = {
  official_measured: "Officiële bol-meting", manual_or_imported: "Handmatig / geïmporteerd",
  derived: "Door ProductRadar berekend", estimated: "Schatting — geen gemeten verkoopcijfer",
};
export function score(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toLocaleString("nl-NL", { maximumFractionDigits: 1 })}/100` : "Onbekend";
}
function number(value: number | null) {
  return value == null ? "Onbekend" : value.toLocaleString("nl-NL", { maximumFractionDigits: 2 });
}
export function ProvenanceLegend() {
  return <details className="comparison-legend"><summary>Wat betekenen de databronnen?</summary><dl>
    <dt>Officiële bol-meting</dt><dd>Aanbiedingen en ratingverdelingen uit opgeslagen bol-metingen; dit zijn geen gemeten verkopen.</dd>
    <dt>Handmatig / geïmporteerd</dt><dd>Door jou of via CSV ingevoerde waarden; volledigheid en btw-basis zijn niet automatisch vastgesteld.</dd>
    <dt>Door ProductRadar berekend</dt><dd>Afgeleide tellingen, financiële metrics en scores op basis van invoer.</dd>
    <dt>Schatting</dt><dd>Een onzekere verwachting, zoals maandverkopen. Geen officieel gemeten bol-verkoopvolume.</dd>
  </dl></details>;
}

export function ComparisonView({ comparison }: { comparison: Comparison }) {
  const v2 = comparison.analysis_v2, market = comparison.market;
  return <div className="decision-comparison" aria-label="Vergelijking Decision Engine v1 en v2">
    <p className="comparison-note">Evaluatiemodus · V1 blijft de standaard. Scores worden bij het uitlezen berekend; deze vergelijking slaat niets op.</p>
    <div className="comparison-scores">
      <section aria-label="Decision Engine v1"><h3>V1 · huidige beoordeling</h3><strong className="comparison-number">{score(comparison.analysis_v1.opportunity_score)}</strong><p>{comparison.analysis_v1.verdict}</p><small>Op basis van bestaande handmatige en importgegevens.</small></section>
      <section aria-label="Decision Engine v2"><h3>V2 · vergelijking</h3><strong className="comparison-number">{score(v2.opportunity_score)}</strong><p>{v2.verdict}</p>
        {v2.opportunity_score == null && <p role="status">Geen definitieve actuele Opportunity Score. Eerst ontbrekende of verouderde gegevens aanvullen.</p>}
      </section>
    </div>
    <p className="comparison-reason">{comparison.primary_reason.text}</p>
    <div className="comparison-subscore-grid">{([
      ["demand", "Demand", "Vraagsignaal"], ["competition", "Competition", "Hoger is gunstiger"],
      ["profitability", "Profitability", "Financiële v2-basis"], ["risk", "Risk", "Hoger betekent meer risico"],
      ["data_confidence", "Data Confidence", "Kwaliteit van bewijs, geen succeskans"],
    ] as const).map(([key, title, help]) => <div key={key}><h4>{title}</h4><strong>{score(v2.subscores[key])}</strong><small>{help}</small></div>)}</div>
    <p className="comparison-note">Scores zijn door ProductRadar berekend. Onbekend is geen nul.</p>
    <section className="comparison-market" aria-label="Marktbron en ouderdom"><h3>Gebruikte marktmeting</h3>
      {market.freshness === "stale" && <p className="comparison-warning" role="alert">Marktdata ouder dan 24 uur. Vernieuw de marktgegevens voordat v2 een actuele definitieve beoordeling kan geven. Getoonde prijzen zijn uitsluitend historisch.</p>}
      {market.freshness === "missing" ? <p>Geen opgeslagen marktmeting beschikbaar.</p> : <>
        <p>{market.source ?? "Onbekende bron"} · {market.api_version ?? "Onbekende versie"} · Officiële bol-meting</p>
        <p>Gemeten: {market.measured_at ?? "Onbekend"} · Ouderdom bij analyse: {market.age_hours == null ? "Onbekend" : `${number(market.age_hours)} uur`} · Snapshot {market.snapshot_id ?? "onbekend"}</p>
        {market.freshness === "invalid" && <p className="comparison-warning">Het meetmoment is ongeldig. Deze bron kan geen actuele beoordeling onderbouwen.</p>}
        <p>{market.freshness === "fresh" ? "Prijsrange in opgeslagen meting (maximaal 24 uur oud)" : "Historische prijsrange — geen actuele prijs"}: {number(market.price_min)} – {number(market.price_max)} EUR</p>
        <p>Unieke verkopers: {number(market.unique_seller_count)} · Aanbiedingen: {number(market.offer_count)} · Door ProductRadar geteld</p>
        {market.status !== "complete" && <p>Geen volledig bruikbare aanbiedingenmeting. Onbekende tellingen betekenen niet dat er weinig concurrentie is.</p>}
      </>}
      <p className="comparison-note">Analysemoment: {comparison.evaluated_at}. Er worden hier geen nieuwe bol-metingen opgehaald.</p>
    </section>
    <div className="comparison-columns">
      <section><h3>Positieve v2-drivers</h3><ul>{v2.positive_drivers.map(d => <li key={d.code}>{d.label}: +{number(d.points_vs_neutral)} punten ten opzichte van neutraal</li>)}</ul>{!v2.positive_drivers.length && <p>Geen onderbouwde positieve drivers beschikbaar.</p>}</section>
      <section><h3>Negatieve v2-drivers</h3><ul>{v2.negative_drivers.map(d => <li key={d.code}>{d.label}: {number(d.points_vs_neutral)} punten ten opzichte van neutraal</li>)}</ul>{!v2.negative_drivers.length && <p>Geen onderbouwde negatieve drivers beschikbaar. Dat bewijst geen laag risico.</p>}</section>
    </div>
    <section><h3>Veiligheidsgrenzen en caps</h3>{v2.safeguards.length ? <ul>{v2.safeguards.map(s => <li key={s.code}>Maximaal {s.cap}/100: {s.explanation}</li>)}</ul> : <p>Geen aanvullende cap toegepast.</p>}
      {v2.opportunity_score == null && <p>Een cap vult een ontbrekende score niet in.</p>}
    </section>
    <section><h3>Kritieke ontbrekende gegevens</h3>{v2.missing_critical_inputs.length ? <ul>{v2.missing_critical_inputs.map(k => <li key={k}>{labels[k] ?? k}</li>)}</ul> : <p>Geen kritieke ontbrekende inputs.</p>}<p>{comparison.input_notice}</p></section>
    <ProvenanceLegend />
    <details><summary>Opgeslagen handmatige waarden en schattingen</summary><p>Deze legacy-waarden zijn niet automatisch gebruikt als v2-invoer. Bron- en invoerdatum zijn onbekend; opgeslagen nullen kunnen oude importdefaults zijn.</p>
      <dl>{comparison.legacy_inputs.map(input => <div key={input.field}><dt>{input.label}</dt><dd>{number(input.value)} {input.unit} · {kinds[input.kind] ?? "Onbekende herkomst"}</dd></div>)}</dl>
    </details>
    <p className="comparison-note">{comparison.difference_notice}</p>
    <details><summary>Analyseversie</summary><p>{v2.decision_engine_version} · {v2.score_config_version}</p><p className="comparison-id">Analyse-ID: {v2.analysis_id}</p></details>
  </div>;
}

export function DecisionComparison({ productId, api = API }: { productId: number; api?: string }) {
  const [data, setData] = useState<Comparison | null>(null);
  const [loading, setLoading] = useState(false), [error, setError] = useState("");
  const requestId = useRef(0);
  useEffect(() => { requestId.current++; setData(null); setError(""); setLoading(false); return () => { requestId.current++; }; }, [productId, api]);
  async function load() {
    const current = ++requestId.current;
    setLoading(true); setData(null); setError("");
    try {
      const response = await fetch(`${api}/comparison/products/${productId}`, { cache: "no-store" });
      if (!response.ok) throw new Error("Vergelijking niet beschikbaar. Probeer opnieuw.");
      const body = await response.json();
      if (body.product?.id !== productId || !body.analysis_v1 || !body.analysis_v2 || !body.market) throw new Error("Onvolledig vergelijkingsantwoord.");
      if (current === requestId.current) setData(body);
    } catch { if (current === requestId.current) setError("Vergelijking niet beschikbaar. Probeer opnieuw."); }
    finally { if (current === requestId.current) setLoading(false); }
  }
  return <section className="panel comparison-panel"><h2>Decision Engine v1 versus v2</h2><p>Vergelijk de bestaande beoordeling met de nieuwe engine op opgeslagen gegevens.</p>
    <button type="button" disabled={loading} onClick={load}>{loading ? "Vergelijking laden…" : "Vergelijk opgeslagen gegevens"}</button>
    {error && <p role="alert">{error}</p>}{data && <ComparisonView comparison={data} />}
  </section>;
}

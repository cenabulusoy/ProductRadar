"use client";

import { useMemo, useState } from "react";
import { Product } from "../lib/types";
import { ScoreBar } from "./ScoreBar";

type Props = { product: Product };

function money(value: number) {
  return new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR" }).format(value);
}

export function ProductDetail({ product }: Props) {
  const [salePrice, setSalePrice] = useState(product.sale_price);
  const [purchasePrice, setPurchasePrice] = useState(product.purchase_price);
  const [shippingCost, setShippingCost] = useState(product.shipping_cost);
  const [commissionRate, setCommissionRate] = useState(product.commission_rate);
  const [returnReserve, setReturnReserve] = useState(2);

  const scenario = useMemo(() => {
    const vat = salePrice - salePrice / 1.21;
    const commission = salePrice * (commissionRate / 100);
    const netProfit = salePrice - vat - purchasePrice - shippingCost - commission - returnReserve;
    const margin = salePrice ? (netProfit / salePrice) * 100 : 0;
    const roi = purchasePrice ? (netProfit / purchasePrice) * 100 : 0;
    const monthlyProfit = netProfit * product.analysis.average_monthly_sales;
    return { vat, commission, netProfit, margin, roi, monthlyProfit };
  }, [salePrice, purchasePrice, shippingCost, commissionRate, returnReserve, product]);

  const advice = product.analysis.opportunity_score >= 75
    ? "Sterke kandidaat"
    : product.analysis.opportunity_score >= 60
      ? "Verder onderzoeken"
      : "Voorzichtig benaderen";

  return (
    <div className="detail-page">
      <a className="back-link" href="/">← Terug naar Product Hunter</a>

      <section className="detail-hero panel">
        <div>
          <span className="eyebrow">{product.category} · {product.brand}</span>
          <h1>{product.name}</h1>
          <p>Een beslisscherm dat marktpotentieel, winst en risico samenbrengt.</p>
        </div>
        <div className="decision-card">
          <span>ProductRadar-advies</span>
          <strong>{advice}</strong>
          <small>Opportunity Score {product.analysis.opportunity_score}/100</small>
        </div>
      </section>

      <section className="detail-metrics">
        <div className="panel metric-card"><span>Verkoopprijs</span><strong>{money(product.sale_price)}</strong><small>huidige invoer</small></div>
        <div className="panel metric-card"><span>Geschatte verkopen</span><strong>{product.monthly_sales_low}–{product.monthly_sales_high}</strong><small>per maand</small></div>
        <div className="panel metric-card"><span>Aanbieders</span><strong>{product.sellers}</strong><small>concurrentiedruk</small></div>
        <div className="panel metric-card"><span>Betrouwbaarheid</span><strong>{product.confidence}%</strong><small>van deze analyse</small></div>
      </section>

      <section className="detail-columns">
        <div className="panel score-panel">
          <div className="section-title"><div><span className="eyebrow">SCORING ENGINE</span><h2>Waarom scoort dit product zo?</h2></div><div className="score-badge">{product.analysis.opportunity_score}</div></div>
          <ScoreBar label="Market Score" value={product.analysis.market_score} />
          <ScoreBar label="Profit Score" value={product.analysis.profit_score} />
          <ScoreBar label="Risk Safety" value={product.analysis.risk_score} />
          <div className="score-explain-grid">
            <div><span>Vraag</span><strong>{product.analysis.demand_score}/100</strong><p>Afgeleid uit verkooprange, reviewgroei en trend.</p></div>
            <div><span>Concurrentie</span><strong>{product.analysis.competition_score}/100</strong><p>Hoger is gunstiger: minder aanbieders en lagere reviewbarrière.</p></div>
            <div><span>Trend</span><strong>{product.analysis.trend_score}/100</strong><p>Indicatie op basis van ingevoerde marktontwikkeling.</p></div>
          </div>
        </div>

        <div className="panel reasons-panel">
          <span className="eyebrow">BESLISSINGSONDERSTEUNING</span>
          <h2>Kopen of verder zoeken?</h2>
          <div className="reason-section positive">
            <h3>Waarom kopen?</h3>
            <ul>{product.analysis.buy_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
          </div>
          <div className="reason-section warning">
            <h3>Waarom niet kopen?</h3>
            <ul>{product.analysis.avoid_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
          </div>
          <p className="disclaimer">Deze analyse is een beslissingshulp. Verkoopcijfers zijn schattingen totdat echte historische marktdata is aangesloten.</p>
        </div>
      </section>

      <section className="panel calculator-panel">
        <div className="section-title"><div><span className="eyebrow">PROFIT CALCULATOR</span><h2>Test je eigen inkoopscenario</h2></div><strong className={scenario.netProfit >= 0 ? "profit-positive" : "profit-negative"}>{money(scenario.netProfit)} winst/stuk</strong></div>
        <div className="calculator-grid">
          <label>Verkoopprijs<input type="number" step="0.01" value={salePrice} onChange={(e) => setSalePrice(Number(e.target.value))} /></label>
          <label>Inkoopprijs<input type="number" step="0.01" value={purchasePrice} onChange={(e) => setPurchasePrice(Number(e.target.value))} /></label>
          <label>Verzending<input type="number" step="0.01" value={shippingCost} onChange={(e) => setShippingCost(Number(e.target.value))} /></label>
          <label>Commissie %<input type="number" step="0.1" value={commissionRate} onChange={(e) => setCommissionRate(Number(e.target.value))} /></label>
          <label>Retourreserve<input type="number" step="0.01" value={returnReserve} onChange={(e) => setReturnReserve(Number(e.target.value))} /></label>
        </div>
        <div className="calculation-results">
          <div><span>Btw-reserve</span><strong>{money(scenario.vat)}</strong></div>
          <div><span>Commissie</span><strong>{money(scenario.commission)}</strong></div>
          <div><span>Marge</span><strong>{scenario.margin.toFixed(1)}%</strong></div>
          <div><span>ROI</span><strong>{scenario.roi.toFixed(1)}%</strong></div>
          <div><span>Geschatte maandwinst</span><strong>{money(scenario.monthlyProfit)}</strong></div>
        </div>
      </section>
    </div>
  );
}

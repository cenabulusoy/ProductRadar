"use client";

import { Product } from "../lib/types";
import { ScoreBar } from "./ScoreBar";

export function ProductCard({ product, onFavorite }: { product: Product; onFavorite: (id: number) => void }) {
  const a = product.analysis;
  return (
    <article className="card">
      <div className="card-head">
        <div>
          <span className="eyebrow">{product.category} · {product.brand}</span>
          <h3>{product.name}</h3>
        </div>
        <button className="favorite" onClick={() => onFavorite(product.id)} aria-label="Favoriet">
          {product.favorite ? "★" : "☆"}
        </button>
      </div>
      <div className="price-row">
        <strong>€{product.sale_price.toFixed(2)}</strong>
        <span>{product.monthly_sales_low}–{product.monthly_sales_high} verkopen p/m</span>
      </div>
      <div className="opportunity"><span>Opportunity Score</span><strong>{a.opportunity_score}</strong></div>
      <ScoreBar label="Market" value={a.market_score} />
      <ScoreBar label="Profit" value={a.profit_score} />
      <ScoreBar label="Risk safety" value={a.risk_score} />
      <div className="metrics">
        <div><span>Winst/stuk</span><strong>€{a.net_profit_per_unit.toFixed(2)}</strong></div>
        <div><span>Marge</span><strong>{a.margin_percent}%</strong></div>
        <div><span>ROI</span><strong>{a.roi_percent}%</strong></div>
      </div>
      <div className="reason-grid">
        <div><h4>Waarom kopen?</h4><p>{a.buy_reasons[0]}</p></div>
        <div><h4>Waarom niet?</h4><p>{a.avoid_reasons[0]}</p></div>
      </div>
      <a className="detail-button" href={`/products/${product.id}`}>Open volledige analyse →</a>
      <footer>{product.sellers} aanbieders · {product.reviews} reviews · {product.confidence}% betrouwbaarheid</footer>
    </article>
  );
}

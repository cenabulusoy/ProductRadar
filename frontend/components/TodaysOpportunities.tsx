import Link from "next/link";
import { Product } from "../lib/types";

type Props = {
  products: Product[];
};

export function TodaysOpportunities({ products }: Props) {
  const opportunities = [...products]
    .sort(
      (a, b) =>
        b.analysis.opportunity_score -
        a.analysis.opportunity_score,
    )
    .slice(0, 3);

  if (!opportunities.length) {
    return null;
  }

  return (
    <section className="todays-opportunities">
      <div className="opportunities-header">
        <div>
          <span className="eyebrow">
            TODAY&apos;S OPPORTUNITIES
          </span>

          <h2>Beste kansen van dit moment</h2>

          <p>
            Automatisch geselecteerd op basis van de
            ProductRadar Opportunity Score.
          </p>
        </div>
      </div>

      <div className="opportunity-list">
        {opportunities.map((product, index) => (
          <Link
            href={`/products/${product.id}`}
            className="opportunity-item"
            key={product.id}
          >
            <div className="opportunity-rank">
              #{index + 1}
            </div>

            <div className="opportunity-product">
              <strong>{product.name}</strong>

              <span>
                {product.brand} · {product.category}
              </span>
            </div>

            <div className="opportunity-metrics">
              <span>
                Marge{" "}
                <strong>
                  {product.analysis.margin_percent.toFixed(1)}%
                </strong>
              </span>

              <span>
                Aanbieders <strong>{product.sellers}</strong>
              </span>
            </div>

            <div className="opportunity-score">
              <span>Score</span>

              <strong>
                {product.analysis.opportunity_score}
              </strong>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}

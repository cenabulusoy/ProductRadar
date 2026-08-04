export type ProductDNAItem = {
  key: string;
  label: string;
  score: number;
  stars: number;
};

export type Analysis = {
  average_monthly_sales: number;
  monthly_revenue: number;
  net_profit_per_unit: number;
  margin_percent: number;
  roi_percent: number;
  market_score: number;
  profit_score: number;
  risk_score: number;
  opportunity_score: number;
  demand_score: number;
  competition_score: number;
  trend_score: number;
  margin_score: number;
  roi_score: number;
  capital_efficiency_score: number;
  confidence_score: number;
  verdict: "Kansrijk" | "Onderzoeken" | "Twijfel" | "Niet inkopen";
  verdict_detail: string;
  buy_reasons: string[];
  avoid_reasons: string[];
  product_dna: ProductDNAItem[];
};

export type Product = {
  id: number;
  name: string;
  category: string;
  brand: string;
  sale_price: number;
  purchase_price: number;
  shipping_cost: number;
  commission_rate: number;
  monthly_sales_low: number;
  monthly_sales_high: number;
  sellers: number;
  reviews: number;
  confidence: number;
  favorite: boolean;
  analysis: Analysis;
};

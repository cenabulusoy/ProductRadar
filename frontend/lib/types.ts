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
  buy_reasons: string[];
  avoid_reasons: string[];
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

export type Comparison = {
  product: { id: number; name: string; ean?: string; category?: string };
  evaluated_at: string;
  default_engine: string;
  analysis_v1: { opportunity_score: number; verdict: string };
  analysis_v2: {
    decision_engine_version: string; score_config_version: string; analysis_id: string;
    status: string; opportunity_score: number | null; verdict: string; verdict_reason: string;
    subscores: { demand: number | null; competition: number | null; profitability: number | null; risk: number | null; data_confidence: number | null };
    safeguards: { code: string; cap: number; explanation: string }[];
    positive_drivers: { code: string; label: string; points_vs_neutral: number }[];
    negative_drivers: { code: string; label: string; points_vs_neutral: number }[];
    missing_critical_inputs: string[]; unknown_signals: string[]; readiness_missing: string[];
  };
  market: { snapshot_id: number | null; measured_at: string | null; age_hours: number | null; freshness: string;
    source: string | null; api_version: string | null; status: string; price_min: number | null; price_max: number | null;
    unique_seller_count: number | null; offer_count: number | null };
  legacy_inputs: { field: string; label: string; value: number | null; unit: string; kind: string; source: string; recorded_at: string | null; used_in_v2: boolean }[];
  primary_reason: { code: string; text: string }; input_notice: string; difference_notice: string;
};
export type EvaluationRow = Comparison | { product: { id: number; name: string }; error: string };
export type Evaluation = { items: EvaluationRow[]; total: number; offset: number; limit: number; next_offset: number | null; evaluated_at: string };

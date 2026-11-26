export interface UserProfile {
  id: number;
  email: string;
  full_name: string;
}

export interface Dataset {
  id: number;
  name: string;
  rows: number;
  columns: number;
  size: number;
  created_at: string;
}

export interface NumericMetric {
  name: string;
  sum: number | null;
  mean: number | null;
  min: number | null;
  max: number | null;
  median: number | null;
  std: number | null;
  valid_count: number;
  q25: number | null;
  q75: number | null;
}

export interface ColumnQuality {
  column: string;
  missing: number;
  missing_pct: number;
  unique: number;
  dtype: string;
}

export interface Insight {
  title: string;
  detail: string;
  type?: string;
}

export interface DatasetProfile {
  rows: number;
  columns: number;
  column_names: string[];
  date_column: string | null;
  numeric_summary: NumericMetric[];
  quality: ColumnQuality[];
  categories: Array<{column: string; values: Array<{name: string; count: number}>}>;
  category_analysis: Array<{
    column: string;
    metric: string;
    metric_type?: "revenue" | "sales_amount";
    values: Array<{name: string; sum: number | null}>;
  }>;
  correlations: Array<{left: string; right: string; coefficient: number; absolute: number}>;
  financial_metrics?: Record<string, {
    status: "available" | "ambiguous" | "unavailable";
    column: string | null;
    candidates: string[];
    total?: number | null;
    average?: number | null;
    count?: number | null;
    valid_count?: number;
    unit?: string;
    aggregation?: string;
    reason?: string;
  }>;
  duplicate_rows: number;
  kpis: {
    total_revenue: number | null;
    total_profit: number | null;
    average_sales: number | null;
    total_sales_amount?: number | null;
    average_sales_amount?: number | null;
    total_units_sold?: number | null;
    average_units_sold?: number | null;
    total_expenses?: number | null;
    transaction_count?: number | null;
    average_profit_margin?: number | null;
    growth: {
      metric: string;
      percent: number;
      previous_period: string;
      current_period: string;
      previous_value: number;
      current_value: number;
    } | null;
    growth_status?: {
      status: "available" | "unavailable";
      reason: string | null;
      current_period?: string;
      required_previous_period?: string;
      previous_period?: string;
    };
  };
  preview: Array<Record<string, unknown>>;
}

export interface DatasetAnalysis {
  dataset: {id: number; name: string};
  profile: DatasetProfile;
  insights: Array<Insight | string>;
}

export interface DatasetPreview {
  rows: Array<Record<string, unknown>>;
  total: number;
  offset: number;
  limit: number;
  columns: string[];
}

export interface ForecastResult {
  available: boolean;
  reason?: string;
  target?: string;
  date_column?: string;
  history?: Array<{date: string; actual: number}>;
  forecast?: Array<{date: string; predicted: number}>;
  metrics?: {
    mae: number | null;
    rmse: number | null;
    baseline_mae: number | null;
    baseline_rmse: number | null;
    mape: number | null;
  };
  caveat?: string;
}

export interface AnomalyResult {
  available: boolean;
  reason?: string;
  count?: number;
  total?: number;
  contamination?: number;
  rows?: Array<{row: number; score: number; reasons: string[]; values: Record<string, unknown>}>;
  note?: string;
}

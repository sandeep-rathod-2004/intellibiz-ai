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
  category_analysis: Array<{column: string; metric: string; values: Array<{name: string; sum: number}>}>;
  correlations: Array<{left: string; right: string; coefficient: number; absolute: number}>;
  duplicate_rows: number;
  kpis: {
    total_revenue: number | null;
    total_profit: number | null;
    average_sales: number | null;
    growth: {
      metric: string;
      percent: number;
      previous_period: string;
      current_period: string;
      previous_value: number;
      current_value: number;
    } | null;
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

import {useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode} from "react";
import {Link, useLocation, useNavigate, useParams} from "react-router-dom";
import {
  Activity, AlertTriangle, ArrowDown, ArrowUp, BarChart3, Check, Database, DollarSign,
  Copy, FileSpreadsheet, Pencil, Plus, RefreshCw, Search, ShieldCheck, Sparkles, Target,
  Trash2, TrendingUp,
} from "lucide-react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {api, errorMessage, errorRetryInfo} from "../lib/api";
import {useAuth} from "../lib/auth";
import {useDashboard} from "../lib/dashboard";
import {copilotProviderStatusLabel, type CopilotProviderState} from "../lib/providerStatus";
import type {
  AnomalyResult, Dataset, DatasetAnalysis, DatasetPreview, ForecastResult, Insight,
} from "../types";

const numberFormat = new Intl.NumberFormat("en-US", {maximumFractionDigits: 2});
const compactFormat = new Intl.NumberFormat("en-US", {notation: "compact", maximumFractionDigits: 1});

function displayValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return numberFormat.format(value);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function MetricCard({icon, label, value, note, tone = "mint"}: {
  icon: ReactNode;
  label: string;
  value: string;
  note: string;
  tone?: string;
}) {
  return (
    <div className="metric-card">
      <div className="metric-top"><div className={`metric-icon ${tone}`}>{icon}</div></div>
      <div className="metric-value">{value}</div>
      <div className="metric-label">{label}</div>
      <div className="metric-note">{note}</div>
    </div>
  );
}

function PageError({message, onRetry}: {message: string; onRetry?: () => void}) {
  if (!message) return null;
  return (
    <div className="notice-banner error-banner" role="alert">
      <span>{message}</span>
      {onRetry && <button className="inline-link" onClick={onRetry}>Retry</button>}
    </div>
  );
}

function EmptyDataset({children}: {children?: ReactNode}) {
  return (
    <div className="empty-state">
      <div className="empty-icon"><Database size={28} /></div>
      <h2>Your intelligence workspace starts here.</h2>
      <p>Upload a CSV or Excel file to generate its data profile, KPIs, quality checks, and model-ready insights.</p>
      {children}
    </div>
  );
}

function RecordsTable({rows, columns, sortBy, descending, onSort}: {
  rows: Array<Record<string, unknown>>;
  columns: string[];
  sortBy?: string;
  descending?: boolean;
  onSort?: (column: string) => void;
}) {
  if (!rows.length) return <div className="chart-empty">No records match this view.</div>;
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>{columns.map(column => (
            <th key={column}>
              {onSort ? (
                <button className="table-sort" onClick={() => onSort(column)} aria-label={`Sort by ${column}`}>
                  {column.replace(/_/g, " ")}
                  {sortBy === column && (descending ? <ArrowDown size={11} /> : <ArrowUp size={11} />)}
                </button>
              ) : column.replace(/_/g, " ")}
            </th>
          ))}</tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${String(row.row ?? row.id ?? "")}-${index}`}>
              {columns.map(column => <td key={column} title={displayValue(row[column])}>{displayValue(row[column])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function OverviewPage() {
  const {
    analysis, analysisError, analysisLoading, datasets, datasetsLoading,
    downloadSample, notify, selectedDataset, selectedDatasetId,
  } = useDashboard();
  const [chartMetric, setChartMetric] = useState<"sum" | "mean">("sum");
  const metrics = (analysis?.profile.numeric_summary ?? []).filter(metric => metric.valid_count > 0);
  const completeness = useMemo(() => {
    if (!analysis?.profile.rows || !analysis.profile.columns) return null;
    const missing = analysis.profile.quality.reduce((sum, item) => sum + item.missing, 0);
    return Math.max(0, 100 - missing / (analysis.profile.rows * analysis.profile.columns) * 100);
  }, [analysis]);
  const chartData = metrics.slice(0, 6).map(metric => ({
    name: metric.name.length > 16 ? `${metric.name.slice(0, 15)}…` : metric.name,
    sum: metric.sum ?? 0,
    mean: metric.mean ?? 0,
  }));
  const forecastReady = Boolean(
    analysis?.profile.column_names.some(column => /date|time/i.test(column)) && metrics.length,
  );
  const anomaliesReady = Boolean(analysis?.profile.rows && analysis.profile.rows >= 10 && metrics.length);

  if (datasetsLoading || analysisLoading) {
    return <div className="page-loading" role="status"><div className="skeleton" /><div className="skeleton" /></div>;
  }
  if (!selectedDataset) {
    return (
      <EmptyDataset>
        <button className="secondary-btn" onClick={() => void downloadSample()}>
          <FileSpreadsheet size={15} /> Download retail_sales.csv sample
        </button>
      </EmptyDataset>
    );
  }

  const insights = analysis?.insights ?? [];
  return (
    <>
      <PageError message={analysisError} />
      <div className="dataset-strip">
        <div className="dataset-ident">
          <div className="file-icon"><FileSpreadsheet size={19} /></div>
          <div><b>{selectedDataset.name}</b><small>{selectedDataset.rows.toLocaleString()} records · {selectedDataset.columns} fields</small></div>
        </div>
        <span className="fresh-tag"><span className="pulse-dot" /> DATASET READY</span>
      </div>
      <div className="metric-grid">
        <MetricCard icon={<Database />} label="Total records" value={selectedDataset.rows.toLocaleString()} note={`${selectedDataset.columns} fields`} />
        <MetricCard
          icon={<DollarSign />}
          label="Total revenue"
          value={analysis?.profile.kpis.total_revenue == null ? "—" : numberFormat.format(analysis.profile.kpis.total_revenue)}
          note={analysis?.profile.kpis.total_revenue == null ? "No revenue field identified" : "Computed from uploaded records"}
          tone="blue"
        />
        <MetricCard
          icon={<DollarSign />}
          label="Total profit"
          value={analysis?.profile.kpis.total_profit == null ? "—" : numberFormat.format(analysis.profile.kpis.total_profit)}
          note={analysis?.profile.kpis.total_profit == null ? "No profit field identified" : "Computed from uploaded records"}
          tone="violet"
        />
        <MetricCard
          icon={<Activity />}
          label="Average sales"
          value={analysis?.profile.kpis.average_sales == null ? "—" : numberFormat.format(analysis.profile.kpis.average_sales)}
          note={analysis?.profile.kpis.average_sales == null ? "No sales field identified" : "Mean of valid sales values"}
        />
        <MetricCard
          icon={<TrendingUp />}
          label="Monthly growth"
          value={analysis?.profile.kpis.growth ? `${analysis.profile.kpis.growth.percent > 0 ? "+" : ""}${numberFormat.format(analysis.profile.kpis.growth.percent)}%` : "—"}
          note={analysis?.profile.kpis.growth ? `${analysis.profile.kpis.growth.previous_period} → ${analysis.profile.kpis.growth.current_period}` : "Requires comparable monthly periods"}
          tone="amber"
        />
        <MetricCard icon={<Activity />} label="Numeric indicators" value={String(metrics.length)} note="Measures profiled" tone="blue" />
        <MetricCard icon={<Target />} label="Data completeness" value={completeness === null ? "—" : `${completeness.toFixed(1)}%`} note="Across all fields" tone="violet" />
        <MetricCard icon={<Sparkles />} label="Insights generated" value={String(insights.length)} note="Computed from source data" tone="amber" />
      </div>

      <div className="section-grid">
        <section className="panel chart-panel">
          <div className="panel-head">
            <div><span className="eyebrow">PERFORMANCE INTELLIGENCE</span><h3>Metric overview</h3></div>
            <label className="chart-control">
              <span className="sr-only">Chart metric</span>
              <select value={chartMetric} onChange={event => setChartMetric(event.target.value as "sum" | "mean")}>
                <option value="sum">Aggregate</option>
                <option value="mean">Average</option>
              </select>
            </label>
          </div>
          {chartData.length ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={chartData} barSize={34}>
                <defs><linearGradient id="barMint" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#69e4c1" /><stop offset="100%" stopColor="#398f9b" /></linearGradient></defs>
                <CartesianGrid strokeDasharray="3 5" stroke="var(--grid)" vertical={false} />
                <XAxis dataKey="name" tick={{fill: "var(--muted)", fontSize: 10}} axisLine={false} tickLine={false} />
                <YAxis tick={{fill: "var(--muted)", fontSize: 10}} axisLine={false} tickLine={false} tickFormatter={value => compactFormat.format(Number(value))} />
                <Tooltip formatter={value => numberFormat.format(Number(value))} contentStyle={{background: "var(--tooltip)", border: "1px solid var(--border)", borderRadius: 12, color: "var(--text)"}} />
                <Bar dataKey={chartMetric} name={chartMetric === "sum" ? "Aggregate" : "Average"} fill="url(#barMint)" radius={[7, 7, 2, 2]} />
              </BarChart>
            </ResponsiveContainer>
          ) : <div className="chart-empty">No numeric fields are available for charting.</div>}
          <div className="chart-legend"><span><i className="legend-dot mint-dot" /> Computed values</span><span className="muted">From uploaded records</span></div>
        </section>

        <section className="panel insight-panel">
          <div className="panel-head"><div><span className="eyebrow">THE SIGNAL</span><h3>Business insights</h3></div><Sparkles className="mint" size={18} /></div>
          <div className="insight-list">
            {insights.slice(0, 5).map((insight: Insight | string, index) => (
              <div className="insight-item" key={`${index}-${typeof insight === "string" ? insight : insight.title}`}>
                <div className="insight-number">0{index + 1}</div>
                <div>{typeof insight === "string" ? <p>{insight}</p> : <><b>{insight.title}</b><p>{insight.detail}</p></>}</div>
              </div>
            ))}
            {!analysis && <div className="skeleton" />}
            {analysis && !insights.length && <p className="subtle">No insight summaries were returned for this dataset.</p>}
          </div>
          <Link className="inline-link" to="/copilot">Ask the AI Copilot <span>↗</span></Link>
        </section>
      </div>

      <div className="section-grid lower-grid">
        <section className="panel">
          <div className="panel-head"><div><span className="eyebrow">DATA HEALTH</span><h3>Quality by field</h3></div><span className="mini-tag">{analysis?.profile.quality.length ?? 0} FIELDS</span></div>
          {analysis?.profile.duplicate_rows ? <p className="subtle">{analysis.profile.duplicate_rows.toLocaleString()} exact duplicate rows detected.</p> : null}
          <div className="quality-list">
            {(analysis?.profile.quality ?? []).slice(0, 8).map(item => (
              <div className="quality-row" key={item.column}>
                <div><b>{item.column}</b><small>{item.dtype} · {item.unique} unique</small></div>
                <div className="quality-track"><span style={{width: `${100 - item.missing_pct}%`}} /></div>
                <strong>{(100 - item.missing_pct).toFixed(1)}%</strong>
              </div>
            ))}
            {!analysis && <div className="skeleton" />}
          </div>
        </section>
        <section className="panel quick-panel">
          <div className="panel-head"><div><span className="eyebrow">MODEL READINESS</span><h3>Analytics status</h3></div><BarChart3 className="mint" size={18} /></div>
          <div className="model-status"><span className={forecastReady ? "status-ready" : "status-waiting"}><TrendingUp size={15} /></span><div><b>Forecast model</b><small>{forecastReady ? "Date and numeric fields are available" : "Needs a date and numeric field"}</small></div></div>
          <div className="model-status"><span className={anomaliesReady ? "status-ready" : "status-waiting"}><AlertTriangle size={15} /></span><div><b>Anomaly detection</b><small>{anomaliesReady ? "Ready for at least 10 records" : "Needs 10+ records and a numeric field"}</small></div></div>
          <div className="model-status"><span className="status-ready"><Check size={15} /></span><div><b>Dataset profile</b><small>Computed from the uploaded file</small></div></div>
        </section>
      </div>

      <section className="panel activity-panel">
        <div className="panel-head"><div><span className="eyebrow">RECENT ACTIVITY</span><h3>Latest datasets</h3></div><Link className="inline-link" to="/datasets">View dataset library ↗</Link></div>
        {datasets.slice(0, 5).map(dataset => (
          <div className="activity-list-row" key={dataset.id}>
            <span className="activity-icon"><Database size={15} /></span>
            <span><b>{dataset.name}</b><small>{dataset.rows.toLocaleString()} rows · uploaded {new Date(dataset.created_at).toLocaleDateString()}</small></span>
            <span className="fresh-tag">READY</span>
          </div>
        ))}
        {!datasets.length && <p className="subtle">No uploaded datasets yet.</p>}
        <span className="sr-only">Selected dataset ID {selectedDatasetId}</span>
      </section>
    </>
  );
}

export function DataExplorerPage() {
  const {
    analysis, datasets, notify, selectedDataset, selectedDatasetId, setSelectedDatasetId,
  } = useDashboard();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState("");
  const [descending, setDescending] = useState(false);
  const [pageSize, setPageSize] = useState(20);
  const [columnFilters, setColumnFilters] = useState<Record<string, string>>({});
  const [visibleColumns, setVisibleColumns] = useState<string[]>([]);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [exporting, setExporting] = useState(false);
  const [result, setResult] = useState<DatasetPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setPage(1);
    setSortBy("");
    setColumnFilters({});
  }, [selectedDatasetId]);

  useEffect(() => {
    setVisibleColumns(analysis?.profile.column_names ?? []);
  }, [analysis?.profile.column_names]);

  const activeColumnFilters = Object.fromEntries(
    Object.entries(columnFilters).filter(([, value]) => value.trim()),
  );

  useEffect(() => {
    if (!selectedDatasetId) {
      setResult(null);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError("");
      api.get<DatasetPreview>(`/datasets/${selectedDatasetId}/preview`, {
        params: {
          offset: (page - 1) * pageSize,
          limit: pageSize,
          search: search.trim() || undefined,
          filters: Object.keys(activeColumnFilters).length ? JSON.stringify(activeColumnFilters) : undefined,
          sort_by: sortBy || undefined,
          descending,
        },
        signal: controller.signal,
      }).then(response => setResult(response.data))
        .catch(requestError => {
          if (!controller.signal.aborted) setError(errorMessage(requestError));
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, search || Object.keys(activeColumnFilters).length ? 250 : 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [selectedDatasetId, page, pageSize, search, columnFilters, sortBy, descending, refreshKey]);

  const changeSort = (column: string) => {
    if (sortBy === column) setDescending(value => !value);
    else {
      setSortBy(column);
      setDescending(false);
    }
  };
  const pageCount = Math.max(1, Math.ceil((result?.total ?? 0) / pageSize));
  const availableColumns = result?.columns ?? analysis?.profile.column_names ?? [];
  const displayedColumns = availableColumns.filter(column => visibleColumns.includes(column));

  const exportFilteredRows = async () => {
    if (!selectedDatasetId) return;
    setExporting(true);
    setError("");
    try {
      const response = await api.get(`/datasets/${selectedDatasetId}/export`, {
        params: {
          search: search.trim() || undefined,
          filters: Object.keys(activeColumnFilters).length ? JSON.stringify(activeColumnFilters) : undefined,
          sort_by: sortBy || undefined,
          descending,
        },
        responseType: "blob",
      });
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `dataset-${selectedDatasetId}-filtered.csv`;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setExporting(false);
    }
  };

  if (!selectedDataset) {
    return <EmptyDataset><Link className="primary-btn" to="/datasets">Open dataset library</Link></EmptyDataset>;
  }
  return (
    <>
      <div className="panel explorer-toolbar">
        <label className="field-control"><span>Dataset</span>
          <select value={selectedDatasetId ?? ""} onChange={event => setSelectedDatasetId(event.target.value ? Number(event.target.value) : null)}>
            {datasets.map(dataset => <option value={dataset.id} key={dataset.id}>{dataset.name}</option>)}
          </select>
        </label>
        <label className="search-control"><Search size={16} /><span className="sr-only">Filter data rows</span>
          <input value={search} onChange={event => {setSearch(event.target.value); setPage(1);}} placeholder="Filter rows by any value…" />
        </label>
        <button className="secondary-btn" onClick={() => {setSearch(""); setPage(1);}} disabled={!search}>Clear filter</button>
        <label className="field-control"><span>Rows per page</span>
          <select aria-label="Rows per page" value={pageSize} onChange={event => {setPageSize(Number(event.target.value)); setPage(1);}}>
            <option value={20}>20</option><option value={50}>50</option><option value={100}>100</option>
          </select>
        </label>
        <button className="secondary-btn" onClick={() => setFiltersOpen(open => !open)} aria-expanded={filtersOpen}>
          Column filters
        </button>
        <button className="secondary-btn" onClick={() => setColumnsOpen(open => !open)} aria-expanded={columnsOpen}>
          Columns
        </button>
        <button className="primary-btn" onClick={() => void exportFilteredRows()} disabled={exporting}>
          {exporting ? "Preparing CSV…" : "Export filtered CSV"}
        </button>
      </div>
      {filtersOpen && (
        <section className="panel explorer-filter-grid" aria-label="Filter by column">
          {availableColumns.map(column => (
            <label className="field-control" key={column}><span>{column}</span>
              <input
                aria-label={`Filter ${column}`}
                value={columnFilters[column] ?? ""}
                onChange={event => {
                  setColumnFilters(current => ({...current, [column]: event.target.value}));
                  setPage(1);
                }}
                placeholder={`Contains ${column}…`}
              />
            </label>
          ))}
          <button className="inline-link" onClick={() => setColumnFilters({})} disabled={!Object.values(columnFilters).some(Boolean)}>
            Clear column filters
          </button>
        </section>
      )}
      {columnsOpen && (
        <section className="panel explorer-column-visibility" aria-label="Choose visible columns">
          {availableColumns.map(column => (
            <label key={column}>
              <input
                type="checkbox"
                checked={visibleColumns.includes(column)}
                disabled={visibleColumns.length === 1 && visibleColumns.includes(column)}
                onChange={event => setVisibleColumns(current =>
                  event.target.checked
                    ? [...current, column]
                    : current.filter(item => item !== column),
                )}
              />
              {column}
            </label>
          ))}
        </section>
      )}
      <PageError message={error} onRetry={() => setRefreshKey(key => key + 1)} />
      <section className="panel">
        <div className="panel-head"><div><span className="eyebrow">SOURCE RECORDS</span><h3>{selectedDataset.name}</h3></div><span className="mini-tag">{(result?.total ?? selectedDataset.rows).toLocaleString()} MATCHING ROWS</span></div>
        {loading ? <div className="skeleton table-skeleton" /> : (
          <RecordsTable
            rows={result?.rows ?? []}
            columns={displayedColumns}
            sortBy={sortBy}
            descending={descending}
            onSort={changeSort}
          />
        )}
        <div className="pagination">
          <span className="subtle">Page {page} of {pageCount} · {result?.total ?? 0} rows</span>
          <div><button className="secondary-btn" onClick={() => setPage(current => Math.max(1, current - 1))} disabled={page <= 1 || loading}>Previous</button>
            <button className="secondary-btn" onClick={() => setPage(current => Math.min(pageCount, current + 1))} disabled={page >= pageCount || loading}>Next</button></div>
        </div>
      </section>
      <section className="panel">
        <div className="panel-head"><div><span className="eyebrow">COLUMN INFORMATION</span><h3>Data quality by field</h3></div></div>
        {analysis?.profile.quality.length ? (
          <div className="column-grid">
            {analysis.profile.quality.map(column => (
              <article className="column-card" key={column.column}>
                <b>{column.column}</b>
                <span>{column.dtype}</span>
                <small>{column.unique.toLocaleString()} unique · {column.missing.toLocaleString()} missing ({column.missing_pct}%)</small>
              </article>
            ))}
          </div>
        ) : <p className="subtle">Column statistics are not available yet.</p>}
      </section>
      <button className="inline-link" onClick={() => notify("Filtering and sorting are applied to the full dataset on the backend.", "info")}>How filtering works</button>
    </>
  );
}

export function ForecastPage() {
  const {
    analysis, analysisLoading, datasets, notify, selectedDataset, selectedDatasetId, setSelectedDatasetId,
  } = useDashboard();
  const [dateColumn, setDateColumn] = useState("");
  const [targetColumn, setTargetColumn] = useState("");
  const [horizon, setHorizon] = useState(6);
  const [forecast, setForecast] = useState<ForecastResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const metrics = (analysis?.profile.numeric_summary ?? []).filter(metric => metric.valid_count > 0);
  const columns = analysis?.profile.column_names ?? [];

  useEffect(() => {
    setForecast(null);
    setError("");
    const defaultDate = analysis?.profile.date_column
      ?? columns.find(column => /date|time/i.test(column))
      ?? "";
    setDateColumn(defaultDate);
    setTargetColumn(metrics.find(metric => /sales|revenue|amount|profit/i.test(metric.name))?.name ?? metrics[0]?.name ?? "");
  }, [selectedDatasetId, analysis]);

  const runForecast = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    if (!selectedDatasetId || !dateColumn || !targetColumn) {
      setError("Select a dataset, date field, and numeric target before running a forecast.");
      return;
    }
    setBusy(true);
    try {
      const response = await api.post<ForecastResult>(`/datasets/${selectedDatasetId}/forecast`, {
        date_column: dateColumn,
        target_column: targetColumn,
        horizon,
      });
      setForecast(response.data);
      if (!response.data.available) notify(response.data.reason ?? "The selected data is not ready for forecasting.", "info");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  };

  const chartData = [
    ...(forecast?.history ?? []).map(point => ({date: point.date, actual: point.actual})),
    ...(forecast?.forecast ?? []).map(point => ({date: point.date, predicted: point.predicted})),
  ];

  return (
    <section className="panel">
      <div className="panel-head"><div><span className="eyebrow">PREDICTIVE INTELLIGENCE</span><h3>Forecast studio</h3><p className="subtle">Random Forest baseline with chronological holdout evaluation.</p></div></div>
      <form className="forecast-controls" onSubmit={runForecast}>
        <label className="field-control"><span>Dataset</span>
          <select value={selectedDatasetId ?? ""} onChange={event => setSelectedDatasetId(event.target.value ? Number(event.target.value) : null)} required>
            <option value="" disabled>Select a dataset</option>
            {datasets.map(dataset => <option value={dataset.id} key={dataset.id}>{dataset.name}</option>)}
          </select>
        </label>
        <label className="field-control"><span>Date field</span>
          <select value={dateColumn} onChange={event => setDateColumn(event.target.value)} required disabled={!columns.length || analysisLoading}>
            <option value="" disabled>Select a date field</option>
            {columns.map(column => <option value={column} key={column}>{column}</option>)}
          </select>
        </label>
        <label className="field-control"><span>Numeric target</span>
          <select value={targetColumn} onChange={event => setTargetColumn(event.target.value)} required disabled={!metrics.length}>
            <option value="" disabled>Select a metric</option>
            {metrics.map(metric => <option value={metric.name} key={metric.name}>{metric.name}</option>)}
          </select>
        </label>
        <label className="field-control"><span>Forecast periods (1–24)</span>
          <input type="number" min={1} max={24} value={horizon} onChange={event => setHorizon(Number(event.target.value))} required />
        </label>
        <button className="primary-btn" type="submit" disabled={busy || analysisLoading || !selectedDataset}>
          <TrendingUp size={15} />{busy ? "Training model…" : "Run forecast"}
        </button>
      </form>
      <PageError message={error} />
      {forecast?.available && forecast.metrics ? (
        <>
          <div className="forecast-metrics">
            <MetricCard icon={<Target />} label="Mean absolute error" value={forecast.metrics.mae === null ? "—" : numberFormat.format(forecast.metrics.mae)} note="Chronological holdout" tone="blue" />
            <MetricCard icon={<Activity />} label="Root mean square error" value={forecast.metrics.rmse === null ? "—" : numberFormat.format(forecast.metrics.rmse)} note="Chronological holdout" tone="mint" />
            <MetricCard icon={<TrendingUp />} label="Naive baseline MAE" value={forecast.metrics.baseline_mae === null ? "—" : numberFormat.format(forecast.metrics.baseline_mae)} note="Last observation holdout" tone="violet" />
            <MetricCard icon={<Activity />} label="MAPE" value={forecast.metrics.mape === null ? "—" : `${numberFormat.format(forecast.metrics.mape)}%`} note="Non-zero holdout values only" tone="amber" />
          </div>
          <div className="forecast-chart">
            <ResponsiveContainer width="100%" height={320}>
              <AreaChart data={chartData}>
                <defs><linearGradient id="forecastFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#719bff" stopOpacity={0.35} /><stop offset="100%" stopColor="#719bff" stopOpacity={0} /></linearGradient></defs>
                <CartesianGrid stroke="var(--grid)" strokeDasharray="3 5" vertical={false} />
                <XAxis dataKey="date" tick={{fill: "var(--muted)", fontSize: 10}} />
                <YAxis tick={{fill: "var(--muted)", fontSize: 11}} />
                <Tooltip contentStyle={{background: "var(--tooltip)", border: "1px solid var(--border)", borderRadius: 12}} />
                <Area dataKey="actual" name="Historical" stroke="#68e0c0" fill="transparent" connectNulls />
                <Area dataKey="predicted" name="Forecast" stroke="#719bff" fill="url(#forecastFill)" strokeDasharray="5 4" connectNulls />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          {forecast.caveat && <p className="caveat"><AlertTriangle size={15} />{forecast.caveat}</p>}
        </>
      ) : (
        <div className="empty-inline">
          <TrendingUp size={26} />
          <h3>{forecast?.reason ?? (selectedDataset ? "Choose a target and run a forecast." : "Select a dataset to begin.")}</h3>
          <p>At least 12 valid dated observations are required by the current baseline model.</p>
        </div>
      )}
    </section>
  );
}

export function AnomaliesPage() {
  const {notify, selectedDataset, selectedDatasetId, setSelectedDatasetId, datasets} = useDashboard();
  const [result, setResult] = useState<AnomalyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [threshold, setThreshold] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [contamination, setContamination] = useState(0.05);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    setResult(null);
    setThreshold(null);
    setSearch("");
  }, [selectedDatasetId]);

  const runDetection = async () => {
    if (!selectedDatasetId) {
      setError("Select a dataset before running anomaly detection.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response = await api.get<AnomalyResult>(`/datasets/${selectedDatasetId}/anomalies`, {
        params: {contamination},
      });
      setResult(response.data);
      const scores = (response.data.rows ?? []).map(row => row.score);
      setThreshold(scores.length ? Math.max(...scores) : null);
      if (!response.data.available) notify(response.data.reason ?? "The selected data is not ready for anomaly detection.", "info");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  };

  const rows = result?.rows ?? [];
  const scoreRange = rows.length ? {
    min: Math.min(...rows.map(row => row.score)),
    max: Math.max(...rows.map(row => row.score)),
  } : null;
  const rankedRows = useMemo(() => [...rows].sort((a, b) => a.score - b.score), [rows]);
  const rankByRow = new Map(rankedRows.map((row, index) => [row.row, index]));
  const filteredRows = rows.filter(row => {
    const matchesScore = threshold === null || row.score <= threshold;
    const matchesSearch = !search || JSON.stringify(row.values).toLowerCase().includes(search.toLowerCase());
    return matchesScore && matchesSearch;
  });
  const displayRows = filteredRows.map(row => ({
    row: row.row + 1,
    anomaly_score: row.score,
    severity: (rankByRow.get(row.row) ?? rows.length) < Math.ceil(rows.length * 0.25) ? "More extreme" : "Flagged",
    ...row.values,
  }));
  const columns = displayRows.length ? Object.keys(displayRows[0]) : ["row", "anomaly_score", "severity"];
  const exportAnomalyRows = async () => {
    if (!selectedDatasetId) return;
    setExporting(true);
    setError("");
    try {
      const response = await api.get(`/datasets/${selectedDatasetId}/anomalies/export`, {
        params: {contamination},
        responseType: "blob",
      });
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `dataset-${selectedDatasetId}-anomalies.csv`;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setExporting(false);
    }
  };

  return (
    <section className="panel">
      <div className="panel-head"><div><span className="eyebrow">MODEL-ASSISTED QUALITY SIGNALS</span><h3>Anomaly detection</h3><p className="subtle">Isolation Forest flags unusual multivariate records for review, not proof of error or fraud.</p></div></div>
      <div className="forecast-controls">
        <label className="field-control"><span>Dataset</span>
          <select value={selectedDatasetId ?? ""} onChange={event => setSelectedDatasetId(event.target.value ? Number(event.target.value) : null)}>
            <option value="">Select a dataset</option>
            {datasets.map(dataset => <option value={dataset.id} key={dataset.id}>{dataset.name}</option>)}
          </select>
        </label>
        <label className="field-control"><span>Sensitivity ({(contamination * 100).toFixed(0)}%)</span>
          <input
            type="range"
            min="0.01"
            max="0.2"
            step="0.01"
            value={contamination}
            onChange={event => setContamination(Number(event.target.value))}
          />
        </label>
        <button className="primary-btn" onClick={() => void runDetection()} disabled={busy || !selectedDataset}>
          <Target size={15} />{busy ? "Scanning…" : "Run detection"}
        </button>
      </div>
      <PageError message={error} />
      {result?.available ? (
        <>
          <div className="anomaly-summary">
            <div className="anomaly-count">{result.count ?? rows.length}<small>FLAGGED RECORDS</small></div>
            <div><b>{result.total ? (((result.count ?? 0) / result.total) * 100).toFixed(1) : "0.0"}% of records flagged</b><p className="subtle">Model sensitivity: {(((result.contamination ?? 0) * 100)).toFixed(0)}%</p></div>
            <button className="secondary-btn" onClick={() => void exportAnomalyRows()} disabled={exporting}>
              {exporting ? "Preparing CSV…" : "Download flagged records"}
            </button>
          </div>
          <div className="filter-toolbar">
            <label className="field-control"><span>Filter by score threshold</span>
              <input
                type="range"
                min={scoreRange?.min ?? 0}
                max={scoreRange?.max ?? 1}
                step="0.001"
                value={threshold ?? scoreRange?.max ?? 1}
                onChange={event => setThreshold(Number(event.target.value))}
                disabled={!scoreRange}
              />
            </label>
            <span className="subtle">{filteredRows.length} shown · lower scores are more atypical</span>
            <label className="search-control"><Search size={15} /><span className="sr-only">Search anomalies</span>
              <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search affected records…" />
            </label>
          </div>
          {result.note && <p className="caveat"><AlertTriangle size={15} />{result.note}</p>}
          <RecordsTable rows={displayRows} columns={columns} />
          {result.count && result.count > rows.length && <p className="subtle">Showing the first {rows.length} flagged records returned by the backend.</p>}
          <p className="subtle severity-note">“More extreme” ranks the lowest decision-function scores within this result; it is not a business risk classification.</p>
        </>
      ) : (
        <div className="empty-inline">
          <Target size={26} />
          <h3>{result?.reason ?? "Run the model to find unusual records."}</h3>
          <p>The existing detector needs at least 10 rows and one numeric column.</p>
        </div>
      )}
    </section>
  );
}

interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  provider: string | null;
  created_at: string;
}

interface Conversation {
  id: number;
  dataset_id: number | null;
  dataset_available: boolean;
  title: string;
  created_at: string;
  updated_at: string;
}

interface ConversationPage {
  items: Conversation[];
  total: number;
  offset: number;
  limit: number;
}

interface MessagePage {
  items: ChatMessage[];
  total: number;
  limit: number;
  has_more: boolean;
}

interface CopilotProviderStatus {
  provider: string;
  status: CopilotProviderState;
  message: string;
  checked_at: string | null;
  retry_after_seconds?: number | null;
}

type ConversationConfirmation =
  | {kind: "delete"; conversation: Conversation}
  | {kind: "clear"};

function conversationDateGroup(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Older";
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const weekAgo = new Date(today);
  weekAgo.setDate(weekAgo.getDate() - 7);
  if (date >= today) return "Today";
  if (date >= yesterday) return "Yesterday";
  if (date >= weekAgo) return "Previous 7 days";
  return "Older";
}

function retryWaitLabel(seconds: number) {
  if (seconds >= 60) {
    const minutes = Math.ceil(seconds / 60);
    return `${minutes} minute${minutes === 1 ? "" : "s"}`;
  }
  return `${seconds} second${seconds === 1 ? "" : "s"}`;
}

export function CopilotPage() {
  const {notify, selectedDataset, selectedDatasetId} = useDashboard();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationOffset, setConversationOffset] = useState(0);
  const [conversationTotal, setConversationTotal] = useState(0);
  const [conversationLoading, setConversationLoading] = useState(true);
  const [historySearch, setHistorySearch] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedConversationId, setSelectedConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [hasOlderMessages, setHasOlderMessages] = useState(false);
  const [olderMessagesLoading, setOlderMessagesLoading] = useState(false);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [retryMessageId, setRetryMessageId] = useState<number | null>(null);
  const [retryAllowed, setRetryAllowed] = useState(false);
  const [retryNotBefore, setRetryNotBefore] = useState<number | null>(null);
  const [retryClock, setRetryClock] = useState(Date.now());
  const [editingConversationId, setEditingConversationId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [confirmation, setConfirmation] = useState<ConversationConfirmation | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [copiedMessageId, setCopiedMessageId] = useState<number | null>(null);
  const [providerStatus, setProviderStatus] = useState<CopilotProviderStatus | null>(null);
  const chatBottomRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);
  const requestLockRef = useRef(false);

  const fetchConversations = useCallback(async (offset = 0) => {
    setConversationLoading(true);
    try {
      const response = await api.get<ConversationPage>("/copilot/conversations", {
        params: {search: searchTerm || undefined, offset, limit: 20},
      });
      setConversations(response.data.items);
      setConversationOffset(response.data.offset);
      setConversationTotal(response.data.total);
      setSelectedConversationId(current => (
        current !== null && response.data.items.some(item => item.id === current)
          ? current
          : response.data.items[0]?.id ?? null
      ));
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setConversationLoading(false);
    }
  }, [searchTerm]);

  const fetchMessages = useCallback(async (
    conversationId: number,
    beforeId?: number,
    signal?: AbortSignal,
  ) => {
    if (beforeId) setOlderMessagesLoading(true);
    else setMessagesLoading(true);
    try {
      const response = await api.get<MessagePage>(
        `/copilot/conversations/${conversationId}/messages`,
        {params: {limit: 50, before_id: beforeId}, signal},
      );
      if (beforeId) {
        setMessages(current => {
          const existingIds = new Set(current.map(message => message.id));
          return [
            ...response.data.items.filter(message => !existingIds.has(message.id)),
            ...current,
          ];
        });
      } else {
        setMessages(response.data.items);
        const latest = response.data.items[response.data.items.length - 1];
        setRetryMessageId(latest?.role === "user" ? latest.id : null);
        setRetryAllowed(false);
        setRetryNotBefore(null);
      }
      setHasOlderMessages(response.data.has_more);
    } catch (requestError) {
      if (!signal?.aborted) setError(errorMessage(requestError));
    } finally {
      if (!signal?.aborted) {
        setMessagesLoading(false);
        setOlderMessagesLoading(false);
      }
    }
  }, []);

  const refreshProviderStatus = useCallback(async () => {
    try {
      const response = await api.get<CopilotProviderStatus>("/copilot/status");
      setProviderStatus(response.data);
    } catch {
      setProviderStatus({
        provider: "unknown",
        status: "unavailable",
        message: "AI provider status could not be checked.",
        checked_at: null,
      });
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearchTerm(historySearch.trim());
      setConversationOffset(0);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [historySearch]);

  useEffect(() => {
    void fetchConversations(conversationOffset);
  }, [fetchConversations, conversationOffset]);

  useEffect(() => {
    void refreshProviderStatus();
  }, [refreshProviderStatus]);

  useEffect(() => {
    if (retryMessageId === null || !providerStatus) return;
    if (
      !retryAllowed
      && ["operational", "rate_limited", "temporarily_unavailable"].includes(providerStatus.status)
    ) {
      setRetryAllowed(true);
    }
    if (providerStatus.retry_after_seconds !== null && providerStatus.retry_after_seconds !== undefined && providerStatus.checked_at) {
      const checkedAt = Date.parse(providerStatus.checked_at);
      const retryAt = checkedAt + providerStatus.retry_after_seconds * 1000;
      if (Number.isFinite(retryAt) && retryAt > Date.now()) {
        setRetryNotBefore(current => current === null ? retryAt : Math.max(current, retryAt));
      }
    }
  }, [providerStatus, retryAllowed, retryMessageId]);

  useEffect(() => {
    if (retryNotBefore === null || retryNotBefore <= Date.now()) {
      if (retryNotBefore !== null) setRetryNotBefore(null);
      return;
    }
    const timer = window.setInterval(() => setRetryClock(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [retryNotBefore]);

  useEffect(() => {
    if (selectedConversationId === null) {
      setMessages([]);
      setRetryMessageId(null);
      setMessagesLoading(false);
      return;
    }
    setError("");
    autoScrollRef.current = true;
    const controller = new AbortController();
    void fetchMessages(selectedConversationId, undefined, controller.signal);
    return () => controller.abort();
  }, [fetchMessages, selectedConversationId]);

  useEffect(() => {
    if (autoScrollRef.current) {
      chatBottomRef.current?.scrollIntoView({behavior: "smooth", block: "end"});
    }
  }, [messages, busy]);

  const activeConversation = conversations.find(
    conversation => conversation.id === selectedConversationId,
  ) ?? null;
  const groupedConversations = useMemo(() => {
    const groups: Record<string, Conversation[]> = {
      Today: [],
      Yesterday: [],
      "Previous 7 days": [],
      Older: [],
    };
    conversations.forEach(conversation => {
      groups[conversationDateGroup(conversation.updated_at)].push(conversation);
    });
    return groups;
  }, [conversations]);

  const startConversation = async () => {
    if (!selectedDatasetId) {
      setError("Select a dataset before starting a Copilot conversation.");
      return;
    }
    setError("");
    try {
      const response = await api.post<Conversation>("/copilot/conversations", {
        dataset_id: selectedDatasetId,
      });
      setHistorySearch("");
      setSearchTerm("");
      setMessages([]);
      setQuestion("");
      setRetryMessageId(null);
      setRetryAllowed(false);
      setRetryNotBefore(null);
      setConversations(current => [
        response.data,
        ...current.filter(item => item.id !== response.data.id),
      ].slice(0, 20));
      setConversationOffset(0);
      setConversationTotal(current => current + 1);
      setSelectedConversationId(response.data.id);
    } catch (requestError) {
      setError(errorMessage(requestError));
    }
  };

  const sendMessage = async (event: FormEvent) => {
    event.preventDefault();
    if (!activeConversation || !question.trim() || busy || requestLockRef.current || retryMessageId !== null) return;
    const content = question.trim();
    let savedUserMessage: ChatMessage | null = null;
    requestLockRef.current = true;
    setBusy(true);
    setError("");
    try {
      const appended = await api.post<ChatMessage>(
        `/copilot/conversations/${activeConversation.id}/messages`,
        {content},
      );
      savedUserMessage = appended.data;
      setMessages(current => [...current, appended.data]);
      setQuestion("");
      autoScrollRef.current = true;
      void fetchConversations(0);
      const response = await api.post<ChatMessage>(
        `/copilot/conversations/${activeConversation.id}/messages/${appended.data.id}/answer`,
      );
      setMessages(current => [...current, response.data]);
      setRetryMessageId(null);
      setRetryAllowed(false);
      setRetryNotBefore(null);
      void fetchConversations(0);
    } catch (requestError) {
      if (savedUserMessage) {
        setRetryMessageId(savedUserMessage.id);
        const retryInfo = errorRetryInfo(requestError);
        setRetryAllowed(retryInfo.retryable);
        setRetryNotBefore(
          retryInfo.retryable && retryInfo.retryAfterSeconds !== null && retryInfo.retryAfterSeconds > 0
            ? Date.now() + retryInfo.retryAfterSeconds * 1000
            : null,
        );
      } else {
        void fetchMessages(activeConversation.id);
      }
      setError(errorMessage(requestError));
    } finally {
      requestLockRef.current = false;
      setBusy(false);
      void refreshProviderStatus();
    }
  };

  const retryMessage = async () => {
    if (!activeConversation || retryMessageId === null || busy || requestLockRef.current || !retryAllowed) return;
    requestLockRef.current = true;
    setBusy(true);
    setError("");
    try {
      const response = await api.post<ChatMessage>(
        `/copilot/conversations/${activeConversation.id}/messages/${retryMessageId}/answer`,
      );
      setMessages(current => current.some(message => message.id === response.data.id)
        ? current
        : [...current, response.data]);
      setRetryMessageId(null);
      setRetryAllowed(false);
      setRetryNotBefore(null);
      void fetchConversations(0);
    } catch (requestError) {
      setError(errorMessage(requestError));
      const retryInfo = errorRetryInfo(requestError);
      setRetryAllowed(retryInfo.retryable);
      setRetryNotBefore(
        retryInfo.retryable && retryInfo.retryAfterSeconds !== null && retryInfo.retryAfterSeconds > 0
          ? Date.now() + retryInfo.retryAfterSeconds * 1000
          : null,
      );
    } finally {
      requestLockRef.current = false;
      setBusy(false);
      void refreshProviderStatus();
    }
  };

  const saveRename = async (conversation: Conversation) => {
    try {
      const response = await api.patch<Conversation>(
        `/copilot/conversations/${conversation.id}`,
        {title: renameValue},
      );
      setConversations(current => current.map(item => (
        item.id === conversation.id ? response.data : item
      )));
      setEditingConversationId(null);
      await fetchConversations(0);
      notify("Conversation renamed.", "success");
    } catch (requestError) {
      setError(errorMessage(requestError));
      notify(errorMessage(requestError), "error");
    }
  };

  const confirmDeletion = async () => {
    if (!confirmation) return;
    setDeleting(true);
    try {
      if (confirmation.kind === "delete") {
        await api.delete(`/copilot/conversations/${confirmation.conversation.id}`);
        if (selectedConversationId === confirmation.conversation.id) {
          setSelectedConversationId(null);
          setMessages([]);
        }
        notify("Conversation and its messages deleted. Dataset and account records were not changed.", "success");
      } else {
        const response = await api.delete<{deleted: number}>("/copilot/conversations", {
          data: {confirmation: "CLEAR"},
        });
        setSelectedConversationId(null);
        setMessages([]);
        setRetryMessageId(null);
        setRetryAllowed(false);
        setRetryNotBefore(null);
        notify(`${response.data.deleted} Copilot conversation(s) cleared. Datasets and account records were not changed.`, "success");
      }
      setConfirmation(null);
      await fetchConversations(0);
    } catch (requestError) {
      setError(errorMessage(requestError));
      notify(errorMessage(requestError), "error");
    } finally {
      setDeleting(false);
    }
  };

  const copyMessage = async (message: ChatMessage) => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopiedMessageId(message.id);
      window.setTimeout(
        () => setCopiedMessageId(current => current === message.id ? null : current),
        1500,
      );
    } catch {
      setError("Could not copy this response. Check browser clipboard permissions.");
    }
  };

  const prompts = [
    "Summarize the computed profile for leadership.",
    "Which measured fields have the highest aggregates?",
    "What data quality issues should I inspect?",
    "What should I investigate next in this dataset?",
  ];

  return (
    <div className="copilot-workspace">
      <aside className="panel copilot-history" aria-label="Copilot conversations">
        <div className="copilot-history-head">
          <div><span className="eyebrow">YOUR WORKSPACE</span><h3>Conversations</h3></div>
          <button className="icon-btn" onClick={() => void startConversation()} disabled={!selectedDatasetId} aria-label="Start a new conversation" title={selectedDataset ? `New conversation about ${selectedDataset.name}` : "Select a dataset first"}>
            <Plus size={17} />
          </button>
        </div>
        <label className="search-control copilot-search">
          <Search size={15} /><span className="sr-only">Search conversations</span>
          <input value={historySearch} onChange={event => setHistorySearch(event.target.value)} placeholder="Search conversations…" />
        </label>
        {!selectedDatasetId && <p className="copilot-history-hint">Select a dataset to start a new conversation.</p>}
        {conversationLoading && !conversations.length && <div className="skeleton copilot-history-skeleton" role="status" />}
        <div className="copilot-history-list">
          {Object.entries(groupedConversations).map(([group, items]) => items.length > 0 && (
            <section key={group} aria-label={group}>
              <span className="eyebrow copilot-date-group">{group}</span>
              {items.map(conversation => (
                <div className={`copilot-history-item ${selectedConversationId === conversation.id ? "active" : ""}`} key={conversation.id}>
                  {editingConversationId === conversation.id ? (
                    <form className="copilot-rename-form" onSubmit={event => {event.preventDefault(); void saveRename(conversation);}}>
                      <input aria-label="Conversation title" value={renameValue} maxLength={160} onChange={event => setRenameValue(event.target.value)} autoFocus />
                      <button className="icon-btn" type="submit" aria-label="Save conversation name"><Check size={14} /></button>
                    </form>
                  ) : (
                    <>
                      <button className="copilot-history-select" onClick={() => setSelectedConversationId(conversation.id)} aria-current={selectedConversationId === conversation.id ? "page" : undefined}>
                        <b>{conversation.title}</b>
                        <small>{new Date(conversation.updated_at).toLocaleString()}</small>
                      </button>
                      <div className="copilot-history-actions">
                        <button className="icon-btn" onClick={() => {setEditingConversationId(conversation.id); setRenameValue(conversation.title);}} aria-label={`Rename ${conversation.title}`} title="Rename"><Pencil size={13} /></button>
                        <button className="icon-btn danger" onClick={() => setConfirmation({kind: "delete", conversation})} aria-label={`Delete ${conversation.title}`} title="Delete"><Trash2 size={13} /></button>
                      </div>
                    </>
                  )}
                </div>
              ))}
            </section>
          ))}
          {!conversationLoading && !conversations.length && (
            <div className="copilot-history-empty">
              <p>{historySearch ? "No conversations match this search." : "Your saved conversations will appear here."}</p>
            </div>
          )}
        </div>
        <div className="copilot-history-footer">
          <button className="text-button" onClick={() => setConfirmation({kind: "clear"})} disabled={conversationTotal === 0}>Clear all history</button>
          <div className="copilot-history-pagination">
            <button className="icon-btn" onClick={() => void fetchConversations(Math.max(0, conversationOffset - 20))} disabled={conversationOffset <= 0 || conversationLoading} aria-label="Previous conversations"><ArrowDown size={13} className="rotate-90" /></button>
            <small>{conversationTotal ? `${conversationOffset + 1}–${Math.min(conversationOffset + 20, conversationTotal)} of ${conversationTotal}` : "0 conversations"}</small>
            <button className="icon-btn" onClick={() => void fetchConversations(conversationOffset + 20)} disabled={conversationOffset + 20 >= conversationTotal || conversationLoading} aria-label="Next conversations"><ArrowUp size={13} className="rotate-90" /></button>
          </div>
        </div>
      </aside>

      <section className="panel copilot-main">
        <div className="copilot-head">
          <div className="copilot-avatar"><Sparkles /></div>
          <div>
            <span className="eyebrow">INTELLIBIZ INTELLIGENCE</span>
            <h3>{activeConversation?.title ?? "Ask beyond the numbers."}</h3>
            <p className="subtle">{activeConversation?.dataset_available
              ? `Conversation context: dataset #${activeConversation.dataset_id}`
              : activeConversation
                ? "The linked dataset is unavailable; saved history remains accessible."
                : "Start a conversation using a selected dataset."}</p>
          </div>
          <span className={`online-label provider-${providerStatus?.status ?? "checking"}`} role="status" title={providerStatus?.message ?? "Checking AI provider status."}>
            <i /> {copilotProviderStatusLabel(providerStatus?.status)}
          </span>
        </div>
        <p className="copilot-local-label" role="status">Local computed analysis available · no AI credits used</p>
        {providerStatus && providerStatus.status !== "operational" && (
          <p className="copilot-provider-notice" role="status">
            {providerStatus.message}
            {providerStatus.retry_after_seconds != null && providerStatus.retry_after_seconds > 0
              ? ` Retry after ${retryWaitLabel(Math.ceil(providerStatus.retry_after_seconds))}.`
              : ""}
          </p>
        )}
        <PageError message={error} />
        <div className="chat-window" onScroll={event => {
          const element = event.currentTarget;
          autoScrollRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 120;
        }} aria-live="polite">
          {hasOlderMessages && activeConversation && (
            <button className="text-button load-older-messages" onClick={() => {
              const firstMessageId = messages[0]?.id;
              if (firstMessageId) {
                autoScrollRef.current = false;
                void fetchMessages(activeConversation.id, firstMessageId);
              }
            }} disabled={olderMessagesLoading}>
              {olderMessagesLoading ? "Loading earlier messages…" : "Load earlier messages"}
            </button>
          )}
          {messagesLoading && !messages.length && <div className="skeleton chat-loading" role="status" />}
          {!messages.length && !messagesLoading && (
            <div className="chat-welcome">
              <div className="welcome-spark"><Sparkles size={22} /></div>
              <h2>{activeConversation ? "Where should we look?" : "Your intelligence workspace"}</h2>
              <p>{activeConversation?.dataset_available
                ? "Questions are answered using computed information from this conversation’s dataset. Source rows are not sent to the provider."
                : activeConversation
                  ? "This conversation’s source dataset was deleted. Its conversation history is preserved."
                  : "Start a conversation to save your questions and AI answers securely to your account."}</p>
              {activeConversation?.dataset_available && (
                <div className="prompt-grid">{prompts.map(prompt => (
                  <button key={prompt} onClick={() => setQuestion(prompt)}>{prompt}<span>↗</span></button>
                ))}</div>
              )}
              {!activeConversation && selectedDatasetId && (
                <button className="primary-btn" onClick={() => void startConversation()}>Start a conversation</button>
              )}
            </div>
          )}
          {messages.map(message => (
            <div className={`chat-message ${message.role}`} key={message.id}>
              <div className="chat-bubble">
                <p>{message.content}</p>
                {message.provider && <small className="message-source">
                  {message.provider === "local_analytics"
                    ? "Local computed analysis · not AI-generated"
                    : `Source: ${message.provider}`}
                </small>}
                <small className="chat-message-time">{new Date(message.created_at).toLocaleTimeString()}</small>
                {message.role === "assistant" && (
                  <button className="copy-message" onClick={() => void copyMessage(message)} aria-label="Copy response" title="Copy response">
                    <Copy size={13} /> {copiedMessageId === message.id ? "Copied" : "Copy"}
                  </button>
                )}
              </div>
            </div>
          ))}
          {busy && <div className="chat-message assistant"><div className="chat-bubble typing" role="status"><i /><i /><i /></div></div>}
          <div ref={chatBottomRef} />
        </div>
        {retryMessageId !== null && activeConversation?.dataset_available && (
          <div className="copilot-retry-notice" role="alert">
            <span>{retryAllowed
              ? "Your question is saved. Retry will reuse it without adding a duplicate message."
              : "Your question is saved, but this provider restriction is not eligible for retry. Start a new conversation to continue with local computed analysis."}
              {retryNotBefore !== null && retryNotBefore > retryClock
                ? ` Retry available in ${retryWaitLabel(Math.ceil((retryNotBefore - retryClock) / 1000))}.`
                : ""}
            </span>
            {retryAllowed && (
              <button
                className="secondary-btn"
                onClick={() => void retryMessage()}
                disabled={busy || (retryNotBefore !== null && retryNotBefore > retryClock)}
              >
                Retry response
              </button>
            )}
          </div>
        )}
        <form className="chat-compose" onSubmit={sendMessage}>
          <input
            aria-label="Ask the AI Copilot"
            placeholder="Ask a question about this dataset…"
            value={question}
            onChange={event => setQuestion(event.target.value)}
            maxLength={1200}
            disabled={busy || messagesLoading || !activeConversation?.dataset_available || retryMessageId !== null}
          />
          <button className="send-btn" disabled={busy || messagesLoading || !activeConversation?.dataset_available || retryMessageId !== null || !question.trim()} aria-label="Send question">
            <Sparkles size={16} />
          </button>
        </form>
        <div className="copilot-disclaimer"><ShieldCheck size={13} /> Only computed dataset facts and a bounded recent conversation are sent. Failed questions remain saved.</div>
      </section>

      <aside className="copilot-side panel">
        <span className="eyebrow">CONTEXT WINDOW</span><h3>What is provided</h3>
        <div className="context-card"><Database size={17} /><div><b>{activeConversation?.dataset_available
          ? (selectedDataset?.id === activeConversation.dataset_id ? selectedDataset.name : `Dataset #${activeConversation.dataset_id}`)
          : "No available dataset"}</b><small>{activeConversation?.dataset_available ? "Owned dataset; profile only" : "History remains separate"}</small></div>{activeConversation?.dataset_available && <Check size={15} className="mint" />}</div>
        <div className="context-card"><BarChart3 size={17} /><div><b>Computed summary</b><small>Source rows excluded</small></div><Check size={15} className="mint" /></div>
        <div className="side-note"><Sparkles size={17} /><b>Evidence first.</b><p>Answers are grounded in the computed profile. Validate important decisions against source records.</p></div>
      </aside>

      {confirmation && (
        <div className="copilot-confirm-backdrop">
          <section className="panel copilot-confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="copilot-confirm-title" aria-describedby="copilot-confirm-description">
            <span className="eyebrow">CONFIRM DELETION</span>
            <h3 id="copilot-confirm-title">{confirmation.kind === "clear" ? "Clear all Copilot history?" : "Delete this conversation?"}</h3>
            <p id="copilot-confirm-description">
              {confirmation.kind === "clear"
                ? "This permanently deletes all your conversations and messages. Uploaded datasets, your account, and security records remain untouched."
                : "This permanently deletes the selected conversation and its messages. Uploaded datasets, your account, and security records remain untouched."}
            </p>
            <div className="copilot-confirm-actions">
              <button className="secondary-btn" onClick={() => setConfirmation(null)} disabled={deleting}>Cancel</button>
              <button className="danger-btn" onClick={() => void confirmDeletion()} disabled={deleting}>{deleting ? "Deleting…" : "Delete"}</button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

export function DatasetsPage() {
  const {datasets, datasetsError, datasetsLoading, notify, refreshDatasets, selectedDatasetId, setSelectedDatasetId} = useDashboard();
  const navigate = useNavigate();

  const deleteDataset = async (dataset: Dataset) => {
    if (!window.confirm(`Permanently delete "${dataset.name}" and its stored file?`)) return;
    try {
      await api.delete(`/datasets/${dataset.id}`);
      if (selectedDatasetId === dataset.id) setSelectedDatasetId(null);
      await refreshDatasets();
      notify(`${dataset.name} was deleted.`, "success");
    } catch (error) {
      notify(errorMessage(error), "error");
    }
  };

  return (
    <section className="panel">
      <div className="panel-head"><div><span className="eyebrow">YOUR DATA ASSETS</span><h3>Dataset library</h3></div>
        <button className="secondary-btn" onClick={() => void refreshDatasets().catch(error => notify(errorMessage(error), "error"))} disabled={datasetsLoading}>
          <RefreshCw size={14} className={datasetsLoading ? "spin" : ""} /> Refresh list
        </button>
      </div>
      <PageError message={datasetsError} />
      {datasets.map(dataset => (
        <article className="library-row" key={dataset.id}>
          <div className="file-icon"><FileSpreadsheet size={18} /></div>
          <div className="library-name">
            <b>{dataset.name}</b>
            <small>{dataset.rows.toLocaleString()} rows · {dataset.columns} columns · {formatBytes(dataset.size)}</small>
            <small>Uploaded {new Date(dataset.created_at).toLocaleString()}</small>
          </div>
          <span className="dataset-status"><i /> Processed</span>
          <button className="secondary-btn" onClick={() => {setSelectedDatasetId(dataset.id); navigate(`/datasets/${dataset.id}`);}}>Open details</button>
          <button className="icon-btn danger" onClick={() => void deleteDataset(dataset)} aria-label={`Delete ${dataset.name}`}><span aria-hidden="true">×</span></button>
        </article>
      ))}
      {!datasets.length && !datasetsLoading && <div className="empty-inline"><Database size={25} /><h3>No datasets yet</h3><p>Upload a CSV or XLSX file to create your first dataset.</p></div>}
    </section>
  );
}

export function DatasetDetailsPage() {
  const {datasetId} = useParams();
  const {datasets, setSelectedDatasetId} = useDashboard();
  const numericId = Number(datasetId);
  const dataset = datasets.find(item => item.id === numericId);
  const [analysis, setAnalysis] = useState<DatasetAnalysis | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!Number.isInteger(numericId) || numericId <= 0) {
      setError("Invalid dataset identifier.");
      setLoading(false);
      return;
    }
    setSelectedDatasetId(numericId);
    const controller = new AbortController();
    api.get<DatasetAnalysis>(`/datasets/${numericId}/analysis`, {signal: controller.signal})
      .then(response => setAnalysis(response.data))
      .catch(requestError => {
        if (!controller.signal.aborted) setError(errorMessage(requestError));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [numericId, setSelectedDatasetId]);

  if (loading) return <div className="skeleton table-skeleton" role="status" />;
  if (error || !dataset || !analysis) return <PageError message={error || "Dataset details are unavailable."} />;
  return (
    <>
      <section className="panel">
        <div className="panel-head"><div><span className="eyebrow">DATASET DETAILS</span><h3>{dataset.name}</h3></div><span className="fresh-tag"><span className="pulse-dot" /> PROCESSED</span></div>
        <div className="dataset-detail-grid">
          <MetricCard icon={<Database />} label="Records" value={dataset.rows.toLocaleString()} note="Validated rows" />
          <MetricCard icon={<BarChart3 />} label="Columns" value={String(dataset.columns)} note="Fields detected" tone="blue" />
          <MetricCard icon={<FileSpreadsheet />} label="File size" value={formatBytes(dataset.size)} note="Stored dataset" tone="violet" />
        </div>
        <p className="subtle">Uploaded {new Date(dataset.created_at).toLocaleString()}</p>
        <div className="heading-actions details-actions">
          <Link className="primary-btn" to="/data-explorer">Explore records</Link>
          <Link className="secondary-btn" to="/forecast">Open forecast studio</Link>
        </div>
      </section>
      <section className="panel">
        <div className="panel-head"><div><span className="eyebrow">FIELD PROFILE</span><h3>Column quality</h3></div></div>
        <div className="column-grid">{analysis.profile.quality.map(item => (
          <article className="column-card" key={item.column}><b>{item.column}</b><span>{item.dtype}</span><small>{item.unique} unique · {item.missing} missing ({item.missing_pct}%)</small></article>
        ))}</div>
      </section>
      <section className="panel"><div className="panel-head"><div><span className="eyebrow">SAMPLE ROWS</span><h3>Stored preview</h3></div></div>
        <RecordsTable rows={analysis.profile.preview} columns={analysis.profile.column_names.slice(0, 10)} />
      </section>
    </>
  );
}

export function SettingsPage() {
  const {user, logout} = useAuth();
  const {theme, setTheme} = useDashboard();
  const location = useLocation();
  const navigate = useNavigate();
  const profileOnly = location.pathname.endsWith("/profile");

  const signOut = async () => {
    if (!window.confirm("Sign out of your IntelliBiz workspace?")) return;
    let notice = "You have been signed out.";
    let noticeKind = "success";
    try {
      await logout();
    } catch (error) {
      notice = `Your local session was cleared, but the server could not confirm token revocation. ${errorMessage(error)}`;
      noticeKind = "error";
    }
    navigate("/login", {replace: true, state: {notice, noticeKind}});
  };

  return (
    <div className="settings-grid">
      <section className="panel">
        <div className="panel-head"><div><span className="eyebrow">ACCOUNT</span><h3>{profileOnly ? "Profile" : "Account settings"}</h3></div><ShieldCheck className="mint" size={18} /></div>
        <div className="settings-field"><span>Full name</span><b>{user?.full_name ?? "—"}</b></div>
        <div className="settings-field"><span>Email address</span><b>{user?.email ?? "—"}</b></div>
        <p className="subtle">Profile edits are not available yet. These values are read from your authenticated account.</p>
      </section>
      <section className="panel">
        <div className="panel-head"><div><span className="eyebrow">PREFERENCES</span><h3>Appearance</h3></div></div>
        <label className="field-control"><span>Color theme</span>
          <select value={theme} onChange={event => setTheme(event.target.value as "dark" | "light")}>
            <option value="dark">Dark</option>
            <option value="light">Light</option>
          </select>
        </label>
        <p className="subtle">Your preference is stored in this browser.</p>
      </section>
      <section className="panel">
        <div className="panel-head"><div><span className="eyebrow">SECURITY</span><h3>Signed-in session</h3></div><ShieldCheck className="mint" size={18} /></div>
        <div className="security-row"><Check size={16} /><span>JWT-authenticated requests</span></div>
        <div className="security-row"><Check size={16} /><span>Passwords are hashed server-side with bcrypt</span></div>
        <p className="subtle">Your session is validated against the API on page load. Sign out to clear this browser’s token.</p>
        <button className="secondary-btn danger" onClick={() => void signOut()}>Log out</button>
      </section>
    </div>
  );
}

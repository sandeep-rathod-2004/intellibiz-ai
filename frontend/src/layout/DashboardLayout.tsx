import {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {AnimatePresence, motion} from "framer-motion";
import {
  AlertTriangle, BrainCircuit, Bell, ChevronDown, Database, Download,
  FileSpreadsheet, LayoutDashboard, LogOut, Menu, Settings, ShieldCheck,
  Sparkles, TrendingUp, Upload, X,
} from "lucide-react";
import {Link, NavLink, Outlet, useLocation, useNavigate} from "react-router-dom";
import {api, errorMessage} from "../lib/api";
import {useAuth} from "../lib/auth";
import type {DashboardOutletContext, ToastKind} from "../lib/dashboard";
import type {Dataset, DatasetAnalysis} from "../types";

const navigation = [
  {label: "Overview", path: "/overview", icon: LayoutDashboard},
  {label: "Data explorer", path: "/data-explorer", icon: Database},
  {label: "Forecast", path: "/forecast", icon: TrendingUp},
  {label: "Anomalies", path: "/anomalies", icon: AlertTriangle},
  {label: "AI copilot", path: "/copilot", icon: Sparkles},
];

const titleByPath: Record<string, string> = {
  "/overview": "Overview",
  "/data-explorer": "Data explorer",
  "/forecast": "Forecast",
  "/anomalies": "Anomalies",
  "/copilot": "AI copilot",
  "/datasets": "Datasets",
  "/settings": "Settings",
  "/settings/profile": "Account profile",
};

interface Toast {
  id: number;
  message: string;
  kind: ToastKind;
}

function initials(name?: string) {
  return name?.trim().split(/\s+/).slice(0, 2).map(part => part[0]).join("").toUpperCase() || "U";
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Date unavailable" : date.toLocaleString();
}

export default function DashboardLayout() {
  const {user, logout} = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetsLoading, setDatasetsLoading] = useState(true);
  const [datasetsError, setDatasetsError] = useState("");
  const [selectedDatasetId, setSelectedDatasetId] = useState<number | null>(null);
  const [analysis, setAnalysis] = useState<DatasetAnalysis | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState("");
  const [analysisAttempt, setAnalysisAttempt] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">(
    () => localStorage.getItem("ib_theme") === "light" ? "light" : "dark",
  );
  const [toast, setToast] = useState<Toast | null>(null);
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const workspaceRef = useRef<HTMLDivElement>(null);
  const notificationsRef = useRef<HTMLDivElement>(null);
  const profileRef = useRef<HTMLDivElement>(null);
  const toastId = useRef(0);

  const notify = useCallback((message: string, kind: ToastKind = "info") => {
    toastId.current += 1;
    setToast({id: toastId.current, message, kind});
  }, []);

  const refreshDatasets = useCallback(async () => {
    setDatasetsLoading(true);
    setDatasetsError("");
    try {
      const response = await api.get<Dataset[]>("/datasets");
      setDatasets(response.data);
      setSelectedDatasetId(current =>
        response.data.some(dataset => dataset.id === current)
          ? current
          : response.data[0]?.id ?? null,
      );
    } catch (error) {
      const message = errorMessage(error);
      setDatasetsError(message);
      throw error;
    } finally {
      setDatasetsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshDatasets().catch(() => undefined);
  }, [refreshDatasets]);

  useEffect(() => {
    localStorage.setItem("ib_theme", theme);
  }, [theme]);

  useEffect(() => {
    if (!selectedDatasetId) {
      setAnalysis(null);
      setAnalysisError("");
      setAnalysisLoading(false);
      return;
    }
    const controller = new AbortController();
    setAnalysisLoading(true);
    setAnalysisError("");
    setAnalysis(null);
    api.get<DatasetAnalysis>(`/datasets/${selectedDatasetId}/analysis`, {signal: controller.signal})
      .then(response => setAnalysis(response.data))
      .catch(error => {
        if (!controller.signal.aborted) setAnalysisError(errorMessage(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setAnalysisLoading(false);
      });
    return () => controller.abort();
  }, [selectedDatasetId, analysisAttempt]);

  const retryAnalysis = useCallback(() => {
    setAnalysisAttempt(attempt => attempt + 1);
  }, []);

  useEffect(() => {
    const routeState = location.state as {notice?: unknown; noticeKind?: unknown} | null;
    if (typeof routeState?.notice !== "string") return;
    notify(routeState.notice, routeState.noticeKind === "error" ? "error" : "success");
    navigate(location.pathname, {replace: true, state: null});
  }, [location.key, location.pathname, location.state, navigate, notify]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setWorkspaceOpen(false);
        setNotificationsOpen(false);
        setProfileOpen(false);
        setMobileOpen(false);
      }
    };
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!workspaceRef.current?.contains(target)) setWorkspaceOpen(false);
      if (!notificationsRef.current?.contains(target)) setNotificationsOpen(false);
      if (!profileRef.current?.contains(target)) setProfileOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timeout = window.setTimeout(() => setToast(current => current?.id === toast.id ? null : current), 4500);
    return () => window.clearTimeout(timeout);
  }, [toast]);

  const selectedDataset = useMemo(
    () => datasets.find(dataset => dataset.id === selectedDatasetId) ?? null,
    [datasets, selectedDatasetId],
  );

  const handleUpload: DashboardOutletContext["handleUpload"] = async event => {
    const input = event.currentTarget;
    const file = input.files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    setUploading(true);
    try {
      const response = await api.post<Dataset>("/datasets/upload", formData);
      await refreshDatasets();
      setSelectedDatasetId(response.data.id);
      notify(`${response.data.name} was uploaded and processed.`, "success");
      navigate("/overview");
    } catch (error) {
      notify(errorMessage(error), "error");
    } finally {
      setUploading(false);
      input.value = "";
    }
  };

  const downloadSample = useCallback(async () => {
    try {
      const response = await api.get("/samples/retail-sales", {responseType: "blob"});
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "retail_sales.csv";
      anchor.click();
      URL.revokeObjectURL(url);
      notify("Sample dataset downloaded. Upload it to explore the data.", "success");
    } catch (error) {
      notify(errorMessage(error), "error");
    }
  }, [notify]);

  const exportReport = async () => {
    if (!selectedDataset) {
      notify("Select a dataset before exporting a report.", "info");
      return;
    }
    setExporting(true);
    try {
      const response = await api.get(`/datasets/${selectedDataset.id}/report`, {responseType: "blob"});
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `intellibiz-report-${selectedDataset.id}.pdf`;
      anchor.click();
      URL.revokeObjectURL(url);
      notify("Report downloaded.", "success");
    } catch (error) {
      notify(errorMessage(error), "error");
    } finally {
      setExporting(false);
    }
  };

  const handleLogout = async () => {
    if (!window.confirm("Sign out of your IntelliBiz workspace?")) return;
    let notice = "You have been signed out.";
    let noticeKind: ToastKind = "success";
    try {
      await logout();
    } catch (error) {
      notice = `Your local session was cleared, but the server could not confirm token revocation. ${errorMessage(error)}`;
      noticeKind = "error";
    }
    setDatasets([]);
    setSelectedDatasetId(null);
    setAnalysis(null);
    navigate("/login", {replace: true, state: {notice, noticeKind}});
  };

  if (!user) return <div className="session-state" role="status">Loading your account…</div>;

  const context: DashboardOutletContext = {
    user,
    datasets,
    datasetsLoading,
    datasetsError,
    selectedDataset,
    selectedDatasetId,
    setSelectedDatasetId,
    analysis,
    analysisLoading,
    analysisError,
    retryAnalysis,
    refreshDatasets,
    handleUpload,
    downloadSample,
    notify,
    theme,
    setTheme,
  };
  const pageTitle =
    titleByPath[location.pathname] ??
    (location.pathname.startsWith("/datasets/") ? "Dataset details" : "IntelliBiz AI");

  return (
    <div className={`app-shell ${theme === "light" ? "light" : ""}`}>
      {mobileOpen && <button className="mobile-overlay" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}
      <aside className={`sidebar ${mobileOpen ? "show" : ""}`}>
        <Link className="brand" to="/overview" aria-label="IntelliBiz AI overview">
          <span className="brand-mark"><BrainCircuit size={22} /></span>
          <span>intellibiz<span className="mint">.</span></span>
        </Link>

        <div className="workspace-wrap" ref={workspaceRef}>
          <button
            className="workspace-trigger"
            aria-expanded={workspaceOpen}
            aria-haspopup="true"
            onClick={() => setWorkspaceOpen(open => !open)}
          >
            <span className="workspace-label">WORKSPACE</span>
            <ChevronDown size={13} />
          </button>
          <button className="workspace" onClick={() => setWorkspaceOpen(open => !open)} aria-expanded={workspaceOpen}>
            <span className="workspace-avatar">{initials(user.full_name)}</span>
            <span className="workspace-copy"><b>{user.full_name}</b><small>Personal workspace</small></span>
            <ChevronDown size={15} />
          </button>
          <AnimatePresence>
            {workspaceOpen && (
              <motion.div className="popover workspace-popover" initial={{opacity: 0, y: -5}} animate={{opacity: 1, y: 0}} exit={{opacity: 0, y: -5}}>
                <b className="popover-title">Your datasets</b>
                {datasets.length ? datasets.slice(0, 6).map(dataset => (
                  <button
                    className="popover-row"
                    key={dataset.id}
                    onClick={() => {
                      setSelectedDatasetId(dataset.id);
                      setWorkspaceOpen(false);
                    }}
                  >
                    <Database size={14} />
                    <span>{dataset.name}</span>
                    {dataset.id === selectedDatasetId && <span className="selected-mark">Selected</span>}
                  </button>
                )) : <p className="popover-empty">Upload a dataset to begin.</p>}
                <Link className="popover-link" to="/datasets" onClick={() => setWorkspaceOpen(false)}>Manage datasets</Link>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <div className="nav-label">ANALYTICS</div>
        <nav aria-label="Analytics">
          {navigation.map(item => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.path}
                to={item.path}
                onClick={() => setMobileOpen(false)}
                className={({isActive}) => `nav-item ${isActive ? "selected" : ""}`}
              >
                <Icon size={17} />{item.label}
                {item.label === "AI copilot" && <span className="nav-new">AI</span>}
              </NavLink>
            );
          })}
        </nav>
        <div className="nav-label space-top">MANAGE</div>
        <nav aria-label="Workspace management">
          <NavLink to="/datasets" onClick={() => setMobileOpen(false)} className={({isActive}) => `nav-item ${isActive || location.pathname.startsWith("/datasets/") ? "selected" : ""}`}>
            <FileSpreadsheet size={17} />Datasets
          </NavLink>
          <NavLink to="/settings" onClick={() => setMobileOpen(false)} className={({isActive}) => `nav-item ${isActive || location.pathname.startsWith("/settings/") ? "selected" : ""}`}>
            <Settings size={17} />Settings
          </NavLink>
        </nav>

        <div className="sidebar-bottom">
          <div className="upgrade-card">
            <ShieldCheck size={17} className="mint" />
            <b>Private workspace</b>
            <p>Your datasets are available only to your signed-in account.</p>
            <span>SECURE DATA ACCESS</span>
          </div>
          <button className="profile-row" onClick={() => navigate("/settings/profile")}>
            <span className="avatar">{initials(user.full_name)}</span>
            <span className="profile-copy"><b>{user.full_name}</b><small>{user.email}</small></span>
            <LogOut size={16} />
          </button>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <button className="icon-btn mobile-menu" aria-label="Open navigation" onClick={() => setMobileOpen(open => !open)}>
            <Menu size={19} />
          </button>
          <div className="crumb">Workspace <span>/</span> <b>{pageTitle}</b></div>
          <div className="top-actions">
            <div className="status-pill" role="status">
              <span className={`pulse-dot ${datasetsError ? "status-error" : ""}`} />
              {datasetsLoading ? "Checking data API…" : datasetsError ? "Data API connection issue" : "Data API connected"}
            </div>
            <label className="top-dataset-select">
              <span className="sr-only">Active dataset</span>
              <select value={selectedDatasetId ?? ""} onChange={event => setSelectedDatasetId(event.target.value ? Number(event.target.value) : null)}>
                <option value="">No dataset</option>
                {datasets.map(dataset => <option value={dataset.id} key={dataset.id}>{dataset.name}</option>)}
              </select>
            </label>
            <button className="icon-btn" onClick={() => setTheme(value => value === "dark" ? "light" : "dark")} title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} aria-label="Toggle theme">
              ◐
            </button>
            <div className="popover-anchor" ref={notificationsRef}>
              <button className="icon-btn" onClick={() => setNotificationsOpen(open => !open)} aria-label="Recent dataset activity" aria-expanded={notificationsOpen}>
                <Bell size={17} />
              </button>
              <AnimatePresence>
                {notificationsOpen && (
                  <motion.div className="popover activity-popover" initial={{opacity: 0, y: -5}} animate={{opacity: 1, y: 0}} exit={{opacity: 0, y: -5}}>
                    <b className="popover-title">Recent dataset activity</b>
                    {datasets.slice(0, 5).map(dataset => (
                      <Link className="activity-row" key={dataset.id} to={`/datasets/${dataset.id}`} onClick={() => setNotificationsOpen(false)}>
                        <span className="activity-icon"><Database size={14} /></span>
                        <span><b>{dataset.name}</b><small>Added {formatDate(dataset.created_at)}</small></span>
                      </Link>
                    ))}
                    {!datasets.length && <p className="popover-empty">No dataset activity yet.</p>}
                    <Link className="popover-link" to="/datasets" onClick={() => setNotificationsOpen(false)}>View all datasets</Link>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
            <div className="popover-anchor" ref={profileRef}>
              <button className="avatar small-avatar avatar-trigger" onClick={() => setProfileOpen(open => !open)} aria-label="Open profile menu" aria-expanded={profileOpen} aria-haspopup="menu">
                {initials(user.full_name)}
              </button>
              <AnimatePresence>
                {profileOpen && (
                  <motion.div className="popover profile-popover" role="menu" initial={{opacity: 0, y: -5}} animate={{opacity: 1, y: 0}} exit={{opacity: 0, y: -5}}>
                    <div className="profile-menu-heading"><b>{user.full_name}</b><small>{user.email}</small></div>
                    <Link role="menuitem" to="/settings/profile" onClick={() => setProfileOpen(false)}>Account / Profile</Link>
                    <Link role="menuitem" to="/settings" onClick={() => setProfileOpen(false)}>Settings</Link>
                    <button role="menuitem" onClick={handleLogout}><LogOut size={14} /> Logout</button>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </header>

        <input ref={fileInput} type="file" accept=".csv,.xlsx" hidden onChange={handleUpload} />
        <div className="content">
          {(datasetsError || analysisError) && (
            <div className="notice-banner error-banner" role="alert">
              <span>{datasetsError || analysisError}</span>
              <button className="inline-link" onClick={() => {
                if (datasetsError) void refreshDatasets().catch(() => undefined);
                if (analysisError) retryAnalysis();
              }}>Retry</button>
            </div>
          )}
          <div className="page-heading">
            <div>
              <div className="eyebrow">INTELLIGENCE, IN MOTION</div>
              <h1>{pageTitle}<span className="mint">.</span></h1>
              <p className="subtle">
                {selectedDataset ? `Working with ${selectedDataset.name}.` : "Your business intelligence workspace."}
              </p>
            </div>
            <div className="heading-actions">
              <button className="secondary-btn" onClick={() => fileInput.current?.click()} disabled={uploading}>
                <Upload size={15} />{uploading ? "Uploading…" : "Upload data"}
              </button>
              <button className="primary-btn" onClick={() => void exportReport()} disabled={exporting || !selectedDataset}>
                <Download size={15} />{exporting ? "Preparing…" : "Export report"}
              </button>
            </div>
          </div>
          <AnimatePresence>
            {toast && (
              <motion.div
                key={toast.id}
                className={`toast toast-${toast.kind}`}
                role={toast.kind === "error" ? "alert" : "status"}
                initial={{opacity: 0, y: -8}}
                animate={{opacity: 1, y: 0}}
                exit={{opacity: 0, y: -8}}
              >
                <span>{toast.message}</span>
                <button aria-label="Dismiss notification" onClick={() => setToast(null)}><X size={15} /></button>
              </motion.div>
            )}
          </AnimatePresence>
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={location.pathname}
              initial={{opacity: 0, y: 10}}
              animate={{opacity: 1, y: 0}}
              exit={{opacity: 0, y: -5}}
              transition={{duration: 0.2}}
            >
              <Outlet context={context} />
            </motion.div>
          </AnimatePresence>
        </div>
        <footer className="footer">
          <span>© 2026 INTELLIBIZ AI</span>
          <span>BUILT FOR CLARITY <i /> POWERED BY DATA</span>
          <span>v1.0.0</span>
        </footer>
      </main>
    </div>
  );
}

import {lazy, Suspense} from "react";
import {Navigate, Route, Routes} from "react-router-dom";
import {AuthProvider, RequireAuth} from "./lib/auth";

const DashboardLayout = lazy(() => import("./layout/DashboardLayout"));
const AuthPage = lazy(() => import("./pages/AuthPage"));
const OverviewPage = lazy(() =>
  import("./pages/DashboardPages").then(module => ({default: module.OverviewPage})),
);
const DataExplorerPage = lazy(() =>
  import("./pages/DashboardPages").then(module => ({default: module.DataExplorerPage})),
);
const ForecastPage = lazy(() =>
  import("./pages/DashboardPages").then(module => ({default: module.ForecastPage})),
);
const AnomaliesPage = lazy(() =>
  import("./pages/DashboardPages").then(module => ({default: module.AnomaliesPage})),
);
const CopilotPage = lazy(() =>
  import("./pages/DashboardPages").then(module => ({default: module.CopilotPage})),
);
const DatasetsPage = lazy(() =>
  import("./pages/DashboardPages").then(module => ({default: module.DatasetsPage})),
);
const DatasetDetailsPage = lazy(() =>
  import("./pages/DashboardPages").then(module => ({default: module.DatasetDetailsPage})),
);
const SettingsPage = lazy(() =>
  import("./pages/DashboardPages").then(module => ({default: module.SettingsPage})),
);

function PageLoading() {
  return <div className="session-state" role="status">Loading workspace…</div>;
}

export default function App() {
  return (
    <AuthProvider>
      <Suspense fallback={<PageLoading />}>
        <Routes>
          <Route path="/login" element={<AuthPage mode="login" />} />
          <Route path="/register" element={<AuthPage mode="register" />} />
          <Route element={<RequireAuth />}>
            <Route element={<DashboardLayout />}>
              <Route index element={<Navigate to="/overview" replace />} />
              <Route path="overview" element={<OverviewPage />} />
              <Route path="data-explorer" element={<DataExplorerPage />} />
              <Route path="forecast" element={<ForecastPage />} />
              <Route path="anomalies" element={<AnomaliesPage />} />
              <Route path="copilot" element={<CopilotPage />} />
              <Route path="datasets" element={<DatasetsPage />} />
              <Route path="datasets/:datasetId" element={<DatasetDetailsPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="settings/profile" element={<SettingsPage />} />
              <Route path="*" element={<Navigate to="/overview" replace />} />
            </Route>
          </Route>
        </Routes>
      </Suspense>
    </AuthProvider>
  );
}

import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import type { RouteName } from "./types";

const LightweightShell = lazy(() => import("./components/Layout").then((module) => ({ default: module.LayoutRoute })));
const HomePage = lazy(() => import("./pages/HomePage").then((module) => ({ default: module.HomePage })));
const ProjectsPage = lazy(() => import("./pages/ProjectsPage").then((module) => ({ default: module.ProjectsPage })));
const AssetsPage = lazy(() => import("./pages/AssetsPage").then((module) => ({ default: module.AssetsPage })));
const WorkflowPage = lazy(() => import("./pages/WorkflowPage").then((module) => ({ default: module.WorkflowPage })));
const TrashPage = lazy(() => import("./pages/TrashPage").then((module) => ({ default: module.TrashPage })));
const ApiSpacePage = lazy(() => import("./pages/ApiSpacePage").then((module) => ({ default: module.ApiSpacePage })));
const WorkspaceRoute = lazy(() => import("./app/WorkspaceRoute").then((module) => ({ default: module.WorkspaceRoute })));

function routePath(route: RouteName) {
  if (route === "home") return "/";
  return `/${route}`;
}

function RouteFallback() {
  return (
    <section className="content-wrap route-fallback" aria-label="Loading page">
      <div className="workflow-card-preview-loading is-generic" role="status" aria-label="Loading page">
        <span className="workflow-card-preview-loading-core" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
      </div>
    </section>
  );
}

function AppRoutes() {
  const navigate = useNavigate();
  const navigateRoute = (route: RouteName, options?: { state?: unknown }) => navigate(routePath(route), options);

  return (
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        <Route element={<LightweightShell />}>
          <Route path="/" element={<HomePage navigate={navigateRoute} />} />
          <Route path="/home" element={<Navigate to="/" replace />} />
          <Route path="/assets" element={<AssetsPage />} />
          <Route path="/api-space" element={<ApiSpacePage />} />
        </Route>
        <Route element={<WorkspaceRoute />}>
          <Route path="/projects" element={<ProjectsPage navigate={navigateRoute} />} />
          <Route path="/workflow" element={<WorkflowPage />} />
          <Route path="/trash" element={<TrashPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}

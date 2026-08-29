import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import type { AppNavigateOptions, RouteName } from "./types";

const LightweightShell = lazy(() => import("./components/Layout").then((module) => ({ default: module.LayoutRoute })));
const HomePage = lazy(() => import("./pages/HomePage").then((module) => ({ default: module.HomePage })));
const ProjectsPage = lazy(() => import("./pages/ProjectsPage").then((module) => ({ default: module.ProjectsPage })));
const AssetsPage = lazy(() => import("./pages/AssetsPage").then((module) => ({ default: module.AssetsPage })));
const WorkflowPage = lazy(() => import("./pages/WorkflowPage").then((module) => ({ default: module.WorkflowPage })));
const TrashPage = lazy(() => import("./pages/TrashPage").then((module) => ({ default: module.TrashPage })));
const ApiSpacePage = lazy(() => import("./pages/ApiSpacePage").then((module) => ({ default: module.ApiSpacePage })));
const HomeTypographyLabPage = lazy(() => import("./pages/HomeTypographyLabPage").then((module) => ({ default: module.HomeTypographyLabPage })));
const WorkspaceRoute = lazy(() => import("./app/WorkspaceRoute").then((module) => ({ default: module.WorkspaceRoute })));

function routePath(route: RouteName, projectId?: string | null) {
  if (route === "home") return "/";
  if (route === "workflow" && projectId?.trim()) {
    return `/workflow/${encodeURIComponent(projectId.trim())}`;
  }
  return `/${route}`;
}

function RouteFallback() {
  return (
    <section className="content-wrap route-fallback" aria-label="Loading page">
      <div className="route-loading" role="status" aria-label="Loading page">
        <span className="route-loading-spinner" aria-hidden="true" />
      </div>
    </section>
  );
}

function AppRoutes() {
  const navigate = useNavigate();
  const navigateRoute = (route: RouteName, options?: AppNavigateOptions) => {
    const { projectId, ...navigateOptions } = options ?? {};
    navigate(routePath(route, projectId), navigateOptions);
  };

  return (
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        <Route path="/design-lab/home-typography" element={<HomeTypographyLabPage />} />
        <Route element={<LightweightShell />}>
          <Route path="/" element={<HomePage navigate={navigateRoute} />} />
          <Route path="/home" element={<Navigate to="/" replace />} />
          <Route path="/assets" element={<AssetsPage />} />
          <Route path="/api-space" element={<ApiSpacePage />} />
        </Route>
        <Route element={<WorkspaceRoute />}>
          <Route path="/projects" element={<ProjectsPage navigate={navigateRoute} />} />
          <Route path="/workflow/:projectId" element={<WorkflowPage />} />
          <Route path="/workflow" element={<WorkflowPage />} />
          <Route path="/trash" element={<TrashPage navigate={navigateRoute} />} />
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

import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { Layout } from "./components/Layout";
import { HomePage } from "./pages/HomePage";
import type { RouteName } from "./types";

const ProjectsPage = lazy(() => import("./pages/ProjectsPage").then((module) => ({ default: module.ProjectsPage })));
const AssetsPage = lazy(() => import("./pages/AssetsPage").then((module) => ({ default: module.AssetsPage })));
const WorkflowPage = lazy(() => import("./pages/WorkflowPage").then((module) => ({ default: module.WorkflowPage })));
const TrashPage = lazy(() => import("./pages/TrashPage").then((module) => ({ default: module.TrashPage })));
const ApiSpacePage = lazy(() => import("./pages/ApiSpacePage").then((module) => ({ default: module.ApiSpacePage })));

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
  const navigateRoute = (route: RouteName) => navigate(routePath(route));

  return (
    <Layout>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<HomePage navigate={navigateRoute} />} />
          <Route path="/home" element={<Navigate to="/" replace />} />
          <Route path="/projects" element={<ProjectsPage navigate={navigateRoute} />} />
          <Route path="/assets" element={<AssetsPage />} />
          <Route path="/workflow" element={<WorkflowPage />} />
          <Route path="/trash" element={<TrashPage />} />
          <Route path="/api-space" element={<ApiSpacePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Layout>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}

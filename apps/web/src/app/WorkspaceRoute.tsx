import { lazy, Suspense, useEffect } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { Layout } from "../components/Layout";
import { WorkspaceProvider } from "./WorkspaceProvider";

const V2WorkflowRevisionControl = lazy(() => import("../components/V2WorkflowRevisionControl"));

type WorkspaceRouteState = {
  startNewProject?: boolean;
};

export function WorkspaceRoute() {
  const location = useLocation();
  const navigate = useNavigate();
  const state = location.state as WorkspaceRouteState | null;
  const startWithNewProject = state?.startNewProject === true;

  useEffect(() => {
    if (!startWithNewProject) return;
    navigate(location.pathname, { replace: true, state: null });
  }, [location.pathname, navigate, startWithNewProject]);

  return (
    <WorkspaceProvider startWithNewProject={startWithNewProject}>
      <Layout workflowControls={location.pathname.startsWith("/workflow") ? (
        <Suspense fallback={null}><V2WorkflowRevisionControl /></Suspense>
      ) : null}>
        <Outlet />
      </Layout>
    </WorkspaceProvider>
  );
}

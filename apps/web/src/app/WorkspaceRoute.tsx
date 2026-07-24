import { lazy, Suspense } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Layout } from "../components/Layout";
import { WorkspaceProvider } from "./WorkspaceProvider";

const V2WorkflowRevisionControl = lazy(() => import("../components/V2WorkflowRevisionControl"));

type WorkspaceRouteState = {
  startNewProject?: boolean;
};

export function WorkspaceRoute() {
  const location = useLocation();
  const state = location.state as WorkspaceRouteState | null;
  const startWithNewProject = state?.startNewProject === true;

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

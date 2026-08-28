import { useEffect, useRef } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { Layout } from "../components/Layout";
import { WorkspaceProvider } from "./WorkspaceProvider";

type WorkspaceRouteState = {
  startNewProject?: boolean;
};

export function WorkspaceRoute() {
  const location = useLocation();
  const navigate = useNavigate();
  const normalizedPath = location.pathname.toLowerCase();
  const state = location.state as WorkspaceRouteState | null;
  const newProjectRouteRef = useRef<string | null>(
    state?.startNewProject === true ? location.pathname : null,
  );
  const routeStateConsumedRef = useRef(false);
  if (
    newProjectRouteRef.current
    && newProjectRouteRef.current !== location.pathname
  ) {
    newProjectRouteRef.current = null;
  }
  const startWithNewProject = newProjectRouteRef.current !== null;

  useEffect(() => {
    if (!startWithNewProject || routeStateConsumedRef.current) return;
    routeStateConsumedRef.current = true;
    void navigate({
      pathname: location.pathname,
      search: location.search,
      hash: location.hash,
    }, {
      replace: true,
      state: null,
    });
  }, [
    location.hash,
    location.pathname,
    location.search,
    navigate,
    startWithNewProject,
  ]);

  return (
    <WorkspaceProvider
      startWithNewProject={startWithNewProject}
      restoreActiveWorkflow={normalizedPath.startsWith("/workflow")}
      projectCatalogScope={normalizedPath === "/trash" ? "trashed" : "active"}
    >
      <Layout>
        <Outlet />
      </Layout>
    </WorkspaceProvider>
  );
}

import { lazy, Suspense } from "react";
import { ReactFlowProvider } from "@xyflow/react";

import "@xyflow/react/dist/style.css";
import "./agent-canvas-page.css";
import { ConnectionEffectsProvider } from "./canvas/connection-effects/ConnectionEffectsProvider.tsx";
import { ProviderBalanceNoticeHost } from "./notifications/ProviderBalanceNoticeHost.tsx";

const AgentCanvasPageSurface = lazy(() => import("./AgentCanvasPageSurface.tsx").then((module) => ({
  default: module.AgentCanvasPage,
})));

export function AgentCanvasPage() {
  return (
    <ReactFlowProvider>
      <ConnectionEffectsProvider>
        <Suspense fallback={<div className="agent-canvas-state" role="status">Opening project...</div>}>
          <AgentCanvasPageSurface />
        </Suspense>
        <ProviderBalanceNoticeHost />
      </ConnectionEffectsProvider>
    </ReactFlowProvider>
  );
}

import { useState } from "react";
import { createRoot } from "react-dom/client";

import { CanvasMediaPreview } from "../../src/features/agent-canvas/canvas/CanvasMediaPreview.tsx";
import { CanvasVideoPreview } from "../../src/features/agent-canvas/canvas/CanvasVideoPreview.tsx";
import type { ProjectAssetSummaryV2 } from "../../src/types-v2.ts";

const sources = {
  v1: "/api/v2/assets/asset-continuity/preview?v=version-1",
  v2: "/api/v2/assets/asset-continuity/preview?v=version-2",
} as const;

const videoAsset = {
  asset_id: "asset-video-continuity",
  version_id: "version-video-1",
  workflow_id: "workflow-1",
  project_id: "project-1",
  media_type: "video",
  poster_url: "/api/v2/assets/asset-video-continuity/poster",
  preview_url: null,
  media_url: "/api/v2/assets/asset-video-continuity/content",
  display_name: "Video continuity poster",
} as ProjectAssetSummaryV2;

function App() {
  const [version, setVersion] = useState<keyof typeof sources>("v1");
  const [mounted, setMounted] = useState(true);
  const [renderRevision, setRenderRevision] = useState(0);
  const source = sources[version];

  return (
    <main>
      <h1>Canvas loaded media continuity</h1>
      <div>
        <button type="button" onClick={() => setRenderRevision((value) => value + 1)}>Runtime rerender</button>
        <button type="button" onClick={() => setMounted((value) => !value)}>{mounted ? "Unmount" : "Remount"}</button>
        <button type="button" onClick={() => setVersion("v1")}>AssetVersion v1</button>
        <button type="button" onClick={() => setVersion("v2")}>AssetVersion v2</button>
      </div>
      {mounted ? (
        <section data-testid="canvas-node" data-render-revision={renderRevision} data-canonical-source={source}>
          <CanvasMediaPreview src={source} alt="Canvas continuity preview" />
          <CanvasVideoPreview asset={videoAsset} label="Video continuity" />
        </section>
      ) : <p data-testid="unmounted">Media node unmounted</p>}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);

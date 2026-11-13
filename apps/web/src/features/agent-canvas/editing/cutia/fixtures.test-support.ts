import type { AgentCanvasWorkflowV2, CanvasNodeV2, ProjectAssetSummaryV2 } from "../../../../types-v2.ts";
import { initialCutiaSnapshot } from "./project.ts";

export function editingFixture() {
  const asset = (id: string, type: "video" | "audio", duration: number) => ({
    asset_id: id, display_name: id, media_type: type, status: "ready", mime_type: type === "video" ? "video/mp4" : "audio/wav",
    media_url: `/api/v2/assets/${id}/content`, duration_seconds: duration, width: 320, height: 180,
  } as ProjectAssetSummaryV2);
  const node = {
    node_id: "editing-1", workflow_id: "workflow-1", node_type: "editing", creative_role: "editing", title: "Film",
    parameters: { existing: "preserve" }, metadata: {}, revision: 1, created_at: "2026-11-12T00:00:00Z",
    structured_content: {
      manifest: { video_entries: [{ asset_id: "video-1", trim_start_seconds: 2, trim_end_seconds: 5 }], bgm: { asset_id: "bgm-1", volume: 0.35 }, output: { resolution: "320x180", fps: 10 }, manifest_revision: 2 },
      preview: { clips: [], warnings: [], estimated_duration_seconds: 3 }, dirty: true, active_export: null, last_successful_export: null,
    },
  } as unknown as CanvasNodeV2;
  const workflow = { workflow_id: "workflow-1", project_id: "project-1", nodes: [node], bindings: [], assets: [asset("video-1", "video", 6), asset("bgm-1", "audio", 2)], revision: 1 } as unknown as AgentCanvasWorkflowV2;
  return { node, workflow, snapshot: initialCutiaSnapshot(workflow, node) };
}

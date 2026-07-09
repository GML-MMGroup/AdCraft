import type { WorkflowNode } from "../../../types.ts";
import { getNodeDefinition, getWorkflowNodeType } from "../canvas/workflowNodeModel.ts";

export function NodeConfigControls({ node, onChange }: { node: WorkflowNode; onChange: (key: string, value: unknown) => void }) {
  const definition = getNodeDefinition(getWorkflowNodeType(node), node.category);
  const config = node.config ?? {};

  if (definition.family === "Image") {
    return (
      <div className="typed-config-grid">
        <label className="node-config-field">
          <span>Model</span>
          <input value={String(config.model ?? "")} placeholder="gpt-image / image model" onChange={(event) => onChange("model", event.target.value)} />
        </label>
        <label className="node-config-field">
          <span>Aspect</span>
          <select value={String(config.aspect_ratio ?? "1:1")} onChange={(event) => onChange("aspect_ratio", event.target.value)}>
            <option value="1:1">1:1</option>
            <option value="16:9">16:9</option>
            <option value="9:16">9:16</option>
            <option value="4:3">4:3</option>
          </select>
        </label>
        <label className="node-config-field">
          <span>Seed</span>
          <input type="number" value={Number(config.seed ?? 0)} onChange={(event) => onChange("seed", Number(event.target.value))} />
        </label>
      </div>
    );
  }

  if (definition.family === "Video" || definition.family === "Preview") {
    return (
      <div className="typed-config-grid">
        <label className="node-config-field">
          <span>Duration</span>
          <input type="number" value={Number(config.duration_seconds ?? 5)} onChange={(event) => onChange("duration_seconds", Number(event.target.value))} />
        </label>
        <label className="node-config-field">
          <span>Resolution</span>
          <select value={String(config.resolution ?? "720p")} onChange={(event) => onChange("resolution", event.target.value)}>
            <option value="480p">480p</option>
            <option value="720p">720p</option>
            <option value="1080p">1080p</option>
          </select>
        </label>
        <label className="node-config-field">
          <span>Aspect</span>
          <select value={String(config.aspect_ratio ?? "16:9")} onChange={(event) => onChange("aspect_ratio", event.target.value)}>
            <option value="16:9">16:9</option>
            <option value="9:16">9:16</option>
            <option value="1:1">1:1</option>
          </select>
        </label>
      </div>
    );
  }

  if (definition.family === "Audio") {
    return (
      <div className="typed-config-grid">
        <label className="node-config-field">
          <span>Audio Mode</span>
          <select value={String(config.audio_mode ?? "bgm_only")} onChange={(event) => onChange("audio_mode", event.target.value)}>
            <option value="none">none</option>
            <option value="bgm_only">bgm only</option>
            <option value="full">full</option>
          </select>
        </label>
        <label className="node-config-field">
          <span>Volume</span>
          <input type="number" min="0" max="1" step="0.05" value={Number(config.volume ?? 0.8)} onChange={(event) => onChange("volume", Number(event.target.value))} />
        </label>
      </div>
    );
  }

  return (
    <div className="typed-config-grid">
      <label className="node-config-field">
        <span>Temperature</span>
        <input type="number" min="0" max="2" step="0.1" value={Number(config.temperature ?? 0.7)} onChange={(event) => onChange("temperature", Number(event.target.value))} />
      </label>
      <label className="node-config-field">
        <span>Max Tokens</span>
        <input type="number" value={Number(config.max_tokens ?? 1200)} onChange={(event) => onChange("max_tokens", Number(event.target.value))} />
      </label>
    </div>
  );
}

import { UploadIcon, VideoIcon } from "../../../icons.tsx";
import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../../types-v2.ts";
import { useTranslation } from "../../../i18n/useTranslation.ts";

export function EditingWorkbench({
  workflow,
  node,
  onOpenEditing,
}: {
  workflow: AgentCanvasWorkflowV2;
  node: CanvasNodeV2;
  onOpenEditing: () => void;
}) {
  const t = useTranslation("en-US");
  const inputs = workflow.bindings
    .filter((binding) => binding.target_node_id === node.node_id && binding.enabled)
    .sort((left, right) => left.order - right.order)
    .map((binding) => {
      const source = binding.source;
      return source.kind === "node_output"
        ? workflow.nodes.find((candidate) => candidate.node_id === source.source_node_id)
        : null;
    })
    .filter((input): input is CanvasNodeV2 => Boolean(input));

  return (
    <div className="agent-node-workbench__body agent-node-workbench__editing">
      <div className="agent-node-workbench__editing-summary">
        <VideoIcon />
        <div>
          <strong>{inputs.length ? `${inputs.length} ${t(inputs.length === 1 ? "Connected source" : "Connected sources")}` : t("No connected video sources")}</strong>
          <span>{t("Arrange clips and optional BGM in the editor.")}</span>
        </div>
      </div>
      <div className="agent-node-workbench__editing-inputs" aria-label={t("Editing sources")}>
        {inputs.map((input, index) => <span key={input.node_id}>{index + 1}. {input.title}</span>)}
      </div>
      <footer className="agent-node-workbench__footer">
        <span>{t("Exports are prepared by the Editing node.")}</span>
        <button
          type="button"
          className="agent-node-workbench__run"
          aria-label={t("Open editing editor")}
          title={t("Open editor")}
          onClick={onOpenEditing}
        >
          <UploadIcon />
        </button>
      </footer>
    </div>
  );
}

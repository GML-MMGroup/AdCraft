import type { CanvasNodeV2 } from "../../../types-v2.ts";
import { promptPreparationForNode } from "../model/promptPreparation.ts";
import { AgentCanvasNodeTypeIcon } from "./AgentCanvasNodeTypeIcon.tsx";
import { isLikelyMarkdown, renderMarkdownAwareText } from "./AgentCanvasMarkdown";

function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function agentCanvasNodeDisplayText(node: CanvasNodeV2): string | null {
  if (node.node_type === "script") {
    const content = node.structured_content.content;
    if (typeof content === "string") return nonEmptyString(content);
    const legacyScript = node.structured_content.script_text;
    if (typeof legacyScript === "string") return nonEmptyString(legacyScript);
    const legacyText = node.structured_content.text;
    if (typeof legacyText === "string") return nonEmptyString(legacyText);
    return nonEmptyString(node.generation_prompt)
      ?? nonEmptyString(node.summary_prompt);
  }
  if (node.node_type === "text") {
    return nonEmptyString(node.structured_content.content)
      ?? nonEmptyString(node.structured_content.text);
  }
  if (node.node_type === "image" || node.node_type === "video") {
    const preparation = promptPreparationForNode(node);
    return preparation.status === "ready"
      ? nonEmptyString(node.generation_prompt)
      : nonEmptyString(node.summary_prompt);
  }
  return null;
}

interface AgentCanvasNodeContentProps {
  node: CanvasNodeV2;
  iconLabel: string;
}

export function AgentCanvasNodeContent({
  node,
  iconLabel,
}: AgentCanvasNodeContentProps) {
  const copy = agentCanvasNodeDisplayText(node);
  if (copy) {
    if (isLikelyMarkdown(copy)) {
      return (
        <div className="agent-canvas-node__content">
          <div className="agent-canvas-node__markdown">
            {renderMarkdownAwareText(copy)}
          </div>
        </div>
      );
    }

    return (
      <div className="agent-canvas-node__content">
        <p>{copy}</p>
      </div>
    );
  }

  return (
    <div className="agent-canvas-node__media-placeholder">
      <AgentCanvasNodeTypeIcon nodeType={node.node_type} label={iconLabel} />
    </div>
  );
}

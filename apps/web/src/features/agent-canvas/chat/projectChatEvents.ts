import type {
  CanvasNodeTypeV2,
  CanvasRuntimeEventV2,
  ChatArtifactCardV2,
  ChatExpertActivityV2,
  ChatProposalCardV2,
  ChatTimelineItemV2,
  ConceptOptionV2,
  SpecialistAgentNameV2,
} from "../../../types-v2.ts";

const SPECIALISTS = new Set<SpecialistAgentNameV2>([
  "script_writer",
  "product_designer",
  "prop_designer",
  "character_designer",
  "scene_designer",
  "storyboard_artist",
  "video_director",
  "bgm_director",
]);

function stringValue(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function stringArray(value: unknown) {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function nodeTypeForProposal(kind: string): CanvasNodeTypeV2 {
  if (kind === "script") return "script";
  if (kind === "video") return "video";
  if (kind === "bgm") return "audio";
  return "image";
}

function specialistValue(payload: Record<string, unknown>): SpecialistAgentNameV2 | null {
  const value = stringValue(payload.specialist, stringValue(payload.specialist_name));
  return SPECIALISTS.has(value as SpecialistAgentNameV2)
    ? value as SpecialistAgentNameV2
    : null;
}

function specialistLabel(specialist: SpecialistAgentNameV2): string {
  return specialist
    .split("_")
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function projectOption(
  value: unknown,
  proposalKind: string,
): ConceptOptionV2 | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const option = value as Record<string, unknown>;
  const optionId = stringValue(option.option_id);
  if (!optionId) return null;
  return {
    option_id: optionId,
    display_name: stringValue(option.display_name, stringValue(option.title, "Option")),
    summary_prompt: stringValue(
      option.summary_prompt,
      stringValue(option.description),
    ),
    semantic_role: stringValue(option.semantic_role, proposalKind),
    proposed_node_type: (
      ["text", "script", "image", "video", "audio", "editing"].includes(
        stringValue(option.proposed_node_type),
      )
        ? option.proposed_node_type
        : nodeTypeForProposal(proposalKind)
    ) as CanvasNodeTypeV2,
    reference_node_ids: stringArray(option.reference_node_ids),
    reference_image_asset_ids: stringArray(option.reference_image_asset_ids),
  };
}

export function projectChatEvents(
  events: CanvasRuntimeEventV2[],
): ChatTimelineItemV2[] {
  const activities = new Map<string, ChatExpertActivityV2>();
  const proposals = new Map<string, ChatProposalCardV2>();
  const artifacts = new Map<string, ChatArtifactCardV2>();

  events.forEach((event) => {
    const payload = event.payload ?? {};
    if (event.event_type.startsWith("expert_activity_")) {
      const specialist = specialistValue(payload);
      const turnId = stringValue(payload.turn_id);
      if (!specialist || !turnId) return;
      const key = stringValue(payload.activity_id, `${turnId}:${specialist}`);
      const previous = activities.get(key);
      const status = event.event_type.endsWith("_completed")
        ? "completed"
        : event.event_type.endsWith("_failed")
          ? "failed"
          : "working";
      activities.set(key, {
        item_type: "expert_activity",
        activity_id: key,
        turn_id: turnId,
        specialist,
        label: specialistLabel(specialist),
        operation: stringValue(payload.operation, "planning"),
        status,
        sequence: previous?.sequence ?? event.seq,
        started_at: previous?.started_at ?? event.created_at,
        finished_at: status === "working" ? null : event.created_at,
      });
      return;
    }

    if (
      event.event_type === "concept_options_ready"
      || event.event_type === "concept_proposal_created"
    ) {
      const proposalPayload = (
        payload.proposal
        && typeof payload.proposal === "object"
        && !Array.isArray(payload.proposal)
      )
        ? payload.proposal as Record<string, unknown>
        : payload;
      const proposalId = stringValue(proposalPayload.proposal_id);
      const turnId = stringValue(proposalPayload.turn_id);
      const specialist = specialistValue(proposalPayload);
      const proposalKind = stringValue(proposalPayload.proposal_kind, "image");
      const options = Array.isArray(proposalPayload.options)
        ? proposalPayload.options
          .map((option) => projectOption(option, proposalKind))
          .filter((option): option is ConceptOptionV2 => Boolean(option))
          .slice(0, 4)
        : [];
      if (!proposalId || !turnId || !specialist || !options.length) return;
      proposals.set(proposalId, {
        item_type: "proposal",
        proposal: {
          proposal_id: proposalId,
          workflow_id: event.workflow_id,
          turn_id: turnId,
          specialist,
          status: "pending",
          options,
          workflow_revision: typeof proposalPayload.workflow_revision === "number"
            ? proposalPayload.workflow_revision
            : 1,
          selection_actor: null,
        },
        sequence: event.seq,
        created_at: event.created_at,
      });
      return;
    }

    if (event.event_type.startsWith("proposal_")) {
      const proposalId = stringValue(payload.proposal_id);
      const existing = proposals.get(proposalId);
      if (!existing) return;
      const status = event.event_type === "proposal_selected"
        ? "selected"
        : event.event_type === "proposal_revised"
          ? "revised"
          : event.event_type === "proposal_skipped"
            ? "skipped"
            : existing.proposal.status;
      proposals.set(proposalId, {
        ...existing,
        proposal: {
          ...existing.proposal,
          status,
          selection_actor: status === "selected" ? "user" : existing.proposal.selection_actor,
        },
      });
      return;
    }

    if (
      event.event_type === "chat_artifact_created"
      || event.event_type === "script_artifact_created"
    ) {
      const artifactId = stringValue(payload.artifact_id, stringValue(payload.entry_id));
      const nodeId = stringValue(payload.script_node_id, event.node_id ?? "");
      if (!artifactId || !nodeId) return;
      artifacts.set(artifactId, {
        item_type: "artifact",
        artifact_id: artifactId,
        artifact_kind: "script",
        node_id: nodeId,
        title: stringValue(payload.title, "Script"),
        summary: stringValue(payload.summary),
        action_label: "View Script",
        source_turn_id: stringValue(payload.source_turn_id) || null,
        sequence: event.seq,
        created_at: event.created_at,
      });
    }
  });

  return [
    ...activities.values(),
    ...proposals.values(),
    ...artifacts.values(),
  ].sort((left, right) => left.sequence - right.sequence);
}

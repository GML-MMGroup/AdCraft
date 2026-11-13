import type { UiMessageKey } from "../../../i18n/uiMessages.ts";
import type {
  AgentCapabilityIdV2,
  AgentCanvasChatTurnV2,
  ChatTimelineItemV2,
  GuidedInteractionV1,
  GuidedProductionJourneyV2,
  GuidedJourneyStageV2,
} from "../../../types-v2.ts";
import type { BrandStageV2 } from "../brand/brandDecisions.ts";

const CAPABILITY_MESSAGES: Record<AgentCapabilityIdV2, UiMessageKey> = {
  world_setting: "World Setting Designer is working...",
  product_design: "Product Designer is working...",
  prop_design: "Prop Designer is working...",
  character_design: "Character Designer is working...",
  scene_design: "Scene Designer is working...",
  script_authoring: "Script Writer is working...",
  storyboard_design: "Storyboard Artist is working...",
  video_direction: "Video Director is working...",
  bgm_direction: "BGM Director is working...",
  quick_media: "Media Creator is working...",
};

const JOURNEY_MESSAGES: Record<GuidedJourneyStageV2, UiMessageKey> = {
  intake: "Understanding your requirements...",
  world_view: CAPABILITY_MESSAGES.world_setting,
  product: CAPABILITY_MESSAGES.product_design,
  props: CAPABILITY_MESSAGES.prop_design,
  character: CAPABILITY_MESSAGES.character_design,
  scene: CAPABILITY_MESSAGES.scene_design,
  narrative_direction: CAPABILITY_MESSAGES.script_authoring,
  style_lock: "Defining the audiovisual style...",
  storyboard_plan: CAPABILITY_MESSAGES.storyboard_design,
  storyboard_grids: CAPABILITY_MESSAGES.storyboard_design,
  videos: CAPABILITY_MESSAGES.video_direction,
  bgm: CAPABILITY_MESSAGES.bgm_direction,
  editing: "Editor is working...",
  completed: "Preparing the next step...",
};

const BRAND_MESSAGES: Record<Exclude<BrandStageV2, "production">, UiMessageKey> = {
  "brand-memory": "Organizing brand information...",
  campaign: "Preparing campaign goals...",
  hypothesis: "Developing creative directions...",
  adspec: "Defining the ad strategy...",
  "creative-route": "Planning the creative approach...",
  "skill-stack": "Selecting creative Skills...",
  "skill-stack-early": "Selecting creative Skills...",
  treatment: "Developing the treatment...",
};

function capabilityMessage(id: unknown): UiMessageKey | null {
  return typeof id === "string" && Object.hasOwn(CAPABILITY_MESSAGES, id)
    ? CAPABILITY_MESSAGES[id as AgentCapabilityIdV2] : null;
}

interface WorkingContext {
  workflowId: string;
  items: readonly ChatTimelineItemV2[];
  turnsById: Readonly<Record<string, AgentCanvasChatTurnV2>>;
  journey?: Pick<GuidedProductionJourneyV2, "stage" | "active_action"> | null;
  interaction?: GuidedInteractionV1 | null;
  waitingForInteraction?: boolean;
  brandStage?: BrandStageV2 | null;
}

/** Prefer current execution authority over historical role cards. */
export function agentWorkingMessage(context: WorkingContext): UiMessageKey {
  const { workflowId, turnsById, items, journey, interaction, brandStage } = context;
  if (context.waitingForInteraction && interaction?.workflow_id === workflowId
    && interaction.content.content_kind === "concept_choice") {
    const message = capabilityMessage(interaction.content.capability_id);
    if (message) return message;
  }
  const activeTurns = Object.values(turnsById)
    .filter(turn => turn.workflow_id === workflowId && ["queued", "running"].includes(turn.status))
    .sort((left, right) => right.created_at.localeCompare(left.created_at));
  const turnMessage = capabilityMessage(activeTurns[0]?.request.capability_id);
  if (turnMessage) return turnMessage;

  const turnIsActive = (id: string) => {
    const turn = turnsById[id];
    return !turn || (turn.workflow_id === workflowId && ["queued", "running"].includes(turn.status));
  };
  const activeItems = [...items].sort((left, right) => right.sequence - left.sequence);
  for (const item of activeItems) {
    if (item.item_type === "expert_activity" && item.status === "working" && turnIsActive(item.turn_id)) {
      return CAPABILITY_MESSAGES[item.capability_id];
    }
    if (item.item_type === "proposal" && item.proposal.workflow_id === workflowId
      && item.proposal.materialization
      && ["queued", "working"].includes(item.proposal.materialization.status)
      && turnIsActive(item.proposal.materialization.turn_id)) {
      return CAPABILITY_MESSAGES[item.proposal.capability_id];
    }
  }
  if (brandStage && brandStage !== "production") return BRAND_MESSAGES[brandStage];
  if (journey) return JOURNEY_MESSAGES[journey.active_action?.stage ?? journey.stage];
  return "Agent is working...";
}

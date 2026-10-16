/** Typed read model for the Brand Professional Mode decision panel (Phase 1). */

export type BrandModeV2 = "creation" | "brand";

export type BrandStageV2 =
  | "brand-memory"
  | "campaign"
  | "hypothesis"
  | "adspec"
  | "skill-stack"
  | "treatment"
  | "production";

export type BrandSlotProvenanceV2 = "user_confirmed" | "agent_recommended";

export interface BrandSlotValueV1 {
  slot_id: string;
  stage: BrandStageV2;
  value: string;
  kind: "fact" | "constraint" | "preference" | "assumption";
  provenance: BrandSlotProvenanceV2;
  confirmed_at: string | null;
}

export interface BrandShortOptionV1 {
  detail?: TreatmentDetail | null;
  option_id: string;
  label: string;
  why: string | null;
}

export interface BrandOptionCardV1 {
  card_id: string;
  stage: BrandStageV2;
  stage_revision: number;
  target_slot_id: string | null;
  question: string;
  options: BrandShortOptionV1[];
}

export interface BrandHypothesisCandidateV1 {
  candidate_id: string;
  label: string;
  insight: string;
  mechanism: string;
  hypothesis: string;
  product_role: string;
  hook_mechanism: string;
  why: string | null;
}

export interface BrandAdSpecItemV1 {
  item_key: string;
  item_text: string;
  state: "locked" | "open" | "variable";
}

export interface BrandSkillStackEntryV1 {
  skill_kind: "creative_method" | "audiovisual_style";
  skill_id: string;
  title: string;
  selected: boolean;
  version: string | null;
  reason: string | null;
}

export interface BrandSkillIdentity {
  skill_id: string;
  version: string;
}

export interface BrandCreativeMethod extends BrandSkillIdentity {
  skill_kind: "creative_method";
  title: string;
  summary: string;
}

export interface BrandSkillSelectionRequest {
  card_id: string;
  expected_stage_revision: number;
  creative_methods: BrandSkillIdentity[];
  audiovisual_style: BrandSkillIdentity;
  confirm: boolean;
}

export interface BrandTreatmentStepResultV1 {
  structured_detail?: TreatmentDetail | null;
  step_key:
    | "hook"
    | "story"
    | "character"
    | "scene"
    | "visual"
    | "camera"
    | "editing"
    | "sound";
  selected_label: string;
  detail: string;
  confirmed_at: string;
}

export interface BrandDecisionPanelV1 {
  brand_profile?: BrandBriefSummary | null;
  campaign_brief?: BrandBriefSummary | null;
  treatment_document?: BrandTreatmentDocument | null;
  project_id: string;
  workflow_id: string;
  mode: BrandModeV2;
  journey: {
    policy_version: "brand_professional_v1";
    stage: BrandStageV2;
    treatment_substep: string | null;
    stage_revision: number;
    stage_status: "ready" | "working" | "waiting_user" | "completed";
  };
  brand_name: string;
  slot_values: BrandSlotValueV1[];
  open_card: BrandOptionCardV1 | null;
  hypotheses: BrandHypothesisCandidateV1[];
  selected_hypothesis_id: string | null;
  adspec: { items: BrandAdSpecItemV1[] } | null;
  skill_stack: { entries: BrandSkillStackEntryV1[] } | null;
  treatment_steps: BrandTreatmentStepResultV1[];
  treatment_locked: boolean;
}

export interface BrandInspectionConversationTurnV1 {
  turn_id: string;
  role: "user" | "assistant" | "system";
  text: string;
  status: string | null;
  error_code: string | null;
  created_at: string | null;
}

export interface BrandJourneyStateV1 {
  policy_version: string;
  stage: BrandStageV2;
  treatment_substep: string | null;
  stage_revision: number;
  stage_status: "ready" | "working" | "waiting_user" | "completed";
}

export interface BrandDecisionLogEntryV1 {
  log_id: string;
  stage: BrandStageV2;
  action: "select" | "reject" | "fusion" | "recommend" | "edit" | "confirm" | "lock";
  target_type: string;
  target_id: string | null;
  detail: Record<string, unknown>;
  created_at: string | null;
}

export interface TreatmentSection { key: string; title: string; text: string; }
export interface TreatmentDetail { sections: TreatmentSection[]; }
export interface BrandBriefSummary {
  values: BrandSlotValueV1[];
  inherited_values: BrandSlotValueV1[];
  unresolved_fields: string[];
}
export interface BrandTreatmentDocument {
  schema_version: string;
  brand_profile: BrandBriefSummary;
  campaign_brief: BrandBriefSummary;
  selected_hypothesis: BrandHypothesisCandidateV1 | null;
  adspec: BrandDecisionPanelV1["adspec"];
  skill_stack: BrandDecisionPanelV1["skill_stack"];
  treatment_steps: BrandTreatmentStepResultV1[];
  product_presentation: TreatmentSection[];
  authorized_asset_references: Array<{ binding_id: string; workflow_id: string; target_node_id: string; asset_id: string; version_id: string; display_name: string; input_role: string }>;
  complete: boolean;
  missing_sections: string[];
  content_digest: string;
  execution_limitations: string[];
}
export interface BrandTreatmentEdit {
  expected_stage_revision: number;
  selected_label: string;
  detail: TreatmentDetail;
}

import { readTreatmentDetail, readTreatmentDocument, readBrandBrief } from "./treatmentReadModel";
import type {
  BrandOptionCardV1,
  BrandDecisionLogEntryV1,
  BrandDecisionPanelV1,
  BrandInspectionConversationTurnV1,
  BrandJourneyStateV1,
  BrandCreativeMethod,
} from "./brandDecisions.ts";

const BRAND_STAGES = [
  "brand-memory",
  "campaign",
  "hypothesis",
  "adspec",
  "skill-stack",
  "treatment",
  "production",
] as const;

function fail(path: string, message: string): never {
  throw new Error(`${path}: ${message}`);
}

function record(value: unknown, path: string): Record<string, unknown> {
  const result = value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
  if (!result) fail(path, "expected object");
  return result;
}

function arr(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) fail(path, "expected array");
  return value;
}

function str(value: unknown, path: string): string {
  if (typeof value !== "string") fail(path, "expected string");
  return value;
}

function nonEmptyStr(value: unknown, path: string): string {
  const result = str(value, path);
  if (!result.trim()) fail(path, "expected non-empty string");
  return result;
}

function int(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) fail(path, "expected integer");
  return value;
}

function optionalStr(value: unknown, path: string): string | null {
  return value === null || value === undefined ? null : str(value, path);
}

function bool(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") fail(path, "expected boolean");
  return value;
}

function isoStr(value: unknown, path: string): string {
  return nonEmptyStr(value, path);
}

function literal<T extends string>(value: unknown, allowed: readonly T[], fallback: T, path: string): T {
  if (typeof value === "string" && (allowed as readonly string[]).includes(value)) {
    return value as T;
  }
  if (value === undefined || value === null) {
    return fallback;
  }
  fail(path, "unexpected enum value");
}

function stage(value: unknown, path: string): BrandDecisionPanelV1["journey"]["stage"] {
  if (typeof value !== "string" || !BRAND_STAGES.includes(value as never)) {
    fail(path, "expected brand stage");
  }
  return value as BrandDecisionPanelV1["journey"]["stage"];
}

function slotKind(value: unknown, path: string): BrandDecisionPanelV1["slot_values"][number]["kind"] {
  return literal(
    value,
    ["fact", "constraint", "preference", "assumption"],
    "fact",
    path,
  );
}

function adSpecState(value: unknown, path: string): "locked" | "open" | "variable" {
  return literal(value, ["locked", "open", "variable"], "open", path);
}

function skillKind(value: unknown, path: string): "creative_method" | "audiovisual_style" {
  return literal(value, ["creative_method", "audiovisual_style"], "creative_method", path);
}

function treatmentStepKey(
  value: unknown,
  path: string,
): BrandDecisionPanelV1["treatment_steps"][number]["step_key"] {
  return literal(
    value,
    ["hook", "story", "character", "scene", "visual", "camera", "editing", "sound"],
    "hook",
    path,
  );
}

function decisionAction(
  value: unknown,
  path: string,
): BrandDecisionLogEntryV1["action"] {
  return literal(
    value,
    ["select", "reject", "fusion", "recommend", "edit", "confirm", "lock"],
    "edit",
    path,
  );
}

export function normalizeBrandDecisionPanelV1(value: unknown): BrandDecisionPanelV1 {
  const root = record(value, "brandDecisions");
  const journey = record(root.journey, "brandDecisions.journey");
  const slotValues = arr(root.slot_values ?? [], "brandDecisions.slot_values").map(
    (item, index) => {
      const slot = record(item, `brandDecisions.slot_values[${index}]`);
      return {
        slot_id: nonEmptyStr(slot.slot_id, `brandDecisions.slot_values[${index}].slot_id`),
        stage: stage(slot.stage, `brandDecisions.slot_values[${index}].stage`),
        value: str(slot.value, `brandDecisions.slot_values[${index}].value`),
        kind: slotKind(slot.kind, `brandDecisions.slot_values[${index}].kind`),
        provenance: slot.provenance === "agent_recommended" ? "agent_recommended" : "user_confirmed",
        confirmed_at: optionalStr(slot.confirmed_at, `brandDecisions.slot_values[${index}].confirmed_at`),
      } satisfies BrandDecisionPanelV1["slot_values"][number];
    },
  );
  const openCardRaw = root.open_card;
  const openCard = openCardRaw
    ? (() => {
      const card = record(openCardRaw, "brandDecisions.open_card");
      const options = arr(card.options, "brandDecisions.open_card.options").map((item, index) => {
        const option = record(item, `brandDecisions.open_card.options[${index}]`);
        return {
          option_id: nonEmptyStr(option.option_id, `brandDecisions.open_card.options[${index}].option_id`),
          label: nonEmptyStr(option.label, `brandDecisions.open_card.options[${index}].label`),
          detail: readTreatmentDetail(option.detail),
      why: optionalStr(option.why, `brandDecisions.open_card.options[${index}].why`),
        };
      });
      return {
        card_id: nonEmptyStr(card.card_id, "brandDecisions.open_card.card_id"),
        stage: stage(card.stage, "brandDecisions.open_card.stage"),
        stage_revision: int(card.stage_revision, "brandDecisions.open_card.stage_revision"),
        target_slot_id: optionalStr(card.target_slot_id, "brandDecisions.open_card.target_slot_id"),
        question: str(card.question, "brandDecisions.open_card.question"),
        options,
      } satisfies BrandDecisionPanelV1["open_card"];
    })()
    : null;
  const hypotheses = arr(root.hypotheses ?? [], "brandDecisions.hypotheses").map((item, index) => {
    const candidate = record(item, `brandDecisions.hypotheses[${index}]`);
    return {
      candidate_id: nonEmptyStr(candidate.candidate_id, `brandDecisions.hypotheses[${index}].candidate_id`),
      label: nonEmptyStr(candidate.label, `brandDecisions.hypotheses[${index}].label`),
      insight: str(candidate.insight, `brandDecisions.hypotheses[${index}].insight`),
      mechanism: str(candidate.mechanism, `brandDecisions.hypotheses[${index}].mechanism`),
      hypothesis: str(candidate.hypothesis, `brandDecisions.hypotheses[${index}].hypothesis`),
      product_role: str(candidate.product_role, `brandDecisions.hypotheses[${index}].product_role`),
      hook_mechanism: str(candidate.hook_mechanism, `brandDecisions.hypotheses[${index}].hook_mechanism`),
      why: optionalStr(candidate.why, `brandDecisions.hypotheses[${index}].why`),
    } satisfies BrandDecisionPanelV1["hypotheses"][number];
  });
  const adspecRaw = root.adspec;
  const adspec = adspecRaw
    ? {
      items: arr(record(adspecRaw, "brandDecisions.adspec").items ?? [], "brandDecisions.adspec.items").map(
        (item, index) => {
          const entry = record(item, `brandDecisions.adspec.items[${index}]`);
          return {
            item_key: nonEmptyStr(entry.item_key, `brandDecisions.adspec.items[${index}].item_key`),
            item_text: str(entry.item_text, `brandDecisions.adspec.items[${index}].item_text`),
            state: adSpecState(entry.state, `brandDecisions.adspec.items[${index}].state`),
          };
        },
      ),
    }
    : null;
  const skillStackRaw = root.skill_stack;
  const skillStack = skillStackRaw
    ? {
      entries: arr(record(skillStackRaw, "brandDecisions.skill_stack").entries ?? [], "brandDecisions.skill_stack.entries").map(
        (item, index) => {
          const entry = record(item, `brandDecisions.skill_stack.entries[${index}]`);
          return {
            skill_kind: skillKind(entry.skill_kind, `brandDecisions.skill_stack.entries[${index}].skill_kind`),
            skill_id: nonEmptyStr(entry.skill_id, `brandDecisions.skill_stack.entries[${index}].skill_id`),
            title: str(entry.title, `brandDecisions.skill_stack.entries[${index}].title`),
            version: optionalStr(entry.version, `brandDecisions.skill_stack.entries[${index}].version`),
            reason: optionalStr(entry.reason, `brandDecisions.skill_stack.entries[${index}].reason`),
            selected: entry.selected === undefined ? true : bool(entry.selected, `brandDecisions.skill_stack.entries[${index}].selected`),
          };
        },
      ),
    }
    : null;
  const treatmentSteps = arr(root.treatment_steps ?? [], "brandDecisions.treatment_steps").map((item, index) => {
    const step = record(item, `brandDecisions.treatment_steps[${index}]`);
    return {
      step_key: treatmentStepKey(step.step_key, `brandDecisions.treatment_steps[${index}].step_key`),
      selected_label: str(step.selected_label, `brandDecisions.treatment_steps[${index}].selected_label`),
      detail: typeof step.detail === "string" ? step.detail : "",
      structured_detail: readTreatmentDetail(step.structured_detail),
      confirmed_at: isoStr(step.confirmed_at, `brandDecisions.treatment_steps[${index}].confirmed_at`),
    } satisfies BrandDecisionPanelV1["treatment_steps"][number];
  });
  return {
    project_id: nonEmptyStr(root.project_id, "brandDecisions.project_id"),
    workflow_id: nonEmptyStr(root.workflow_id, "brandDecisions.workflow_id"),
    mode: root.mode === "brand" ? "brand" : "creation",
    journey: {
      policy_version: "brand_professional_v1",
      stage: stage(journey.stage, "brandDecisions.journey.stage"),
      treatment_substep: optionalStr(journey.treatment_substep, "brandDecisions.journey.treatment_substep"),
      stage_revision: int(journey.stage_revision, "brandDecisions.journey.stage_revision"),
      stage_status: journey.stage_status === "working"
        || journey.stage_status === "waiting_user"
        || journey.stage_status === "completed"
        ? journey.stage_status
        : "ready",
    },
    brand_name: str(root.brand_name, "brandDecisions.brand_name"),
    slot_values: slotValues,
    open_card: openCard,
    hypotheses,
    selected_hypothesis_id: optionalStr(root.selected_hypothesis_id, "brandDecisions.selected_hypothesis_id"),
    adspec,
    skill_stack: skillStack,
    treatment_steps: treatmentSteps,
    treatment_locked: root.treatment_locked === true,
    brand_profile: readBrandBrief(root.brand_profile),
    campaign_brief: readBrandBrief(root.campaign_brief),
    treatment_document: readTreatmentDocument(root.treatment_document),
  };
}

export function normalizeBrandInspectionConversation(
  value: unknown,
): BrandInspectionConversationTurnV1[] {
  const root = record(value, "brandInspection");
  const turns = arr(root.turns ?? [], "brandInspection.turns");
  return turns.map((item, index) => {
    const turn = record(item, `brandInspection.turns[${index}]`);
    return {
      turn_id: nonEmptyStr(turn.turn_id, `brandInspection.turns[${index}].turn_id`),
      role: turn.role === "user" ? "user" : turn.role === "system" ? "system" : "assistant",
      text: typeof turn.text === "string" ? turn.text : "",
      status: optionalStr(turn.status, `brandInspection.turns[${index}].status`),
      error_code: optionalStr(turn.error_code, `brandInspection.turns[${index}].error_code`),
      created_at: optionalStr(turn.created_at, `brandInspection.turns[${index}].created_at`),
    } satisfies BrandInspectionConversationTurnV1;
  });
}

export function normalizeBrandCreativeMethods(value: unknown): { items: BrandCreativeMethod[] } {
  const root = record(value, "brandCreativeMethods");
  return { items: arr(root.items, "brandCreativeMethods.items").map((item, index) => {
    const path = `brandCreativeMethods.items[${index}]`;
    const entry = record(item, path);
    if (entry.skill_kind !== "creative_method") fail(path, "expected creative method");
    return {
      skill_kind: "creative_method",
      skill_id: nonEmptyStr(entry.skill_id, `${path}.skill_id`),
      version: nonEmptyStr(entry.version, `${path}.version`),
      title: str(entry.title, `${path}.title`),
      summary: str(entry.summary, `${path}.summary`),
    };
  }) };
}

export function normalizeBrandInspectionDecisionLog(
  value: unknown,
): BrandDecisionLogEntryV1[] {
  const root = record(value, "brandInspection");
  const entries = arr(root.entries ?? [], "brandInspection.entries");
  return entries.map((item, index) => {
    const entry = record(item, `brandInspection.entries[${index}]`);
    return {
      log_id: nonEmptyStr(entry.log_id, `brandInspection.entries[${index}].log_id`),
      stage: stage(entry.stage, `brandInspection.entries[${index}].stage`),
      action: decisionAction(entry.action, `brandInspection.entries[${index}].action`),
      target_type: str(entry.target_type, `brandInspection.entries[${index}].target_type`),
      target_id: optionalStr(entry.target_id, `brandInspection.entries[${index}].target_id`),
      detail: entry.detail && typeof entry.detail === "object" && !Array.isArray(entry.detail)
        ? entry.detail as Record<string, unknown>
        : {},
      created_at: optionalStr(entry.created_at, `brandInspection.entries[${index}].created_at`),
    } satisfies BrandDecisionLogEntryV1;
  });
}

export function normalizeBrandInspectionTraces(value: unknown): unknown[] {
  const root = record(value, "brandInspection");
  return Array.isArray(root.traces) ? root.traces : [];
}

export function normalizeBrandOptionCardV1(
  value: unknown,
): BrandOptionCardV1 {
  const card = record(value, "brandOptionCard");
  const options = arr(card.options ?? [], "brandOptionCard.options").map((item, index) => {
    const option = record(item, `brandOptionCard.options[${index}]`);
    return {
      option_id: nonEmptyStr(option.option_id, `brandOptionCard.options[${index}].option_id`),
      label: nonEmptyStr(option.label, `brandOptionCard.options[${index}].label`),
      detail: readTreatmentDetail(option.detail),
      why: optionalStr(option.why, `brandOptionCard.options[${index}].why`),
    };
  });
  return {
    card_id: nonEmptyStr(card.card_id, "brandOptionCard.card_id"),
    stage: stage(card.stage, "brandOptionCard.stage"),
    stage_revision: int(card.stage_revision, "brandOptionCard.stage_revision"),
    target_slot_id: optionalStr(card.target_slot_id, "brandOptionCard.target_slot_id"),
    question: str(card.question, "brandOptionCard.question"),
    options,
  };
}

export function normalizeBrandJourneyStateV1(value: unknown): BrandJourneyStateV1 {
  const root = record(value, "brandJourney");
  const status = root.stage_status;
  return {
    policy_version: str(root.policy_version ?? "brand_professional_v1", "brandJourney.policy_version"),
    stage: stage(root.stage, "brandJourney.stage"),
    treatment_substep: optionalStr(root.treatment_substep, "brandJourney.treatment_substep"),
    stage_revision: int(root.stage_revision, "brandJourney.stage_revision"),
    stage_status: status === "working" || status === "waiting_user" || status === "completed"
      ? status
      : "ready",
  };
}

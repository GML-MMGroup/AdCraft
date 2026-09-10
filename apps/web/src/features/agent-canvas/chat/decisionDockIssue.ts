import { isV2ApiError } from "../../../api/agentCanvasApi.ts";

export interface DecisionDockIssue {
  code?: string | null;
  summary: string;
  detail: string | null;
  fieldId: string | null;
  retryable: boolean;
}

const STALE_CODES = new Set([
  "guided_interaction_stale",
  "guidance_revision_conflict",
  "journey_revision_conflict",
  "guided_reference_source_kind_invalid",
  "guided_reference_source_target_invalid",
  "guided_reference_source_revision_conflict",
]);

const REFERENCE_CANDIDATE_INVALID_CODES = new Set([
  "guided_reference_source_asset_not_found",
  "guided_reference_source_asset_foreign_workflow",
  "reference_candidate_not_found",
  "guided_reference_source_asset_unreadable",
  "guided_reference_source_asset_not_image",
]);

function technicalDetail(error: unknown): string | null {
  if (isV2ApiError(error)) {
    return error.code ? `${error.code}: ${error.message}` : error.message;
  }
  return error instanceof Error && error.message.trim() ? error.message.trim() : null;
}

export function isDecisionDockStaleError(error: unknown): boolean {
  return isV2ApiError(error) && Boolean(error.code && STALE_CODES.has(error.code));
}

export function isReferenceCandidateInvalidIssue(
  issue: DecisionDockIssue | null,
): boolean {
  return Boolean(issue?.code && REFERENCE_CANDIDATE_INVALID_CODES.has(issue.code));
}

export function decisionDockIssueFromError(error: unknown): DecisionDockIssue {
  const detail = technicalDetail(error);
  const code = isV2ApiError(error) ? error.code ?? null : null;
  if (isV2ApiError(error) && error.code === "guided_duration_value_invalid") {
    return {
      code,
      summary: "Choose one of the supported duration values.",
      detail,
      fieldId: "production_duration_seconds",
      retryable: true,
    };
  }
  if (isDecisionDockStaleError(error)) {
    return {
      code,
      summary: "The workflow changed before this response was saved. Review the latest options and try again.",
      detail,
      fieldId: null,
      retryable: true,
    };
  }
  if (error instanceof Error && error.name === "V2NetworkError") {
    return {
      code,
      summary: "Connection interrupted. Check your connection and try again.",
      detail,
      fieldId: null,
      retryable: true,
    };
  }
  if (isV2ApiError(error) && error.status === 422) {
    return {
      code,
      summary: "Review this response and try again.",
      detail,
      fieldId: null,
      retryable: true,
    };
  }
  if (isV2ApiError(error) && error.status >= 500) {
    return {
      code,
      summary: "The agent could not submit this response. Try again.",
      detail,
      fieldId: null,
      retryable: true,
    };
  }
  return {
    code,
    summary: "The guided response could not be submitted.",
    detail,
    fieldId: null,
    retryable: true,
  };
}

const PRODUCT_SOURCE_ASSET_CODES = new Set([
  "guided_product_asset_not_found",
  "guided_product_asset_foreign_workflow",
  "guided_product_asset_not_image",
  "guided_product_asset_unreadable",
]);

const PRODUCT_SOURCE_COMPILER_CODES = new Set([
  "guided_product_multiview_compilation_failed",
  "guided_product_ffmpeg_unavailable",
]);

export function productSourceDecisionDockIssueFromCode(
  code: string,
  detail = code,
): DecisionDockIssue {
  if (code === "guided_product_multiview_count_invalid") {
    return {
      summary: "Select the required number of Product images and try again.",
      detail,
      fieldId: null,
      retryable: true,
    };
  }
  if (PRODUCT_SOURCE_ASSET_CODES.has(code)) {
    return {
      summary: "One of the selected Product images is unavailable. Replace it and try again.",
      detail,
      fieldId: null,
      retryable: true,
    };
  }
  if (PRODUCT_SOURCE_COMPILER_CODES.has(code)) {
    return {
      summary: "The Product views could not be compiled. Your uploaded images are still available.",
      detail,
      fieldId: null,
      retryable: true,
    };
  }
  return {
    summary: "The Product source could not be applied. Review the selected images and try again.",
    detail,
    fieldId: null,
    retryable: true,
  };
}

export function productSourceDecisionDockIssueFromError(error: unknown): DecisionDockIssue {
  if (isV2ApiError(error) && error.code && !isDecisionDockStaleError(error)) {
    return productSourceDecisionDockIssueFromCode(error.code, technicalDetail(error) ?? error.code);
  }
  return decisionDockIssueFromError(error);
}

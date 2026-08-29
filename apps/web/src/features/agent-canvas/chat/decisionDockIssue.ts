import { isV2ApiError } from "../../../api/agentCanvasApi.ts";

export interface DecisionDockIssue {
  summary: string;
  detail: string | null;
  fieldId: string | null;
  retryable: boolean;
}

const STALE_CODES = new Set([
  "guided_interaction_stale",
  "guidance_revision_conflict",
  "journey_revision_conflict",
]);

function technicalDetail(error: unknown): string | null {
  if (isV2ApiError(error)) {
    return error.code ? `${error.code}: ${error.message}` : error.message;
  }
  return error instanceof Error && error.message.trim() ? error.message.trim() : null;
}

export function isDecisionDockStaleError(error: unknown): boolean {
  if (!isV2ApiError(error)) return false;
  if (Boolean(error.code && STALE_CODES.has(error.code))) return true;
  // Revision preconditions can be reported without a stable error code. Keep
  // 422 validation errors (for example invalid duration values) actionable in
  // the dock, while treating explicit stale/conflict wording as authority
  // failures that require a timeline refresh.
  if (![409, 412, 422].includes(error.status)) return false;
  const text = `${error.code ?? ""} ${error.message}`.toLowerCase();
  if (/(stale|supersed|revision|precondition|conflict|no longer current)/.test(text)) return true;
  // Some gateways omit the detail message but retain the optimistic-lock
  // fields in the structured payload.
  return Object.keys(error.details).some((key) =>
    /(revision|expected|current|precondition)/i.test(key)
  );
}

export function decisionDockIssueFromError(error: unknown): DecisionDockIssue {
  const detail = technicalDetail(error);
  if (isV2ApiError(error) && error.code === "guided_duration_value_invalid") {
    return {
      summary: "Choose one of the supported duration values.",
      detail,
      fieldId: "production_duration_seconds",
      retryable: true,
    };
  }
  if (isDecisionDockStaleError(error)) {
    return {
      summary: "The workflow changed before this response was saved. Review the latest options and try again.",
      detail,
      fieldId: null,
      retryable: true,
    };
  }
  if (error instanceof Error && error.name === "V2NetworkError") {
    return {
      summary: "Connection interrupted. Check your connection and try again.",
      detail,
      fieldId: null,
      retryable: true,
    };
  }
  if (isV2ApiError(error) && error.status === 422) {
    return {
      summary: "Review this response and try again.",
      detail,
      fieldId: null,
      retryable: true,
    };
  }
  if (isV2ApiError(error) && error.status >= 500) {
    return {
      summary: "The agent could not submit this response. Try again.",
      detail,
      fieldId: null,
      retryable: true,
    };
  }
  return {
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

import type { GraphValidationIssue, GraphValidationResult } from "../../../types.ts";

export function normalizeGraphValidationResult(value: unknown): GraphValidationResult {
  if (!value || typeof value !== "object") {
    return {
      valid: false,
      errors: [{ level: "error", code: "invalid_validation_response", message: "Invalid graph validation response." }],
      warnings: [],
    };
  }

  const record = value as Record<string, unknown>;
  const errors = normalizeValidationIssues(record.errors, "error");
  const warnings = normalizeValidationIssues(record.warnings, "warning");
  const detailIssues = normalizeValidationIssues(record.detail, "error");
  const allErrors = errors.length ? errors : detailIssues;
  return {
    valid: typeof record.valid === "boolean" ? record.valid : allErrors.length === 0,
    errors: allErrors,
    warnings,
  };
}

export function validationIssues(result: GraphValidationResult | null | undefined, key: "errors" | "warnings") {
  return normalizeValidationIssues(result?.[key], key === "errors" ? "error" : "warning");
}

function normalizeValidationIssues(value: unknown, fallbackLevel: GraphValidationIssue["level"]): GraphValidationIssue[] {
  if (!value) return [];
  if (Array.isArray(value)) {
    return value.map((item, index) => normalizeValidationIssue(item, fallbackLevel, index));
  }
  return [normalizeValidationIssue(value, fallbackLevel, 0)];
}

function normalizeValidationIssue(value: unknown, fallbackLevel: GraphValidationIssue["level"], index: number): GraphValidationIssue {
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const level = record.level === "warning" || record.level === "info" || record.level === "error" ? record.level : fallbackLevel;
    const loc = Array.isArray(record.loc) ? record.loc.join(".") : "";
    return {
      level,
      code: typeof record.code === "string" ? record.code : typeof record.type === "string" ? record.type : `validation_${index}`,
      node_id: typeof record.node_id === "string" ? record.node_id : undefined,
      edge_id: typeof record.edge_id === "string" ? record.edge_id : undefined,
      message: typeof record.message === "string" ? record.message : typeof record.msg === "string" ? `${loc ? `${loc}: ` : ""}${record.msg}` : JSON.stringify(record),
    };
  }
  return {
    level: fallbackLevel,
    code: `validation_${index}`,
    message: String(value),
  };
}

export function firstIssueMessage(issues: unknown) {
  return normalizeValidationIssues(issues, "error")[0]?.message;
}

import { NodeWorkbenchFieldError } from "./NodeWorkbenchFeedback.tsx";
import type { ModelParameterDescriptorV1 } from "../../../api/providerRegistry.ts";
import { InlineParameterSelect } from "./InlineParameterSelect.tsx";
import {
  modelParameterLabel,
  validateModelParameters,
} from "./modelParameterDescriptors.ts";
import { useTranslation } from "../../../i18n/useTranslation.ts";
import { resolutionAspectRatio } from "./resolutionAspectRatio.ts";

function updateParameter(
  parameters: Readonly<Record<string, unknown>>,
  name: string,
  value: unknown,
): Record<string, unknown> {
  const next = { ...parameters };
  if (value === undefined) delete next[name];
  else next[name] = value;
  return next;
}

export function ModelParameterControls({
  descriptors,
  parameters,
  disabled,
  onChange,
  layout = "grid",
}: {
  descriptors: readonly ModelParameterDescriptorV1[];
  parameters: Readonly<Record<string, unknown>>;
  disabled: boolean;
  onChange: (parameters: Record<string, unknown>) => void;
  layout?: "grid" | "inline";
}) {
  const t = useTranslation("en-US");
  if (!descriptors.length) return null;
  const issues = validateModelParameters(descriptors, parameters);
  const issueByName = new Map(issues.map((issue) => [issue.name, issue.message]));

  return (
    <div className={`agent-node-workbench__model-parameters${layout === "inline" ? " agent-node-workbench__model-parameters--inline" : ""}`} aria-label={t("Model parameters")}>
      {descriptors.map((descriptor) => {
        const label = modelParameterLabel(descriptor.name);
        const value = parameters[descriptor.name];
        const issue = issueByName.get(descriptor.name);
        if (descriptor.value_type === "boolean") {
          return (
            <div className="agent-node-workbench__parameter" key={descriptor.name}>
              <label className="agent-node-workbench__parameter-toggle">
                <input
                  aria-label={label}
                  type="checkbox"
                  checked={value === true}
                  disabled={disabled}
                  onChange={(event) => onChange(updateParameter(
                    parameters,
                    descriptor.name,
                    event.currentTarget.checked,
                  ))}
                />
                <span>{label}</span>
              </label>
              {value !== undefined ? (
                <button
                  type="button"
                  className="agent-node-workbench__parameter-clear"
                    aria-label={t("Clear {label}", { label })}
                  disabled={disabled}
                  onClick={() => onChange(updateParameter(parameters, descriptor.name, undefined))}
                >
                    {t("Clear")}
                </button>
              ) : null}
              {issue ? <NodeWorkbenchFieldError><span>{label}: </span><span>{issue}</span></NodeWorkbenchFieldError> : null}
            </div>
          );
        }
        if (layout === "inline" && descriptor.value_type === "enum") {
          return (
            <div className="agent-node-workbench__parameter" key={descriptor.name}>
              <InlineParameterSelect
                label={label}
                value={typeof value === "string" ? value : ""}
                options={descriptor.allowed_values}
                valueSuffix={descriptor.name === "duration_seconds" ? "s" : undefined}
                disabled={disabled}
                onChange={(next) => onChange(updateParameter(parameters, descriptor.name, next))}
              />
              {issue ? <NodeWorkbenchFieldError><span>{label}: </span><span>{issue}</span></NodeWorkbenchFieldError> : null}
            </div>
          );
        }
        if (layout === "inline" && descriptor.name === "duration_seconds"
          && (descriptor.value_type === "integer" || descriptor.value_type === "number")) {
          return (
            <label className="agent-node-workbench__parameter" key={descriptor.name}>
              <span className="agent-node-workbench__duration-control" title={t("Duration (s)")}>
                <input
                  aria-label={label}
                  type="number"
                  min={descriptor.minimum ?? undefined}
                  max={descriptor.maximum ?? undefined}
                  step={descriptor.value_type === "integer" ? 1 : "any"}
                  value={typeof value === "number" ? value : ""}
                  placeholder="auto"
                  style={{ width: `${typeof value === "number" ? Math.max(1, String(value).length) : 4}ch` }}
                  disabled={disabled}
                  onChange={(event) => onChange(updateParameter(
                    parameters, descriptor.name,
                    event.currentTarget.value === "" ? undefined : event.currentTarget.valueAsNumber,
                  ))}
                />
                {typeof value === "number" ? <span aria-hidden="true">s</span> : null}
              </span>
              {issue ? <NodeWorkbenchFieldError><span>{label}: </span><span>{issue}</span></NodeWorkbenchFieldError> : null}
            </label>
          );
        }
        return (
          <label className="agent-node-workbench__parameter" key={descriptor.name}>
            {layout === "grid" ? <span title={label}>{label}</span> : null}
            {descriptor.value_type === "enum" ? (
              <select
                aria-label={label}
                value={typeof value === "string" ? value : ""}
                disabled={disabled}
                onChange={(event) => onChange(updateParameter(
                  parameters,
                  descriptor.name,
                  event.currentTarget.value || undefined,
                ))}
              >
                <option value="">{t("Not set")}</option>
                {typeof value === "string" && !descriptor.allowed_values.includes(value) ? (
                  <option value={value}>{t("{value} (unsupported)", { value })}</option>
                ) : null}
                {descriptor.allowed_values.map((option) => (
                  <option value={option} key={option}>
                    {resolutionAspectRatio(option)
                      ? t("{value} ({ratio})", { value: option, ratio: resolutionAspectRatio(option)! })
                      : option}
                  </option>
                ))}
              </select>
            ) : descriptor.value_type === "string" ? (
              <input
                aria-label={label}
                type="text"
                value={typeof value === "string" ? value : ""}
                disabled={disabled}
                onChange={(event) => onChange(updateParameter(
                  parameters,
                  descriptor.name,
                  event.currentTarget.value || undefined,
                ))}
              />
            ) : (
              <input
                aria-label={label}
                type="number"
                min={descriptor.minimum ?? undefined}
                max={descriptor.maximum ?? undefined}
                step={descriptor.value_type === "integer" ? 1 : "any"}
                value={typeof value === "number" ? value : ""}
                disabled={disabled}
                onChange={(event) => onChange(updateParameter(
                  parameters,
                  descriptor.name,
                  event.currentTarget.value === "" ? undefined : event.currentTarget.valueAsNumber,
                ))}
              />
            )}
            {issue ? <NodeWorkbenchFieldError><span>{label}: </span><span>{issue}</span></NodeWorkbenchFieldError> : null}
          </label>
        );
      })}
    </div>
  );
}

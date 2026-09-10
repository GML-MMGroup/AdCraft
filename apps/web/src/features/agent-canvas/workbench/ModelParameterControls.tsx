import type { ModelParameterDescriptorV1 } from "../../../api/providerRegistry.ts";
import { InlineParameterSelect } from "./InlineParameterSelect.tsx";
import {
  modelParameterLabel,
  validateModelParameters,
} from "./modelParameterDescriptors.ts";

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
  if (!descriptors.length) return null;
  const issues = validateModelParameters(descriptors, parameters);
  const issueByName = new Map(issues.map((issue) => [issue.name, issue.message]));

  return (
    <div className={`agent-node-workbench__model-parameters${layout === "inline" ? " agent-node-workbench__model-parameters--inline" : ""}`} aria-label="Model parameters">
      {descriptors.map((descriptor) => {
        const label = modelParameterLabel(descriptor.name);
        const displayLabel = layout === "inline"
          ? descriptor.name === "duration_seconds" ? "Duration (s)" : descriptor.name === "aspect_ratio" ? "Ratio" : label
          : label;
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
                  aria-label={`Clear ${label}`}
                  disabled={disabled}
                  onClick={() => onChange(updateParameter(parameters, descriptor.name, undefined))}
                >
                  Clear
                </button>
              ) : null}
              {issue ? <p className="agent-node-workbench__field-error">{issue}</p> : null}
            </div>
          );
        }
        if (layout === "inline" && descriptor.value_type === "enum") {
          return (
            <div className="agent-node-workbench__parameter" key={descriptor.name}>
              <span title={label}>{displayLabel}</span>
              <InlineParameterSelect
                label={label}
                value={typeof value === "string" ? value : ""}
                options={descriptor.allowed_values}
                disabled={disabled}
                onChange={(next) => onChange(updateParameter(parameters, descriptor.name, next))}
              />
              {issue ? <p className="agent-node-workbench__field-error">{issue}</p> : null}
            </div>
          );
        }
        return (
          <label className="agent-node-workbench__parameter" key={descriptor.name}>
            <span title={label}>{displayLabel}</span>
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
                <option value="">Not set</option>
                {typeof value === "string" && !descriptor.allowed_values.includes(value) ? (
                  <option value={value}>{value} (unsupported)</option>
                ) : null}
                {descriptor.allowed_values.map((option) => (
                  <option value={option} key={option}>{option}</option>
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
            {issue ? <p className="agent-node-workbench__field-error">{issue}</p> : null}
          </label>
        );
      })}
    </div>
  );
}

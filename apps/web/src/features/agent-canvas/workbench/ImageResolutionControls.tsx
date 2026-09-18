import type { ImageResolutionCapabilitiesV1 } from "../../../api/providerRegistry.ts";
import {
  defaultImageResolutionParameter,
  IMAGE_ASPECT_RATIO_PARAMETER,
  IMAGE_RESOLUTION_PARAMETER,
  IMAGE_SIZE_PARAMETER,
  imageResolutionIssues,
  imageResolutionPairOptions,
  imageResolutionParameter,
  type ImageResolutionPairParameter,
} from "./imageResolutionCapabilities.ts";

function parameterSelect({
  label,
  name,
  value,
  options,
  disabled,
  onChange,
}: {
  label: string;
  name: string;
  value: string;
  options: readonly string[];
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className="agent-node-workbench__parameter" key={name}>
      <span title={label}>{label}</span>
      <select
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.currentTarget.value)}
      >
        <option value="">Not set</option>
        {value && !options.includes(value) ? (
          <option value={value}>{value} (unsupported)</option>
        ) : null}
        {options.map((option) => (
          <option value={option} key={option}>{option}</option>
        ))}
      </select>
    </label>
  );
}

export function ImageResolutionControls({
  capabilities,
  parameters,
  disabled,
  onChange,
}: {
  capabilities: ImageResolutionCapabilitiesV1;
  parameters: Readonly<Record<string, unknown>>;
  disabled: boolean;
  onChange: (parameters: Record<string, unknown>) => void;
}) {
  const modes = capabilities.parameter_modes;
  const issues = imageResolutionIssues(capabilities, parameters);
  const issueByName = new Map(issues.map((issue) => [issue.name, issue.message]));

  const selectSize = (value: string) => {
    const next = { ...parameters };
    delete next[IMAGE_RESOLUTION_PARAMETER];
    delete next[IMAGE_ASPECT_RATIO_PARAMETER];
    if (value) next[IMAGE_SIZE_PARAMETER] = value;
    else delete next[IMAGE_SIZE_PARAMETER];
    onChange(next);
  };

  const selectPair = (name: ImageResolutionPairParameter, value: string) => {
    const otherName: ImageResolutionPairParameter = name === IMAGE_RESOLUTION_PARAMETER
      ? IMAGE_ASPECT_RATIO_PARAMETER
      : IMAGE_RESOLUTION_PARAMETER;
    // A resolution without its aspect ratio (or the reverse) is rejected by the
    // adapter, so the counterpart falls back to its default or first option.
    const otherValue = imageResolutionParameter(parameters, otherName)
      ?? defaultImageResolutionParameter(capabilities, otherName)
      ?? imageResolutionPairOptions(capabilities, otherName)[0];
    const next = { ...parameters };
    delete next[IMAGE_SIZE_PARAMETER];
    if (value) next[name] = value;
    else delete next[name];
    if (otherValue) next[otherName] = otherValue;
    else delete next[otherName];
    onChange(next);
  };

  return (
    <div className="agent-node-workbench__model-parameters" aria-label="Image resolution">
      {modes.includes("size")
        ? parameterSelect({
          label: "Size",
          name: IMAGE_SIZE_PARAMETER,
          value: imageResolutionParameter(parameters, IMAGE_SIZE_PARAMETER)
            ?? defaultImageResolutionParameter(capabilities, IMAGE_SIZE_PARAMETER)
            ?? "",
          options: capabilities.size_options,
          disabled,
          onChange: selectSize,
        })
        : null}
      {modes.includes("resolution_with_aspect_ratio")
        ? ([IMAGE_RESOLUTION_PARAMETER, IMAGE_ASPECT_RATIO_PARAMETER] as const).map((name) => (
          <div key={name}>
            {parameterSelect({
              label: name === IMAGE_RESOLUTION_PARAMETER ? "Resolution" : "Ratio",
              name,
              value: imageResolutionParameter(parameters, name)
                ?? defaultImageResolutionParameter(capabilities, name)
                ?? "",
              options: imageResolutionPairOptions(capabilities, name),
              disabled,
              onChange: (value) => selectPair(name, value),
            })}
            {issueByName.get(name) ? (
              <p className="agent-node-workbench__field-error">{issueByName.get(name)}</p>
            ) : null}
          </div>
        ))
        : null}
    </div>
  );
}

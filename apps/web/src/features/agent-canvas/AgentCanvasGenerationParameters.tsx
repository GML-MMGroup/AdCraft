import type { ProviderModelCapabilityV2 } from "../../types-v2.ts";

type GenerationParameters = Record<string, unknown>;

export function AgentCanvasGenerationParameters({
  capability,
  parameters,
  disabled,
  onChange,
}: {
  capability: ProviderModelCapabilityV2 | null;
  parameters: GenerationParameters;
  disabled: boolean;
  onChange: (parameters: GenerationParameters) => void;
}) {
  if (!capability) return null;
  const supported = new Set(capability.supported_parameters);

  function update(name: string, value: unknown) {
    const next = structuredClone(parameters);
    if (value === "" || value === undefined) {
      delete next[name];
    } else {
      next[name] = value;
    }
    onChange(next);
  }

  return (
    <div className="agent-canvas-inspector__parameters" aria-label="Generation parameters">
      {supported.has("aspect_ratio") && capability.supported_aspect_ratios.length ? (
        <label>
          <span>Aspect ratio</span>
          <select
            value={typeof parameters.aspect_ratio === "string" ? parameters.aspect_ratio : ""}
            disabled={disabled}
            onChange={(event) => update("aspect_ratio", event.currentTarget.value)}
          >
            <option value="">Automatic</option>
            {capability.supported_aspect_ratios.map((aspectRatio) => (
              <option value={aspectRatio} key={aspectRatio}>{aspectRatio}</option>
            ))}
          </select>
        </label>
      ) : null}

      {supported.has("duration_seconds") ? (
        <label>
          <span>Duration (seconds)</span>
          <input
            type="number"
            value={numberInputValue(parameters.duration_seconds)}
            min={capability.duration_range_seconds?.[0]}
            max={capability.duration_range_seconds?.[1]}
            step="1"
            disabled={disabled}
            onChange={(event) => update(
              "duration_seconds",
              event.currentTarget.value === "" ? "" : Number(event.currentTarget.value),
            )}
          />
        </label>
      ) : null}

      {supported.has("size") ? (
        <label>
          <span>Image size</span>
          <input
            value={typeof parameters.size === "string" ? parameters.size : ""}
            placeholder="1024x1024"
            disabled={disabled}
            onChange={(event) => update("size", event.currentTarget.value)}
          />
        </label>
      ) : null}

      {supported.has("resolution") ? (
        <label>
          <span>Resolution</span>
          <input
            value={typeof parameters.resolution === "string" ? parameters.resolution : ""}
            placeholder="1920x1080"
            disabled={disabled}
            onChange={(event) => update("resolution", event.currentTarget.value)}
          />
        </label>
      ) : null}

      {supported.has("generate_audio") ? (
        <label className="agent-canvas-inspector__toggle">
          <input
            type="checkbox"
            checked={parameters.generate_audio === true}
            disabled={disabled}
            onChange={(event) => update("generate_audio", event.currentTarget.checked)}
          />
          <span>Generate native audio</span>
        </label>
      ) : null}
    </div>
  );
}

function numberInputValue(value: unknown): number | "" {
  return typeof value === "number" && Number.isFinite(value) ? value : "";
}

import { useMemo, useState } from "react";

import type { ProviderModelSummaryV1 } from "../../../api/providerRegistry.ts";
import type {
  CanvasModelSelectionModeV2,
  CanvasModelSummaryV2,
  CanvasRuntimeModelResolutionV2,
} from "../../../types-v2.ts";

function modelSummaryLabel(model: Pick<ProviderModelSummaryV1, "display_name" | "provider_id" | "capability">): string {
  return `${model.display_name} · ${model.provider_id} · ${model.capability}`;
}

function modelFromNodeSummary(summary: CanvasModelSummaryV2): ProviderModelSummaryV1 {
  return {
    model_ref: summary.model_ref,
    provider_id: summary.provider_id,
    provider_model_id: summary.model_ref,
    display_name: summary.display_name,
    capability: summary.capability,
    capability_metadata: {},
    availability: summary.availability,
    unavailable_reason: summary.unavailable_reason,
    catalog_revision: summary.catalog_revision,
  };
}

export function CanvasModelPicker({
  models,
  loading,
  error,
  selectionMode,
  modelRef,
  modelSummary,
  modelResolution,
  disabled,
  onChange,
}: {
  models: ProviderModelSummaryV1[];
  loading: boolean;
  error: string | null;
  selectionMode: CanvasModelSelectionModeV2;
  modelRef: string | null;
  modelSummary: CanvasModelSummaryV2 | null;
  modelResolution?: CanvasRuntimeModelResolutionV2 | null;
  disabled: boolean;
  onChange: (mode: CanvasModelSelectionModeV2, modelRef: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const selectedModel = useMemo(() => {
    if (selectionMode !== "explicit" || !modelRef) return null;
    return models.find((model) => model.model_ref === modelRef)
      ?? (modelSummary?.model_ref === modelRef ? modelFromNodeSummary(modelSummary) : null);
  }, [modelRef, modelSummary, models, selectionMode]);
  const selectedLabel = selectionMode === "default"
    ? "Default model"
    : selectedModel
      ? modelSummaryLabel(selectedModel)
      : `${modelRef ?? "Selected model"} · unavailable`;

  return (
    <div className="agent-node-workbench__model-picker">
      <span className="agent-node-workbench__model-label">Model</span>
      <details open={open} onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}>
        <summary aria-label="Choose model" aria-disabled={disabled || loading}>
          <span>{loading ? "Loading compatible models..." : selectedLabel}</span>
          {selectedModel ? <small className={`is-${selectedModel.availability}`}>{selectedModel.availability}</small> : null}
        </summary>
        <div className="agent-node-workbench__model-menu" role="listbox" aria-label="Compatible models">
          <button
            type="button"
            role="option"
            aria-selected={selectionMode === "default"}
            disabled={disabled}
            onClick={() => {
              onChange("default", null);
              setOpen(false);
            }}
          >
            <strong>Default model</strong>
            <small>Uses the current API Space default for this node type.</small>
          </button>
          {models.map((model) => {
            const available = model.availability === "available";
            const selected = selectionMode === "explicit" && modelRef === model.model_ref;
            return (
              <button
                type="button"
                role="option"
                aria-selected={selected}
                key={model.model_ref}
                disabled={disabled || !available}
                title={model.unavailable_reason ?? undefined}
                onClick={() => {
                  onChange("explicit", model.model_ref);
                  setOpen(false);
                }}
              >
                <strong>{model.display_name}</strong>
                <small>{model.provider_id} · {model.capability} · {model.availability}</small>
                {model.unavailable_reason ? <em>{model.unavailable_reason}</em> : null}
              </button>
            );
          })}
          {!models.length && !loading ? <p>No compatible models are currently available.</p> : null}
        </div>
      </details>
      {error ? <p className="agent-node-workbench__field-error">{error}</p> : null}
      {selectionMode === "explicit" && selectedModel?.unavailable_reason ? (
        <p className="agent-node-workbench__field-error">{selectedModel.unavailable_reason}</p>
      ) : null}
      {modelResolution ? (
        <p className="agent-node-workbench__model-resolution">
          Running with {modelResolution.provider_id} · {modelResolution.provider_model_id}
        </p>
      ) : null}
    </div>
  );
}

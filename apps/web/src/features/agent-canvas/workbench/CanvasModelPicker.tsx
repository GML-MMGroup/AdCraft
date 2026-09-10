import { createPortal } from "react-dom";
import { ChevronDownIcon, ChevronUpIcon } from "../../../icons.tsx";
import { useMemo } from "react";
import { useWorkbenchMenu } from "./useWorkbenchMenu.ts";

import type { ProviderModelSummaryV1 } from "../../../api/providerRegistry.ts";
import { modelEligibility } from "../../../api/providerModelPolicy.ts";
import type {
  CanvasModelSelectionModeV2,
  CanvasModelSummaryV2,
  CanvasRuntimeModelResolutionV2,
} from "../../../types-v2.ts";

function modelSummaryLabel(model: Pick<ProviderModelSummaryV1, "display_name" | "provider_id" | "capability">): string {
  return `${model.display_name} · ${model.provider_id} · ${model.capability}`;
}

function readableTransport(value: string): string {
  return value.replaceAll("_", " ");
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
  appearance = "default",
  showOptionDetails = true,
  showStatusDetails = true,
  defaultModelRef,
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
  appearance?: "default" | "monochrome";
  showOptionDetails?: boolean;
  showStatusDetails?: boolean;
  defaultModelRef?: string | null;
}) {
  const selectedModel = useMemo(() => {
    if (selectionMode !== "explicit" || !modelRef) return null;
    return models.find((model) => model.model_ref === modelRef)
      ?? (modelSummary?.model_ref === modelRef ? modelFromNodeSummary(modelSummary) : null);
  }, [modelRef, modelSummary, models, selectionMode]);
  const visibleModels = useMemo(
    () => models.filter((model) => modelEligibility(model, "diagnostic").visible),
    [models],
  );
  const defaultModelName = models.find((model) => model.model_ref === defaultModelRef)?.display_name;
  const defaultLabel = defaultModelRef === undefined
    ? "Default model"
    : `Default model · ${error ? "Unavailable" : defaultModelName ?? (defaultModelRef ? "Name unavailable" : "Not configured")}`;
  const selectedLabel = selectionMode === "default"
    ? defaultLabel
    : selectedModel
      ? showStatusDetails ? modelSummaryLabel(selectedModel) : selectedModel.display_name
      : `${modelRef ?? "Selected model"} · unavailable`;

  const { open, setOpen, menuStyle, triggerRef, menuRef } = useWorkbenchMenu(disabled || loading, visibleModels.length);

  const menu = open ? createPortal(
    <div
      ref={menuRef}
      className={`agent-node-workbench__model-menu${appearance === "monochrome" ? " agent-node-workbench__model-menu--monochrome" : ""}`}
      role="listbox"
      aria-label="Compatible models"
      style={menuStyle}
    >
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
        <strong>{defaultLabel}</strong>
        {showOptionDetails ? <small>Uses the current API Space default for this node type.</small> : null}
      </button>
      {visibleModels.map((model) => {
        const eligibility = modelEligibility(model, "diagnostic");
        const selected = selectionMode === "explicit" && modelRef === model.model_ref;
        return (
          <button
            type="button"
            role="option"
            aria-selected={selected}
            key={model.model_ref}
            disabled={disabled || !eligibility.selectable}
            title={eligibility.reason ?? undefined}
            onClick={() => {
              onChange("explicit", model.model_ref);
              setOpen(false);
            }}
          >
            <strong>{model.display_name}</strong>
            {showOptionDetails ? (
              <>
                <small>
                  {model.provider_id} · {model.capability} · {model.availability}
                  {model.conformance_status ? ` · ${model.conformance_status}` : ""}
                </small>
                {model.adapter_id && model.transport_kind && model.release_tier ? (
                  <small>
                    {model.adapter_id} · {readableTransport(model.transport_kind)} · {model.release_tier}
                  </small>
                ) : null}
                {eligibility.reason ? <em>{eligibility.reason}</em> : null}
              </>
            ) : null}
          </button>
        );
      })}
      {!visibleModels.length && !loading ? <p>No compatible models are currently available.</p> : null}
      {!showStatusDetails && error ? <p role="alert">{error}</p> : null}
    </div>,
    document.body,
  ) : null;

  return (
    <div className={`agent-node-workbench__model-picker${appearance === "monochrome" ? " agent-node-workbench__model-picker--monochrome" : ""}`}>
      <span className="agent-node-workbench__model-label">Model</span>
      <details
        open={open}
      >
        <summary
          ref={triggerRef}
          aria-label="Choose model"
          aria-expanded={open}
          aria-disabled={disabled || loading}
          title={!showStatusDetails ? error ?? (selectedModel ? modelEligibility(selectedModel, "diagnostic").reason ?? selectedLabel : selectedLabel) : undefined}
          onClick={(event) => {
            event.preventDefault();
            if (disabled || loading) {
              return;
            }
            setOpen((current) => !current);
          }}
        >
          <span>{loading ? "Loading compatible models..." : selectedLabel}</span>
          {showStatusDetails && selectedModel ? <small className={`is-${selectedModel.availability}`}>{selectedModel.availability}</small> : null}
          {appearance === "monochrome" ? (
            <span className="agent-node-workbench__model-chevron" aria-hidden="true">
              {open ? <ChevronDownIcon /> : <ChevronUpIcon />}
            </span>
          ) : null}
        </summary>
      </details>
      {menu}
      {showStatusDetails && error ? <p className="agent-node-workbench__field-error">{error}</p> : null}
      {showStatusDetails && selectionMode === "explicit" && selectedModel && !modelEligibility(selectedModel, "diagnostic").selectable ? (
        <p className="agent-node-workbench__field-error">
          {modelEligibility(selectedModel, "diagnostic").reason}
        </p>
      ) : null}
      {showStatusDetails && modelResolution ? (
        <p className="agent-node-workbench__model-resolution">
          Running with {modelResolution.provider_id} · {modelResolution.provider_model_id}
        </p>
      ) : null}
    </div>
  );
}

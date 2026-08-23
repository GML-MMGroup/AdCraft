import { createPortal } from "react-dom";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type { ProviderModelSummaryV1 } from "../../../api/providerRegistry.ts";
import type {
  CanvasModelSelectionModeV2,
  CanvasModelSummaryV2,
  CanvasRuntimeModelResolutionV2,
} from "../../../types-v2.ts";

const MODEL_MENU_MAX_HEIGHT = 236;
const MODEL_MENU_WIDTH = 360;
const MODEL_MENU_GAP = 5;
const VIEWPORT_GUTTER = 12;

interface ModelMenuPosition {
  top: number;
  left: number;
  width: number;
  maxHeight: number;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

function calculateModelMenuPosition(
  triggerRect: DOMRect,
  menuRect: DOMRect | null,
): ModelMenuPosition {
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const width = Math.min(
    MODEL_MENU_WIDTH,
    Math.max(0, viewportWidth - VIEWPORT_GUTTER * 2),
  );
  const maxHeight = Math.min(
    MODEL_MENU_MAX_HEIGHT,
    Math.max(120, viewportHeight - VIEWPORT_GUTTER * 2),
  );
  const menuHeight = Math.min(menuRect?.height || MODEL_MENU_MAX_HEIGHT, maxHeight);
  const canPlaceBelow = triggerRect.bottom + MODEL_MENU_GAP + menuHeight
    <= viewportHeight - VIEWPORT_GUTTER;
  const canPlaceAbove = triggerRect.top - MODEL_MENU_GAP - menuHeight >= VIEWPORT_GUTTER;
  const placeAbove = !canPlaceBelow && canPlaceAbove;
  const requestedTop = placeAbove
    ? triggerRect.top - MODEL_MENU_GAP - menuHeight
    : triggerRect.bottom + MODEL_MENU_GAP;
  const top = clamp(
    requestedTop,
    VIEWPORT_GUTTER,
    viewportHeight - menuHeight - VIEWPORT_GUTTER,
  );
  const left = clamp(
    triggerRect.left,
    VIEWPORT_GUTTER,
    viewportWidth - width - VIEWPORT_GUTTER,
  );

  return { top, left, width, maxHeight };
}

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
  const [menuPosition, setMenuPosition] = useState<ModelMenuPosition | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
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

  useEffect(() => {
    if (disabled || loading) {
      setOpen(false);
    }
  }, [disabled, loading]);

  useLayoutEffect(() => {
    if (!open) {
      setMenuPosition(null);
      return;
    }

    let frame: number | null = null;
    const updatePosition = () => {
      frame = null;
      const trigger = triggerRef.current;
      if (!trigger) return;
      setMenuPosition(calculateModelMenuPosition(
        trigger.getBoundingClientRect(),
        menuRef.current?.getBoundingClientRect() ?? null,
      ));
    };
    const schedulePositionUpdate = () => {
      if (frame !== null) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(updatePosition);
    };

    updatePosition();
    window.addEventListener("resize", schedulePositionUpdate);
    window.addEventListener("scroll", schedulePositionUpdate, true);
    return () => {
      if (frame !== null) window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", schedulePositionUpdate);
      window.removeEventListener("scroll", schedulePositionUpdate, true);
    };
  }, [models.length, open]);

  useEffect(() => {
    if (!open) return;
    const closeFromOutside = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (triggerRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", closeFromOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeFromOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const menu = open && menuPosition ? createPortal(
    <div
      ref={menuRef}
      className="agent-node-workbench__model-menu"
      role="listbox"
      aria-label="Compatible models"
      style={{
        position: "fixed",
        top: menuPosition.top,
        left: menuPosition.left,
        width: menuPosition.width,
        maxHeight: menuPosition.maxHeight,
      }}
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
    </div>,
    document.body,
  ) : null;

  return (
    <div className="agent-node-workbench__model-picker">
      <span className="agent-node-workbench__model-label">Model</span>
      <button
        ref={triggerRef}
        type="button"
        className="agent-node-workbench__model-trigger"
        aria-label="Choose model"
        aria-expanded={open}
        aria-haspopup="listbox"
        disabled={disabled || loading}
        onClick={() => setOpen((current) => !current)}
      >
        <span>{loading ? "Loading compatible models..." : selectedLabel}</span>
        {selectedModel ? <small className={`is-${selectedModel.availability}`}>{selectedModel.availability}</small> : null}
      </button>
      {menu}
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

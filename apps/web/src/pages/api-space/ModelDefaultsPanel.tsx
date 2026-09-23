import { useEffect, useMemo, useState } from "react";

import {
  MODEL_DEFAULT_PURPOSES,
  type ModelDefaultPurpose,
  type ModelDefaultModeV1,
  type ModelThinkingModeV1,
  type ModelDefaultsPatchRequestV1,
  type ModelDefaultsResponseV1,
  type ProviderModelSummaryV1,
} from "../../api/providerRegistry.ts";
import {
  modelEligibility,
  RETIRED_ARK_MINI_MODEL_REF,
  selectableModelOptions,
} from "../../api/providerModelPolicy.ts";
import { type ApiSpaceNotice } from "./providerRegistryMessages.ts";

export function ModelDefaultsPanel({
  defaults,
  modelsByPurpose,
  loading,
  pending,
  notice,
  onSave,
}: {
  defaults: ModelDefaultsResponseV1;
  modelsByPurpose: Record<ModelDefaultPurpose, ProviderModelSummaryV1[]>;
  loading: boolean;
  pending: boolean;
  notice: ApiSpaceNotice;
  onSave: (changes: ModelDefaultsPatchRequestV1) => Promise<void>;
}) {
  const [modelDraft, setModelDraft] = useState(defaults.defaults);
  const [modeDraft, setModeDraft] = useState(defaults.modes ?? {});
  const [thinkingModeDraft, setThinkingModeDraft] = useState(defaults.thinking_modes ?? {});
  const [changedModels, setChangedModels] = useState<Set<ModelDefaultPurpose>>(new Set());
  const [changedModes, setChangedModes] = useState<Set<ModelDefaultPurpose>>(new Set());
  const [changedThinkingModes, setChangedThinkingModes] = useState<Set<ModelDefaultPurpose>>(new Set());

  useEffect(() => {
    setModelDraft(defaults.defaults);
    setModeDraft(defaults.modes ?? {});
    setThinkingModeDraft(defaults.thinking_modes ?? {});
    setChangedModels(new Set());
    setChangedModes(new Set());
    setChangedThinkingModes(new Set());
  }, [defaults]);

  const changes = useMemo<ModelDefaultsPatchRequestV1>(() => {
    const nextDefaults = Object.fromEntries(
      Array.from(changedModels)
        .map((purpose) => [purpose, modelDraft[purpose]])
        .filter((entry): entry is [ModelDefaultPurpose, string] => Boolean(entry[1])),
    ) as Partial<Record<ModelDefaultPurpose, string>>;
    const nextModes = Object.fromEntries(
      Array.from(changedModes)
        .map((purpose) => [purpose, modeDraft[purpose]])
        .filter((entry): entry is [ModelDefaultPurpose, ModelDefaultModeV1] => Boolean(entry[1])),
    ) as Partial<Record<ModelDefaultPurpose, ModelDefaultModeV1>>;
    const nextThinkingModes = Object.fromEntries(
      Array.from(changedThinkingModes)
        .map((purpose) => [purpose, thinkingModeDraft[purpose]])
        .filter((entry): entry is [ModelDefaultPurpose, ModelThinkingModeV1] => Boolean(entry[1])),
    ) as Partial<Record<ModelDefaultPurpose, ModelThinkingModeV1>>;
    return {
      ...(Object.keys(nextDefaults).length ? { defaults: nextDefaults } : {}),
      ...(Object.keys(nextModes).length ? { modes: nextModes } : {}),
      ...(Object.keys(nextThinkingModes).length ? { thinking_modes: nextThinkingModes } : {}),
    };
  }, [changedModels, changedModes, changedThinkingModes, modeDraft, modelDraft, thinkingModeDraft]);

  const hasChanges = Boolean(
    Object.keys(changes.defaults ?? {}).length
      || Object.keys(changes.modes ?? {}).length
      || Object.keys(changes.thinking_modes ?? {}).length,
  );
  const disabled = loading || pending;

  const updateModel = (purpose: ModelDefaultPurpose, modelRef: string) => {
    setModelDraft((current) => ({ ...current, [purpose]: modelRef }));
    setChangedModels((current) => new Set(current).add(purpose));
  };

  const updateMode = (purpose: ModelDefaultPurpose, mode: ModelDefaultModeV1) => {
    setModeDraft((current) => ({ ...current, [purpose]: mode }));
    setChangedModes((current) => new Set(current).add(purpose));
  };

  const updateThinkingMode = (purpose: ModelDefaultPurpose, mode: ModelThinkingModeV1) => {
    setThinkingModeDraft((current) => ({ ...current, [purpose]: mode }));
    setChangedThinkingModes((current) => new Set(current).add(purpose));
  };

  return (
    <section className="api-space-provider-surface api-space-defaults" aria-labelledby="model-defaults-title">
      <header className="api-space-provider-header">
        <div>
          <span className="api-space-eyebrow">Installation defaults</span>
          <h2 id="model-defaults-title">Default models</h2>
        </div>
        <span className="api-space-local-badge">Applies to new runs</span>
      </header>
      <p className="api-space-intro">
        Choose the backend-approved model used when a node follows its default selection. Explicit node choices stay pinned.
      </p>
      <div className="api-space-default-grid">
        {MODEL_DEFAULT_PURPOSES.map((purpose) => {
          const allOptions = modelsByPurpose[purpose];
          const options = selectableModelOptions(allOptions);
          const selected = modelDraft[purpose] ?? "";
          const selectedCatalogModel = allOptions.find((model) => model.model_ref === selected);
          const selectedIsHidden = selected.startsWith("fake:")
            || selected === RETIRED_ARK_MINI_MODEL_REF
            || Boolean(selectedCatalogModel && !modelEligibility(selectedCatalogModel, "diagnostic").visible);
          const visibleSelected = selectedIsHidden ? "" : selected;
          const selectedMissing = Boolean(visibleSelected)
            && !options.some((model) => model.model_ref === visibleSelected);
          return (
            <div className="api-space-default-field" key={purpose}>
              <label htmlFor={`default-model-${purpose}`}>{defaultLabel(purpose)}</label>
              <select
                id={`default-model-${purpose}`}
                aria-label={`${defaultLabel(purpose)} default model`}
                value={visibleSelected}
                disabled={disabled}
                onChange={(event) => updateModel(purpose, event.currentTarget.value)}
              >
                <option value="">No default selected</option>
                {selectedMissing ? <option value={visibleSelected}>{visibleSelected} (unavailable)</option> : null}
                {options.map((model) => (
                  <option key={model.model_ref} value={model.model_ref}>
                    {model.display_name} · {model.provider_id}
                  </option>
                ))}
              </select>
              {purpose === "audio" ? (
                <div className="api-space-routing-mode">
                  <span id="audio-routing-mode-label">Audio routing mode</span>
                  <div aria-labelledby="audio-routing-mode-label" className="api-space-routing-toggle" role="radiogroup">
                    {(["automatic", "explicit"] as const).map((mode) => (
                      <button
                        aria-checked={(modeDraft.audio ?? "explicit") === mode}
                        className={(modeDraft.audio ?? "explicit") === mode ? "is-active" : undefined}
                        disabled={disabled}
                        key={mode}
                        onClick={() => updateMode("audio", mode)}
                        role="radio"
                        type="button"
                      >
                        {mode === "automatic" ? "Automatic" : "Explicit"}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
              {purpose === "agent" || purpose === "text" ? (
                <ThinkingModeControl
                  purpose={purpose}
                  model={selectedCatalogModel}
                  value={thinkingModeDraft[purpose] ?? "enabled"}
                  disabled={disabled}
                  onChange={updateThinkingMode}
                />
              ) : null}
            </div>
          );
        })}
      </div>
      <footer className="api-space-save-bar">
        <button className="send-btn" type="button" disabled={!hasChanges || disabled} onClick={() => void onSave(changes)}>
          {pending ? "Saving defaults..." : "Save default models"}
        </button>
        {notice ? <span className={`api-space-inline-notice is-${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>{notice.message}</span> : null}
      </footer>
    </section>
  );
}

function ThinkingModeControl({
  purpose,
  model,
  value,
  disabled,
  onChange,
}: {
  purpose: ModelDefaultPurpose;
  model: ProviderModelSummaryV1 | undefined;
  value: ModelThinkingModeV1;
  disabled: boolean;
  onChange: (purpose: ModelDefaultPurpose, mode: ModelThinkingModeV1) => void;
}) {
  const supported = model?.capability_metadata?.supported_thinking_modes;
  if (
    !Array.isArray(supported)
    || !supported.includes("disabled")
    || !supported.includes("enabled")
  ) {
    return null;
  }
  return (
    <div className="api-space-routing-mode">
      <span id={`${purpose}-thinking-mode-label`}>Thinking mode</span>
      <div
        aria-labelledby={`${purpose}-thinking-mode-label`}
        className="api-space-routing-toggle"
        role="radiogroup"
      >
        {(["disabled", "enabled"] as const).map((mode) => (
          <button
            aria-checked={value === mode}
            className={value === mode ? "is-active" : undefined}
            disabled={disabled}
            key={mode}
            onClick={() => onChange(purpose, mode)}
            role="radio"
            type="button"
          >
            {mode === "enabled" ? "Thinking" : "Non-thinking"}
          </button>
        ))}
      </div>
    </div>
  );
}

function defaultLabel(purpose: ModelDefaultPurpose): string {
  return purpose.charAt(0).toUpperCase() + purpose.slice(1);
}

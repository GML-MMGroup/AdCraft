import { useEffect, useMemo, useState } from "react";

import {
  MODEL_DEFAULT_PURPOSES,
  type ModelDefaultPurpose,
  type ModelDefaultModeV1,
  type ModelDefaultsPatchRequestV1,
  type ModelDefaultsResponseV1,
  type ProviderModelSummaryV1,
} from "../../api/providerRegistry.ts";
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
  const [changedModels, setChangedModels] = useState<Set<ModelDefaultPurpose>>(new Set());
  const [changedModes, setChangedModes] = useState<Set<ModelDefaultPurpose>>(new Set());

  useEffect(() => {
    setModelDraft(defaults.defaults);
    setModeDraft(defaults.modes ?? {});
    setChangedModels(new Set());
    setChangedModes(new Set());
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
    return {
      ...(Object.keys(nextDefaults).length ? { defaults: nextDefaults } : {}),
      ...(Object.keys(nextModes).length ? { modes: nextModes } : {}),
    };
  }, [changedModels, changedModes, modeDraft, modelDraft]);

  const hasChanges = Boolean(Object.keys(changes.defaults ?? {}).length || Object.keys(changes.modes ?? {}).length);
  const disabled = loading || pending;

  const updateModel = (purpose: ModelDefaultPurpose, modelRef: string) => {
    setModelDraft((current) => ({ ...current, [purpose]: modelRef }));
    setChangedModels((current) => new Set(current).add(purpose));
  };

  const updateMode = (purpose: ModelDefaultPurpose, mode: ModelDefaultModeV1) => {
    setModeDraft((current) => ({ ...current, [purpose]: mode }));
    setChangedModes((current) => new Set(current).add(purpose));
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
          const options = modelsByPurpose[purpose];
          const selected = modelDraft[purpose] ?? "";
          const selectedMissing = Boolean(selected) && !options.some((model) => model.model_ref === selected);
          return (
            <div className="api-space-default-field" key={purpose}>
              <label htmlFor={`default-model-${purpose}`}>{defaultLabel(purpose)}</label>
              <select
                id={`default-model-${purpose}`}
                aria-label={`${defaultLabel(purpose)} default model`}
                value={selected}
                disabled={disabled}
                onChange={(event) => updateModel(purpose, event.currentTarget.value)}
              >
                <option value="">No default selected</option>
                {selectedMissing ? <option value={selected}>{selected} (unavailable)</option> : null}
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

function defaultLabel(purpose: ModelDefaultPurpose): string {
  return purpose.charAt(0).toUpperCase() + purpose.slice(1);
}

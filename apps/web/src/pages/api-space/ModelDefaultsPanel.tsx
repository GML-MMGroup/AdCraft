import { useEffect, useMemo, useState } from "react";

import {
  MODEL_DEFAULT_PURPOSES,
  type ModelDefaultPurpose,
  type ModelDefaultsResponseV1,
  type ProviderModelSummaryV1,
} from "../../api/providerRegistry.ts";
import { type ApiSpaceNotice } from "./providerRegistryMessages.ts";

export function ModelDefaultsPanel({
  defaults,
  modelsByPurpose,
  pending,
  notice,
  onSave,
}: {
  defaults: ModelDefaultsResponseV1;
  modelsByPurpose: Record<ModelDefaultPurpose, ProviderModelSummaryV1[]>;
  pending: boolean;
  notice: ApiSpaceNotice;
  onSave: (defaults: Partial<Record<ModelDefaultPurpose, string>>) => Promise<void>;
}) {
  const [draft, setDraft] = useState(defaults.defaults);
  const [changed, setChanged] = useState<Set<ModelDefaultPurpose>>(new Set());

  useEffect(() => {
    setDraft(defaults.defaults);
    setChanged(new Set());
  }, [defaults]);

  const changes = useMemo(() => Object.fromEntries(
    Array.from(changed)
      .map((purpose) => [purpose, draft[purpose]])
      .filter((entry): entry is [ModelDefaultPurpose, string] => Boolean(entry[1])),
  ) as Partial<Record<ModelDefaultPurpose, string>>, [changed, draft]);

  const update = (purpose: ModelDefaultPurpose, modelRef: string) => {
    setDraft((current) => ({ ...current, [purpose]: modelRef }));
    setChanged((current) => new Set(current).add(purpose));
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
          const selected = draft[purpose] ?? "";
          const selectedMissing = Boolean(selected) && !options.some((model) => model.model_ref === selected);
          return (
            <label className="api-space-default-field" key={purpose}>
              <span>{defaultLabel(purpose)}</span>
              <select
                aria-label={`${defaultLabel(purpose)} default model`}
                value={selected}
                disabled={pending}
                onChange={(event) => update(purpose, event.currentTarget.value)}
              >
                <option value="">No default selected</option>
                {selectedMissing ? <option value={selected}>{selected} (unavailable)</option> : null}
                {options.map((model) => (
                  <option key={model.model_ref} value={model.model_ref}>
                    {model.display_name} · {model.provider_id}
                  </option>
                ))}
              </select>
            </label>
          );
        })}
      </div>
      <footer className="api-space-save-bar">
        <button className="send-btn" type="button" disabled={!Object.keys(changes).length || pending} onClick={() => void onSave(changes)}>
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

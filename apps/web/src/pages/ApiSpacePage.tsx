import { useMemo, useState } from "react";
import { PageHeader } from "../components/Layout";
import {
  API_SPACE_PROVIDER_CATALOG,
  DEFAULT_SEEDANCE_PROVIDER,
  type ApiProviderCategory,
  type ApiProviderConfig,
} from "../apiSpace/providerCatalog";

type SeedanceFormState = {
  model: string;
  baseUrl: string;
  apiKey: string;
  resolution: "480p" | "720p" | "1080p";
  ratio: "16:9" | "9:16" | "1:1";
  duration: number;
  generateAudio: boolean;
  watermark: boolean;
  advancedJson: Record<string, unknown>;
};

const CATEGORY_ORDER: ApiProviderCategory[] = ["text", "image", "video", "audio", "composition"];

export function ApiSpacePage() {
  const [selectedCategory, setSelectedCategory] = useState<ApiProviderCategory>("video");
  const [form, setForm] = useState<SeedanceFormState>(() => seedanceFormFromProvider(DEFAULT_SEEDANCE_PROVIDER));
  const [advancedJsonText, setAdvancedJsonText] = useState(() => JSON.stringify(DEFAULT_SEEDANCE_PROVIDER.advanced_json, null, 2));
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");

  const selectedGroup = useMemo(
    () => API_SPACE_PROVIDER_CATALOG.find((group) => group.category === selectedCategory) ?? API_SPACE_PROVIDER_CATALOG[0],
    [selectedCategory],
  );
  const selectedProvider = selectedGroup.providers[0];
  const editable = selectedProvider?.editable === true;

  function selectCategory(category: ApiProviderCategory) {
    setSelectedCategory(category);
    setFeedback("");
    setError("");
  }

  function updateForm(patch: Partial<SeedanceFormState>) {
    setForm((current) => ({ ...current, ...patch }));
    setFeedback("");
    setError("");
  }

  function saveDemoConfig() {
    if (!editable) {
      setFeedback("");
      setError("This provider is not editable yet.");
      return;
    }

    try {
      const parsed = advancedJsonText.trim() ? JSON.parse(advancedJsonText) : {};
      setForm((current) => ({
        ...current,
        apiKey: "",
        advancedJson: recordValue(parsed),
      }));
      setFeedback("Demo saved. Backend API required before this affects workflow runs.");
      setError("");
    } catch {
      setFeedback("");
      setError("JSON Config must be valid JSON.");
    }
  }

  function resetDemoConfig() {
    const nextForm = seedanceFormFromProvider(DEFAULT_SEEDANCE_PROVIDER);
    setForm(nextForm);
    setAdvancedJsonText(JSON.stringify(nextForm.advancedJson, null, 2));
    setFeedback("");
    setError("");
    setSelectedCategory("video");
  }

  return (
    <section className="content-wrap api-space-page">
      <PageHeader title="API Space" subtitle="Model provider configuration workspace." />

      <div className="api-space-layout">
        <aside className="api-space-sidebar" aria-label="Model categories">
          {CATEGORY_ORDER.map((category) => {
            const group = API_SPACE_PROVIDER_CATALOG.find((item) => item.category === category);
            if (!group) return null;
            const active = selectedCategory === category;
            const provider = group.providers[0];
            return (
              <button
                key={category}
                className={`api-space-category ${active ? "is-active" : ""}`}
                type="button"
                onClick={() => selectCategory(category)}
              >
                <span>{group.label}</span>
                <strong>{provider?.display_name ?? "Provider"}</strong>
                <em className={`api-space-status is-${provider?.status ?? "disabled"}`}>
                  {provider?.editable ? "Editable" : "Coming soon"}
                </em>
              </button>
            );
          })}
        </aside>

        <div className="api-space-detail">
          <div className="api-space-detail-heading">
            <div>
              <span>{selectedGroup.label}</span>
              <h2>{selectedProvider?.display_name ?? "Provider"}</h2>
            </div>
            <em className={`api-space-status is-${selectedProvider?.status ?? "disabled"}`}>
              {editable ? "Demo only" : "Coming soon"}
            </em>
          </div>

          {editable && selectedProvider ? (
            <SeedanceConfigPanel
              provider={selectedProvider}
              form={form}
              advancedJsonText={advancedJsonText}
              feedback={feedback}
              error={error}
              onUpdate={updateForm}
              onChangeAdvancedJson={(value) => {
                setAdvancedJsonText(value);
                setFeedback("");
                setError("");
              }}
              onSave={saveDemoConfig}
              onReset={resetDemoConfig}
            />
          ) : (
            <ComingSoonPanel provider={selectedProvider} />
          )}
        </div>
      </div>
    </section>
  );
}

function SeedanceConfigPanel({
  provider,
  form,
  advancedJsonText,
  feedback,
  error,
  onUpdate,
  onChangeAdvancedJson,
  onSave,
  onReset,
}: {
  provider: ApiProviderConfig;
  form: SeedanceFormState;
  advancedJsonText: string;
  feedback: string;
  error: string;
  onUpdate: (patch: Partial<SeedanceFormState>) => void;
  onChangeAdvancedJson: (value: string) => void;
  onSave: () => void;
  onReset: () => void;
}) {
  return (
    <>
      <div className="api-space-summary">
        <span>Provider</span>
        <strong>{provider.display_name}</strong>
        <span>Status</span>
        <strong>Backend API required</strong>
      </div>

      <div className="api-space-form-grid">
        <label>
          <span>Model</span>
          <input value={form.model} onChange={(event) => onUpdate({ model: event.target.value })} />
        </label>
        <label>
          <span>API Key</span>
          <input
            value={form.apiKey}
            type="password"
            placeholder="Not saved in demo"
            autoComplete="off"
            onChange={(event) => onUpdate({ apiKey: event.target.value })}
          />
        </label>
        <label className="is-wide">
          <span>Base URL</span>
          <input value={form.baseUrl} placeholder="https://ark.cn-beijing.volces.com/api/v3" onChange={(event) => onUpdate({ baseUrl: event.target.value })} />
        </label>
        <label>
          <span>Resolution</span>
          <select value={form.resolution} onChange={(event) => onUpdate({ resolution: event.target.value as SeedanceFormState["resolution"] })}>
            <option value="480p">480p</option>
            <option value="720p">720p</option>
            <option value="1080p">1080p</option>
          </select>
        </label>
        <label>
          <span>Ratio</span>
          <select value={form.ratio} onChange={(event) => onUpdate({ ratio: event.target.value as SeedanceFormState["ratio"] })}>
            <option value="16:9">16:9</option>
            <option value="9:16">9:16</option>
            <option value="1:1">1:1</option>
          </select>
        </label>
        <label>
          <span>Duration</span>
          <input type="number" min={1} max={30} value={form.duration} onChange={(event) => onUpdate({ duration: Number(event.target.value) || 1 })} />
        </label>
        <label className="api-space-toggle">
          <input type="checkbox" checked={form.generateAudio} onChange={(event) => onUpdate({ generateAudio: event.target.checked })} />
          <span>Generate Audio</span>
        </label>
        <label className="api-space-toggle">
          <input type="checkbox" checked={form.watermark} onChange={(event) => onUpdate({ watermark: event.target.checked })} />
          <span>Watermark</span>
        </label>
      </div>

      <label className="api-space-json">
        <span>JSON Config</span>
        <textarea value={advancedJsonText} spellCheck={false} onChange={(event) => onChangeAdvancedJson(event.target.value)} />
      </label>

      <div className="api-space-actions">
        <button className="send-btn" type="button" onClick={onSave}>
          Save demo config
        </button>
        <button className="small-action" type="button" onClick={onReset}>
          Reset
        </button>
        {feedback ? <span className="api-space-feedback is-success">{feedback}</span> : null}
        {error ? <span className="api-space-feedback is-error">{error}</span> : null}
      </div>
    </>
  );
}

function ComingSoonPanel({ provider }: { provider?: ApiProviderConfig }) {
  return (
    <div className="api-space-coming-soon">
      <span>{provider?.display_name ?? "Provider"}</span>
      <h3>Coming soon</h3>
      <p>{provider?.description ?? "This provider category is not configurable yet."}</p>
    </div>
  );
}

function seedanceFormFromProvider(provider: ApiProviderConfig): SeedanceFormState {
  return {
    model: provider.model,
    baseUrl: provider.base_url,
    apiKey: "",
    resolution: provider.parameters.resolution ?? "480p",
    ratio: provider.parameters.ratio ?? "16:9",
    duration: provider.parameters.duration ?? 5,
    generateAudio: Boolean(provider.parameters.generate_audio),
    watermark: Boolean(provider.parameters.watermark),
    advancedJson: provider.advanced_json,
  };
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

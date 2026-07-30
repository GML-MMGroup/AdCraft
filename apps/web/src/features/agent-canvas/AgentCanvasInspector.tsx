import { useEffect, useRef, useState } from "react";

import {
  V2_AUTHORING_DRAFT_DISCARDED_EVENT,
  type V2AuthoringConflictResolution,
} from "../../api/v2AuthoringConflictEvents.ts";
import {
  ChevronDownIcon,
  ChevronUpIcon,
  CloseIcon,
  EditIcon,
  PlayIcon,
  SaveIcon,
  TrashIcon,
  UploadIcon,
} from "../../icons.tsx";
import { isV2ApiError } from "../../api/agentCanvasApi.ts";
import type {
  AgentCanvasImageLibraryCategoryV2,
  AgentCanvasWorkflowV2,
  CanvasBindingInputRoleV2,
  CanvasBindingPatchRequestV2,
  CanvasConnectionPolicyV2,
  CanvasNodePatchRequestV2,
  CanvasNodeV2,
  CanvasVariationDraftUpsertV2,
  ProviderModelCapabilityV2,
  SaveAgentCanvasImageToLibraryRequestV2,
} from "../../types-v2.ts";

type PatchNode = (
  nodeId: string,
  patch: CanvasNodePatchRequestV2,
  options?: { coalesce?: boolean; optimistic?: boolean },
) => Promise<void>;

type PatchBinding = (
  bindingId: string,
  patch: CanvasBindingPatchRequestV2,
) => Promise<unknown>;

function defaultLibraryCategory(node: CanvasNodeV2): AgentCanvasImageLibraryCategoryV2 {
  const role = node.creative_role.toLocaleLowerCase();
  if (role.includes("scene")) return "scene";
  if (role.includes("product") || role.includes("prop")) return "prop";
  return "character";
}

function actionErrorMessage(error: unknown): string {
  if (isV2ApiError(error) && error.code === "provider_input_unsupported") {
    return `Provider input unsupported: ${error.message}`;
  }
  return error instanceof Error ? error.message : "The node could not be updated.";
}

export function AgentCanvasInspector({
  workflow,
  node,
  patchNode,
  patchBinding,
  deleteBinding,
  connectionPolicy,
  providerCapabilities = [],
  providerCapabilitiesLoading = false,
  providerCapabilitiesError = null,
  onRun,
  onSaveVariation,
  onDiscardVariation,
  onMaterializeVariation,
  onSaveImageToLibrary,
  onDelete,
  onOpenEditing,
  onClose,
}: {
  workflow: AgentCanvasWorkflowV2;
  node: CanvasNodeV2;
  patchNode: PatchNode;
  patchBinding?: PatchBinding;
  deleteBinding?: (bindingId: string) => Promise<void>;
  connectionPolicy?: CanvasConnectionPolicyV2 | null;
  providerCapabilities?: ProviderModelCapabilityV2[];
  providerCapabilitiesLoading?: boolean;
  providerCapabilitiesError?: string | null;
  onRun: (node: CanvasNodeV2) => Promise<void>;
  onSaveVariation: (
    nodeId: string,
    request: CanvasVariationDraftUpsertV2,
  ) => Promise<void>;
  onDiscardVariation: (nodeId: string) => Promise<void>;
  onMaterializeVariation: (
    node: CanvasNodeV2,
    action: "create_draft" | "generate",
  ) => Promise<CanvasNodeV2 | null>;
  onSaveImageToLibrary: (
    assetId: string,
    request: SaveAgentCanvasImageToLibraryRequestV2,
  ) => Promise<void>;
  onDelete: (nodeId: string) => Promise<void>;
  onOpenEditing: () => void;
  onClose: () => void;
}) {
  const [title, setTitle] = useState(node.variation_draft?.title ?? node.title);
  const [prompt, setPrompt] = useState(
    node.variation_draft?.generation_prompt ?? node.generation_prompt ?? "",
  );
  const [textContent, setTextContent] = useState(
    typeof node.structured_content.content === "string"
      ? node.structured_content.content
      : typeof node.structured_content.script_text === "string"
        ? node.structured_content.script_text
        : "",
  );
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [libraryCategory, setLibraryCategory] = useState<AgentCanvasImageLibraryCategoryV2>(
    defaultLibraryCategory(node),
  );
  const [libraryName, setLibraryName] = useState(node.title);
  const [librarySaved, setLibrarySaved] = useState(false);
  const [modelId, setModelId] = useState(node.variation_draft?.model_id ?? node.model_id ?? "");
  const [parameters, setParameters] = useState<Record<string, unknown>>(
    node.variation_draft?.parameters ?? node.parameters,
  );
  const draftNodeIdRef = useRef(node.node_id);

  useEffect(() => {
    const changedNode = draftNodeIdRef.current !== node.node_id;
    if (!changedNode && dirty) return;
    draftNodeIdRef.current = node.node_id;
    setTitle(node.variation_draft?.title ?? node.title);
    setPrompt(node.variation_draft?.generation_prompt ?? node.generation_prompt ?? "");
    setTextContent(
      typeof node.structured_content.content === "string"
        ? node.structured_content.content
        : typeof node.structured_content.script_text === "string"
          ? node.structured_content.script_text
          : "",
    );
    setLibraryCategory(defaultLibraryCategory(node));
    setLibraryName(node.title);
    setLibrarySaved(false);
    setModelId(node.variation_draft?.model_id ?? node.model_id ?? "");
    setParameters(node.variation_draft?.parameters ?? node.parameters);
    setError(null);
    if (changedNode) setDirty(false);
  }, [dirty, node]);

  useEffect(() => {
    function discardConflictDraft(event: Event) {
      const resolution = (event as CustomEvent<V2AuthoringConflictResolution>).detail;
      if (
        resolution?.action !== "discard"
        || resolution.target.resource !== "workflow"
        || resolution.target.id !== workflow.workflow_id
        || !(resolution.operationPath.split("?", 1)[0] ?? "").includes(
          `/nodes/${encodeURIComponent(node.node_id)}`,
        )
      ) return;
      setTitle(node.variation_draft?.title ?? node.title);
      setPrompt(node.variation_draft?.generation_prompt ?? node.generation_prompt ?? "");
      setTextContent(
        typeof node.structured_content.content === "string"
          ? node.structured_content.content
          : typeof node.structured_content.script_text === "string"
            ? node.structured_content.script_text
            : "",
      );
      setModelId(node.variation_draft?.model_id ?? node.model_id ?? "");
      setParameters(node.variation_draft?.parameters ?? node.parameters);
      setDirty(false);
      setError(null);
    }

    window.addEventListener(
      V2_AUTHORING_DRAFT_DISCARDED_EVENT,
      discardConflictDraft as EventListener,
    );
    return () => window.removeEventListener(
      V2_AUTHORING_DRAFT_DISCARDED_EVENT,
      discardConflictDraft as EventListener,
    );
  }, [node, workflow.workflow_id]);

  const isScriptDocument = node.node_type === "script" && node.status === "ready";
  const editsTextContent = node.node_type === "text" || isScriptDocument;
  const editsGenerationPrompt = (
    node.node_type !== "text"
    && node.node_type !== "editing"
    && !isScriptDocument
  );
  const isReadyMedia = ["image", "video", "audio"].includes(node.node_type) && node.status === "ready";
  const canSaveImageToLibrary = (
    node.node_type === "image"
    && node.status === "ready"
    && Boolean(node.output_asset_id)
  );
  const usesProvider = ["script", "image", "video", "audio"].includes(node.node_type);
  const canConfigureProvider = usesProvider && (node.status === "draft" || isReadyMedia);
  const currentModelIsCompatible = (
    !modelId
    || providerCapabilities.some((capability) => capability.model_id === modelId)
  );
  const inboundBindings = workflow.bindings
    .filter((binding) => binding.target_node_id === node.node_id)
    .sort((left, right) => left.order - right.order);

  function sourcePresentation(binding: (typeof inboundBindings)[number]) {
    if (binding.source.kind === "image_asset") {
      const sourceAssetId = binding.source.source_asset_id;
      const asset = workflow.assets.find((item) => item.asset_id === sourceAssetId);
      return {
        name: asset?.display_name ?? sourceAssetId,
        previewUrl: asset?.preview_url ?? asset?.media_url ?? null,
      };
    }
    const sourceNodeId = binding.source.source_node_id;
    const sourceNode = workflow.nodes.find((item) => item.node_id === sourceNodeId);
    const asset = sourceNode?.output_asset_id
      ? workflow.assets.find((item) => item.asset_id === sourceNode.output_asset_id)
      : null;
    return {
      name: sourceNode?.title ?? sourceNodeId,
      previewUrl: asset?.preview_url ?? asset?.media_url ?? null,
    };
  }

  function allowedInputRoles(binding: (typeof inboundBindings)[number]) {
    if (!connectionPolicy) {
      return [
        "text_context",
        "image_reference",
        "video_reference",
        "audio_reference",
      ] satisfies CanvasBindingInputRoleV2[];
    }
    if (binding.source.kind === "image_asset") {
      return connectionPolicy.image_asset_targets[node.node_type] ?? [binding.input_role];
    }
    const sourceNodeId = binding.source.source_node_id;
    const sourceNode = workflow.nodes.find((item) => (
      item.node_id === sourceNodeId
    ));
    const rule = sourceNode
      ? connectionPolicy.input_roles.find((candidate) => (
          candidate.source_node_type === sourceNode.node_type
          && candidate.target_node_type === node.node_type
        ))
      : null;
    return rule?.roles ?? [binding.input_role];
  }

  async function updateBinding(
    bindingId: string,
    patch: CanvasBindingPatchRequestV2,
  ) {
    if (!patchBinding) return;
    await perform(() => patchBinding(bindingId, patch));
  }

  async function perform(action: () => Promise<unknown>): Promise<boolean> {
    setPending(true);
    setError(null);
    try {
      await action();
      return true;
    } catch (actionError) {
      setError(actionErrorMessage(actionError));
      return false;
    } finally {
      setPending(false);
    }
  }

  async function save(): Promise<boolean> {
    if (isReadyMedia) {
      if (!prompt.trim()) {
        setError("Enter a generation prompt before saving the variation.");
        return false;
      }
      const saved = await perform(() => onSaveVariation(node.node_id, {
        title: title.trim() || `${node.title} variation`,
        generation_prompt: prompt.trim(),
        model_id: modelId || null,
        parameters,
      }));
      if (saved) setDirty(false);
      return saved;
    }
    const structuredContent = editsTextContent
      ? {
          ...node.structured_content,
          content: textContent,
        }
      : undefined;
    const saved = await perform(() => patchNode(node.node_id, {
      title: title.trim() || node.title,
      generation_prompt: editsGenerationPrompt ? prompt : node.generation_prompt,
      ...(usesProvider ? { model_id: modelId || null } : {}),
      ...(usesProvider ? { parameters } : {}),
      ...(structuredContent ? { structured_content: structuredContent } : {}),
    }));
    if (saved) setDirty(false);
    return saved;
  }

  async function materializeVariation(action: "create_draft" | "generate") {
    if ((dirty || !node.variation_draft) && !(await save())) return;
    await perform(() => onMaterializeVariation(node, action));
  }

  async function discardVariation() {
    const discarded = await perform(() => onDiscardVariation(node.node_id));
    if (!discarded) return;
    setTitle(node.title);
    setPrompt(node.generation_prompt ?? "");
    setModelId(node.model_id ?? "");
    setParameters(node.parameters);
    setDirty(false);
  }

  async function run() {
    if (dirty && !(await save())) return;
    await perform(() => onRun(node));
  }

  async function saveImageToLibrary() {
    if (!node.output_asset_id) return;
    const displayName = libraryName.trim();
    if (!displayName) {
      setError("Enter a name before saving this image.");
      return;
    }
    const saved = await perform(() => onSaveImageToLibrary(node.output_asset_id!, {
      category: libraryCategory,
      display_name: displayName,
    }));
    if (saved) setLibrarySaved(true);
  }

  return (
    <aside className="agent-canvas-inspector" aria-label={`${node.node_type} node settings`}>
      <header>
        <div>
          <span>{node.node_type}</span>
          <strong>{node.title}</strong>
        </div>
        <button type="button" aria-label="Close node settings" title="Close" onClick={onClose}>
          <CloseIcon />
        </button>
      </header>

      <div className="agent-canvas-inspector__body">
        <label>
          <span>Name</span>
          <input
            value={title}
            disabled={pending}
            onChange={(event) => {
              setTitle(event.currentTarget.value);
              setDirty(true);
            }}
          />
        </label>

        {editsTextContent ? (
          <label>
            <span>{node.node_type === "script" ? "Script" : "Text"}</span>
            <textarea
              value={textContent}
              disabled={pending}
              onChange={(event) => {
                setTextContent(event.currentTarget.value);
                setDirty(true);
              }}
            />
          </label>
        ) : editsGenerationPrompt ? (
          <label>
            <span>Generation prompt</span>
            <textarea
              value={prompt}
              disabled={pending}
              onChange={(event) => {
                setPrompt(event.currentTarget.value);
                setDirty(true);
              }}
            />
          </label>
        ) : null}

        {canConfigureProvider ? (
          <label>
            <span>Provider model</span>
            <select
              value={modelId}
              disabled={pending || providerCapabilitiesLoading}
              onChange={(event) => {
                setModelId(event.currentTarget.value);
                setDirty(true);
              }}
            >
              <option value="">
                {providerCapabilitiesLoading ? "Loading compatible models..." : "Automatic"}
              </option>
              {!currentModelIsCompatible && modelId ? (
                <option value={modelId} disabled>{modelId} (incompatible)</option>
              ) : null}
              {providerCapabilities.filter((capability) => capability.available).map((capability) => (
                <option value={capability.model_id} key={capability.model_id}>
                  {capability.model_id} - {capability.provider}
                </option>
              ))}
            </select>
            {providerCapabilitiesError ? (
              <small className="agent-canvas-inspector__field-error">
                {providerCapabilitiesError}
              </small>
            ) : null}
          </label>
        ) : null}

        {node.node_type === "video" && canConfigureProvider ? (
          <section className="agent-canvas-inspector__parameters" aria-label="Video generation settings">
            <label>
              <span>Requested duration (seconds)</span>
              <input
                type="number"
                min="1"
                step="1"
                value={typeof parameters.requested_duration_seconds === "number"
                  ? parameters.requested_duration_seconds
                  : ""}
                disabled={pending}
                onChange={(event) => {
                  const next = { ...parameters };
                  if (event.currentTarget.value === "") {
                    delete next.requested_duration_seconds;
                  } else {
                    next.requested_duration_seconds = Number(event.currentTarget.value);
                  }
                  delete next.effective_duration_seconds;
                  setParameters(next);
                  setDirty(true);
                }}
              />
            </label>
            {typeof parameters.effective_duration_seconds === "number" ? (
              <small>Effective duration: {parameters.effective_duration_seconds}s</small>
            ) : null}
            {providerCapabilities.some((capability) => capability.supports_native_audio) ? (
              <label className="agent-canvas-inspector__toggle">
                <input
                  type="checkbox"
                  checked={parameters.native_audio !== false}
                  disabled={pending}
                  onChange={(event) => {
                    setParameters({ ...parameters, native_audio: event.currentTarget.checked });
                    setDirty(true);
                  }}
                />
                <span>Generate native dialogue, environment, and action audio</span>
              </label>
            ) : null}
          </section>
        ) : null}

        {inboundBindings.length ? (
          <section className="agent-canvas-inspector__inputs" aria-label="Node inputs">
            <div className="agent-canvas-inspector__inputs-heading">
              <strong>Inputs</strong>
              <span>{inboundBindings.length}</span>
            </div>
            {inboundBindings.map((binding, index) => {
              const source = sourcePresentation(binding);
              const inputRoles = allowedInputRoles(binding);
              return (
                <article key={binding.binding_id} className={!binding.enabled ? "is-disabled" : ""}>
                  <div className="agent-canvas-inspector__input-source">
                    {source.previewUrl ? (
                      <img src={source.previewUrl} alt="" loading="lazy" decoding="async" />
                    ) : (
                      <span aria-hidden="true">{index + 1}</span>
                    )}
                    <div>
                      <strong>{binding.label || `Input ${index + 1}`}</strong>
                      <small>{source.name}</small>
                    </div>
                    <div className="agent-canvas-inspector__input-order">
                      <button
                        type="button"
                        aria-label={`Move ${binding.label || `Input ${index + 1}`} earlier`}
                        title="Move earlier"
                        disabled={pending || !patchBinding || index === 0}
                        onClick={() => void updateBinding(binding.binding_id, {
                          order: inboundBindings[index - 1]?.order ?? 0,
                        })}
                      >
                        <ChevronUpIcon />
                      </button>
                      <button
                        type="button"
                        aria-label={`Move ${binding.label || `Input ${index + 1}`} later`}
                        title="Move later"
                        disabled={pending || !patchBinding || index === inboundBindings.length - 1}
                        onClick={() => void updateBinding(binding.binding_id, {
                          order: inboundBindings[index + 1]?.order ?? binding.order,
                        })}
                      >
                        <ChevronDownIcon />
                      </button>
                      <button
                        type="button"
                        className="is-danger"
                        aria-label={`Remove ${binding.label || `Input ${index + 1}`}`}
                        title="Remove input"
                        disabled={pending || !deleteBinding}
                        onClick={() => void perform(() => deleteBinding!(binding.binding_id))}
                      >
                        <TrashIcon />
                      </button>
                    </div>
                  </div>
                  <label>
                    <span>Input role</span>
                    <select
                      value={binding.input_role}
                      disabled={pending || !patchBinding}
                      onChange={(event) => void updateBinding(binding.binding_id, {
                        input_role: event.currentTarget.value as CanvasBindingInputRoleV2,
                      })}
                    >
                      {inputRoles.map((inputRole) => (
                        <option value={inputRole} key={inputRole}>
                          {inputRole.replaceAll("_", " ")}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="agent-canvas-inspector__input-flags">
                    <label>
                      <input
                        type="checkbox"
                        checked={binding.required}
                        disabled={pending || !patchBinding}
                        onChange={(event) => void updateBinding(binding.binding_id, {
                          required: event.currentTarget.checked,
                        })}
                      />
                      <span>Required</span>
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={binding.enabled}
                        disabled={pending || !patchBinding}
                        onChange={(event) => void updateBinding(binding.binding_id, {
                          enabled: event.currentTarget.checked,
                        })}
                      />
                      <span>Enabled</span>
                    </label>
                  </div>
                </article>
              );
            })}
          </section>
        ) : null}

        {isReadyMedia ? (
          <section className="agent-canvas-inspector__variation" aria-label="Ready media variation">
            <div>
              <button
                type="button"
                className="agent-canvas-inspector__primary"
                aria-label="Create variation draft"
                disabled={pending || !prompt.trim()}
                onClick={() => void materializeVariation("create_draft")}
              >
                <EditIcon />
                <span>Create draft</span>
              </button>
              <button
                type="button"
                className="agent-canvas-inspector__primary"
                aria-label="Generate variation"
                disabled={pending || !prompt.trim()}
                onClick={() => void materializeVariation("generate")}
              >
                <PlayIcon />
                <span>Generate</span>
              </button>
            </div>
            {node.variation_draft ? (
              <button
                type="button"
                className="agent-canvas-inspector__variation-discard"
                aria-label="Discard variation draft"
                disabled={pending}
                onClick={() => void discardVariation()}
              >
                <TrashIcon />
                <span>Discard saved variation</span>
              </button>
            ) : null}
          </section>
        ) : null}

        {canSaveImageToLibrary ? (
          <section className="agent-canvas-inspector__library" aria-label="Save image to My Assets">
            <strong>My Assets</strong>
            <label>
              <span>Library category</span>
              <select
                value={libraryCategory}
                disabled={pending}
                onChange={(event) => {
                  setLibraryCategory(event.currentTarget.value as AgentCanvasImageLibraryCategoryV2);
                  setLibrarySaved(false);
                }}
              >
                <option value="character">Character</option>
                <option value="scene">Scene</option>
                <option value="prop">Prop</option>
              </select>
            </label>
            <label>
              <span>Library name</span>
              <input
                value={libraryName}
                disabled={pending}
                onChange={(event) => {
                  setLibraryName(event.currentTarget.value);
                  setLibrarySaved(false);
                }}
              />
            </label>
            <button
              type="button"
              className="agent-canvas-inspector__primary"
              disabled={pending || !libraryName.trim()}
              aria-label="Save image to My Assets"
              onClick={() => void saveImageToLibrary()}
            >
              <SaveIcon />
              <span>{librarySaved ? "Saved to My Assets" : "Save to My Assets"}</span>
            </button>
          </section>
        ) : null}

        {node.node_type === "editing" ? (
          <button
            type="button"
            className="agent-canvas-inspector__primary"
            onClick={onOpenEditing}
          >
            <UploadIcon />
            <span>Open editor</span>
          </button>
        ) : null}

        {error ? <p className="agent-canvas-inspector__error" role="alert">{error}</p> : null}
      </div>

      <footer>
        <button
          type="button"
          className="agent-canvas-inspector__danger"
          aria-label="Delete node"
          title="Delete node"
          disabled={pending}
          onClick={() => void perform(() => onDelete(node.node_id))}
        >
          <TrashIcon />
        </button>
        <div>
          {["script", "image", "video", "audio"].includes(node.node_type)
            && (node.status === "draft" || node.status === "failed") ? (
            <button
              type="button"
              aria-label={node.status === "failed" ? "Retry node" : "Run node"}
              title={node.status === "failed" ? "Retry node" : "Run node"}
              disabled={pending}
              onClick={() => void run()}
            >
              <PlayIcon />
            </button>
          ) : null}
          {node.node_type !== "editing" ? (
            <button
              type="button"
              className="agent-canvas-inspector__save"
              aria-label={isReadyMedia ? "Save variation draft" : "Save node"}
              title={isReadyMedia ? "Save variation draft" : "Save node"}
              disabled={pending}
              onClick={() => void save()}
            >
              <SaveIcon />
            </button>
          ) : null}
        </div>
      </footer>
    </aside>
  );
}

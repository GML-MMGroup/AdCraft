import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { api, mediaUrl } from "../api/client";
import { ASSET_LIBRARY_UPLOAD_EVENT } from "../api/workflowNormalizers";
import { AssetsIcon, CloseIcon, SendIcon, UploadIcon } from "../icons";
import { useApp } from "../AppContextValue";
import type { AssetLibraryReference, AssetReferenceSuggestCategory, AssetReferenceSuggestion, AssetUploadOptions, CanvasTargetReference, ChatNodeReference } from "../types";
import {
  ASSET_MENTION_CATEGORIES,
  type AssetReferenceTargetContext,
  type ReferenceScope,
  assetMentionQueryFromText,
  assetReferenceKey,
  assetReferenceFromSuggestion,
  mergeAssetReferences,
  syncAssetMentionReferencesWithText,
} from "../workflow/assetMentions";
import {
  canvasTargetReferenceFromAssetSuggestion,
  mergeCanvasTargetReferences,
  syncCanvasTargetReferencesWithText,
} from "../workflow/canvasTargets.ts";
import {
  canvasTargetReferenceFromOption,
  mergeNodeReferences,
  nodeReferenceFromOption,
  syncNodeMentionReferencesWithText,
  type NodeMentionOption,
} from "../workflow/nodeMentions.ts";
import {
  composerAttachmentFromSuggestion,
  composerAttachmentFromUploadedAsset,
  composerAttachmentFromV2InputAsset,
  mergeComposerAttachments,
  removeComposerAttachment,
  syncComposerAttachmentsWithReferences,
  type ComposerAttachment,
} from "../workflow/composerAttachments.ts";
import { extractV2AssetLocators } from "../workflow-v2/assetLocators.ts";
import { useV2AssetLocatorPaste } from "../features/workflow/v2/chat/useV2AssetLocatorPaste.ts";
import type { V2InputAssetUploadItem } from "../types-v2.ts";
import type { V2StructuredChatTarget } from "../features/workflow/v2/operations/v2SlotOperationTypes.ts";

export type PromptGenerateContext = {
  asset_references: AssetLibraryReference[];
  node_references?: ChatNodeReference[];
  target_references?: CanvasTargetReference[];
  asset_locators?: string[];
  input_asset_locators?: string[];
  structuredTargets?: V2StructuredChatTarget[];
  selected_item_id?: string | null;
  selected_asset_id?: string | null;
};

type AssetMentionContext = {
  workflowId?: string | null;
  nodeId?: string | null;
};

interface PromptComposerProps {
  placeholder: string;
  onGenerate: (prompt: string, context?: PromptGenerateContext) => Promise<void> | void;
  initialValue?: string;
  compact?: boolean;
  className?: string;
  disabled?: boolean;
  clearOnGenerate?: boolean;
  emptyPromptMessage?: string;
  secondaryActions?: ReactNode;
  assetMentionContext?: AssetMentionContext;
  referenceScope?: ReferenceScope;
  referenceTargetContext?: AssetReferenceTargetContext;
  mentionReferences?: AssetLibraryReference[];
  onMentionReferencesChange?: (references: AssetLibraryReference[]) => void;
  nodeMentionOptions?: NodeMentionOption[];
  mentionNodeReferences?: ChatNodeReference[];
  onMentionNodeReferencesChange?: (references: ChatNodeReference[]) => void;
  mentionTargetReferences?: CanvasTargetReference[];
  onMentionTargetReferencesChange?: (references: CanvasTargetReference[]) => void;
  uploadOptions?: AssetUploadOptions | ((file: File) => AssetUploadOptions);
  onUploadInputAsset?: (file: File) => Promise<V2InputAssetUploadItem[]>;
  acceptedFileTypes?: string;
  assetPickerEnabled?: boolean;
  onUploadFile?: (file: File) => Promise<void> | void;
  onDraftChange?: (prompt: string, context?: PromptGenerateContext) => void;
}

const DEFAULT_ACCEPTED_FILE_TYPES = "image/*,video/*,audio/*,.pdf,.txt,.md,.doc,.docx,application/pdf,text/plain,text/markdown,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export function PromptComposer({
  placeholder,
  onGenerate,
  initialValue = "",
  compact = false,
  className,
  disabled = false,
  clearOnGenerate = true,
  emptyPromptMessage = "Describe the video you want to create first.",
  secondaryActions,
  assetMentionContext,
  referenceScope = "global_prompt",
  referenceTargetContext,
  mentionReferences: controlledMentionReferences,
  onMentionReferencesChange,
  nodeMentionOptions = [],
  mentionNodeReferences: controlledMentionNodeReferences,
  onMentionNodeReferencesChange,
  mentionTargetReferences: controlledMentionTargetReferences,
  onMentionTargetReferencesChange,
  uploadOptions,
  onUploadInputAsset,
  acceptedFileTypes = DEFAULT_ACCEPTED_FILE_TYPES,
  assetPickerEnabled = true,
  onUploadFile,
  onDraftChange,
}: PromptComposerProps) {
  const [value, setValue] = useState(initialValue);
  const [error, setError] = useState("");
  const [localMentionReferences, setLocalMentionReferences] = useState<AssetLibraryReference[]>([]);
  const [localMentionNodeReferences, setLocalMentionNodeReferences] = useState<ChatNodeReference[]>([]);
  const [localMentionTargetReferences, setLocalMentionTargetReferences] = useState<CanvasTargetReference[]>([]);
  const [structuredTargets, setStructuredTargets] = useState<V2StructuredChatTarget[]>([]);
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const [assetPickerOpen, setAssetPickerOpen] = useState(false);
  const [assetPickerQuery, setAssetPickerQuery] = useState("");
  const [assetPickerSuggestions, setAssetPickerSuggestions] = useState<AssetReferenceSuggestion[]>([]);
  const [assetPickerLoading, setAssetPickerLoading] = useState(false);
  const [assetPickerError, setAssetPickerError] = useState("");
  const [assetPickerRefreshNonce, setAssetPickerRefreshNonce] = useState(0);
  const mentionReferences = controlledMentionReferences ?? localMentionReferences;
  const nodeMentionReferences = controlledMentionNodeReferences ?? localMentionNodeReferences;
  const canvasTargetReferences = controlledMentionTargetReferences ?? localMentionTargetReferences;
  const effectiveReferenceTargetContext = {
    ...referenceTargetContext,
    referenceScope,
  };
  const inputRef = useRef<HTMLInputElement>(null);
  const { uploadAsset, busy } = useApp();
  const controlsDisabled = busy || disabled;
  const resolveV2AssetLocators = useV2AssetLocatorPaste(assetMentionContext?.workflowId, (target) => {
    setStructuredTargets((current) => mergeStructuredTargets(current, [target]));
  });

  function draftContext(
    prompt: string,
    nextReferences = mentionReferences,
    nextAttachments = attachments,
    nextNodeReferences = nodeMentionReferences,
    nextTargetReferences = canvasTargetReferences,
    nextStructuredTargets = structuredTargets,
  ): PromptGenerateContext {
    return {
      asset_references: mergeAssetReferences(
        nextReferences,
        nextAttachments.map((item) => item.reference),
      ),
      node_references: nextNodeReferences,
      target_references: nextTargetReferences,
      asset_locators: extractV2AssetLocators(prompt),
      input_asset_locators: uniqueStrings(nextAttachments.map((item) => item.inputAssetLocator).filter((locator): locator is string => Boolean(locator))),
      structuredTargets: nextStructuredTargets,
    };
  }

  function notifyDraftChange(
    prompt: string,
    nextReferences = mentionReferences,
    nextAttachments = attachments,
    nextNodeReferences = nodeMentionReferences,
    nextTargetReferences = canvasTargetReferences,
    nextStructuredTargets = structuredTargets,
  ) {
    onDraftChange?.(prompt, draftContext(prompt, nextReferences, nextAttachments, nextNodeReferences, nextTargetReferences, nextStructuredTargets));
  }

  useEffect(() => {
    setValue(initialValue);
    setError("");
  }, [initialValue]);

  useEffect(() => {
    if (!assetPickerOpen) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setAssetPickerLoading(true);
      setAssetPickerError("");
      api
        .suggestAssetReferences({
          q: assetPickerQuery,
          workflow_id: assetMentionContext?.workflowId,
          node_id: assetMentionContext?.nodeId,
          include_canvas_assets: true,
          include_library_assets: true,
          limit: 30,
        })
        .then((response) => {
          if (cancelled) return;
          setAssetPickerSuggestions(response.suggestions ?? []);
        })
        .catch((loadError) => {
          if (cancelled) return;
          setAssetPickerSuggestions([]);
          setAssetPickerError(loadError instanceof Error ? loadError.message : "Asset suggestions failed");
        })
        .finally(() => {
          if (!cancelled) setAssetPickerLoading(false);
        });
    }, 180);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [assetMentionContext?.nodeId, assetMentionContext?.workflowId, assetPickerOpen, assetPickerQuery, assetPickerRefreshNonce]);

  useEffect(() => {
    function handleAssetLibraryRefresh() {
      setAssetPickerRefreshNonce((value) => value + 1);
    }

    window.addEventListener(ASSET_LIBRARY_UPLOAD_EVENT, handleAssetLibraryRefresh);
    return () => {
      window.removeEventListener(ASSET_LIBRARY_UPLOAD_EVENT, handleAssetLibraryRefresh);
    };
  }, []);

  function setMentionReferences(references: AssetLibraryReference[]) {
    if (onMentionReferencesChange) {
      onMentionReferencesChange(references);
      return;
    }
    setLocalMentionReferences(references);
  }

  function setMentionNodeReferences(references: ChatNodeReference[]) {
    if (onMentionNodeReferencesChange) {
      onMentionNodeReferencesChange(references);
      return;
    }
    setLocalMentionNodeReferences(references);
  }

  function setMentionTargetReferences(references: CanvasTargetReference[]) {
    if (onMentionTargetReferencesChange) {
      onMentionTargetReferencesChange(references);
      return;
    }
    setLocalMentionTargetReferences(references);
  }

  async function handleFile(file?: File) {
    if (!file) return;
    setError("");
    try {
      if (onUploadFile) {
        await onUploadFile(file);
        return;
      }
      const resolvedUploadOptions = typeof uploadOptions === "function"
        ? uploadOptions(file)
        : uploadOptions ?? { asset_role: "reference" };
      if (onUploadInputAsset) {
        const inputAssets = await onUploadInputAsset(file);
        const inputAttachments = inputAssets.map(composerAttachmentFromV2InputAsset).filter((item): item is ComposerAttachment => Boolean(item));
        const nextAttachments = mergeComposerAttachments(attachments, inputAttachments);
        setAttachments(nextAttachments);
        notifyDraftChange(value, mentionReferences, nextAttachments);
        return;
      }
      const asset = await uploadAsset(file, resolvedUploadOptions);
      const attachment = composerAttachmentFromUploadedAsset(asset);
      if (attachment) {
        const nextAttachments = mergeComposerAttachments(attachments, [attachment]);
        setAttachments(nextAttachments);
        notifyDraftChange(value, mentionReferences, nextAttachments);
      }
    } catch (event) {
      setError(event instanceof Error ? event.message : "Upload failed");
    }
  }

  async function submit() {
    setError("");
    const prompt = value.trim();
    if (!prompt) {
      setError(emptyPromptMessage);
      return;
    }
    try {
      const context = draftContext(prompt);
      if (clearOnGenerate) clearMessageDraft();
      await onGenerate(prompt, context);
    } catch (event) {
      setError(event instanceof Error ? event.message : "Send failed");
    }
  }

  function clearMessageDraft() {
    setValue("");
    setMentionReferences([]);
    setMentionNodeReferences([]);
    setMentionTargetReferences([]);
    setStructuredTargets([]);
    setAttachments([]);
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    void submit();
  }

  function handleComposerChange(
    nextValue: string,
    nextReferences: AssetLibraryReference[],
    nextNodeReferences: ChatNodeReference[],
    nextTargetReferences: CanvasTargetReference[],
  ) {
    const nextStructuredTargets = syncStructuredTargetsWithText(structuredTargets, nextValue);
    const nextAttachments = syncComposerAttachmentsWithReferences(attachments, nextReferences);
    setValue(nextValue);
    setMentionReferences(nextReferences);
    setMentionNodeReferences(nextNodeReferences);
    setMentionTargetReferences(nextTargetReferences);
    setStructuredTargets(nextStructuredTargets);
    void resolveV2AssetLocators(nextValue);
    setAttachments(nextAttachments);
    notifyDraftChange(nextValue, nextReferences, nextAttachments, nextNodeReferences, nextTargetReferences, nextStructuredTargets);
  }

  function handleAssetSuggestionSelected(suggestion: AssetReferenceSuggestion, reference: AssetLibraryReference) {
    const attachment = composerAttachmentFromSuggestion(suggestion, reference);
    if (attachment) {
      const nextAttachments = mergeComposerAttachments(attachments, [attachment]);
      setAttachments(nextAttachments);
      notifyDraftChange(value, mentionReferences, nextAttachments);
    }
  }

  function openAssetPicker() {
    setAssetPickerError("");
    setAssetPickerOpen((current) => !current);
  }

  function selectAssetPickerSuggestion(suggestion: AssetReferenceSuggestion) {
    const reference: AssetLibraryReference = {
      ...assetReferenceFromSuggestionForComposer(
        suggestion,
        effectiveReferenceTargetContext,
        assetMentionContext?.nodeId,
      ),
      mention_text: undefined,
    };
    const attachment = composerAttachmentFromSuggestion(suggestion, reference);
    if (!attachment) {
      setAssetPickerError("Only image assets can be attached here.");
      return;
    }
    const nextReferences = mergeAssetReferences(mentionReferences, [reference]);
    const nextAttachments = mergeComposerAttachments(attachments, [attachment]);
    setMentionReferences(nextReferences);
    setAttachments(nextAttachments);
    notifyDraftChange(value, nextReferences, nextAttachments);
    setAssetPickerOpen(false);
    setAssetPickerQuery("");
  }

  function removeAttachment(attachment: ComposerAttachment) {
    const removedReferenceKey = assetReferenceKey(attachment.reference);
    const nextAttachments = removeComposerAttachment(attachments, attachment.id);
    const nextReferences = mentionReferences.filter((reference) => assetReferenceKey(reference) !== removedReferenceKey);
    setAttachments(nextAttachments);
    setMentionReferences(nextReferences);
    notifyDraftChange(value, nextReferences, nextAttachments);
  }

  return (
    <div className={`prompt-composer ${compact ? "is-compact" : ""} ${className ?? ""}`}>
      <ComposerAttachmentPreview attachments={attachments} onRemove={removeAttachment} />
      <AssetMentionInput
        value={value}
        placeholder={placeholder}
        disabled={controlsDisabled}
        mentionReferences={mentionReferences}
        mentionNodeReferences={nodeMentionReferences}
        mentionTargetReferences={canvasTargetReferences}
        nodeMentionOptions={nodeMentionOptions}
        workflowId={assetMentionContext?.workflowId}
        nodeId={assetMentionContext?.nodeId}
        referenceTargetContext={effectiveReferenceTargetContext}
        onKeyDown={handleKeyDown}
        onAssetSuggestionSelected={handleAssetSuggestionSelected}
        onChange={handleComposerChange}
      />
      {error ? <div className="inline-error">{error}</div> : null}
      <AssetMentionChips references={mentionReferences} />
      <NodeMentionChips references={nodeMentionReferences} />
      <TargetMentionChips references={canvasTargetReferences} />
      {assetPickerEnabled && assetPickerOpen ? (
        <ComposerAssetPicker
          query={assetPickerQuery}
          suggestions={assetPickerSuggestions}
          loading={assetPickerLoading}
          error={assetPickerError}
          onQueryChange={setAssetPickerQuery}
          onClose={() => setAssetPickerOpen(false)}
          onSelect={selectAssetPickerSuggestion}
        />
      ) : null}
      <div className="composer-footer">
        <div className="composer-tools">
          <input
            ref={inputRef}
            aria-label="Upload file"
            type="file"
            hidden
            accept={acceptedFileTypes}
            onChange={(event) => {
              void handleFile(event.currentTarget.files?.[0]);
              event.currentTarget.value = "";
            }}
          />
          <button className="pill-btn icon-only" aria-label="Upload file" title="Upload file" onClick={() => inputRef.current?.click()} disabled={controlsDisabled}>
            <UploadIcon />
          </button>
          {assetPickerEnabled ? (
            <button
              className={`pill-btn icon-only ${assetPickerOpen ? "is-active" : ""}`}
              type="button"
              aria-label="Choose asset"
              title="Choose asset"
              aria-expanded={assetPickerOpen}
              onClick={openAssetPicker}
              disabled={controlsDisabled}
            >
              <AssetsIcon />
            </button>
          ) : null}
          {secondaryActions}
        </div>
        <button className="send-btn icon-only" aria-label="Generate" title="Generate" onClick={() => void submit()} disabled={controlsDisabled}>
          <SendIcon />
        </button>
      </div>
    </div>
  );
}

type LocalPromptComposerProps = Omit<PromptComposerProps, "compact" | "className">

export function LocalPromptComposer({ clearOnGenerate = true, ...props }: LocalPromptComposerProps) {
  return (
    <PromptComposer
      {...props}
      compact
      className="local-prompt-composer"
      clearOnGenerate={clearOnGenerate}
    />
  );
}

function assetReferenceFromSuggestionForComposer(
  suggestion: AssetReferenceSuggestion,
  referenceTargetContext: AssetReferenceTargetContext | undefined,
  fallbackNodeId?: string | null,
) {
  const referenceScope = referenceTargetContext?.referenceScope ?? "global_prompt";
  return assetReferenceFromSuggestion(suggestion, {
    ...referenceTargetContext,
    referenceScope,
    nodeId: referenceScope === "global_prompt" ? null : referenceTargetContext?.nodeId ?? fallbackNodeId,
  });
}

function ComposerAttachmentPreview({
  attachments,
  onRemove,
}: {
  attachments: ComposerAttachment[];
  onRemove: (attachment: ComposerAttachment) => void;
}) {
  if (!attachments.length) return null;
  return (
    <div className="composer-attachment-preview" aria-label="Current message attachments">
      {attachments.map((attachment, index) => {
        const src = attachmentPreviewSrc(attachment.previewUrl);
        const label = attachment.reference.display_name ?? attachment.filename ?? attachment.assetId ?? `Attachment ${index + 1}`;
        return (
          <div className="composer-attachment-item" key={attachment.id}>
            {src ? <img src={src} alt={label} loading="lazy" decoding="async" /> : null}
            <span className="composer-attachment-fallback">
              <AssetsIcon />
            </span>
            <button
              className="composer-attachment-remove"
              type="button"
              aria-label={`Remove attachment ${label}`}
              title="Remove attachment"
              onClick={() => onRemove(attachment)}
            >
              <CloseIcon />
            </button>
          </div>
        );
      })}
    </div>
  );
}

function attachmentPreviewSrc(path?: string | null) {
  if (!path) return "";
  if (/^(https?:|data:|blob:)/i.test(path) || path.startsWith("/")) return path;
  return mediaUrl(path);
}

function ComposerAssetPicker({
  query,
  suggestions,
  loading,
  error,
  onQueryChange,
  onClose,
  onSelect,
}: {
  query: string;
  suggestions: AssetReferenceSuggestion[];
  loading: boolean;
  error: string;
  onQueryChange: (query: string) => void;
  onClose: () => void;
  onSelect: (suggestion: AssetReferenceSuggestion) => void;
}) {
  return (
    <div className="composer-asset-picker" role="dialog" aria-label="Choose asset">
      <div className="composer-asset-picker-header">
        <input
          className="composer-asset-picker-search"
          value={query}
          placeholder="Search assets"
          aria-label="Search assets"
          autoFocus
          onChange={(event) => onQueryChange(event.target.value)}
        />
        <button className="composer-asset-picker-close" type="button" aria-label="Close asset picker" title="Close" onClick={onClose}>
          <CloseIcon />
        </button>
      </div>
      <div className="composer-asset-picker-list" role="listbox" aria-label="Asset results">
        {loading ? <span className="composer-asset-picker-empty">Searching assets...</span> : null}
        {error ? <span className="composer-asset-picker-empty">{error}</span> : null}
        {!loading && !error && !suggestions.length ? <span className="composer-asset-picker-empty">No matching assets</span> : null}
        {suggestions.slice(0, 30).map((suggestion) => (
          <button
            key={[suggestion.reference_source, suggestion.entity_id ?? "", suggestion.asset_id ?? "", suggestion.display_name].join(":")}
            className="composer-asset-picker-option"
            type="button"
            role="option"
            onClick={() => onSelect(suggestion)}
          >
            <AssetMentionThumb suggestion={suggestion} />
            <span>
              <strong>{suggestion.display_name}</strong>
              <em>{suggestion.entity_type ?? suggestion.asset_type ?? "asset"} · {suggestion.reference_source === "canvas_asset" ? "Current canvas" : "Asset Library"}</em>
            </span>
            {suggestion.warning || suggestion.warnings?.length ? <small>{suggestion.warning ?? suggestion.warnings?.[0]}</small> : null}
          </button>
        ))}
      </div>
    </div>
  );
}

export function AssetMentionInput({
  value,
  placeholder,
  mentionReferences,
  mentionNodeReferences = [],
  mentionTargetReferences = [],
  nodeMentionOptions = [],
  workflowId,
  nodeId,
  referenceTargetContext,
  rows,
  className,
  disabled = false,
  onKeyDown,
  onAssetSuggestionSelected,
  onChange,
}: {
  value: string;
  placeholder?: string;
  mentionReferences: AssetLibraryReference[];
  mentionNodeReferences?: ChatNodeReference[];
  mentionTargetReferences?: CanvasTargetReference[];
  nodeMentionOptions?: NodeMentionOption[];
  workflowId?: string | null;
  nodeId?: string | null;
  referenceTargetContext?: AssetReferenceTargetContext;
  rows?: number;
  className?: string;
  disabled?: boolean;
  onKeyDown?: (event: ReactKeyboardEvent<HTMLTextAreaElement>) => void;
  onAssetSuggestionSelected?: (suggestion: AssetReferenceSuggestion, reference: AssetLibraryReference) => void;
  onChange: (value: string, references: AssetLibraryReference[], nodeReferences: ChatNodeReference[], targetReferences: CanvasTargetReference[]) => void;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [activeCategory, setActiveCategory] = useState<AssetReferenceSuggestCategory>("all");
  const [query, setQuery] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [triggerRange, setTriggerRange] = useState<{ start: number; end: number } | null>(null);
  const [suggestions, setSuggestions] = useState<AssetReferenceSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [assetMentionRefreshNonce, setAssetMentionRefreshNonce] = useState(0);
  const activeCategoryConfig = useMemo(
    () => ASSET_MENTION_CATEGORIES.find((item) => item.key === activeCategory) ?? ASSET_MENTION_CATEGORIES[0],
    [activeCategory],
  );
  const nodeSuggestions = useMemo(
    () => filterNodeMentionOptionList(nodeMentionOptions, query).slice(0, 12),
    [nodeMentionOptions, query],
  );

  useEffect(() => {
    if (!menuOpen) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError("");
      api
        .suggestAssetReferences({
          q: query,
          types: activeCategoryConfig.types,
          workflow_id: workflowId,
          node_id: nodeId,
          include_canvas_assets: true,
          include_library_assets: true,
          limit: 30,
        })
        .then((response) => {
          if (cancelled) return;
          setSuggestions(response.suggestions ?? []);
        })
        .catch((loadError) => {
          if (cancelled) return;
          setSuggestions([]);
          setError(loadError instanceof Error ? loadError.message : "Asset suggestions failed");
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 180);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [activeCategoryConfig.types, activeCategory, menuOpen, nodeId, query, workflowId, assetMentionRefreshNonce]);

  useEffect(() => {
    function handleAssetLibraryRefresh() {
      setAssetMentionRefreshNonce((value) => value + 1);
    }

    window.addEventListener(ASSET_LIBRARY_UPLOAD_EVENT, handleAssetLibraryRefresh);
    return () => {
      window.removeEventListener(ASSET_LIBRARY_UPLOAD_EVENT, handleAssetLibraryRefresh);
    };
  }, []);

  function updateMentionTrigger(nextValue: string, caretIndex: number | null | undefined) {
    const trigger = assetMentionQueryFromText(nextValue, caretIndex);
    setTriggerRange(trigger ? { start: trigger.start, end: trigger.end } : null);
    setQuery(trigger?.query ?? "");
    setMenuOpen(Boolean(trigger));
  }

  function handleChange(nextValue: string, caretIndex: number | null | undefined) {
    const nextReferences = syncAssetMentionReferencesWithText(nextValue, mentionReferences);
    const nextNodeReferences = syncNodeMentionReferencesWithText(nextValue, mentionNodeReferences);
    const nextTargetReferences = syncCanvasTargetReferencesWithText(nextValue, mentionTargetReferences);
    onChange(nextValue, nextReferences, nextNodeReferences, nextTargetReferences);
    updateMentionTrigger(nextValue, caretIndex);
  }

  function selectSuggestion(suggestion: AssetReferenceSuggestion) {
    const reference = assetReferenceFromSuggestionForComposer(suggestion, referenceTargetContext, nodeId);
    const mentionText = reference.mention_text ?? `@${suggestion.display_name}`;
    const range = triggerRange ?? { start: value.length, end: value.length };
    const prefix = value.slice(0, range.start);
    const suffix = value.slice(range.end);
    const needsTrailingSpace = suffix.length > 0 && !/^\s/.test(suffix);
    const nextValue = `${prefix}${mentionText}${needsTrailingSpace ? " " : ""}${suffix}`;
    const nextReferences = mergeAssetReferences(mentionReferences, [reference]);
    const targetReference = canvasTargetReferenceFromAssetSuggestion(suggestion, { nodeId, mentionText });
    const nextTargetReferences = targetReference
      ? mergeCanvasTargetReferences(mentionTargetReferences, [targetReference])
      : mentionTargetReferences;
    onChange(nextValue, nextReferences, mentionNodeReferences, nextTargetReferences);
    onAssetSuggestionSelected?.(suggestion, reference);
    setMenuOpen(false);
    setQuery("");
    setTriggerRange(null);
    window.setTimeout(() => {
      const nextCaret = prefix.length + mentionText.length + (needsTrailingSpace ? 1 : 0);
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(nextCaret, nextCaret);
    }, 0);
  }

  function selectNodeSuggestion(option: NodeMentionOption) {
    const targetReference = canvasTargetReferenceFromOption(option);
    const mentionText = targetReference.mention_text ?? option.mention_text;
    const range = triggerRange ?? { start: value.length, end: value.length };
    const prefix = value.slice(0, range.start);
    const suffix = value.slice(range.end);
    const needsTrailingSpace = suffix.length > 0 && !/^\s/.test(suffix);
    const nextValue = `${prefix}${mentionText}${needsTrailingSpace ? " " : ""}${suffix}`;
    const nextNodeReferences = targetReference.target_type === "node"
      ? mergeNodeReferences(mentionNodeReferences, [nodeReferenceFromOption(option)])
      : mentionNodeReferences;
    const nextTargetReferences = mergeCanvasTargetReferences(mentionTargetReferences, [targetReference]);
    onChange(nextValue, mentionReferences, nextNodeReferences, nextTargetReferences);
    setMenuOpen(false);
    setQuery("");
    setTriggerRange(null);
    window.setTimeout(() => {
      const nextCaret = prefix.length + mentionText.length + (needsTrailingSpace ? 1 : 0);
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(nextCaret, nextCaret);
    }, 0);
  }

  return (
    <div className={`asset-mention-input ${className ?? ""}`}>
      <textarea
        ref={textareaRef}
        value={value}
        rows={rows}
        placeholder={placeholder}
        disabled={disabled}
        onKeyDown={onKeyDown}
        onChange={(event) => handleChange(event.target.value, event.target.selectionStart)}
        onClick={(event) => updateMentionTrigger(value, event.currentTarget.selectionStart)}
        onKeyUp={(event) => updateMentionTrigger(value, event.currentTarget.selectionStart)}
      />
      {menuOpen ? (
        <div className="asset-mention-menu" role="listbox" aria-label="@asset suggestions">
          {nodeSuggestions.length ? (
            <div className="node-mention-section" aria-label="@node suggestions">
              <strong>Nodes</strong>
              {nodeSuggestions.map((option) => (
                <button
                  key={[option.target_type ?? "node", option.node_id, option.item_id ?? "", option.asset_id ?? ""].join(":")}
                  className="asset-mention-option node-mention-option"
                  type="button"
                  role="option"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => selectNodeSuggestion(option)}
                >
                  <span className="asset-mention-thumb">N</span>
                  <span>
                    <strong>{option.mention_text}</strong>
                    <em>{option.title} · {option.target_type ?? "node"} · {option.semantic_type ?? option.node_type ?? option.node_id}</em>
                  </span>
                </button>
              ))}
            </div>
          ) : null}
          <div className="asset-mention-category-row">
            {ASSET_MENTION_CATEGORIES.map((category) => (
              <button
                key={category.key}
                className={category.key === activeCategory ? "is-active" : ""}
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => setActiveCategory(category.key)}
              >
                {category.label}
              </button>
            ))}
          </div>
          {loading ? <span className="asset-mention-empty">Searching assets...</span> : null}
          {error ? <span className="asset-mention-empty">{error}</span> : null}
          {!loading && !error && !suggestions.length ? <span className="asset-mention-empty">No matching assets</span> : null}
          {suggestions.slice(0, 30).map((suggestion) => (
            <button
              key={[suggestion.reference_source, suggestion.entity_id ?? "", suggestion.asset_id ?? "", suggestion.display_name].join(":")}
              className="asset-mention-option"
              type="button"
              role="option"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => selectSuggestion(suggestion)}
            >
              <AssetMentionThumb suggestion={suggestion} />
              <span>
                <strong>{suggestion.display_name}</strong>
                <em>{suggestion.entity_type ?? suggestion.asset_type ?? "asset"} · {suggestion.reference_source === "canvas_asset" ? "Current canvas" : "Asset Library"}</em>
              </span>
              {suggestion.warning || suggestion.warnings?.length ? <small>{suggestion.warning ?? suggestion.warnings?.[0]}</small> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function AssetMentionThumb({ suggestion }: { suggestion: AssetReferenceSuggestion }) {
  const path = suggestion.thumbnail_url ?? suggestion.preview_url ?? suggestion.thumbnail_path ?? suggestion.local_path;
  if (!path) return <span className="asset-mention-thumb">{suggestion.reference_source === "canvas_asset" ? "C" : "L"}</span>;
  const src = /^https?:\/\//i.test(path) || path.startsWith("/") ? path : mediaUrl(path);
  return (
    <span className="asset-mention-thumb has-image">
      <img src={src} alt="" loading="lazy" decoding="async" />
    </span>
  );
}

function AssetMentionChips({ references }: { references: AssetLibraryReference[] }) {
  if (!references.length) return null;
  return (
    <div className="asset-mention-chips" aria-label="Selected @asset references">
      {references.map((reference) => (
        <span key={[reference.reference_source ?? "asset_library", reference.entity_id ?? "", reference.asset_id ?? "", reference.target_node_id ?? ""].join(":")} className="asset-mention-chip">
          <span>{reference.mention_text ?? reference.display_name ?? reference.entity_id ?? reference.asset_id}</span>
          <em>{reference.reference_source === "canvas_asset" ? "Current canvas" : "Asset Library"}</em>
        </span>
      ))}
    </div>
  );
}

function NodeMentionChips({ references }: { references: ChatNodeReference[] }) {
  if (!references.length) return null;
  return (
    <div className="asset-mention-chips node-mention-chips" aria-label="Selected @node references">
      {references.map((reference) => (
        <span key={[reference.node_id, reference.node_type ?? "", reference.mention_text].join(":")} className="asset-mention-chip node-mention-chip">
          <span>{reference.mention_text}</span>
          <em>{reference.node_type ?? "node"}</em>
        </span>
      ))}
    </div>
  );
}

function TargetMentionChips({ references }: { references: CanvasTargetReference[] }) {
  const visibleReferences = references.filter((reference) => reference.target_type !== "node");
  if (!visibleReferences.length) return null;
  return (
    <div className="asset-mention-chips target-mention-chips" aria-label="Selected canvas target references">
      {visibleReferences.map((reference) => (
        <span key={[reference.target_type, reference.node_id ?? "", reference.item_id ?? "", reference.asset_id ?? ""].join(":")} className="asset-mention-chip target-mention-chip">
          <span>{reference.mention_text ?? reference.asset_id ?? reference.item_id ?? reference.node_id}</span>
          <em>{reference.target_type}{reference.semantic_type ? ` · ${reference.semantic_type}` : ""}</em>
        </span>
      ))}
    </div>
  );
}

function filterNodeMentionOptionList(options: NodeMentionOption[], query: string) {
  const normalizedQuery = normalizeNodeMentionFilter(query);
  if (!normalizedQuery) return options;
  return options.filter((option) =>
    [option.node_id, option.node_type ?? "", option.title, option.mention_text, option.item_id ?? "", option.asset_id ?? "", option.semantic_type ?? "", option.target_type ?? ""]
      .some((value) => normalizeNodeMentionFilter(value).includes(normalizedQuery)),
  );
}

function normalizeNodeMentionFilter(value: string) {
  return value.toLowerCase().replace(/^@/, "").replace(/[^a-z0-9\u4e00-\u9fa5]+/g, "");
}

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
}

function mergeStructuredTargets(current: V2StructuredChatTarget[], next: V2StructuredChatTarget[]) {
  const merged = new Map<string, V2StructuredChatTarget>();
  for (const target of [...current, ...next]) {
    merged.set(structuredTargetKey(target), target);
  }
  return Array.from(merged.values());
}

function syncStructuredTargetsWithText(targets: V2StructuredChatTarget[], text: string) {
  return targets.filter((target) => {
    const locator = target.asset_id && target.version_id ? `asset:${target.asset_id}@${target.version_id}` : "";
    const mentionText = target.mention_text ?? "";
    return (locator && text.includes(locator)) || (mentionText && text.includes(mentionText));
  });
}

function structuredTargetKey(target: V2StructuredChatTarget) {
  return [
    target.target_type,
    target.node_id ?? "",
    target.item_id ?? "",
    target.slot_id ?? "",
    target.asset_id ?? "",
    target.version_id ?? "",
  ].join(":");
}

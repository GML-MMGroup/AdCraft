import { useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { CloseIcon, SendIcon, UploadIcon } from "../icons";
import type { V2InputAssetUploadItem } from "../types-v2.ts";

const ASSET_LOCATOR_PATTERN = /asset:[A-Za-z0-9_-]+@[A-Za-z0-9_-]+/g;

export type HomePromptGenerateContext = {
  asset_locators?: string[];
  input_asset_locators?: string[];
};

type HomePromptAttachment = {
  id: string;
  label: string;
  locator?: string;
  previewUrl?: string | null;
};

interface HomePromptComposerProps {
  placeholder: string;
  onGenerate: (prompt: string, context?: HomePromptGenerateContext) => Promise<void> | void;
  onUploadInputAsset?: (file: File) => Promise<V2InputAssetUploadItem[]>;
}

export function HomePromptComposer({ placeholder, onGenerate, onUploadInputAsset }: HomePromptComposerProps) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [attachments, setAttachments] = useState<HomePromptAttachment[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleFile(file?: File) {
    if (!file || !onUploadInputAsset) return;
    setError("");
    setBusy(true);
    try {
      const inputAssets = await onUploadInputAsset(file);
      setAttachments((current) => mergeAttachments(current, inputAssets.map(attachmentFromInputAsset)));
    } catch (event) {
      setError(event instanceof Error ? event.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    setError("");
    const prompt = value.trim();
    if (!prompt) {
      setError("Describe the video you want to create first.");
      return;
    }
    setBusy(true);
    try {
      await onGenerate(prompt, {
        asset_locators: extractAssetLocators(prompt),
        input_asset_locators: uniqueStrings(attachments.map((item) => item.locator).filter((locator): locator is string => Boolean(locator))),
      });
      setValue("");
      setAttachments([]);
    } catch (event) {
      setError(event instanceof Error ? event.message : "Send failed");
    } finally {
      setBusy(false);
    }
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    void submit();
  }

  return (
    <div className="prompt-composer home-prompt-composer">
      {attachments.length ? (
        <div className="composer-attachment-preview">
          {attachments.map((attachment) => (
            <span className="composer-attachment-item" key={attachment.id}>
              {attachment.previewUrl ? <img src={attachment.previewUrl} alt={attachment.label} loading="lazy" decoding="async" /> : <span className="composer-attachment-fallback">{attachment.label.slice(0, 1).toUpperCase()}</span>}
              <button
                className="composer-attachment-remove"
                type="button"
                aria-label={`Remove ${attachment.label}`}
                onClick={() => setAttachments((current) => current.filter((item) => item.id !== attachment.id))}
              >
                <CloseIcon />
              </button>
            </span>
          ))}
        </div>
      ) : null}
      <textarea
        value={value}
        placeholder={placeholder}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={handleKeyDown}
      />
      {error ? <div className="inline-error">{error}</div> : null}
      <div className="composer-footer">
        <div className="composer-tools">
          <input
            ref={inputRef}
            type="file"
            hidden
            accept="image/*,video/*,audio/*,.pdf,.txt,.md,.doc,.docx,application/pdf,text/plain,text/markdown,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={(event) => {
              void handleFile(event.target.files?.[0]);
              event.currentTarget.value = "";
            }}
          />
          <button className="pill-btn icon-only" aria-label="Upload file" title="Upload file" onClick={() => inputRef.current?.click()} disabled={busy}>
            <UploadIcon />
          </button>
        </div>
        <button className="send-btn icon-only" aria-label="Generate" title="Generate" onClick={() => void submit()} disabled={busy}>
          <SendIcon />
        </button>
      </div>
    </div>
  );
}

function attachmentFromInputAsset(asset: V2InputAssetUploadItem): HomePromptAttachment {
  return {
    id: asset.locator || `${asset.asset_id}:${asset.version_id}`,
    label: asset.display_name || asset.asset_id || "Uploaded reference",
    locator: asset.locator,
    previewUrl: asset.public_url,
  };
}

function mergeAttachments(current: HomePromptAttachment[], incoming: HomePromptAttachment[]) {
  const next = [...current];
  for (const attachment of incoming) {
    if (!next.some((item) => item.id === attachment.id)) next.push(attachment);
  }
  return next;
}

function extractAssetLocators(text: string) {
  return uniqueStrings(text.match(ASSET_LOCATOR_PATTERN) ?? []);
}

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values));
}

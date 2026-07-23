import { CloseIcon } from "../../../icons.tsx";
import type { SlotMicroEditAttachment } from "../v2/slots/useSlotMicroEdit.ts";

type V2BgmReferenceAttachmentsProps = {
  attachments: SlotMicroEditAttachment[];
  onRemove: (attachment: SlotMicroEditAttachment) => void;
};

const MAX_FILENAME_LENGTH = 64;

const STATUS_LABELS: Record<SlotMicroEditAttachment["status"], string> = {
  draft: "Ready",
  registering: "Uploading",
  registered: "Registered",
  attached: "Attached",
  failed: "Upload failed",
};

export function V2BgmReferenceAttachments({
  attachments,
  onRemove,
}: V2BgmReferenceAttachmentsProps) {
  if (!attachments.length) return null;

  return (
    <div className="v2-bgm-reference-attachments" aria-label="BGM reference attachments">
      {attachments.map((attachment, index) => {
        const filename = safeFilename(attachment.filename, index);
        return (
          <span
            className={`v2-bgm-reference-attachment status-${attachment.status}`}
            key={attachment.id}
          >
            <span className="v2-bgm-reference-filename">{filename}</span>
            <span className="v2-bgm-reference-status">{STATUS_LABELS[attachment.status]}</span>
            <button
              type="button"
              className="icon-only"
              aria-label={`Remove ${filename}`}
              title={attachment.status === "registering" ? "Upload in progress" : `Remove ${filename}`}
              disabled={attachment.status === "registering"}
              onClick={() => onRemove(attachment)}
            >
              <CloseIcon />
            </button>
          </span>
        );
      })}
    </div>
  );
}

function safeFilename(filename: string | null | undefined, index: number) {
  const basename = filename?.split(/[\\/]/).pop()?.trim() || `Audio reference ${index + 1}`;
  if (basename.length <= MAX_FILENAME_LENGTH) return basename;

  const extensionIndex = basename.lastIndexOf(".");
  const extension = extensionIndex > 0 ? basename.slice(extensionIndex) : "";
  if (extension.length > 0 && extension.length <= 12) {
    return `${basename.slice(0, MAX_FILENAME_LENGTH - extension.length - 3)}...${extension}`;
  }
  return `${basename.slice(0, MAX_FILENAME_LENGTH - 3)}...`;
}

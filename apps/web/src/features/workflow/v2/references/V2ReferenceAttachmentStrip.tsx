import type { V2SlotAttachment } from "../operations/v2SlotOperationTypes.ts";
import { DeferredVideo } from "../../../../components/media/DeferredVideo.tsx";

type V2ReferenceAttachmentStripProps = {
  attachments: V2SlotAttachment[];
  onRemove: (attachment: V2SlotAttachment) => void;
};

export function V2ReferenceAttachmentStrip({ attachments, onRemove }: V2ReferenceAttachmentStripProps) {
  if (!attachments.length) return null;
  return (
    <div className="v2-reference-attachment-strip" aria-label="Slot scoped reference attachments">
      {attachments.map((attachment) => (
        <figure className="v2-reference-attachment" key={`${attachment.sourceAssetId}:${attachment.sourceVersionId ?? "current"}`}>
          {attachment.mediaType === "image" && attachment.previewUrl ? <img src={attachment.previewUrl} alt={attachment.displayName} loading="lazy" decoding="async" /> : null}
          {attachment.mediaType === "video" && attachment.previewUrl ? <DeferredVideo src={attachment.previewUrl} muted playsInline preload="metadata" /> : null}
          {attachment.mediaType === "audio" && attachment.previewUrl ? <audio src={attachment.previewUrl} controls preload="metadata" /> : null}
          {attachment.mediaType !== "image" && attachment.mediaType !== "video" && attachment.mediaType !== "audio" ? <span>{attachment.displayName}</span> : null}
          <figcaption>
            <strong>{attachment.displayName}</strong>
            <small>{attachment.semanticType}</small>
          </figcaption>
          <button type="button" aria-label={`Remove reference ${attachment.displayName}`} onClick={() => onRemove(attachment)}>
            Remove
          </button>
        </figure>
      ))}
    </div>
  );
}

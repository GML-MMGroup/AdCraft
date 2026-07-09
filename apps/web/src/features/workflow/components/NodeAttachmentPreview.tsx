import { mediaUrl } from "../../../api/client";
import { DocumentIcon } from "../../../icons";
import { assetFileMissing } from "../../../workflow/assetLifecycle.ts";
import { mediaAssetOriginalPath, mediaAssetPosterPath, mediaAssetPreviewPath } from "../../../workflow/mediaPreview.ts";
import type { UploadedAsset } from "../../../types";

/* eslint-disable jsx-a11y/no-static-element-interactions, jsx-a11y/no-noninteractive-tabindex -- Legacy compound attachment tile supports optional open behavior while preserving a nested remove button. */
export function NodeAttachmentPreview({ asset, onRemove, onOpen }: { asset: UploadedAsset; onRemove?: () => void; onOpen?: () => void }) {
  const assetType = asset.asset_type as string;
  const missingFile = assetFileMissing(asset);
  const previewPath = mediaAssetPreviewPath(asset) || mediaAssetPosterPath(asset) || mediaAssetOriginalPath(asset);
  const previewSrc = mediaUrl(previewPath);
  const isImage = !missingFile && assetType === "image" && previewSrc;

  return (
    <span
      className={`node-attachment-tile ${onOpen ? "is-openable" : ""} ${missingFile ? "is-missing-file" : ""}`}
      data-asset-id={asset.asset_id}
      title={asset.filename}
      role={onOpen ? "button" : undefined}
      tabIndex={onOpen ? 0 : undefined}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (!onOpen) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
    >
      {missingFile ? <span className="node-attachment-missing">文件缺失 / 不可预览</span> : isImage ? <img src={previewSrc} alt={asset.filename} loading="lazy" decoding="async" /> : <DocumentIcon />}
      {onRemove ? (
        <button
          type="button"
          aria-label={`Remove ${asset.filename}`}
          onClick={(event) => {
            event.stopPropagation();
            onRemove();
          }}
        >
          x
        </button>
      ) : null}
    </span>
  );
}
/* eslint-enable jsx-a11y/no-static-element-interactions, jsx-a11y/no-noninteractive-tabindex */

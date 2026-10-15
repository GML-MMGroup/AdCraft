import { AssetsIcon, UploadIcon } from "../../../icons.tsx";
import { useTranslation } from "../../../i18n/useTranslation.ts";

export function NodeAssetActions({
  disabled = false,
  showUpload = true,
  onUpload,
  onOpenAssets,
}: {
  disabled?: boolean;
  showUpload?: boolean;
  onUpload: () => void;
  onOpenAssets: () => void;
}) {
  const t = useTranslation("en-US");
  return (
    <div className="agent-node-workbench__asset-actions" aria-label={t("Reference actions")}>
      {showUpload ? (
        <button
          type="button"
          aria-label={t("Upload image reference")}
          title={t("Upload reference")}
          disabled={disabled}
          onClick={onUpload}
        >
          <UploadIcon />
        </button>
      ) : null}
      <button
        type="button"
        aria-label={t("Choose asset references")}
        title={t("Choose from Assets")}
        disabled={disabled}
        onClick={onOpenAssets}
      >
        <AssetsIcon />
      </button>
    </div>
  );
}

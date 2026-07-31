import { AssetsIcon, UploadIcon } from "../../../icons.tsx";

export function NodeAssetActions({
  disabled = false,
  onUpload,
  onOpenAssets,
}: {
  disabled?: boolean;
  onUpload: () => void;
  onOpenAssets: () => void;
}) {
  return (
    <div className="agent-node-workbench__asset-actions" aria-label="Reference actions">
      <button
        type="button"
        aria-label="Upload image reference"
        title="Upload reference"
        disabled={disabled}
        onClick={onUpload}
      >
        <UploadIcon />
      </button>
      <button
        type="button"
        aria-label="Choose asset references"
        title="Choose from Assets"
        disabled={disabled}
        onClick={onOpenAssets}
      >
        <AssetsIcon />
      </button>
    </div>
  );
}

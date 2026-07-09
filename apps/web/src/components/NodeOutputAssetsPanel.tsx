import { memo, type ReactNode } from "react";

type NodeOutputAssetsPanelProps = {
  children: ReactNode;
};

export const NodeOutputAssetsPanel = memo(function NodeOutputAssetsPanel({ children }: NodeOutputAssetsPanelProps) {
  return <div className="asset-preview-section">{children}</div>;
});

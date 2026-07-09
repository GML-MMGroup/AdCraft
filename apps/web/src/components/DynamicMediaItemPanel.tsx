import { memo, type ReactNode } from "react";

type DynamicMediaItemPanelProps = {
  children: ReactNode;
};

export const DynamicMediaItemPanel = memo(function DynamicMediaItemPanel({ children }: DynamicMediaItemPanelProps) {
  return <div className="dynamic-media-item-panel">{children}</div>;
});

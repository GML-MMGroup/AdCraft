import { memo, type ReactNode } from "react";

type FinalCompositionPanelProps = {
  children: ReactNode;
};

export const FinalCompositionPanel = memo(function FinalCompositionPanel({ children }: FinalCompositionPanelProps) {
  return <div className="final-composition-panel">{children}</div>;
});

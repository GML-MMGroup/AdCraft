import type { ReactNode } from "react";
import { ChevronDownIcon, ConfirmIcon } from "../../../icons.tsx";

/** A compact, read-only record of a choice, with its original context on demand. */
export function SelectionReceipt({ label, heading, value, children }: {
  label: string;
  heading: string;
  value: string;
  children?: ReactNode;
}) {
  const summary = <>
    <span className="agent-chat__selection-receipt-mark" aria-hidden="true"><ConfirmIcon /></span>
    <span className="agent-chat__selection-receipt-copy"><small>{heading}</small><strong>{value}</strong></span>
    {children ? <ChevronDownIcon /> : null}
  </>;
  return <article className="agent-chat__selection-receipt" aria-label={label}>
    {children ? <details>
      <summary>{summary}</summary>
      <div className="agent-chat__selection-receipt-detail">{children}</div>
    </details> : <div className="agent-chat__selection-receipt-summary">{summary}</div>}
  </article>;
}

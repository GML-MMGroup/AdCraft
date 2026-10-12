import { useEffect, useState } from "react";
import { BrandTreatmentReview } from "../brand/BrandTreatmentReview";
import "./brand-treatment-confirmation.css";
export function BrandTreatmentConfirmation({ workflowId, responseLocale, onConfirmed, onProductionRefresh }: {
  workflowId: string; responseLocale: string; onConfirmed: () => Promise<void> | void; onProductionRefresh?: () => Promise<void> | void;
}) {
  const [open, setOpen] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [visible, setVisible] = useState(() => document.visibilityState !== "hidden");
  useEffect(() => {
    const updateVisibility = () => setVisible(document.visibilityState !== "hidden");
    document.addEventListener("visibilitychange", updateVisibility);
    return () => document.removeEventListener("visibilitychange", updateVisibility);
  }, []);
  const zh = responseLocale.startsWith("zh");
  return <section className="brand-treatment-confirmation"
    data-awaiting-review={!open && !confirmed}
    data-motion-paused={!visible}
    aria-label={zh ? "创意方案确认" : "Treatment confirmation"}>
    <p>{zh ? "请查看完整创意方案及执行限制，确认后锁定。" : "Review the full treatment and execution limitations, then confirm to lock."}</p>
    <button type="button" onClick={() => setOpen(true)}>{zh ? "打开最终审阅" : "Review treatment"}</button>
    {open && <BrandTreatmentReview key={workflowId} workflowId={workflowId} onClose={() => setOpen(false)}
      onConfirmed={async () => {
        // The lock succeeded before this callback; do not resume the reminder
        // if refreshing the workspace fails or the parent stays mounted.
        setConfirmed(true);
        await onConfirmed();
      }} onProductionRefresh={onProductionRefresh}/>}
  </section>;
}

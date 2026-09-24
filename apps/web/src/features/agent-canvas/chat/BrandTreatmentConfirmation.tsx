import { useState } from "react";
import { BrandTreatmentReview } from "../brand/BrandTreatmentReview";
export function BrandTreatmentConfirmation({ workflowId, responseLocale, onConfirmed, onProductionRefresh }: {
  workflowId: string; responseLocale: string; onConfirmed: () => Promise<void> | void; onProductionRefresh?: () => Promise<void> | void;
}) {
  const [open, setOpen] = useState(false);
  const zh = responseLocale.startsWith("zh");
  return <section className="agent-chat__notice" aria-label={zh ? "创意方案确认" : "Treatment confirmation"}>
    <p>{zh ? "请查看完整创意方案及执行限制，确认后锁定。" : "Review the full treatment and execution limitations, then confirm to lock."}</p>
    <button type="button" onClick={() => setOpen(true)}>{zh ? "打开最终审阅" : "Review treatment"}</button>
    {open && <BrandTreatmentReview key={workflowId} workflowId={workflowId} onClose={() => setOpen(false)} onConfirmed={onConfirmed} onProductionRefresh={onProductionRefresh}/>}
  </section>;
}

import { useRef, useState } from "react";
import { agentCanvasApi } from "../../../api/agentCanvasApi.ts";

export function BrandTreatmentConfirmation({
  workflowId,
  responseLocale,
  onConfirmed,
}: {
  workflowId: string;
  responseLocale: string;
  onConfirmed: () => Promise<void> | void;
}) {
  const inFlight = useRef(false);
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  const chinese = responseLocale.startsWith("zh");

  async function confirm() {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    setFailed(false);
    try {
      await agentCanvasApi.brandLockTreatment(workflowId);
      await onConfirmed();
    } catch {
      setFailed(true);
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }

  return (
    <section className="agent-chat__notice" aria-label={chinese ? "创意方案确认" : "Treatment confirmation"}>
      <div>
        <p>{chinese
          ? "八项创意方案已完成，声音/BGM 选择已保存。请确认并锁定当前方案。"
          : "All eight treatment decisions are complete, including sound/BGM. Confirm and lock the treatment."}</p>
        {failed ? <p role="alert">{chinese ? "确认失败，请重试。" : "Confirmation failed. Please retry."}</p> : null}
        <button type="button" disabled={pending} onClick={() => void confirm()}>
          {pending
            ? (chinese ? "正在确认…" : "Confirming…")
            : (chinese ? "确认并锁定创意方案" : "Confirm and lock treatment")}
        </button>
      </div>
    </section>
  );
}

import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";

import type { ProviderBalanceNotice } from "./providerBalanceNotice.ts";
import "./ProviderBalanceDialog.css";

export function ProviderBalanceDialog({
  notice,
  onDismiss,
}: {
  notice: ProviderBalanceNotice;
  onDismiss: () => void;
}) {
  const titleId = useId();
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onDismiss();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onDismiss]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <div className="provider-balance-notice">
      <button
        type="button"
        className="provider-balance-notice__backdrop"
        aria-label="关闭余额不足提示"
        tabIndex={-1}
        onClick={onDismiss}
      />
      <section
        className="provider-balance-notice__panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <h2 id={titleId} className="provider-balance-notice__title">
          {notice.providerLabel} 账户余额不足
        </h2>
        <p className="provider-balance-notice__body">
          本次生成已停止：{notice.providerLabel}认为当前 API Key 的余额或额度不足。
          请为该供应商的 API Key 充值或更换 Key 后重新运行。
        </p>
        {notice.detail ? (
          <p className="provider-balance-notice__detail">{notice.detail}</p>
        ) : null}
        <div className="provider-balance-notice__actions">
          <button type="button" ref={closeRef} onClick={onDismiss}>
            知道了
          </button>
        </div>
      </section>
    </div>,
    document.body,
  );
}

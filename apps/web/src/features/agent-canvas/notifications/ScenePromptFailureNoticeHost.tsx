import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { useTranslation } from "../../../i18n/useTranslation.ts";
import type { CanvasRuntimeSnapshotV2 } from "../../../types-v2.ts";
import {
  scenePromptFailureNotice,
  type ScenePromptFailureNode,
  type ScenePromptFailureNotice,
} from "./scenePromptFailureNotice.ts";
import "./ScenePromptFailureNoticeHost.css";

export function ScenePromptFailureNoticeHost({ nodes, runtime, onInspect }: {
  nodes: readonly ScenePromptFailureNode[];
  runtime: CanvasRuntimeSnapshotV2 | null;
  onInspect?: (nodeId: string) => void;
}) {
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(() => new Set());
  const notice = nodes.map(node => scenePromptFailureNotice(
    node,
    runtime?.workflow_id === node.workflow_id ? runtime.node_runtime[node.node_id] : undefined,
  )).find(candidate => candidate && !dismissed.has(candidate.key));
  if (!notice) return null;
  const dismiss = () => setDismissed(current => new Set([...current, notice.key]));
  return <ScenePromptFailureDialog key={notice.key} notice={notice} onDismiss={dismiss}
    onInspect={onInspect ? () => { dismiss(); onInspect(notice.nodeId); } : undefined} />;
}

function ScenePromptFailureDialog({ notice, onDismiss, onInspect }: {
  notice: ScenePromptFailureNotice;
  onDismiss: () => void;
  onInspect?: () => void;
}) {
  const t = useTranslation();
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    const previousFocus = document.activeElement;
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || !dialog) return;
      const buttons = [...dialog.querySelectorAll<HTMLButtonElement>("button")];
      const first = buttons[0];
      const last = buttons.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first?.focus();
      }
    };
    dialog?.addEventListener("keydown", trapFocus);
    dialog?.showModal();
    confirmRef.current?.focus();
    return () => {
      dialog?.removeEventListener("keydown", trapFocus);
      dialog?.close();
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
  }, []);

  return createPortal(
    <dialog ref={dialogRef} className="scene-prompt-failure" role="alertdialog"
      aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId}
      onCancel={event => { event.preventDefault(); onDismiss(); }}>
      <h2 id={titleId}>{t("Scene generation was blocked by a prompt check")}</h2>
      <div id={descriptionId} className="scene-prompt-failure__copy">
        <p className="scene-prompt-failure__node">{notice.nodeTitle}</p>
        <p>{t(notice.reason)}</p>
        <p>{t("This scene image is still missing. Any multi-view generation that depends on it cannot continue. Your completed content has been preserved.")}</p>
        <p className="scene-prompt-failure__guidance">{t(notice.guidance)}</p>
      </div>
      <div className="scene-prompt-failure__actions">
        {onInspect ? <button type="button" onClick={onInspect}>{t("View scene")}</button> : null}
        <button type="button" ref={confirmRef} onClick={onDismiss}>{t("Got it")}</button>
      </div>
    </dialog>,
    document.body,
  );
}

import { useEffect, useRef } from "react";
import type { ChangeEventHandler } from "react";
import type { FocusEventHandler } from "react";
import type { RefObject } from "react";

const FOUR_LINE_HEIGHT = 88;

export function FourLinePromptEditor({
  ariaLabel,
  value,
  disabled = false,
  placeholder,
  preparing = false,
  onChange,
  onBlur,
  editorRef: providedEditorRef,
}: {
  ariaLabel: string;
  value: string;
  disabled?: boolean;
  placeholder?: string;
  preparing?: boolean;
  onChange: ChangeEventHandler<HTMLTextAreaElement>;
  onBlur?: FocusEventHandler<HTMLTextAreaElement>;
  editorRef?: RefObject<HTMLTextAreaElement | null>;
}) {
  const internalEditorRef = useRef<HTMLTextAreaElement>(null);
  const editorRef = providedEditorRef ?? internalEditorRef;

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;

    const onWheel = (event: WheelEvent) => {
      const maximumScroll = editor.scrollHeight - editor.clientHeight;
      if (maximumScroll <= 0 || event.deltaY === 0) return;

      const reachedBoundary = event.deltaY > 0
        ? editor.scrollTop >= maximumScroll
        : editor.scrollTop <= 0;
      if (reachedBoundary) return;

      event.preventDefault();
      const nextScrollTop = editor.scrollTop + (event.deltaY > 0 ? FOUR_LINE_HEIGHT : -FOUR_LINE_HEIGHT);
      editor.scrollTop = Math.max(0, Math.min(maximumScroll, nextScrollTop));
    };

    editor.addEventListener("wheel", onWheel, { passive: false });
    return () => editor.removeEventListener("wheel", onWheel);
  }, [editorRef]);

  const showPreparingPrompt = preparing && !value.trim();

  return (
    <span className="agent-node-workbench__editor-shell">
      {showPreparingPrompt ? (
        <span className="agent-node-workbench__preparing-prompt" aria-hidden="true">
          提示词正在准备...
        </span>
      ) : null}
      <textarea
        ref={editorRef}
        className="agent-node-workbench__four-line-editor"
        aria-label={ariaLabel}
        aria-busy={showPreparingPrompt}
        value={value}
        disabled={disabled}
        placeholder={showPreparingPrompt ? undefined : placeholder}
        onChange={onChange}
        onBlur={onBlur}
      />
    </span>
  );
}

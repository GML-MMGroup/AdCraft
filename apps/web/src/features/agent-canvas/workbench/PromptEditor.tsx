import { useEffect, useRef, useState } from "react";
import type { ChangeEventHandler } from "react";
import type { FocusEventHandler } from "react";
import type { RefObject } from "react";
import { useTranslation } from "../../../i18n/useTranslation.ts";

const VISIBLE_LINES = 7;
const DEFAULT_LINE_HEIGHT = 22;
const PREPARING_CHARACTER_DELAY = 150;
const PREPARING_HOLD_DELAY = 900;

export function PromptEditor({
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
  const t = useTranslation("en-US");
  const preparingPromptText = t("Prompt is being prepared...");
  const internalEditorRef = useRef<HTMLTextAreaElement>(null);
  const editorRef = providedEditorRef ?? internalEditorRef;
  const [preparingText, setPreparingText] = useState("");

  useEffect(() => {
    if (!preparing || value.trim()) {
      setPreparingText("");
      return undefined;
    }

    const delay = preparingText.length < preparingPromptText.length
      ? PREPARING_CHARACTER_DELAY
      : PREPARING_HOLD_DELAY;
    const timer = window.setTimeout(() => {
      setPreparingText((current) => current.length < preparingPromptText.length
        ? preparingPromptText.slice(0, current.length + 1)
        : "");
    }, delay);
    return () => window.clearTimeout(timer);
  }, [preparing, preparingText, preparingPromptText, value]);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;

    let scrollTimer: number | undefined;
    const lineHeight = () => Number.parseFloat(window.getComputedStyle(editor).lineHeight) || DEFAULT_LINE_HEIGHT;
    const alignScroll = () => {
      const maximumScroll = Math.max(0, editor.scrollHeight - editor.clientHeight);
      const height = lineHeight();
      editor.scrollTop = Math.max(0, Math.min(maximumScroll, Math.round(editor.scrollTop / height) * height));
    };
    const onScroll = () => {
      window.clearTimeout(scrollTimer);
      // Scrollbar, touch and caret movement can otherwise stop between text lines.
      scrollTimer = window.setTimeout(alignScroll, 100);
    };
    const onWheel = (event: WheelEvent) => {
      const maximumScroll = editor.scrollHeight - editor.clientHeight;
      if (maximumScroll <= 0 || event.deltaY === 0) return;

      const reachedBoundary = event.deltaY > 0
        ? editor.scrollTop >= maximumScroll
        : editor.scrollTop <= 0;
      if (reachedBoundary) return;

      event.preventDefault();
      const height = lineHeight();
      const nextLine = Math.round(editor.scrollTop / height) + (event.deltaY > 0 ? VISIBLE_LINES : -VISIBLE_LINES);
      const nextScrollTop = nextLine * height;
      editor.scrollTop = Math.max(0, Math.min(maximumScroll, nextScrollTop));
    };

    editor.addEventListener("wheel", onWheel, { passive: false });
    editor.addEventListener("scroll", onScroll);
    return () => {
      editor.removeEventListener("wheel", onWheel);
      editor.removeEventListener("scroll", onScroll);
      window.clearTimeout(scrollTimer);
    };
  }, [editorRef]);

  const showPreparingPrompt = preparing && !value.trim();

  return (
    <span className="agent-node-workbench__editor-shell">
      {showPreparingPrompt ? (
        <span className="agent-node-workbench__preparing-prompt" aria-hidden="true">
          {preparingText}
        </span>
      ) : null}
      <textarea
        ref={editorRef}
        rows={VISIBLE_LINES}
        className="agent-node-workbench__prompt-editor"
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

import { useEffect, useRef } from "react";
import type { ChangeEventHandler } from "react";
import type { FocusEventHandler } from "react";

const FOUR_LINE_HEIGHT = 88;

export function FourLinePromptEditor({
  ariaLabel,
  value,
  disabled = false,
  placeholder,
  onChange,
  onBlur,
}: {
  ariaLabel: string;
  value: string;
  disabled?: boolean;
  placeholder?: string;
  onChange: ChangeEventHandler<HTMLTextAreaElement>;
  onBlur?: FocusEventHandler<HTMLTextAreaElement>;
}) {
  const editorRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;

    const onWheel = (event: WheelEvent) => {
      const maximumScroll = editor.scrollHeight - editor.clientHeight;
      if (maximumScroll <= 0 || event.deltaY === 0) return;

      event.preventDefault();
      const nextScrollTop = editor.scrollTop + (event.deltaY > 0 ? FOUR_LINE_HEIGHT : -FOUR_LINE_HEIGHT);
      editor.scrollTop = Math.max(0, Math.min(maximumScroll, nextScrollTop));
    };

    editor.addEventListener("wheel", onWheel, { passive: false });
    return () => editor.removeEventListener("wheel", onWheel);
  }, []);

  return (
    <textarea
      ref={editorRef}
      className="agent-node-workbench__four-line-editor"
      aria-label={ariaLabel}
      value={value}
      disabled={disabled}
      placeholder={placeholder}
      onChange={onChange}
      onBlur={onBlur}
    />
  );
}

import type { ChangeEventHandler, WheelEventHandler } from "react";

const FOUR_LINE_HEIGHT = 88;

export function FourLinePromptEditor({
  ariaLabel,
  value,
  disabled = false,
  placeholder,
  onChange,
}: {
  ariaLabel: string;
  value: string;
  disabled?: boolean;
  placeholder?: string;
  onChange: ChangeEventHandler<HTMLTextAreaElement>;
}) {
  const onWheel: WheelEventHandler<HTMLTextAreaElement> = (event) => {
    const editor = event.currentTarget;
    const maximumScroll = editor.scrollHeight - editor.clientHeight;
    if (maximumScroll <= 0 || event.deltaY === 0) return;

    event.preventDefault();
    const nextScrollTop = editor.scrollTop + (event.deltaY > 0 ? FOUR_LINE_HEIGHT : -FOUR_LINE_HEIGHT);
    editor.scrollTop = Math.max(0, Math.min(maximumScroll, nextScrollTop));
  };

  return (
    <textarea
      className="agent-node-workbench__four-line-editor"
      aria-label={ariaLabel}
      value={value}
      disabled={disabled}
      placeholder={placeholder}
      onChange={onChange}
      onWheel={onWheel}
    />
  );
}

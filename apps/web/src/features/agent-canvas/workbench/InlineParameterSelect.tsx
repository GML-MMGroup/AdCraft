import { useId } from "react";
import { createPortal } from "react-dom";
import { ChevronDownIcon, ChevronUpIcon } from "../../../icons.tsx";
import { useWorkbenchMenu } from "./useWorkbenchMenu.ts";

export function InlineParameterSelect({
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  options: readonly string[];
  disabled: boolean;
  onChange: (value: string | undefined) => void;
}) {
  const menuId = useId();
  const { open, setOpen, menuStyle, triggerRef, menuRef } = useWorkbenchMenu(disabled, options.length);
  const unsupported = Boolean(value) && !options.includes(value);
  const selectedLabel = unsupported ? `${value} (unsupported)` : value || "Not set";
  const select = (next: string | undefined) => {
    if (disabled) return;
    onChange(next);
    setOpen(false);
    triggerRef.current?.focus();
  };

  return (
    <div className="agent-node-workbench__model-picker agent-node-workbench__model-picker--monochrome">
      <details open={open}>
        <summary
          ref={triggerRef}
          aria-label={label}
          aria-expanded={open}
          aria-haspopup="listbox"
          aria-controls={open ? menuId : undefined}
          aria-disabled={disabled}
          title={selectedLabel}
          onClick={(event) => {
            event.preventDefault();
            if (!disabled) setOpen((current) => !current);
          }}
        >
          <span>{selectedLabel}</span>
          <span className="agent-node-workbench__model-chevron" aria-hidden="true">
            {open ? <ChevronDownIcon /> : <ChevronUpIcon />}
          </span>
        </summary>
      </details>
      {open ? createPortal(
        <div
          id={menuId}
          ref={menuRef}
          className="agent-node-workbench__model-menu agent-node-workbench__model-menu--monochrome"
          role="listbox"
          aria-label={label}
          style={menuStyle}
        >
          <button type="button" role="option" aria-selected={!value} disabled={disabled} onClick={() => select(undefined)}>
            <strong>Not set</strong>
          </button>
          {unsupported ? (
            <button type="button" role="option" aria-selected disabled>
              <strong>{selectedLabel}</strong>
            </button>
          ) : null}
          {options.map((option) => (
            <button
              type="button"
              role="option"
              key={option}
              aria-selected={value === option}
              disabled={disabled}
              onClick={() => select(option)}
            >
              <strong>{option}</strong>
            </button>
          ))}
        </div>,
        document.body,
      ) : null}
    </div>
  );
}

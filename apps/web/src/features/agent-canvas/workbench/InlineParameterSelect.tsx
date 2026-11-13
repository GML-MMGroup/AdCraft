import { useId } from "react";
import { createPortal } from "react-dom";
import { ChevronDownIcon, ChevronUpIcon } from "../../../icons.tsx";
import { useWorkbenchMenu } from "./useWorkbenchMenu.ts";
import { useTranslation } from "../../../i18n/useTranslation.ts";
import { resolutionAspectRatio } from "./resolutionAspectRatio.ts";
import { AspectRatioIcon } from "./AspectRatioIcon.tsx";

export function InlineParameterSelect({
  label,
  value,
  options,
  disabled,
  onChange,
  unsetLabel,
  valueSuffix = "",
}: {
  label: string;
  value: string;
  options: readonly string[];
  disabled: boolean;
  unsetLabel?: string;
  valueSuffix?: string;
  onChange: (value: string | undefined) => void;
}) {
  const t = useTranslation("en-US");
  const menuId = useId();
  const { open, setOpen, menuStyle, triggerRef, menuRef } = useWorkbenchMenu(disabled, options.length);
  const optionLabel = (option: string) => {
    const ratio = resolutionAspectRatio(option);
    return ratio ? t("{value} ({ratio})", { value: option, ratio }) : `${option}${valueSuffix}`;
  };
  const emptyLabel = unsetLabel ?? t("Not set");
  const unsupported = Boolean(value) && !options.includes(value);
  const selectedLabel = unsupported ? t("{value} (unsupported)", { value: optionLabel(value) }) : value ? optionLabel(value) : emptyLabel;
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
          <span className="agent-node-workbench__parameter-value">
            <AspectRatioIcon value={value} />
            <span className="agent-node-workbench__model-name-text">{selectedLabel}</span>
          </span>
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
            <strong>{emptyLabel}</strong>
          </button>
          {unsupported ? (
            <button type="button" role="option" aria-selected disabled>
              <span className="agent-node-workbench__model-option-name">
                <AspectRatioIcon value={value} /><strong>{selectedLabel}</strong>
              </span>
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
              <span className="agent-node-workbench__model-option-name">
                <AspectRatioIcon value={option} /><strong>{optionLabel(option)}</strong>
              </span>
            </button>
          ))}
        </div>,
        document.body,
      ) : null}
    </div>
  );
}

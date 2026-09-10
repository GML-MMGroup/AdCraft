import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ModelParameterDescriptorV1 } from "../../../api/providerRegistry.ts";
import { ModelParameterControls } from "./ModelParameterControls.tsx";

const descriptors: ModelParameterDescriptorV1[] = [
  {
    name: "duration_seconds",
    value_type: "enum",
    required: false,
    allowed_values: ["5", "10", "30"],
    minimum: null,
    maximum: null,
    default: "10",
  },
  {
    name: "generate_audio",
    value_type: "boolean",
    required: false,
    allowed_values: [],
    minimum: null,
    maximum: null,
    default: null,
  },
];

afterEach(() => cleanup());

describe("ModelParameterControls", () => {
  it("uses the shared monochrome menu for inline enums without changing parameter identities", () => {
    const onChange = vi.fn();
    const props = { descriptors, parameters: { generate_audio: true }, disabled: false, onChange, layout: "inline" as const };
    const { rerender } = render(<ModelParameterControls {...props} />);
    const trigger = screen.getByLabelText("Duration seconds");
    expect(trigger.closest(".agent-node-workbench__model-picker--monochrome")).toBeTruthy();
    fireEvent.click(trigger);
    const menu = screen.getByRole("listbox", { name: "Duration seconds" });
    expect(menu.classList.contains("agent-node-workbench__model-menu--monochrome")).toBe(true);
    expect(screen.getAllByRole("option").map((item) => item.textContent)).toEqual(["Not set", "5", "10", "30"]);
    fireEvent.click(screen.getByRole("option", { name: "30", exact: true }));
    expect(onChange).toHaveBeenLastCalledWith({ generate_audio: true, duration_seconds: "30" });
    expect(screen.queryByRole("listbox")).toBeNull();
    rerender(<ModelParameterControls {...props} parameters={{ generate_audio: true, duration_seconds: "30" }} />);
    fireEvent.click(trigger);
    expect(screen.getByRole("option", { name: "30", exact: true }).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByRole("option", { name: "Not set" }));
    expect(onChange).toHaveBeenLastCalledWith({ generate_audio: true });
  });

  it("preserves unsupported inline values and dismisses or disables the menu without changes", () => {
    const onChange = vi.fn();
    const props = { descriptors, parameters: { duration_seconds: "45" }, disabled: false, onChange, layout: "inline" as const };
    const { rerender } = render(<ModelParameterControls {...props} />);
    const trigger = screen.getByLabelText("Duration seconds");
    expect(trigger.textContent).toContain("45 (unsupported)");
    expect(screen.getByText("Choose one of: 5, 10, 30.")).toBeTruthy();
    fireEvent.click(trigger);
    expect((screen.getByRole("option", { name: "45 (unsupported)" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(document.activeElement).toBe(screen.getByRole("option", { name: "Not set" }));
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(screen.getByRole("option", { name: "5", exact: true }));
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
    expect(document.activeElement).toBe(screen.getByRole("option", { name: "Not set" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(document.activeElement).toBe(trigger);
    fireEvent.click(trigger);
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("listbox")).toBeNull();
    fireEvent.click(trigger);
    rerender(<ModelParameterControls {...props} disabled />);
    expect(screen.queryByRole("listbox")).toBeNull();
    fireEvent.click(trigger);
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("renders only backend descriptors and leaves defaults unset", () => {
    render(
      <ModelParameterControls
        descriptors={descriptors}
        parameters={{}}
        disabled={false}
        onChange={vi.fn()}
      />,
    );

    expect((screen.getByLabelText("Duration seconds") as HTMLSelectElement).value).toBe("");
    expect((screen.getByLabelText("Generate audio") as HTMLInputElement).checked).toBe(false);
    expect(screen.queryByLabelText("Resolution")).toBeNull();
  });

  it("submits an advertised 30-second value and can explicitly clear it", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <ModelParameterControls
        descriptors={descriptors}
        parameters={{}}
        disabled={false}
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByLabelText("Duration seconds"), { target: { value: "30" } });
    expect(onChange).toHaveBeenLastCalledWith({ duration_seconds: "30" });

    rerender(
      <ModelParameterControls
        descriptors={descriptors}
        parameters={{ duration_seconds: "30" }}
        disabled={false}
        onChange={onChange}
      />,
    );
    fireEvent.change(screen.getByLabelText("Duration seconds"), { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith({});
  });

  it("keeps an incompatible existing value visible with a correction error", () => {
    render(
      <ModelParameterControls
        descriptors={descriptors}
        parameters={{ duration_seconds: "45" }}
        disabled={false}
        onChange={vi.fn()}
      />,
    );

    expect((screen.getByLabelText("Duration seconds") as HTMLSelectElement).value).toBe("45");
    expect(screen.getByText("Choose one of: 5, 10, 30.")).toBeTruthy();
  });
});

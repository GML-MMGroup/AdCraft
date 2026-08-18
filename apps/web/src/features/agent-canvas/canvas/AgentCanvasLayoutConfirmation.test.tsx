import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentCanvasLayoutConfirmation } from "./AgentCanvasLayoutConfirmation.tsx";

afterEach(() => cleanup());

describe("AgentCanvasLayoutConfirmation", () => {
  it("renders approved copy and dispatches explicit actions", () => {
    const onUndo = vi.fn();
    const onKeep = vi.fn();
    render(
      <AgentCanvasLayoutConfirmation
        status="previewing"
        error={null}
        onUndo={onUndo}
        onKeep={onKeep}
      />,
    );

    expect(document.body.contains(screen.getByRole("dialog", { name: "是否保留此次排布" }))).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "保留" }));
    expect(onKeep).toHaveBeenCalledOnce();
    expect(onUndo).not.toHaveBeenCalled();
  });

  it("focuses its heading on mount", () => {
    render(
      <AgentCanvasLayoutConfirmation
        status="previewing"
        error={null}
        onUndo={vi.fn()}
        onKeep={vi.fn()}
      />,
    );

    expect(document.activeElement).toBe(screen.getByText("是否保留此次排布"));
  });

  it("uses Escape to undo", () => {
    const onUndo = vi.fn();
    render(
      <AgentCanvasLayoutConfirmation
        status="previewing"
        error={null}
        onUndo={onUndo}
        onKeep={vi.fn()}
      />,
    );

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onUndo).toHaveBeenCalledOnce();
  });

  it("undoes on an outside pointerdown but not a pointerdown inside the dialog", () => {
    const onUndo = vi.fn();
    render(
      <AgentCanvasLayoutConfirmation
        status="previewing"
        error={null}
        onUndo={onUndo}
        onKeep={vi.fn()}
      />,
    );

    fireEvent.pointerDown(screen.getByRole("dialog"));
    expect(onUndo).not.toHaveBeenCalled();

    fireEvent.pointerDown(document.body);
    expect(onUndo).toHaveBeenCalledOnce();
  });

  it("disables actions and ignores dismissal while saving", () => {
    const onUndo = vi.fn();
    const onKeep = vi.fn();
    render(
      <AgentCanvasLayoutConfirmation
        status="saving"
        error={null}
        onUndo={onUndo}
        onKeep={onKeep}
      />,
    );

    expect((screen.getByRole("button", { name: "撤销" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "保留" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.pointerDown(document.body);

    expect(onUndo).not.toHaveBeenCalled();
    expect(onKeep).not.toHaveBeenCalled();
  });

  it("keeps the save error visible with both actions enabled", () => {
    render(
      <AgentCanvasLayoutConfirmation
        status="save_error"
        error="Unable to save the canvas layout."
        onUndo={vi.fn()}
        onKeep={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert").textContent).toBe("Unable to save the canvas layout.");
    expect((screen.getByRole("button", { name: "撤销" }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: "保留" }) as HTMLButtonElement).disabled).toBe(false);
  });
});

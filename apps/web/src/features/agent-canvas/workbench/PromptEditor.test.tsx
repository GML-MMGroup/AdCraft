import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PromptEditor } from "./PromptEditor.tsx";

afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("PromptEditor", () => {
  it("moves by one complete seven-line page for a wheel gesture", () => {
    const { getByLabelText } = render(
      <PromptEditor
        ariaLabel="Generation prompt"
        value="Line 1\nLine 2\nLine 3\nLine 4\nLine 5\nLine 6\nLine 7\nLine 8"
        onChange={vi.fn()}
      />,
    );
    const editor = getByLabelText("Generation prompt") as HTMLTextAreaElement;
    Object.defineProperty(editor, "clientHeight", { configurable: true, value: 154 });
    Object.defineProperty(editor, "scrollHeight", { configurable: true, value: 308 });
    Object.defineProperty(editor, "scrollTop", { configurable: true, value: 0, writable: true });

    fireEvent.wheel(editor, { deltaY: 24 });

    expect(editor.scrollTop).toBe(154);
  });

  it("hands downward scrolling to the workbench after reaching the prompt end", () => {
    const { getByLabelText } = render(
      <PromptEditor
        ariaLabel="Generation prompt"
        value="Line 1\nLine 2\nLine 3\nLine 4\nLine 5\nLine 6\nLine 7\nLine 8"
        onChange={vi.fn()}
      />,
    );
    const editor = getByLabelText("Generation prompt") as HTMLTextAreaElement;
    Object.defineProperty(editor, "clientHeight", { configurable: true, value: 154 });
    Object.defineProperty(editor, "scrollHeight", { configurable: true, value: 308 });
    Object.defineProperty(editor, "scrollTop", { configurable: true, value: 154, writable: true });
    const event = new WheelEvent("wheel", { bubbles: true, cancelable: true, deltaY: 24 });

    editor.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(false);
  });

  it("declares seven rows and aligns a settled scrollbar position to a complete line", () => {
    vi.useFakeTimers();
    const { getByLabelText } = render(
      <PromptEditor ariaLabel="Generation prompt" value="Long prompt" onChange={vi.fn()} />,
    );
    const editor = getByLabelText("Generation prompt") as HTMLTextAreaElement;
    editor.style.lineHeight = "22px";
    Object.defineProperty(editor, "clientHeight", { configurable: true, value: 154 });
    Object.defineProperty(editor, "scrollHeight", { configurable: true, value: 308 });
    Object.defineProperty(editor, "scrollTop", { configurable: true, value: 35, writable: true });

    expect(editor.rows).toBe(7);
    fireEvent.scroll(editor);
    vi.advanceTimersByTime(150);
    expect(editor.scrollTop).toBe(44);
  });

  it("registers the custom wheel handler as non-passive and cleans it up", () => {
    const addEventListener = vi.spyOn(HTMLTextAreaElement.prototype, "addEventListener");
    const removeEventListener = vi.spyOn(HTMLTextAreaElement.prototype, "removeEventListener");
    const { unmount } = render(
      <PromptEditor
        ariaLabel="Generation prompt"
        value="Prompt"
        onChange={vi.fn()}
      />,
    );

    const wheelRegistration = addEventListener.mock.calls.find(([type]) => type === "wheel");
    expect(wheelRegistration?.[2]).toMatchObject({ passive: false });

    unmount();

    expect(removeEventListener).toHaveBeenCalledWith(
      "wheel",
      wheelRegistration?.[1],
    );
  });
});

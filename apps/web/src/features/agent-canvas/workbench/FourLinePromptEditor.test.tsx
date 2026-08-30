import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FourLinePromptEditor } from "./FourLinePromptEditor.tsx";

describe("FourLinePromptEditor", () => {
  it("moves by one complete four-line page for a wheel gesture", () => {
    render(
      <FourLinePromptEditor
        ariaLabel="Generation prompt"
        value="Line 1\nLine 2\nLine 3\nLine 4\nLine 5\nLine 6\nLine 7\nLine 8"
        onChange={vi.fn()}
      />,
    );
    const editor = screen.getByLabelText("Generation prompt") as HTMLTextAreaElement;
    Object.defineProperty(editor, "clientHeight", { configurable: true, value: 88 });
    Object.defineProperty(editor, "scrollHeight", { configurable: true, value: 176 });
    Object.defineProperty(editor, "scrollTop", { configurable: true, value: 0, writable: true });

    fireEvent.wheel(editor, { deltaY: 24 });

    expect(editor.scrollTop).toBe(88);
  });

  it("registers the custom wheel handler as non-passive and cleans it up", () => {
    const addEventListener = vi.spyOn(HTMLTextAreaElement.prototype, "addEventListener");
    const removeEventListener = vi.spyOn(HTMLTextAreaElement.prototype, "removeEventListener");
    const { unmount } = render(
      <FourLinePromptEditor
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

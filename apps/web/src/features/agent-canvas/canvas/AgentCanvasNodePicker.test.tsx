import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentCanvasNodePicker } from "./AgentCanvasNodePicker.tsx";

afterEach(() => cleanup());

describe("AgentCanvasNodePicker", () => {
  it("offers every canonical authoring node type including Script", () => {
    const onSelect = vi.fn();
    const { container } = render(
      <AgentCanvasNodePicker
        menuLabel="Add node types"
        onSelect={onSelect}
      />,
    );

    expect(screen.getAllByRole("menuitem")).toHaveLength(6);
    expect(screen.getByRole("menuitem", { name: "Add Script node" })).toBeTruthy();
    expect(Array.from(container.querySelectorAll(".agent-canvas-node-icon")).map((icon) => icon.getAttribute("data-icon-source"))).toEqual([
      "/imgs/node-icons/text.svg",
      "/imgs/node-icons/text.svg",
      "/imgs/node-icons/picture.svg",
      "/imgs/node-icons/video.svg",
      "/imgs/node-icons/audio.svg",
      "/imgs/node-icons/video.svg",
    ]);

    fireEvent.click(screen.getByRole("menuitem", { name: "Add Script node" }));
    expect(onSelect).toHaveBeenCalledWith("script");
  });
});

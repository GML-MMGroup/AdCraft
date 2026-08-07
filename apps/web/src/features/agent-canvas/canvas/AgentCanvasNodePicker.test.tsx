import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentCanvasNodePicker } from "./AgentCanvasNodePicker.tsx";

afterEach(() => cleanup());

describe("AgentCanvasNodePicker", () => {
  it("offers the visible authoring types without Script", () => {
    const onSelect = vi.fn();
    render(
      <AgentCanvasNodePicker
        menuLabel="Add node types"
        onSelect={onSelect}
      />,
    );

    expect(screen.getAllByRole("menuitem")).toHaveLength(5);
    expect(screen.queryByRole("menuitem", { name: "Add Script node" })).toBeNull();

    fireEvent.click(screen.getByRole("menuitem", { name: "Add Image node" }));
    expect(onSelect).toHaveBeenCalledWith("image");
  });
});

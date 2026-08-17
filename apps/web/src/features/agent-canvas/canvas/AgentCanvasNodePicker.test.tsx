import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentCanvasNodePicker } from "./AgentCanvasNodePicker.tsx";

afterEach(() => cleanup());

describe("AgentCanvasNodePicker", () => {
  it("offers every canonical authoring node type including Script", () => {
    const onSelect = vi.fn();
    render(
      <AgentCanvasNodePicker
        menuLabel="Add node types"
        onSelect={onSelect}
      />,
    );

    expect(screen.getAllByRole("menuitem")).toHaveLength(6);
    expect(screen.getByRole("menuitem", { name: "Add Script node" })).toBeTruthy();

    fireEvent.click(screen.getByRole("menuitem", { name: "Add Script node" }));
    expect(onSelect).toHaveBeenCalledWith("script");
  });
});

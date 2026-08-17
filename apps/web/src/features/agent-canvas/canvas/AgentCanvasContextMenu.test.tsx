import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentCanvasContextMenu } from "./AgentCanvasContextMenu.tsx";

afterEach(() => cleanup());

describe("AgentCanvasContextMenu", () => {
  it("opens the shared node picker from Add node and creates at the context position", () => {
    const onCreateNode = vi.fn();

    render(
      <AgentCanvasContextMenu
        menuPosition={{ x: 240, y: 180 }}
        canvasPosition={{ x: 84, y: 132 }}
        onCreateNode={onCreateNode}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("menuitem", { name: "Add node" })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: "Add Image node" })).toBeNull();

    fireEvent.click(screen.getByRole("menuitem", { name: "Add node" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Add Script node" }));

    expect(onCreateNode).toHaveBeenCalledWith("script", { x: 84, y: 132 });
  });

  it("closes when Escape is pressed or the backdrop is clicked", () => {
    const onClose = vi.fn();

    render(
      <AgentCanvasContextMenu
        menuPosition={{ x: 240, y: 180 }}
        canvasPosition={{ x: 84, y: 132 }}
        onCreateNode={vi.fn()}
        onClose={onClose}
      />,
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Close canvas menu" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("moves the single menu to the latest right-click position and resets its picker", () => {
    const onRelocate = vi.fn();

    render(
      <AgentCanvasContextMenu
        menuPosition={{ x: 240, y: 180 }}
        canvasPosition={{ x: 84, y: 132 }}
        onCreateNode={vi.fn()}
        onClose={vi.fn()}
        onRelocate={onRelocate}
      />,
    );

    fireEvent.click(screen.getByRole("menuitem", { name: "Add node" }));
    expect(screen.getByRole("menuitem", { name: "Add Image node" })).toBeTruthy();

    fireEvent.contextMenu(screen.getByRole("button", { name: "Close canvas menu" }), {
      clientX: 520,
      clientY: 340,
    });

    expect(onRelocate).toHaveBeenCalledWith({ x: 520, y: 340 });
    expect(screen.getByRole("menuitem", { name: "Add node" })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: "Add Image node" })).toBeNull();
  });

  it("keeps the expanded node picker inside the viewport", () => {
    render(
      <AgentCanvasContextMenu
        menuPosition={{ x: 9999, y: 9999 }}
        canvasPosition={{ x: 84, y: 132 }}
        onCreateNode={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    const menu = screen.getByRole("menu", { name: "Canvas actions" });
    expect(menu.style.left).toBe("800px");
    expect(menu.style.top).toBe("698px");

    fireEvent.click(screen.getByRole("menuitem", { name: "Add node" }));
    expect(menu.style.top).toBe("504px");
  });
});

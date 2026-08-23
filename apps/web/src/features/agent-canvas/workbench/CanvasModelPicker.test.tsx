import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ProviderModelSummaryV1 } from "../../../api/providerRegistry.ts";
import { CanvasModelPicker } from "./CanvasModelPicker.tsx";

const model: ProviderModelSummaryV1 = {
  model_ref: "siliconflow/glm-image",
  provider_id: "siliconflow",
  provider_model_id: "glm-image",
  display_name: "GLM Image",
  capability: "image",
  capability_metadata: {},
  availability: "available",
  unavailable_reason: null,
  catalog_revision: 3,
};

function renderPicker(overrides: Partial<ComponentProps<typeof CanvasModelPicker>> = {}) {
  return render(
    <CanvasModelPicker
      models={[model]}
      loading={false}
      error={null}
      selectionMode="default"
      modelRef={null}
      modelSummary={null}
      modelResolution={null}
      disabled={false}
      onChange={vi.fn()}
      {...overrides}
    />,
  );
}

afterEach(() => {
  cleanup();
});

describe("CanvasModelPicker", () => {
  it("renders the menu in document.body and places it below the trigger", () => {
    renderPicker();
    const trigger = screen.getByRole("button", { name: "Choose model" });
    vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue({
      left: 100,
      right: 280,
      top: 200,
      bottom: 232,
      width: 180,
      height: 32,
      x: 100,
      y: 200,
      toJSON: () => ({}),
    });

    fireEvent.click(trigger);

    const menu = screen.getByRole("listbox");
    expect(menu.parentElement).toBe(document.body);
    expect(menu.style.position).toBe("fixed");
    expect(menu.style.left).toBe("100px");
    expect(menu.style.top).toBe("237px");
  });

  it("opens upward when the trigger is near the bottom of the viewport", () => {
    renderPicker();
    const trigger = screen.getByRole("button", { name: "Choose model" });
    vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue({
      left: 100,
      right: 280,
      top: 600,
      bottom: 632,
      width: 180,
      height: 32,
      x: 100,
      y: 600,
      toJSON: () => ({}),
    });

    fireEvent.click(trigger);

    const menu = screen.getByRole("listbox");
    expect(menu.style.position).toBe("fixed");
    expect(menu.style.left).toBe("100px");
    expect(menu.style.top).toBe("359px");
  });

  it("does not open while loading or disabled", () => {
    const { rerender } = renderPicker({ loading: true });
    const loadingTrigger = screen.getByRole("button", { name: "Choose model" });
    expect(loadingTrigger.hasAttribute("disabled")).toBe(true);
    fireEvent.click(loadingTrigger);
    expect(screen.queryByRole("listbox")).toBeNull();

    rerender(
      <CanvasModelPicker
        models={[model]}
        loading={false}
        error={null}
        selectionMode="default"
        modelRef={null}
        modelSummary={null}
        modelResolution={null}
        disabled
        onChange={vi.fn()}
      />,
    );
    const disabledTrigger = screen.getByRole("button", { name: "Choose model" });
    expect(disabledTrigger.hasAttribute("disabled")).toBe(true);
    fireEvent.click(disabledTrigger);
    expect(screen.queryByRole("listbox")).toBeNull();
  });
});

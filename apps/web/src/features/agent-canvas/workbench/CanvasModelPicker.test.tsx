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
  it("omits status details from compact image controls but keeps catalog errors in the menu", () => {
    renderPicker({
      showStatusDetails: false,
      selectionMode: "explicit",
      modelRef: model.model_ref,
      error: "Catalog could not be refreshed",
    });
    const trigger = screen.getByLabelText("Choose model");
    expect(trigger.textContent).toBe("GLM Image");
    expect(trigger.querySelector("small")).toBeNull();
    expect(screen.queryByText("Catalog could not be refreshed")).toBeNull();
    fireEvent.click(trigger);
    expect(screen.getByRole("listbox").textContent).toContain("Catalog could not be refreshed");
  });
  it("shows the current default name without using a previous node model or pinning the default", () => {
    const onChange = vi.fn();
    renderPicker({ defaultModelRef: model.model_ref, showOptionDetails: false, onChange });
    expect(screen.getByLabelText("Choose model").textContent).toBe("Default model · GLM Image");
    fireEvent.click(screen.getByLabelText("Choose model"));
    fireEvent.click(screen.getByRole("option", { name: "Default model · GLM Image" }));
    expect(onChange).toHaveBeenCalledExactlyOnceWith("default", null);
  });

  it.each([
    [null, null, "Not configured"],
    ["missing:model", null, "Name unavailable"],
    [null, "Catalog request failed", "Unavailable"],
  ])("does not guess the default name for %s / %s", (defaultModelRef, error, label) => {
    renderPicker({ defaultModelRef, error });
    expect(screen.getByLabelText("Choose model").textContent).toBe(`Default model · ${label}`);
  });

  it("renders name-only options while preserving disabled models and exact selection", () => {
    const onChange = vi.fn();
    renderPicker({
      showOptionDetails: false,
      onChange,
      models: [
        { ...model, conformance_status: "certified" },
        { ...model, model_ref: "mock:unverified", display_name: "Unverified image", adapter_id: "mock-image-v1", conformance_status: "unverified" },
      ],
    });
    fireEvent.click(screen.getByLabelText("Choose model"));
    const menu = screen.getByRole("listbox");
    expect(menu.querySelectorAll("small, em")).toHaveLength(0);
    expect(menu.textContent).toBe("Default modelGLM ImageUnverified image");
    const disabledOption = screen.getByRole("option", { name: "Unverified image" }) as HTMLButtonElement;
    expect(disabledOption.disabled).toBe(true);
    fireEvent.click(disabledOption);
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("option", { name: "GLM Image" }));
    expect(onChange).toHaveBeenCalledExactlyOnceWith("explicit", model.model_ref);
  });

  it("applies opt-in monochrome appearance to the trigger and portaled menu", () => {
    const onChange = vi.fn();
    renderPicker({ appearance: "monochrome", models: [{ ...model, conformance_status: "certified" }], onChange });
    const trigger = screen.getByLabelText("Choose model");
    expect(trigger.closest(".agent-node-workbench__model-picker--monochrome")).toBeTruthy();
    const chevrons = trigger.querySelector(".agent-node-workbench__model-chevron");
    expect(chevrons?.getAttribute("aria-hidden")).toBe("true");
    expect(chevrons?.querySelectorAll("svg")).toHaveLength(1);
    expect(chevrons?.querySelector("path")?.getAttribute("d")).toBe("m7 14.5 5-5 5 5");
    fireEvent.click(trigger);
    expect(chevrons?.querySelectorAll("svg")).toHaveLength(1);
    expect(chevrons?.querySelector("path")?.getAttribute("d")).toBe("m7 9.5 5 5 5-5");
    const menu = screen.getByRole("listbox", { name: "Compatible models" });
    expect(menu.classList.contains("agent-node-workbench__model-menu--monochrome")).toBe(true);
    expect(menu.parentElement).toBe(document.body);
    fireEvent.click(screen.getByRole("option", { name: /GLM Image/ }));
    expect(onChange).toHaveBeenCalledExactlyOnceWith("explicit", model.model_ref);
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(chevrons?.querySelector("path")?.getAttribute("d")).toBe("m7 14.5 5-5 5 5");
  });

  it("shows an unverified catalog model as disabled with its conformance reason", () => {
    const unverified: ProviderModelSummaryV1 = {
      ...model,
      model_ref: "openrouter:openai/gpt-image-2",
      provider_id: "openrouter",
      provider_model_id: "openai/gpt-image-2",
      display_name: "GPT Image 2",
      adapter_id: "openrouter-image-native-v1",
      transport_kind: "openrouter_images_native",
      release_tier: "optional",
      conformance_status: "unverified",
    };
    renderPicker({ models: [unverified] });

    fireEvent.click(screen.getByLabelText("Choose model"));

    const option = screen.getByText("GPT Image 2").closest("button");
    expect(option?.disabled).toBe(true);
    expect(screen.getByText("Model conformance has not been verified.")).toBeTruthy();
    expect(screen.getByText("openrouter-image-native-v1 · openrouter images native · optional")).toBeTruthy();
  });

  it("does not render fake, deprecated, or retired Ark Mini catalog rows", () => {
    renderPicker({
      models: [
        model,
        { ...model, model_ref: "fake:image", provider_id: "fake", display_name: "Fake image" },
        { ...model, model_ref: "vendor:old", availability: "deprecated", display_name: "Old image" },
        {
          ...model,
          model_ref: "volcengine_ark:doubao-seed-2-0-mini-260428",
          provider_id: "volcengine_ark",
          display_name: "Doubao Seed 2.0 Mini",
        },
        {
          ...model,
          model_ref: "openai:gpt-image-2",
          provider_id: "openai",
          provider_model_id: "gpt-image-2",
          display_name: "Retired OpenAI GPT Image 2",
          adapter_id: "openai-image-v1",
          transport_kind: "openai_images_native",
          conformance_status: "certified",
        },
      ],
    });

    fireEvent.click(screen.getByLabelText("Choose model"));

    expect(screen.getByText("GLM Image")).toBeTruthy();
    expect(screen.queryByText("Fake image")).toBeNull();
    expect(screen.queryByText("Old image")).toBeNull();
    expect(screen.queryByText("Doubao Seed 2.0 Mini")).toBeNull();
    expect(screen.queryByText("Retired OpenAI GPT Image 2")).toBeNull();
  });

  it("renders the menu in document.body and places it below the trigger", () => {
    renderPicker();
    const trigger = screen.getByLabelText("Choose model");
    expect(trigger.querySelector(".agent-node-workbench__model-chevron")).toBeNull();
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
    const trigger = screen.getByLabelText("Choose model");
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
    const loadingTrigger = screen.getByLabelText("Choose model");
    expect(loadingTrigger.getAttribute("aria-disabled")).toBe("true");
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
    const disabledTrigger = screen.getByLabelText("Choose model");
    expect(disabledTrigger.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(disabledTrigger);
    expect(screen.queryByRole("listbox")).toBeNull();
  });
});

import { ReactFlowProvider } from "@xyflow/react";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentCanvasPointerBackgrounds } from "./AgentCanvasPointerBackgrounds.tsx";

describe("AgentCanvasPointerBackgrounds", () => {
  it("keeps the base and illuminated dot patterns exactly aligned", () => {
    const { container } = render(
      <ReactFlowProvider>
        <AgentCanvasPointerBackgrounds />
      </ReactFlowProvider>,
    );

    const backgrounds = Array.from(container.querySelectorAll<SVGSVGElement>("svg.react-flow__background"));
    expect(backgrounds).toHaveLength(2);

    const [baseBackground, pointerBackground] = backgrounds;
    const basePattern = baseBackground.querySelector("pattern");
    const pointerPattern = pointerBackground.querySelector("pattern");
    const baseDot = basePattern?.querySelector("circle");
    const pointerDot = pointerPattern?.querySelector("circle");

    expect(pointerBackground.classList.contains("agent-canvas-pointer-background")).toBe(true);
    expect(baseBackground.style.getPropertyValue("--xy-background-pattern-color-props")).toBe(
      "var(--agent-canvas-base-dot-color)",
    );
    expect(pointerBackground.style.getPropertyValue("--xy-background-color-props")).toBe("transparent");
    expect(pointerPattern?.getAttribute("x")).toBe(basePattern?.getAttribute("x"));
    expect(pointerPattern?.getAttribute("y")).toBe(basePattern?.getAttribute("y"));
    expect(pointerPattern?.getAttribute("width")).toBe(basePattern?.getAttribute("width"));
    expect(pointerPattern?.getAttribute("height")).toBe(basePattern?.getAttribute("height"));
    expect(pointerPattern?.getAttribute("patternTransform")).toBe(basePattern?.getAttribute("patternTransform"));
    expect(pointerDot?.getAttribute("r")).toBe(baseDot?.getAttribute("r"));
  });
});

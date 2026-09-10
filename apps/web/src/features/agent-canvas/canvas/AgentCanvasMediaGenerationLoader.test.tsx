import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  AgentCanvasMediaGenerationLoader,
  mediaGenerationLoaderDelays,
} from "./AgentCanvasMediaGenerationLoader.tsx";

afterEach(cleanup);

describe("mediaGenerationLoaderDelays", () => {
  it("returns byte-for-byte stable delays for the same node ID", () => {
    expect(mediaGenerationLoaderDelays("image-node-1")).toEqual(
      mediaGenerationLoaderDelays("image-node-1"),
    );
  });

  it("normally assigns different phases to different node IDs", () => {
    expect(mediaGenerationLoaderDelays("image-node-1")).not.toEqual(
      mediaGenerationLoaderDelays("image-node-2"),
    );
  });

  it("returns negative delays bounded by the orbit and breathe durations", () => {
    const delays = mediaGenerationLoaderDelays("bounded-media-node");
    const orbitDelay = Number.parseFloat(delays["--agent-canvas-loader-orbit-delay"]);
    const breatheDelay = Number.parseFloat(delays["--agent-canvas-loader-breathe-delay"]);

    expect(delays["--agent-canvas-loader-orbit-delay"]).toMatch(/^-\d+\.\d{3}s$/);
    expect(delays["--agent-canvas-loader-breathe-delay"]).toMatch(/^-\d+\.\d{3}s$/);
    expect(orbitDelay).toBeGreaterThanOrEqual(-6.4);
    expect(orbitDelay).toBeLessThanOrEqual(0);
    expect(breatheDelay).toBeGreaterThanOrEqual(-2.4);
    expect(breatheDelay).toBeLessThanOrEqual(0);
  });
});

describe("AgentCanvasMediaGenerationLoader", () => {
  it("applies the stable node phase to the Loader root", () => {
    const nodeId = "video-node-7";
    const expected = mediaGenerationLoaderDelays(nodeId);

    render(<AgentCanvasMediaGenerationLoader mediaType="video" nodeId={nodeId} />);

    const loader = screen.getByRole("status", { name: "Generating video" });
    expect(loader.style.getPropertyValue("--agent-canvas-loader-orbit-delay")).toBe(
      expected["--agent-canvas-loader-orbit-delay"],
    );
    expect(loader.style.getPropertyValue("--agent-canvas-loader-breathe-delay")).toBe(
      expected["--agent-canvas-loader-breathe-delay"],
    );
  });
});

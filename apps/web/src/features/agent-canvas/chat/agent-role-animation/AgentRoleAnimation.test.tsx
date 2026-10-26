import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RoleVisualSnapshot } from "./agentRoleVisualResource.ts";
import type { AgentRoleMotionState } from "./types.ts";
import "../agent-canvas-chat.css";

const visual = vi.hoisted(() => ({ snapshot: vi.fn() }));
vi.mock("./useAgentRoleVisual.ts", () => ({ useAgentRoleVisual: visual.snapshot }));
import { AgentRoleAnimation } from "./AgentRoleAnimation.tsx";

function Artwork({ motionState }: { motionState: AgentRoleMotionState }) {
  return <svg data-motion-state={motionState}><circle r="8" /></svg>;
}
const ready: RoleVisualSnapshot = { status: "ready", source: "/role.png", Artwork, error: null, generation: 1, fallbackKind: "none" };
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("AgentRoleAnimation visual lifecycle", () => {
  it("does not expose a generic error marker during ordinary pending loading", () => {
    visual.snapshot.mockReturnValue({ ...ready, status: "pending", source: null, Artwork: null });
    const { container } = render(<AgentRoleAnimation capabilityId="scene_design" motionState="working" />);
    expect(container.querySelector('[data-role-generic-fallback="true"]')).toBeNull();
  });
  it("uses bitmap only for terminal state even when artwork was previously cached", () => {
    visual.snapshot.mockReturnValue(ready);
    const { container, rerender } = render(<AgentRoleAnimation capabilityId="scene_design" motionState="working" />);
    expect(container.querySelector("svg")).not.toBeNull();
    rerender(<AgentRoleAnimation capabilityId="scene_design" motionState="idle" />);
    expect(container.querySelector("svg")).toBeNull();
    expect(screen.getByTestId("agent-role-static-icon").getAttribute("src")).toBe("/role.png");
  });
  it("shows ready artwork without an initial invisible crossfade frame", () => {
    visual.snapshot.mockReturnValue(ready);
    const { container } = render(<AgentRoleAnimation capabilityId="scene_design" motionState="working" />);
    const artwork = container.querySelector<HTMLElement>(".agent-chat__role-animation-artwork")!;
    expect(getComputedStyle(artwork).opacity).not.toBe("0");
    expect(container.querySelector("svg")?.getAttribute("data-motion-state")).toBe("working");
  });
  it("leaves the working visual empty during resource failure", () => {
    visual.snapshot.mockReturnValue({ ...ready, status: "fallback", Artwork: null, error: "offline" });
    render(<AgentRoleAnimation capabilityId="scene_design" motionState="working" />);
    const frame = screen.getByTestId("agent-role-animation-frame");
    expect(getComputedStyle(frame).width).toBe("32px");
    expect(getComputedStyle(frame).height).toBe("32px");
    expect(frame.dataset.roleWaitingMotion).toBeUndefined();
    expect(screen.queryByTestId("agent-role-static-icon")).toBeNull();
  });
  it("provides visible generic fallback when even bundled bitmap fails", () => {
    visual.snapshot.mockReturnValue({ ...ready, status: "fallback", Artwork: null, source: null, fallbackKind: "generic" });
    const { container } = render(<AgentRoleAnimation capabilityId="scene_design" motionState="idle" />);
    expect(container.querySelector('[data-role-generic-fallback="true"]')).not.toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });
  it("contains artwork render failure without hiding the surrounding identity", () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const BrokenArtwork = () => { throw new Error("broken artwork"); };
    visual.snapshot.mockReturnValue({ ...ready, Artwork: BrokenArtwork });
    render(<AgentRoleAnimation capabilityId="scene_design" motionState="working" />);
    expect(screen.queryByTestId("agent-role-static-icon")).toBeNull();
    expect(log).toHaveBeenCalled();
    expect(screen.getByTestId("agent-role-animation-frame").dataset.roleWaitingMotion).toBeUndefined();
  });
  it("keeps the animated artwork mounted across the whole working stretch", () => {
    visual.snapshot.mockReturnValue(ready);
    const { rerender } = render(<AgentRoleAnimation capabilityId="world_setting" motionState="working" />);
    expect(screen.getByTestId("agent-role-animation-frame").dataset.motionState).toBe("working");
    rerender(<AgentRoleAnimation capabilityId="world_setting" motionState="working" />);
    expect(screen.getByTestId("agent-role-animation-frame").dataset.motionState).toBe("working");
  });
});

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AudioTrackControls } from "./AudioTrackControls.tsx";

afterEach(cleanup);

describe("AudioTrackControls", () => {
  it("keeps enable and volume controls below the Audio Track label without fade controls", () => {
    render(
      <AudioTrackControls
        disabled={false}
        enabled
        onSetBgm={vi.fn()}
        onSetBgmVolume={vi.fn()}
        volume={0.4}
      />,
    );

    const controls = screen.getByRole("region", { name: "Audio track controls" });
    expect(controls.classList.contains("agent-editing-timeline__audio-controls--under-label")).toBe(true);
    expect(within(controls).getByRole("checkbox", { name: "Enabled" })).toBeTruthy();
    const volume = within(controls).getByRole("slider", { name: "BGM volume" });
    expect(volume.getAttribute("style")).toContain("--audio-volume: 40%");
    expect(controls.querySelector('img[src="/icon/ant-design--audio-filled.svg"]')).toBeTruthy();
    expect(within(controls).queryByText("Volume")).toBeNull();
    expect(within(controls).queryByText("Fade in")).toBeNull();
    expect(within(controls).queryByText("Fade out")).toBeNull();
  });

  it("forwards enable and volume changes without exposing fade behavior", () => {
    const onSetBgm = vi.fn();
    const onSetBgmVolume = vi.fn();
    render(
      <AudioTrackControls
        disabled={false}
        enabled
        onSetBgm={onSetBgm}
        onSetBgmVolume={onSetBgmVolume}
        volume={0.4}
      />,
    );

    const controls = screen.getByRole("region", { name: "Audio track controls" });
    fireEvent.click(within(controls).getByRole("checkbox", { name: "Enabled" }));
    fireEvent.change(within(controls).getByRole("slider", { name: "BGM volume" }), { target: { value: "0.7" } });

    expect(onSetBgm).toHaveBeenCalledWith({ enabled: false });
    expect(onSetBgmVolume).toHaveBeenCalledWith(0.7);
  });
});

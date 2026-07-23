import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { V2AudioPlayer } from "./V2AudioPlayer.tsx";

function CanvasCard({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events -- Test-only canvas card wrapper verifies that nested player controls do not bubble clicks.
    <div onClick={onClick}>{children}</div>
  );
}

describe("V2AudioPlayer", () => {
  let playMock: ReturnType<typeof vi.fn>;
  let pauseMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    playMock = vi.fn(function play(this: HTMLMediaElement) {
      this.dispatchEvent(new Event("play"));
      return Promise.resolve();
    });
    pauseMock = vi.fn(function pause(this: HTMLMediaElement) {
      this.dispatchEvent(new Event("pause"));
    });
    vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(playMock);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(pauseMock);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("plays, pauses, seeks, and mutes without propagating card clicks", () => {
    const onCardClick = vi.fn();
    const { container } = render(
      <CanvasCard onClick={onCardClick}>
        <V2AudioPlayer
          src="/media/bgm.mp3"
          label="Selected soundtrack"
          durationSeconds={12}
          playbackGroup="bgm-slot"
        />
      </CanvasCard>,
    );

    const audio = container.querySelector("audio") as HTMLAudioElement;
    fireEvent.click(screen.getByRole("button", { name: "Play Selected soundtrack" }));
    fireEvent.change(screen.getByRole("slider", { name: "Seek Selected soundtrack" }), { target: { value: "6" } });
    fireEvent.click(screen.getByRole("button", { name: "Mute Selected soundtrack" }));
    fireEvent.click(screen.getByRole("button", { name: "Pause Selected soundtrack" }));

    expect(playMock).toHaveBeenCalledTimes(1);
    expect(pauseMock).toHaveBeenCalledTimes(1);
    expect(audio.currentTime).toBe(6);
    expect(audio.muted).toBe(true);
    expect(screen.getByText("0:06 / 0:12")).toBeTruthy();
    expect(onCardClick).not.toHaveBeenCalled();
  });

  it("pauses the active player when another player in its playback group starts", () => {
    const { container } = render(
      <>
        <V2AudioPlayer src="/media/first.mp3" label="First soundtrack" playbackGroup="bgm-slot" />
        <V2AudioPlayer src="/media/second.mp3" label="Second soundtrack" playbackGroup="bgm-slot" />
      </>,
    );

    const [firstAudio] = Array.from(container.querySelectorAll("audio"));
    fireEvent.click(screen.getByRole("button", { name: "Play First soundtrack" }));
    fireEvent.click(screen.getByRole("button", { name: "Play Second soundtrack" }));

    expect(pauseMock).toHaveBeenCalledWith();
    expect(pauseMock.mock.instances).toContain(firstAudio);
  });

  it("shows a bounded playback error when play is rejected", async () => {
    playMock.mockImplementationOnce(() => Promise.reject(new Error("Autoplay denied")));
    render(<V2AudioPlayer src="/media/bgm.mp3" label="Selected soundtrack" playbackGroup="bgm-slot" />);

    fireEvent.click(screen.getByRole("button", { name: "Play Selected soundtrack" }));

    expect((await screen.findByRole("alert")).textContent).toBe("Playback unavailable.");
    expect(screen.getByRole("button", { name: "Play Selected soundtrack" })).toBeTruthy();
  });

  it("shows an unavailable state and disables controls without a source", () => {
    render(<V2AudioPlayer src={null} label="Selected soundtrack" playbackGroup="bgm-slot" />);

    expect(screen.getByText("Audio unavailable.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Play Selected soundtrack" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("slider", { name: "Seek Selected soundtrack" }) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Mute Selected soundtrack" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows an unavailable state when the audio element reports an error", () => {
    const { container } = render(<V2AudioPlayer src="/media/bgm.mp3" label="Selected soundtrack" playbackGroup="bgm-slot" />);

    fireEvent.error(container.querySelector("audio") as HTMLAudioElement);

    expect(screen.getByRole("alert").textContent).toBe("Audio unavailable.");
    expect((screen.getByRole("button", { name: "Play Selected soundtrack" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("removes an unmounted player from its playback group", () => {
    const first = render(<V2AudioPlayer src="/media/first.mp3" label="First soundtrack" playbackGroup="bgm-slot" />);

    fireEvent.click(screen.getByRole("button", { name: "Play First soundtrack" }));
    first.unmount();
    pauseMock.mockClear();

    render(<V2AudioPlayer src="/media/second.mp3" label="Second soundtrack" playbackGroup="bgm-slot" />);
    fireEvent.click(screen.getByRole("button", { name: "Play Second soundtrack" }));

    expect(pauseMock).not.toHaveBeenCalled();
  });

  it("removes media listeners when unmounted", () => {
    const removeEventListener = vi.spyOn(HTMLMediaElement.prototype, "removeEventListener");
    const player = render(<V2AudioPlayer src="/media/bgm.mp3" label="Selected soundtrack" playbackGroup="bgm-slot" />);

    player.unmount();

    for (const eventName of ["loadedmetadata", "durationchange", "timeupdate", "play", "pause", "ended", "error"]) {
      expect(removeEventListener).toHaveBeenCalledWith(eventName, expect.any(Function));
    }
  });

  it("synchronizes elapsed time and metadata duration from the audio element", () => {
    const { container } = render(<V2AudioPlayer src="/media/bgm.mp3" label="Selected soundtrack" playbackGroup="bgm-slot" />);
    const audio = container.querySelector("audio") as HTMLAudioElement;
    Object.defineProperty(audio, "duration", { configurable: true, value: 19 });
    Object.defineProperty(audio, "currentTime", { configurable: true, value: 7, writable: true });

    fireEvent.loadedMetadata(audio);
    fireEvent.timeUpdate(audio);

    expect(screen.getByText("0:07 / 0:19")).toBeTruthy();
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { api } from "../api/client.ts";
import { LocalPromptComposer } from "./PromptComposer.tsx";

const uploadAsset = vi.fn();

vi.mock("../AppContextValue", () => ({
  useApp: () => ({
    busy: false,
    uploadAsset,
  }),
}));

afterEach(() => {
  cleanup();
  uploadAsset.mockReset();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("LocalPromptComposer", () => {
  it("routes an accepted file to the supplied upload handler and can hide the asset picker", async () => {
    const onUploadFile = vi.fn().mockResolvedValue(undefined);
    const { container } = render(
      <LocalPromptComposer
        placeholder="BGM"
        onGenerate={vi.fn()}
        acceptedFileTypes="audio/*"
        assetPickerEnabled={false}
        onUploadFile={onUploadFile}
      />,
    );
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    const file = new File(["audio"], "score.mp3", { type: "audio/mpeg" });

    expect(input?.accept).toBe("audio/*");
    fireEvent.change(input as HTMLInputElement, { target: { files: [file] } });

    await waitFor(() => expect(onUploadFile).toHaveBeenCalledWith(file));
    expect(uploadAsset).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Choose asset" })).toBeNull();
  });

  it("preserves the generic upload and asset picker defaults", () => {
    const { container } = render(
      <LocalPromptComposer
        placeholder="Generic prompt"
        onGenerate={vi.fn()}
      />,
    );

    expect(container.querySelector<HTMLInputElement>('input[type="file"]')?.accept).toContain("image/*");
    expect(screen.getByRole("button", { name: "Choose asset" })).toBeTruthy();
  });

  it("treats @ as plain prompt text when asset mentions are disabled", async () => {
    vi.useFakeTimers();
    const suggestAssetReferences = vi.spyOn(api, "suggestAssetReferences").mockResolvedValue({ suggestions: [] });
    render(
      <LocalPromptComposer
        placeholder="BGM"
        onGenerate={vi.fn()}
        assetPickerEnabled={false}
        assetMentionsEnabled={false}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText("BGM"), { target: { value: "music @", selectionStart: 7 } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });

    expect(suggestAssetReferences).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox", { name: "@asset suggestions" })).toBeNull();
  });

  it("does not carry attachments into a different draft identity", async () => {
    uploadAsset.mockResolvedValue({
      asset_id: "image-reference",
      asset_type: "image",
      filename: "reference.png",
      local_path: "/media/reference.png",
    });
    const onGenerate = vi.fn();
    const view = render(
      <LocalPromptComposer
        draftIdentity="image-slot"
        placeholder="Image"
        initialValue="Image prompt"
        onGenerate={onGenerate}
      />,
    );
    const file = new File(["image"], "reference.png", { type: "image/png" });
    fireEvent.change(view.container.querySelector<HTMLInputElement>('input[type="file"]') as HTMLInputElement, {
      target: { files: [file] },
    });
    await waitFor(() => expect(screen.getByLabelText("Current message attachments")).toBeTruthy());

    view.rerender(
      <LocalPromptComposer
        draftIdentity="bgm-slot"
        placeholder="BGM"
        initialValue="Music prompt"
        assetPickerEnabled={false}
        assetMentionsEnabled={false}
        onGenerate={onGenerate}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Generate" }));

    await waitFor(() => expect(onGenerate).toHaveBeenCalledTimes(1));
    expect(onGenerate.mock.calls[0][1]?.asset_references).toEqual([]);
    expect(screen.queryByLabelText("Current message attachments")).toBeNull();
  });

  it("closes stale asset suggestions when the next draft disables mentions", async () => {
    vi.useFakeTimers();
    vi.spyOn(api, "suggestAssetReferences").mockResolvedValue({
      suggestions: [{
        reference_source: "asset_library",
        entity_id: "entity-1",
        asset_id: "asset-1",
        display_name: "Visual reference",
        asset_type: "image",
      }],
    });
    const view = render(
      <LocalPromptComposer
        draftIdentity="image-slot"
        placeholder="Image"
        onGenerate={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByPlaceholderText("Image"), { target: { value: "@", selectionStart: 1 } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(screen.getByRole("listbox", { name: "@asset suggestions" })).toBeTruthy();

    view.rerender(
      <LocalPromptComposer
        draftIdentity="bgm-slot"
        placeholder="BGM"
        assetPickerEnabled={false}
        assetMentionsEnabled={false}
        onGenerate={vi.fn()}
      />,
    );

    expect(screen.queryByRole("listbox", { name: "@asset suggestions" })).toBeNull();
  });

  it("ignores an upload that resolves after the draft identity changes", async () => {
    let resolveUpload: ((asset: unknown) => void) | undefined;
    uploadAsset.mockReturnValue(new Promise((resolve) => {
      resolveUpload = resolve;
    }));
    const view = render(
      <LocalPromptComposer
        draftIdentity="image-slot"
        placeholder="Image"
        onGenerate={vi.fn()}
      />,
    );
    fireEvent.change(view.container.querySelector<HTMLInputElement>('input[type="file"]') as HTMLInputElement, {
      target: { files: [new File(["image"], "reference.png", { type: "image/png" })] },
    });

    view.rerender(
      <LocalPromptComposer
        draftIdentity="bgm-slot"
        placeholder="BGM"
        assetPickerEnabled={false}
        assetMentionsEnabled={false}
        onGenerate={vi.fn()}
      />,
    );
    await act(async () => {
      resolveUpload?.({
        asset_id: "late-image",
        asset_type: "image",
        filename: "reference.png",
        local_path: "/media/reference.png",
      });
      await Promise.resolve();
    });

    expect(screen.queryByLabelText("Current message attachments")).toBeNull();
  });
});

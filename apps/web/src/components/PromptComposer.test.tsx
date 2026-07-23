import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

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
});

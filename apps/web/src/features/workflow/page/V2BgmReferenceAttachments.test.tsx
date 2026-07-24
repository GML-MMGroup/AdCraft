import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import type { SlotMicroEditAttachment } from "../v2/slots/useSlotMicroEdit.ts";
import { V2BgmReferenceAttachments } from "./V2BgmReferenceAttachments.tsx";

afterEach(cleanup);

describe("V2BgmReferenceAttachments", () => {
  it("shows bounded filenames and statuses without paths or raw errors", () => {
    const attachments: SlotMicroEditAttachment[] = [
      attachment({
        id: "upload:registering",
        filename: "/private/uploads/score.mp3",
        preview_url: "blob:http://localhost/private-audio",
        status: "registering",
      }),
      attachment({
        id: "upload:registered",
        filename: "registered.wav",
        status: "registered",
      }),
      attachment({
        id: "upload:attached",
        filename: `${"long-soundtrack-name-".repeat(5)}final.mp3`,
        source_asset_id: "asset-1",
        relation_id: "relation-1",
        status: "attached",
      }),
      attachment({
        id: "upload:failed",
        filename: "failed.mp3",
        status: "failed",
        error: '{"path":"/srv/private/audio.mp3","stack":"provider internals"}',
      }),
    ];

    const { container } = render(
      <V2BgmReferenceAttachments attachments={attachments} onRemove={vi.fn()} />,
    );

    expect(screen.getByText("score.mp3")).toBeTruthy();
    expect(screen.getByText("Uploading")).toBeTruthy();
    expect(screen.getByText("Registered")).toBeTruthy();
    expect(screen.getByText("Attached")).toBeTruthy();
    expect(screen.getByText("Upload failed")).toBeTruthy();
    const filenames = [...container.querySelectorAll<HTMLElement>(".v2-bgm-reference-filename")];
    expect(filenames.every((element) => element.textContent!.length <= 64)).toBe(true);
    expect(container.textContent).not.toContain("/private/");
    expect(container.textContent).not.toContain("blob:");
    expect(container.textContent).not.toContain("/srv/private");
    expect(container.textContent).not.toContain("provider internals");
  });

  it("returns the selected attachment for removal", () => {
    const onRemove = vi.fn();
    const attached = attachment({
      id: "upload:attached",
      filename: "score.mp3",
      source_asset_id: "asset-1",
      relation_id: "relation-1",
      status: "attached",
    });
    render(<V2BgmReferenceAttachments attachments={[attached]} onRemove={onRemove} />);

    fireEvent.click(screen.getByRole("button", { name: "Remove score.mp3" }));

    expect(onRemove).toHaveBeenCalledWith(attached);
  });

  it("blocks repeated removal while the Slot request is in flight", () => {
    const onRemove = vi.fn();
    const attached = attachment({
      id: "upload:attached",
      filename: "score.mp3",
      source_asset_id: "asset-1",
      relation_id: "relation-1",
      status: "attached",
    });
    render(
      <V2BgmReferenceAttachments
        attachments={[attached]}
        disabled
        onRemove={onRemove}
      />,
    );

    const removeButton = screen.getByRole("button", { name: "Remove score.mp3" }) as HTMLButtonElement;
    expect(removeButton.disabled).toBe(true);
    fireEvent.click(removeButton);
    expect(onRemove).not.toHaveBeenCalled();
  });
});

function attachment(patch: Partial<SlotMicroEditAttachment>): SlotMicroEditAttachment {
  return {
    id: "upload:test",
    source: "upload",
    filename: "score.mp3",
    semantic_type: "bgm_audio",
    status: "registering",
    ...patch,
  };
}

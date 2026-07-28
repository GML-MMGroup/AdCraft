import { describe, expect, it, vi } from "vitest";

import { deleteCanvasEntities } from "./deleteCanvasEntities.ts";

describe("deleteCanvasEntities", () => {
  it("recovers canonical state and rethrows when a backend deletion fails", async () => {
    const remove = vi.fn()
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error("delete failed"));
    const recover = vi.fn().mockResolvedValue(undefined);

    await expect(deleteCanvasEntities(["one", "two"], remove, recover))
      .rejects.toThrow("delete failed");

    expect(recover).toHaveBeenCalledOnce();
  });

  it("does not refresh canonical state after successful deletions", async () => {
    const remove = vi.fn().mockResolvedValue(undefined);
    const recover = vi.fn().mockResolvedValue(undefined);

    await deleteCanvasEntities(["one", "two"], remove, recover);

    expect(remove).toHaveBeenCalledTimes(2);
    expect(recover).not.toHaveBeenCalled();
  });
});

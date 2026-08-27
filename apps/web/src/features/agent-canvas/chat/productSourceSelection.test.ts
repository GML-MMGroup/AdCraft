import { describe, expect, it } from "vitest";

import {
  ProductSourceSelectionError,
  addProductSourceItem,
  createAssetVersionDraftItem,
  createLocalFileDraftItem,
  moveProductSourceItem,
  removeProductSourceItem,
  resolveProductSourceAssetVersions,
  validateProductSourceDraft,
} from "./productSourceSelection.ts";

function localFile(name: string) {
  return new File([name], name, { type: "image/png", lastModified: 100 });
}

describe("productSourceSelection", () => {
  it("replaces the current Main source when a new source is selected", () => {
    const first = createAssetVersionDraftItem({
      assetId: "asset-1",
      versionId: "version-1",
      displayName: "First",
      previewUrl: "/first.png",
    });
    const second = createAssetVersionDraftItem({
      assetId: "asset-2",
      versionId: "version-2",
      displayName: "Second",
      previewUrl: "/second.png",
    });

    expect(addProductSourceItem([first], second, "main", 1)).toEqual([second]);
  });

  it("appends unique Multiview sources and rejects duplicate immutable identities", () => {
    const first = createAssetVersionDraftItem({
      assetId: "asset-1",
      versionId: "version-1",
      displayName: "Front",
      previewUrl: null,
    });
    const second = createAssetVersionDraftItem({
      assetId: "asset-2",
      versionId: "version-2",
      displayName: "Side",
      previewUrl: null,
    });
    expect(addProductSourceItem([first], second, "multiview", 8)).toEqual([first, second]);
    expect(() => addProductSourceItem([first], first, "multiview", 8)).toThrowError(
      new ProductSourceSelectionError("duplicate", "This Product source is already selected."),
    );
  });

  it("rejects duplicate local files and sources above the backend maximum", () => {
    const first = createLocalFileDraftItem(localFile("front.png"), "upload-key-1", "blob:front");
    const duplicate = createLocalFileDraftItem(localFile("front.png"), "upload-key-2", "blob:front-2");
    const side = createLocalFileDraftItem(localFile("side.png"), "upload-key-3", "blob:side");

    expect(() => addProductSourceItem([first], duplicate, "multiview", 8)).toThrowError(
      ProductSourceSelectionError,
    );
    expect(() => addProductSourceItem([first], side, "multiview", 1)).toThrowError(
      new ProductSourceSelectionError("max_count", "You can select at most 1 Product source."),
    );
  });

  it("moves ordered Multiview sources without crossing list bounds", () => {
    const first = createLocalFileDraftItem(localFile("front.png"), "upload-key-1", "blob:front");
    const second = createLocalFileDraftItem(localFile("side.png"), "upload-key-2", "blob:side");
    const third = createLocalFileDraftItem(localFile("back.png"), "upload-key-3", "blob:back");

    expect(moveProductSourceItem([first, second, third], second.key, -1)).toEqual([second, first, third]);
    expect(moveProductSourceItem([first, second, third], first.key, -1)).toEqual([first, second, third]);
    expect(moveProductSourceItem([first, second, third], third.key, 1)).toEqual([first, second, third]);
    expect(removeProductSourceItem([first, second, third], second.key)).toEqual([first, third]);
  });

  it("validates backend Main and Multiview cardinality", () => {
    const first = createLocalFileDraftItem(localFile("front.png"), "upload-key-1", "blob:front");
    const second = createLocalFileDraftItem(localFile("side.png"), "upload-key-2", "blob:side");

    expect(validateProductSourceDraft([], "main", 1, 1)).toBe("Select exactly 1 Product source.");
    expect(validateProductSourceDraft([first], "main", 1, 1)).toBeNull();
    expect(validateProductSourceDraft([first], "multiview", 2, 8)).toBe("Select 2-8 Product sources.");
    expect(validateProductSourceDraft([first, second], "multiview", 2, 8)).toBeNull();
  });

  it("resolves mixed existing and uploaded sources in visible order", () => {
    const existing = createAssetVersionDraftItem({
      assetId: "asset-existing",
      versionId: "version-existing",
      displayName: "Existing",
      previewUrl: null,
    });
    const uploaded = createLocalFileDraftItem(localFile("side.png"), "upload-key-side", "blob:side");
    const resolved = resolveProductSourceAssetVersions(
      [uploaded, existing],
      new Map([[uploaded.key, {
        assetId: "asset-uploaded",
        versionId: "version-uploaded",
        pendingHandoffId: "handoff-1",
      }]]),
    );

    expect(resolved).toEqual({
      assetVersions: [
        { asset_id: "asset-uploaded", version_id: "version-uploaded" },
        { asset_id: "asset-existing", version_id: "version-existing" },
      ],
      pendingHandoffId: "handoff-1",
    });
  });

  it("rejects unresolved uploads and conflicting pending handoffs", () => {
    const first = createLocalFileDraftItem(localFile("front.png"), "upload-key-1", "blob:front");
    const second = createLocalFileDraftItem(localFile("side.png"), "upload-key-2", "blob:side");

    expect(() => resolveProductSourceAssetVersions([first], new Map())).toThrowError(
      new ProductSourceSelectionError("unresolved_upload", "A Product upload did not return an immutable AssetVersion."),
    );
    expect(() => resolveProductSourceAssetVersions(
      [first, second],
      new Map([
        [first.key, { assetId: "asset-1", versionId: "version-1", pendingHandoffId: "handoff-1" }],
        [second.key, { assetId: "asset-2", versionId: "version-2", pendingHandoffId: "handoff-2" }],
      ]),
    )).toThrowError(
      new ProductSourceSelectionError("conflicting_handoff", "The Product uploads returned conflicting pending handoffs."),
    );
  });
});

import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  HOLOGRAM_SCENE_FILENAMES,
  hologramSceneUrlForAsset,
} from "./recommendedSceneHologramCatalog.ts";

function pngColorType(path: string) {
  const bytes = readFileSync(path);
  expect(bytes.subarray(1, 4).toString("ascii")).toBe("PNG");
  return bytes[25];
}

describe("recommended scene hologram catalog", () => {
  it("maps canonical recommended scene entity IDs to matching frontend assets", () => {
    expect(hologramSceneUrlForAsset("recommended:recommended-v1-scene-001")).toBe(
      "/assets/hologram/scene-001-multi-view.png",
    );
    expect(hologramSceneUrlForAsset("recommended:recommended-v1-scene-020")).toBe(
      "/assets/hologram/scene-020-multi-view.png",
    );
  });

  it("does not guess a hologram for an unknown backend identity", () => {
    expect(hologramSceneUrlForAsset("recommended:scene-without-catalog-id")).toBeNull();
  });

  it("ships all twenty holograms as RGBA PNGs", () => {
    const directory = resolve(process.cwd(), "public/assets/hologram");
    const actual = readdirSync(directory).filter((name) => name.endsWith(".png")).sort();

    expect(actual).toEqual([...HOLOGRAM_SCENE_FILENAMES]);
    for (const filename of actual) {
      expect(pngColorType(resolve(directory, filename)), filename).toBe(6);
    }
  });
});

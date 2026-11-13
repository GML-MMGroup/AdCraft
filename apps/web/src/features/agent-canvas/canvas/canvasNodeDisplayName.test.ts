import { describe, expect, it } from "vitest";
import { translateUi } from "../../../i18n/uiMessages.ts";
import type { CanvasNodeV2 } from "../../../types-v2.ts";
import { canvasNodeDisplayName } from "./canvasNodeDisplayName.ts";

function node(
  creative_role: CanvasNodeV2["creative_role"],
  metadata: Record<string, unknown> = {},
): CanvasNodeV2 {
  return { creative_role, metadata, structured_content: {}, prompt_preparation: null } as CanvasNodeV2;
}

const zh = (key: Parameters<typeof translateUi>[1], values?: Parameters<typeof translateUi>[2]) =>
  translateUi("zh-CN", key, values);

describe("canvasNodeDisplayName", () => {
  it("pairs each character's Main and Turnaround using its persisted identity even before prompt preparation", () => {
    for (const number of [1, 2, 3]) {
      const metadata = { occurrence_id: `character-${number}` };
      expect(canvasNodeDisplayName(node("character", { ...metadata, character_phase: "main" }), zh))
        .toBe(`角色 ${number} · 主图`);
      expect(canvasNodeDisplayName(node("character", { ...metadata, character_phase: "turnaround" }), zh))
        .toBe(`角色 ${number} · 三视图`);
    }
  });

  it("preserves character numbers when a sibling is deleted, nodes move, or generation is retried", () => {
    const third = node("character", { occurrence_id: "character-3", character_phase: "main" });
    const first = node("character", { occurrence_id: "character-1", character_phase: "main" });
    const refreshed = JSON.parse(JSON.stringify([third, first])) as CanvasNodeV2[];
    expect(refreshed.map(value => canvasNodeDisplayName({
      ...value, position: { x: 1000, y: -200 }, status: "working", revision: 10,
    }, zh))).toEqual(["角色 3 · 主图", "角色 1 · 主图"]);
  });

  it("pairs five storyboard grids and videos by sequence_index, regardless of titles or execution order", () => {
    for (const number of [5, 1, 3, 2, 4]) {
      const metadata = { source_sequence_id: `sequence-${number}`, sequence_index: number };
      expect(canvasNodeDisplayName({ ...node("storyboard_sequence", metadata), title: "Renamed grid 99" }, zh))
        .toBe(`分镜 ${number}`);
      expect(canvasNodeDisplayName(node("storyboard_video", metadata), zh)).toBe(`分镜视频 ${number}`);
    }
  });

  it("uses durable character metadata over a stale prompt-preparation projection", () => {
    const character = node("character", { occurrence_id: "character-2", character_phase: "turnaround" });
    character.prompt_preparation = {
      occurrence_id: "character-1", character_phase: "main",
    } as CanvasNodeV2["prompt_preparation"];
    expect(canvasNodeDisplayName(character)).toBe("Character 2 · Turnaround");
  });

  it("can display the persisted identity from structured content or prompt preparation", () => {
    const character = node("character");
    character.structured_content = { occurrence_id: "character-2", character_asset_kind: "turnaround" };
    expect(canvasNodeDisplayName(character, zh)).toBe("角色 2 · 三视图");
    character.structured_content = {};
    character.prompt_preparation = {
      occurrence_id: "character-2", role_variant: "character_main",
    } as CanvasNodeV2["prompt_preparation"];
    expect(canvasNodeDisplayName(character)).toBe("Character 2 · Main");
  });

  it.each([undefined, null, 0, -1, 1.5, "2", NaN, Infinity, Number.MAX_SAFE_INTEGER + 1])(
    "does not invent a sequence number from invalid metadata: %s",
    sequence_index => {
      const storyboard = node("storyboard_sequence", { sequence_index });
      storyboard.title = "Storyboard 99";
      expect(canvasNodeDisplayName(storyboard)).toBe("Storyboard Sequence");
    },
  );

  it.each(["custom-character-2", "character-0", "character-2-copy", "character-9007199254740992"])(
    "does not interpret arbitrary occurrence IDs as ordinal numbers: %s",
    occurrence_id => {
      expect(canvasNodeDisplayName(node("character", { occurrence_id, character_phase: "main" })))
        .toBe("Character Main");
    },
  );

  it("keeps exported videos and other node types out of storyboard and character numbering", () => {
    expect(canvasNodeDisplayName(node("general_video", { sequence_index: 2 }))).toBe("General Video");
    expect(canvasNodeDisplayName(node("product", { occurrence_id: "character-2", character_phase: "main" })))
      .toBe("Product");
  });
});

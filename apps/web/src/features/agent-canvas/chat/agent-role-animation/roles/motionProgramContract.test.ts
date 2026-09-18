import { describe, expect, it } from "vitest";
import { BGM_DIRECTOR_MOTION_PROGRAM } from "./BgmDirectorAnimation.tsx";
import { CHARACTER_DESIGNER_MOTION_PROGRAM } from "./characterDesignerMotion.ts";
import { PRODUCT_DESIGNER_MOTION_PROGRAM } from "./ProductDesignerAnimation.tsx";
import { PROP_DESIGNER_MOTION_PROGRAM } from "./PropDesignerAnimation.tsx";
import { QUICK_MEDIA_MOTION_PROGRAM } from "./QuickMediaAnimation.tsx";
import { SCENE_DESIGNER_MOTION_PROGRAM } from "./SceneDesignerAnimation.tsx";
import { SCRIPT_WRITER_MOTION_PROGRAM } from "./scriptWriterMotion.ts";
import { STORYBOARD_ARTIST_MOTION_PROGRAM } from "./StoryboardArtistAnimation.tsx";
import { VIDEO_DIRECTOR_MOTION_PROGRAM } from "./VideoDirectorAnimation.tsx";
import { WORLD_SETTING_MOTION_PROGRAM } from "./WorldSettingAnimation.tsx";

const programs = [
  ["World Setting", WORLD_SETTING_MOTION_PROGRAM],
  ["Product Designer", PRODUCT_DESIGNER_MOTION_PROGRAM],
  ["Prop Designer", PROP_DESIGNER_MOTION_PROGRAM],
  ["Character Designer", CHARACTER_DESIGNER_MOTION_PROGRAM],
  ["Scene Designer", SCENE_DESIGNER_MOTION_PROGRAM],
  ["Script Writer", SCRIPT_WRITER_MOTION_PROGRAM],
  ["Storyboard Artist", STORYBOARD_ARTIST_MOTION_PROGRAM],
  ["BGM Director", BGM_DIRECTOR_MOTION_PROGRAM],
  ["Video Director", VIDEO_DIRECTOR_MOTION_PROGRAM],
  ["Quick Media", QUICK_MEDIA_MOTION_PROGRAM],
] as const;

describe("agent role motion program contract", () => {
  it.each(programs)("%s keeps its working tracks continuously playable", (_name, program) => {
    expect(program.working.length).toBeGreaterThan(0);
    expect(program.working.every(({ options }) => options.iterations === Infinity)).toBe(true);
  });

  it("allows only an explicit finite intro before the continuous working phase", () => {
    for (const [, program] of programs) {
      for (const track of program.workingIntro ?? []) {
        expect(track.options.iterations).toBe(1);
      }
    }
  });
});

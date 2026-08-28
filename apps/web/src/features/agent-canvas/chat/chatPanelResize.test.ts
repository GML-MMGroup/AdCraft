import { describe, expect, it } from "vitest";

import {
  getAgentChatResizeBounds,
  resizeAgentChatWidth,
} from "./chatPanelResize.ts";

describe("chat panel resize math", () => {
  it("keeps the current panel width as the minimum and reserves canvas space", () => {
    expect(getAgentChatResizeBounds(390, 1440)).toEqual({ minWidth: 390, maxWidth: 720 });
    expect(getAgentChatResizeBounds(330, 800)).toEqual({ minWidth: 330, maxWidth: 480 });
  });

  it("expands when the left edge moves left and clamps both boundaries", () => {
    const bounds = getAgentChatResizeBounds(390, 1440);

    expect(resizeAgentChatWidth({ startX: 1050, startWidth: 390, pointerX: 850, bounds })).toBe(590);
    expect(resizeAgentChatWidth({ startX: 1050, startWidth: 390, pointerX: 1000, bounds })).toBe(440);
    expect(resizeAgentChatWidth({ startX: 1050, startWidth: 390, pointerX: 100, bounds })).toBe(720);
    expect(resizeAgentChatWidth({ startX: 1050, startWidth: 390, pointerX: 1200, bounds })).toBe(390);
  });
});

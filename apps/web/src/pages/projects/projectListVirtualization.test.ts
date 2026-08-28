import { describe, expect, it } from "vitest";

import { getProjectGridColumnCount, getVirtualProjectWindow } from "./projectListVirtualization.ts";

describe("project list virtualization", () => {
  it("calculates a stable column count from the measured grid width", () => {
    expect(getProjectGridColumnCount(320)).toBe(1);
    expect(getProjectGridColumnCount(760)).toBe(3);
    expect(getProjectGridColumnCount(1280)).toBe(5);
  });

  it("keeps only the viewport rows plus overscan rows mounted", () => {
    expect(getVirtualProjectWindow({
      itemCount: 100,
      columnCount: 4,
      scrollTop: 0,
      viewportHeight: 720,
      rowHeight: 308,
      overscanRows: 1,
    })).toEqual({
      startRow: 0,
      endRow: 4,
      startIndex: 0,
      endIndex: 16,
      totalRows: 25,
      totalHeight: 7700,
    });
  });

  it("clamps the virtual window when scrolling near the end", () => {
    expect(getVirtualProjectWindow({
      itemCount: 9,
      columnCount: 3,
      scrollTop: 1800,
      viewportHeight: 720,
      rowHeight: 308,
      overscanRows: 1,
    })).toEqual({
      startRow: 1,
      endRow: 3,
      startIndex: 3,
      endIndex: 9,
      totalRows: 3,
      totalHeight: 924,
    });
  });
});

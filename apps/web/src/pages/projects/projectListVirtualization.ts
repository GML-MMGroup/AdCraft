export const PROJECT_CARD_HEIGHT = 292;
export const PROJECT_GRID_GAP = 16;
export const PROJECT_GRID_MIN_CARD_WIDTH = 220;
export const PROJECT_VIRTUAL_OVERSCAN_ROWS = 1;
export const PROJECT_GRID_ROW_HEIGHT = PROJECT_CARD_HEIGHT + PROJECT_GRID_GAP;

export type VirtualProjectWindow = {
  startRow: number;
  endRow: number;
  startIndex: number;
  endIndex: number;
  totalRows: number;
  totalHeight: number;
};

export function getProjectGridColumnCount(
  width: number,
  minCardWidth = PROJECT_GRID_MIN_CARD_WIDTH,
  gap = PROJECT_GRID_GAP,
) {
  if (!Number.isFinite(width) || width <= 0) return 1;
  return Math.max(1, Math.floor((width + gap) / (minCardWidth + gap)));
}

export function getVirtualProjectWindow({
  itemCount,
  columnCount,
  scrollTop,
  viewportHeight,
  rowHeight = PROJECT_GRID_ROW_HEIGHT,
  overscanRows = PROJECT_VIRTUAL_OVERSCAN_ROWS,
}: {
  itemCount: number;
  columnCount: number;
  scrollTop: number;
  viewportHeight: number;
  rowHeight?: number;
  overscanRows?: number;
}): VirtualProjectWindow {
  const safeItemCount = Math.max(0, Math.floor(itemCount));
  const safeColumnCount = Math.max(1, Math.floor(columnCount));
  const safeRowHeight = Math.max(1, rowHeight);
  const safeViewportHeight = Math.max(0, viewportHeight);
  const safeOverscanRows = Math.max(0, Math.floor(overscanRows));
  const totalRows = Math.ceil(safeItemCount / safeColumnCount);
  const totalHeight = totalRows * safeRowHeight;

  if (totalRows === 0) {
    return {
      startRow: 0,
      endRow: 0,
      startIndex: 0,
      endIndex: 0,
      totalRows,
      totalHeight,
    };
  }

  const safeScrollTop = Math.max(0, Number.isFinite(scrollTop) ? scrollTop : 0);
  const firstVisibleRow = Math.min(totalRows - 1, Math.floor(safeScrollTop / safeRowHeight));
  const lastVisibleRow = Math.min(
    totalRows,
    Math.max(firstVisibleRow + 1, Math.ceil((safeScrollTop + safeViewportHeight) / safeRowHeight)),
  );
  const startRow = Math.max(0, firstVisibleRow - safeOverscanRows);
  const endRow = Math.min(totalRows, lastVisibleRow + safeOverscanRows);

  return {
    startRow,
    endRow,
    startIndex: startRow * safeColumnCount,
    endIndex: Math.min(safeItemCount, endRow * safeColumnCount),
    totalRows,
    totalHeight,
  };
}

export interface ContainedFrame {
  width: number;
  height: number;
}

export function fitContainedFrame(
  containerWidth: number,
  containerHeight: number,
  ratio: number,
): ContainedFrame {
  if (
    !Number.isFinite(containerWidth)
    || !Number.isFinite(containerHeight)
    || !Number.isFinite(ratio)
    || containerWidth <= 0
    || containerHeight <= 0
    || ratio <= 0
  ) {
    return { width: 0, height: 0 };
  }
  if (containerWidth / containerHeight > ratio) {
    return { width: containerHeight * ratio, height: containerHeight };
  }
  return { width: containerWidth, height: containerWidth / ratio };
}

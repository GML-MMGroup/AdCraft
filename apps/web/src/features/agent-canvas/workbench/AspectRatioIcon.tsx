/** A frame preview for explicit ratios and pixel dimensions; auto/quality values have no orientation. */
export function AspectRatioIcon({ value }: { value: string }) {
  const dimensions = /^\s*(\d+(?:\.\d+)?)\s*[:x×*]\s*(\d+(?:\.\d+)?)\s*$/i.exec(value);
  if (!dimensions) return null;
  const width = Number(dimensions[1]);
  const height = Number(dimensions[2]);
  if (!(width > 0 && height > 0 && Number.isFinite(width) && Number.isFinite(height))) return null;
  const scale = 14 / Math.max(width, height);
  const frameWidth = width * scale;
  const frameHeight = height * scale;

  return (
    <svg className="agent-node-workbench__aspect-ratio-icon" width="18" height="18" viewBox="0 0 18 18"
      fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true" focusable="false">
      <rect x={(18 - frameWidth) / 2} y={(18 - frameHeight) / 2}
        width={frameWidth} height={frameHeight} rx="1.5" />
    </svg>
  );
}

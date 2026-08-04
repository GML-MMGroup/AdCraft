import type { TypographyRegionId, TypographyRegionSettings } from "./fontCatalog";

type TypographySettings = Record<TypographyRegionId, TypographyRegionSettings>;

export function serializeTypographyConfig(settings: TypographySettings): string {
  return `${JSON.stringify(settings, null, 2)}\n`;
}

export function downloadTypographyConfig(settings: TypographySettings, date = new Date()): void {
  const blob = new Blob([serializeTypographyConfig(settings)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");

  anchor.href = url;
  anchor.download = `adcraft-home-typography-${date.toISOString().slice(0, 10)}.json`;
  anchor.hidden = true;

  try {
    document.body.append(anchor);
    anchor.click();
  } finally {
    anchor.remove();
    URL.revokeObjectURL(url);
  }
}

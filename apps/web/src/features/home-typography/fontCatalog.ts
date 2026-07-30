export type FontSource = "local" | "system" | "web";

export type TypographyRegionId =
  | "heroMain"
  | "heroAccent"
  | "heroBody"
  | "heroAction"
  | "navigation"
  | "sectionHeading"
  | "sectionBody"
  | "cardTitle"
  | "cardMeta";

export type TypographyRegionSettings = {
  fontId: string;
  fontWeight: number;
  fontStyle: "normal" | "italic";
  fontSizePx: number;
  lineHeight: number;
  letterSpacingEm: number;
  textTransform: "none" | "uppercase" | "small-caps";
};

export type TypographyRegionDefinition = {
  id: TypographyRegionId;
  label: string;
};

export type FontCatalogEntry = {
  id: string;
  label: string;
  family: string;
  fallback: string;
  source: FontSource;
  weights: readonly number[];
  supportsItalic: boolean;
  googleFamily?: string;
};

export const FONT_CATALOG: readonly FontCatalogEntry[] = [
  { id: "manrope", label: "Manrope", family: "Manrope", fallback: "sans-serif", source: "local", weights: [400, 500, 600, 700, 800], supportsItalic: false },
  { id: "instrument-serif", label: "Instrument Serif", family: "Instrument Serif", fallback: "serif", source: "local", weights: [400], supportsItalic: true },
  { id: "jetbrains-mono", label: "JetBrains Mono", family: "JetBrains Mono", fallback: "monospace", source: "local", weights: [400, 500, 600, 700], supportsItalic: false },
  { id: "arial", label: "Arial", family: "Arial", fallback: "sans-serif", source: "system", weights: [400, 700], supportsItalic: true },
  { id: "georgia", label: "Georgia", family: "Georgia", fallback: "serif", source: "system", weights: [400, 700], supportsItalic: true },
  { id: "times-new-roman", label: "Times New Roman", family: "Times New Roman", fallback: "serif", source: "system", weights: [400, 700], supportsItalic: true },
  { id: "trebuchet-ms", label: "Trebuchet MS", family: "Trebuchet MS", fallback: "sans-serif", source: "system", weights: [400, 700], supportsItalic: true },
  { id: "verdana", label: "Verdana", family: "Verdana", fallback: "sans-serif", source: "system", weights: [400, 700], supportsItalic: true },
  { id: "courier-new", label: "Courier New", family: "Courier New", fallback: "monospace", source: "system", weights: [400, 700], supportsItalic: true },
  { id: "dm-sans", label: "DM Sans", family: "DM Sans", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700], supportsItalic: true, googleFamily: "DM Sans" },
  { id: "inter", label: "Inter", family: "Inter", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: true, googleFamily: "Inter" },
  { id: "space-grotesk", label: "Space Grotesk", family: "Space Grotesk", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700], supportsItalic: false, googleFamily: "Space Grotesk" },
  { id: "plus-jakarta-sans", label: "Plus Jakarta Sans", family: "Plus Jakarta Sans", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: true, googleFamily: "Plus Jakarta Sans" },
  { id: "work-sans", label: "Work Sans", family: "Work Sans", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: true, googleFamily: "Work Sans" },
  { id: "fraunces", label: "Fraunces", family: "Fraunces", fallback: "serif", source: "web", weights: [400, 500, 600, 700], supportsItalic: true, googleFamily: "Fraunces" },
  { id: "dm-serif-display", label: "DM Serif Display", family: "DM Serif Display", fallback: "serif", source: "web", weights: [400], supportsItalic: true, googleFamily: "DM Serif Display" },
  { id: "libre-baskerville", label: "Libre Baskerville", family: "Libre Baskerville", fallback: "serif", source: "web", weights: [400, 700], supportsItalic: true, googleFamily: "Libre Baskerville" },
  { id: "playfair-display", label: "Playfair Display", family: "Playfair Display", fallback: "serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: true, googleFamily: "Playfair Display" },
  { id: "cormorant-garamond", label: "Cormorant Garamond", family: "Cormorant Garamond", fallback: "serif", source: "web", weights: [400, 500, 600, 700], supportsItalic: true, googleFamily: "Cormorant Garamond" },
  { id: "ibm-plex-mono", label: "IBM Plex Mono", family: "IBM Plex Mono", fallback: "monospace", source: "web", weights: [400, 500, 600, 700], supportsItalic: true, googleFamily: "IBM Plex Mono" },
];

export const TYPOGRAPHY_REGION_DEFINITIONS: readonly TypographyRegionDefinition[] = [
  { id: "heroMain", label: "Hero main" },
  { id: "heroAccent", label: "Hero accent" },
  { id: "heroBody", label: "Hero body" },
  { id: "heroAction", label: "Hero action" },
  { id: "navigation", label: "Navigation" },
  { id: "sectionHeading", label: "Section heading" },
  { id: "sectionBody", label: "Section body" },
  { id: "cardTitle", label: "Card title" },
  { id: "cardMeta", label: "Card meta" },
];

export const DEFAULT_REGION_SETTINGS: Record<TypographyRegionId, TypographyRegionSettings> = {
  heroMain: { fontId: "instrument-serif", fontWeight: 400, fontStyle: "normal", fontSizePx: 64, lineHeight: 1.15, letterSpacingEm: 0.012, textTransform: "none" },
  heroAccent: { fontId: "instrument-serif", fontWeight: 400, fontStyle: "italic", fontSizePx: 64, lineHeight: 1.15, letterSpacingEm: 0.012, textTransform: "none" },
  heroBody: { fontId: "manrope", fontWeight: 400, fontStyle: "normal", fontSizePx: 18, lineHeight: 1.6, letterSpacingEm: 0, textTransform: "none" },
  heroAction: { fontId: "manrope", fontWeight: 700, fontStyle: "normal", fontSizePx: 14, lineHeight: 1.2, letterSpacingEm: 0, textTransform: "none" },
  navigation: { fontId: "manrope", fontWeight: 600, fontStyle: "normal", fontSizePx: 14, lineHeight: 1.2, letterSpacingEm: 0, textTransform: "none" },
  sectionHeading: { fontId: "manrope", fontWeight: 700, fontStyle: "normal", fontSizePx: 40, lineHeight: 1.05, letterSpacingEm: 0, textTransform: "none" },
  sectionBody: { fontId: "manrope", fontWeight: 400, fontStyle: "normal", fontSizePx: 18, lineHeight: 1.6, letterSpacingEm: 0, textTransform: "none" },
  cardTitle: { fontId: "manrope", fontWeight: 700, fontStyle: "normal", fontSizePx: 18, lineHeight: 1.3, letterSpacingEm: 0, textTransform: "none" },
  cardMeta: { fontId: "manrope", fontWeight: 500, fontStyle: "normal", fontSizePx: 13, lineHeight: 1.4, letterSpacingEm: 0, textTransform: "uppercase" },
};

function copySettings(settings: TypographyRegionSettings): TypographyRegionSettings {
  return { ...settings };
}

export function resetRegionSettings(regionId: TypographyRegionId): TypographyRegionSettings {
  return copySettings(DEFAULT_REGION_SETTINGS[regionId]);
}

export function resetAllRegionSettings(
  _settings: Record<TypographyRegionId, TypographyRegionSettings>,
): Record<TypographyRegionId, TypographyRegionSettings> {
  return Object.fromEntries(
    TYPOGRAPHY_REGION_DEFINITIONS.map(({ id }) => [id, resetRegionSettings(id)]),
  ) as Record<TypographyRegionId, TypographyRegionSettings>;
}

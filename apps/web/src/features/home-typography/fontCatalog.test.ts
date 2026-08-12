import { describe, expect, it } from "vitest";

import {
  DEFAULT_REGION_SETTINGS,
  FONT_CATALOG,
  HANDWRITTEN_FONT_COLLECTIONS,
  getFontsForRegion,
  resetAllRegionSettings,
  resetRegionSettings,
} from "./fontCatalog";

describe("home typography font catalog", () => {
  it("keeps Hero main and Hero accent as separate settings", () => {
    expect(DEFAULT_REGION_SETTINGS.heroMain)
      .not.toBe(DEFAULT_REGION_SETTINGS.heroAccent);
    expect(resetRegionSettings("heroAccent")).toEqual(DEFAULT_REGION_SETTINGS.heroAccent);
    expect(DEFAULT_REGION_SETTINGS.heroAccent).toMatchObject({
      fontId: "georgia",
      fontStyle: "italic",
    });
  });

  it("offers local, system, and web font sources", () => {
    expect(new Set(FONT_CATALOG.map((font) => font.source)))
      .toEqual(new Set(["local", "system", "web"]));
  });

  it("offers a broad handwritten catalog only for the Hero accent", () => {
    const accentFonts = getFontsForRegion("heroAccent");
    const mainFonts = getFontsForRegion("heroMain");
    const handwrittenFonts = accentFonts.filter((font) => font.collection?.startsWith("handwritten-"));

    expect(handwrittenFonts.length).toBeGreaterThanOrEqual(90);
    expect(handwrittenFonts).toContainEqual(expect.objectContaining({
      id: "dancing-script",
      family: "Dancing Script",
      source: "web",
    }));
    expect(mainFonts).not.toContainEqual(expect.objectContaining({ id: "dancing-script" }));
    expect(handwrittenFonts.every((font) => font.allowedRegions?.includes("heroAccent"))).toBe(true);
    expect(new Set(handwrittenFonts.map((font) => font.collection)))
      .toEqual(new Set(HANDWRITTEN_FONT_COLLECTIONS.map(({ id }) => id)));
  });

  it("keeps font identifiers unique after adding the handwritten catalog", () => {
    const fontIds = FONT_CATALOG.map((font) => font.id);

    expect(new Set(fontIds).size).toBe(fontIds.length);
  });

  it("includes the extended web font set for sans, serif, display, and mono exploration", () => {
    const webFontIds = new Set(
      FONT_CATALOG
        .filter((font) => font.source === "web")
        .map((font) => font.id),
    );

    expect([...webFontIds]).toEqual(expect.arrayContaining([
      "geist",
      "sora",
      "outfit",
      "urbanist",
      "instrument-sans",
      "ibm-plex-sans",
      "bodoni-moda",
      "lora",
      "newsreader",
      "source-serif-4",
      "spectral",
      "crimson-pro",
      "syne",
      "bricolage-grotesque",
      "abril-fatface",
      "unbounded",
      "space-mono",
      "fira-code",
      "dm-mono",
    ]));
  });

  it("adds the additional curated faces without duplicating locally served fonts", () => {
    const webFontIds = new Set(
      FONT_CATALOG
        .filter((font) => font.source === "web")
        .map((font) => font.id),
    );

    expect([...webFontIds]).toEqual(expect.arrayContaining([
      "archivo",
      "cabin",
      "noto-sans",
      "red-hat-display",
      "rubik",
      "merriweather",
      "eb-garamond",
      "literata",
      "alegreya",
      "archivo-black",
      "anton",
      "bebas-neue",
      "righteous",
      "yeseva-one",
      "roboto-mono",
      "inconsolata",
      "source-code-pro",
    ]));
    expect(webFontIds.has("manrope")).toBe(false);
    expect(webFontIds.has("jetbrains-mono")).toBe(false);
  });

  it("restores every region to the production defaults", () => {
    const changed = {
      ...DEFAULT_REGION_SETTINGS,
      heroAccent: { ...DEFAULT_REGION_SETTINGS.heroAccent, fontId: "dm-serif-display" },
    };

    expect(resetAllRegionSettings(changed)).toEqual(DEFAULT_REGION_SETTINGS);
  });
});

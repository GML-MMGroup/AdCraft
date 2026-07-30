import { describe, expect, it } from "vitest";

import {
  DEFAULT_REGION_SETTINGS,
  FONT_CATALOG,
  resetAllRegionSettings,
  resetRegionSettings,
} from "./fontCatalog";

describe("home typography font catalog", () => {
  it("keeps Hero main and Hero accent as separate settings", () => {
    expect(DEFAULT_REGION_SETTINGS.heroMain)
      .not.toBe(DEFAULT_REGION_SETTINGS.heroAccent);
    expect(resetRegionSettings("heroAccent")).toEqual(DEFAULT_REGION_SETTINGS.heroAccent);
  });

  it("offers local, system, and web font sources", () => {
    expect(new Set(FONT_CATALOG.map((font) => font.source)))
      .toEqual(new Set(["local", "system", "web"]));
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

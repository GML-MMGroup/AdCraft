import { existsSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const appRoot = process.cwd();
const homeStyles = readFileSync(resolve(appRoot, "src/pages/home.css"), "utf8");
const styles = [
  "styles/base.css",
  "pages/home.css",
  "pages/projects.css",
  "pages/assets.css",
  "pages/api-space.css",
  "features/workflow/workflow.css",
  "features/workflow/v2/screenplay/screenplay.css",
  "features/workflow/final-composition/final-composition.css",
].map((path) => readFileSync(resolve(appRoot, "src", path), "utf8")).join("\n");
const indexHtml = readFileSync(resolve(appRoot, "index.html"), "utf8");
const labLoader = readFileSync(
  resolve(appRoot, "src/features/home-typography/webFontLoader.ts"),
  "utf8",
);
const fontFiles = [
  "manrope-latin-variable.woff2",
  "instrument-serif-latin.woff2",
  "instrument-serif-latin-italic.woff2",
  "dancing-script-latin-variable.woff2",
  "jetbrains-mono-latin-variable.woff2",
];
const approvedWeights = new Set([400, 500, 600, 700, 800, 900]);
const invalidWeights = [...styles.matchAll(/font-weight:\s*(\d+)/g)]
  .map((match) => Number(match[1]))
  .filter((weight) => !approvedWeights.has(weight));

describe("typography system", () => {
  it("applies the exported home typography settings to every homepage region", () => {
    const expectedRules = [
      ['[data-home-typography-region="heroMain"]', '"Trebuchet MS"', '60px', '400', 'italic', '1.1', '0.016em'],
      ['[data-home-typography-region="heroAccent"]', 'Georgia', '70px', '400', 'italic', '1.2', '0.046em'],
      ['[data-home-typography-region="heroBody"]', 'Arial', '16px', '400', 'italic', '1.5', '0.006em'],
      ['[data-home-typography-region="heroAction"]', '"JetBrains Mono"', '14px', '400', 'normal', '1.1', '0.004em'],
      ['[data-home-typography-region="navigation"]', '"Manrope"', '14px', '400', 'normal', '1.2', '0'],
      ['[data-home-typography-region="sectionHeading"]', '"JetBrains Mono"', '37px', '400', 'normal', '1.05', '-0.004em'],
      ['[data-home-typography-region="sectionBody"]', '"Manrope"', '18px', '400', 'normal', '1.6', '0'],
      ['[data-home-typography-region="cardTitle"]', '"Manrope"', '15px', '400', 'normal', '1.15', '-0.002em'],
      ['[data-home-typography-region="cardMeta"]', '"Manrope"', '13px', '400', 'normal', '1.4', '0'],
    ] as const;

    for (const [region, family, size, weight, style, lineHeight, spacing] of expectedRules) {
      const escapedRegion = region.replaceAll("[", "\\[").replaceAll("]", "\\]");
      const pattern = new RegExp(
        `${escapedRegion}\\s*\\{[^}]*font-family:\\s*${family}[^}]*font-size:\\s*${size}[^}]*font-weight:\\s*${weight}[^}]*font-style:\\s*${style}[^}]*line-height:\\s*${lineHeight}[^}]*letter-spacing:\\s*${spacing}`,
        "s",
      );

      expect(homeStyles).toMatch(pattern);
    }

    expect(homeStyles).toMatch(/\[data-home-typography-region="cardMeta"\]\s*\{[^}]*text-transform:\s*uppercase/s);
  });

  it("uses locally served typefaces instead of Google Fonts", () => {
    expect(indexHtml).not.toContain("fonts.googleapis.com");
    expect(indexHtml).not.toContain("fonts.gstatic.com");
    expect(styles).toContain('url("/fonts/manrope-latin-variable.woff2")');
    expect(styles).toContain('url("/fonts/instrument-serif-latin.woff2")');
    expect(styles).toContain('url("/fonts/instrument-serif-latin-italic.woff2")');
    expect(styles).toContain('url("/fonts/dancing-script-latin-variable.woff2")');
    expect(styles).toContain('url("/fonts/jetbrains-mono-latin-variable.woff2")');
    expect(homeStyles).not.toContain('url("/fonts/space-grotesk-latin-variable.woff2")');
    expect(homeStyles).not.toContain('url("/fonts/inter-latin-variable.woff2")');
    expect(homeStyles).not.toContain('url("/fonts/barlow-condensed-black-italic.woff2")');

    for (const fontFile of fontFiles) {
      const path = resolve(appRoot, "public/fonts", fontFile);
      expect(existsSync(path)).toBe(true);
      expect(statSync(path).size).toBeGreaterThan(0);
    }
  });

  it("keeps Google Fonts out of production styles while allowing the isolated lab loader", () => {
    expect(indexHtml).not.toContain("fonts.googleapis.com");
    expect(styles).not.toContain("fonts.googleapis.com");
    expect(labLoader).toContain("fonts.googleapis.com");
    expect(labLoader).toContain("dataset.homeTypographyFont");
  });

  it("defines the interface, brand, and technical font roles", () => {
    expect(styles).toContain('--font-ui: "Manrope"');
    expect(styles).toContain('--font-brand: "Instrument Serif"');
    expect(styles).toContain('--font-mono: "JetBrains Mono"');
    expect(styles).toContain("font-family: var(--font-ui)");
    expect(styles).toContain("font-family: var(--font-mono)");
  });

  it("keeps operational headings compact and gives the homepage its exported display scale", () => {
    expect(styles).toMatch(/\.page-title\s*\{[^}]*font-size:\s*clamp\(40px, 3\.4vw, 48px\)/s);
    expect(homeStyles).toMatch(/\[data-home-typography-region="sectionHeading"\]\s*\{[^}]*font-size:\s*37px/s);
    expect(homeStyles).toMatch(/\[data-home-typography-region="heroMain"\]\s*\{[^}]*font-size:\s*60px/s);
    expect(homeStyles).toMatch(/\[data-home-typography-region="heroAccent"\]\s*\{[^}]*font-size:\s*70px/s);
    expect(homeStyles).toMatch(/@media \(max-width: 620px\)\s*\{\s*\.home-page \.home-product-hero__title\[data-home-typography-region="heroMain"\]\s*\{[^}]*font-size:\s*40px/s);
    expect(invalidWeights).toEqual([]);
  });
});

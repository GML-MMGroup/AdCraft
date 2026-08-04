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
  "jetbrains-mono-latin-variable.woff2",
  "space-grotesk-latin-variable.woff2",
  "inter-latin-variable.woff2",
  "barlow-condensed-black-italic.woff2",
];
const approvedWeights = new Set([400, 500, 600, 700, 800, 900]);
const invalidWeights = [...styles.matchAll(/font-weight:\s*(\d+)/g)]
  .map((match) => Number(match[1]))
  .filter((weight) => !approvedWeights.has(weight));
const mobileHeroStyles = homeStyles.match(
  /@media \(max-width: 620px\)[\s\S]*?\.home-product-hero__title\s*\{[^}]*\}/,
)?.[0] ?? "";

describe("typography system", () => {
  it("uses locally served typefaces instead of Google Fonts", () => {
    expect(indexHtml).not.toContain("fonts.googleapis.com");
    expect(indexHtml).not.toContain("fonts.gstatic.com");
    expect(styles).toContain('url("/fonts/manrope-latin-variable.woff2")');
    expect(styles).toContain('url("/fonts/instrument-serif-latin.woff2")');
    expect(styles).toContain('url("/fonts/instrument-serif-latin-italic.woff2")');
    expect(styles).toContain('url("/fonts/jetbrains-mono-latin-variable.woff2")');
    expect(homeStyles).toContain('url("/fonts/space-grotesk-latin-variable.woff2")');
    expect(homeStyles).toContain('url("/fonts/inter-latin-variable.woff2")');
    expect(homeStyles).toContain('url("/fonts/barlow-condensed-black-italic.woff2")');

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

  it("keeps operational headings compact and gives the homepage its approved display scale", () => {
    expect(styles).toMatch(/\.page-title\s*\{[^}]*font-size:\s*clamp\(40px, 3\.4vw, 48px\)/s);
    expect(styles).toMatch(/\.section-title h2\s*\{[^}]*font-size:\s*clamp\(32px, 3vw, 40px\)/s);
    expect(homeStyles).toMatch(/\.home-product-hero__title\s*\{[^}]*font-size:\s*62px/s);
    expect(homeStyles).toMatch(/\.home-product-hero__accent\s*\{[^}]*font-size:\s*150px/s);
    expect(mobileHeroStyles).toMatch(/\.home-product-hero__title\s*\{[^}]*font-size:\s*40px/s);
    expect(invalidWeights).toEqual([]);
  });
});

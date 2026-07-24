import { existsSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const appRoot = process.cwd();
const styles = readFileSync(resolve(appRoot, "src/styles.css"), "utf8");
const indexHtml = readFileSync(resolve(appRoot, "index.html"), "utf8");
const fontFiles = [
  "manrope-latin-variable.woff2",
  "instrument-serif-latin.woff2",
  "instrument-serif-latin-italic.woff2",
  "jetbrains-mono-latin-variable.woff2",
];
const approvedWeights = new Set([400, 500, 600, 700, 800]);
const invalidWeights = [...styles.matchAll(/font-weight:\s*(\d+)/g)]
  .map((match) => Number(match[1]))
  .filter((weight) => !approvedWeights.has(weight));
const mobileHeroStyles = styles.match(
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

    for (const fontFile of fontFiles) {
      const path = resolve(appRoot, "public/fonts", fontFile);
      expect(existsSync(path)).toBe(true);
      expect(statSync(path).size).toBeGreaterThan(0);
    }
  });

  it("defines the interface, brand, and technical font roles", () => {
    expect(styles).toContain('--font-ui: "Manrope"');
    expect(styles).toContain('--font-brand: "Instrument Serif"');
    expect(styles).toContain('--font-mono: "JetBrains Mono"');
    expect(styles).toContain("font-family: var(--font-ui)");
    expect(styles).toContain("font-family: var(--font-mono)");
  });

  it("keeps operational headings compact and weights on the approved scale", () => {
    expect(styles).toMatch(/\.page-title\s*\{[^}]*font-size:\s*clamp\(40px, 3\.4vw, 48px\)/s);
    expect(styles).toMatch(/\.section-title h2\s*\{[^}]*font-size:\s*clamp\(32px, 3vw, 40px\)/s);
    expect(styles).toMatch(/\.home-product-hero__title\s*\{[^}]*font-size:\s*clamp\(48px, 5vw, 68px\)/s);
    expect(mobileHeroStyles).toMatch(/\.home-product-hero__title\s*\{[^}]*font-size:\s*clamp\(42px, 12vw, 56px\)/s);
    expect(invalidWeights).toEqual([]);
  });
});

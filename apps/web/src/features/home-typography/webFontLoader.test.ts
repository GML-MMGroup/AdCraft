import { afterEach, describe, expect, it } from "vitest";

import { FONT_CATALOG } from "./fontCatalog";
import {
  getWebFontStylesheetHref,
  getWebFontStylesheetId,
  loadWebFont,
} from "./webFontLoader";

const webFont = FONT_CATALOG.find((font) => font.source === "web");
const localFont = FONT_CATALOG.find((font) => font.source === "local");
const systemFont = FONT_CATALOG.find((font) => font.source === "system");

if (!webFont || !localFont || !systemFont) {
  throw new Error("The catalog must define web, local, and system fonts.");
}

afterEach(() => {
  document.head.querySelectorAll("link[data-home-typography-font]").forEach((link) => link.remove());
});

describe("home typography web font loader", () => {
  it("adds a selected web font stylesheet once", async () => {
    const loading = loadWebFont(webFont);
    const link = document.head.querySelector<HTMLLinkElement>(
      `#${getWebFontStylesheetId(webFont.id)}`,
    );

    expect(link).not.toBeNull();
    link?.dispatchEvent(new Event("load"));
    await loading;

    await loadWebFont(webFont);

    expect(document.head.querySelectorAll(`#${getWebFontStylesheetId(webFont.id)}`)).toHaveLength(1);
  });

  it("does not add a stylesheet for local or system faces", async () => {
    await expect(loadWebFont(localFont)).resolves.toBeUndefined();
    await expect(loadWebFont(systemFont)).resolves.toBeUndefined();

    expect(document.head.querySelectorAll("link[data-home-typography-font]")).toHaveLength(0);
  });

  it("requests only supported variants for a handwritten web font", () => {
    const dancingScript = FONT_CATALOG.find((font) => font.id === "dancing-script");

    expect(dancingScript).toBeDefined();
    expect(getWebFontStylesheetHref(dancingScript!)).toBe(
      "https://fonts.googleapis.com/css2?family=Dancing%20Script:wght@400;500;600;700&display=swap",
    );
  });
});

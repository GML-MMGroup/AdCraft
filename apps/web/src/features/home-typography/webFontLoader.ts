import type { FontCatalogEntry } from "./fontCatalog";

const webFontPromises = new Map<string, Promise<void>>();

export function getWebFontStylesheetId(fontId: string): string {
  return `home-typography-font-${fontId}`;
}

export function loadWebFont(font: FontCatalogEntry): Promise<void> {
  if (font.source !== "web") {
    return Promise.resolve();
  }

  const existingPromise = webFontPromises.get(font.id);
  if (existingPromise) {
    return existingPromise;
  }

  const stylesheetId = getWebFontStylesheetId(font.id);
  const existingLink = document.getElementById(stylesheetId) as HTMLLinkElement | null;

  const promise = new Promise<void>((resolve, reject) => {
    if (existingLink) {
      existingLink.addEventListener("load", () => resolve(), { once: true });
      existingLink.addEventListener("error", () => reject(new Error(`Failed to load ${font.label}.`)), { once: true });
      return;
    }

    const link = document.createElement("link");
    link.id = stylesheetId;
    link.rel = "stylesheet";
    link.dataset.homeTypographyFont = font.id;
    link.href = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(font.googleFamily ?? font.family)}:ital,wght@0,400;1,400&display=swap`;
    link.addEventListener("load", () => resolve(), { once: true });
    link.addEventListener("error", () => reject(new Error(`Failed to load ${font.label}.`)), { once: true });
    document.head.append(link);
  });

  webFontPromises.set(font.id, promise);
  return promise;
}

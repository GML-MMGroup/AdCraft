import { useEffect, useState } from "react";
import type { Theme } from "../../theme/themePreference";

function currentDocumentTheme(): Theme {
  if (typeof document === "undefined") return "light";
  return document.documentElement.dataset.theme === "dark"
    ? "dark"
    : "light";
}

export function useDocumentTheme() {
  const [theme, setTheme] = useState<Theme>(currentDocumentTheme);

  useEffect(() => {
    const documentElement = document.documentElement;
    const observer = new MutationObserver(() => {
      setTheme(currentDocumentTheme());
    });
    observer.observe(documentElement, {
      attributeFilter: ["data-theme"],
      attributes: true,
    });

    setTheme(currentDocumentTheme());
    return () => observer.disconnect();
  }, []);

  return theme;
}

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { LocaleProvider } from "../i18n/locale";
import { agentCanvasApi } from "../api/agentCanvasApi";

vi.mock("../api/agentCanvasApi", () => ({
  agentCanvasApi: {
    agentCanvasCreativeSession: vi.fn(),
    updateAgentCanvasCreativeSessionLocale: vi.fn(),
  },
}));
const setup = () => render(<LocaleProvider><LanguageSwitcher /></LocaleProvider>);

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.spyOn(navigator, "languages", "get").mockReturnValue(["en-US"]);
});
afterEach(() => { cleanup(); localStorage.clear(); });

describe("language switch", () => {
  it("switches immediately and persists the preference across remounts without a workflow request", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "切换到中文" }));
    expect(screen.getByRole("button", { name: "切换到中文" }).getAttribute("aria-pressed")).toBe("true");
    expect(localStorage.getItem("adcraft.locale")).toBe("zh-CN");
    expect(document.documentElement.lang).toBe("zh-CN");
    cleanup(); setup();
    expect(screen.getByRole("group", { name: "语言：中文" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Switch to English" }));
    expect(document.documentElement.lang).toBe("en-US");
    expect(localStorage.getItem("adcraft.locale")).toBe("en-US");
    expect(agentCanvasApi.agentCanvasCreativeSession).not.toHaveBeenCalled();
    expect(agentCanvasApi.updateAgentCanvasCreativeSessionLocale).not.toHaveBeenCalled();
  });

  it.each([
    [["zh-Hant", "en-US"], "zh-CN"],
    [["en-GB", "zh-CN"], "en-US"],
    [["fr-FR", "zh-CN"], "zh-CN"],
    [["fr-FR"], "en-US"],
  ] as const)("uses the first supported browser language in %j without a saved preference", (languages, expected) => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue([...languages]);
    vi.spyOn(navigator, "language", "get").mockReturnValue(languages[0]);
    setup();
    expect(document.documentElement.lang).toBe(expected);
  });

  it("prefers a saved choice over the browser and the initial fallback", () => {
    localStorage.setItem("adcraft.locale", "zh-CN");
    render(<LocaleProvider initialLocale="en-US"><LanguageSwitcher /></LocaleProvider>);
    expect(document.documentElement.lang).toBe("zh-CN");
  });

  it("ignores an invalid saved preference and detects the browser language", () => {
    localStorage.setItem("adcraft.locale", "invalid");
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["zh-CN"]);
    setup();
    expect(document.documentElement.lang).toBe("zh-CN");
  });

  it("detects and switches language when browser storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("Storage blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("Storage blocked"); });
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["zh-CN"]);
    setup();
    expect(document.documentElement.lang).toBe("zh-CN");
    fireEvent.click(screen.getByRole("button", { name: "Switch to English" }));
    expect(document.documentElement.lang).toBe("en-US");
  });
});

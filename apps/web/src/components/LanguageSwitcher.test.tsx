import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { LocaleProvider, localeChangedEventName } from "../i18n/locale";
import { agentCanvasApi, V2ApiError } from "../api/agentCanvasApi";

vi.mock("../api/agentCanvasApi", async importOriginal => ({
  ...await importOriginal<typeof import("../api/agentCanvasApi")>(),
  agentCanvasApi: {
    agentCanvasCreativeSession: vi.fn(),
    updateAgentCanvasCreativeSessionLocale: vi.fn(),
  },
}));
const read = vi.mocked(agentCanvasApi.agentCanvasCreativeSession);
const update = vi.mocked(agentCanvasApi.updateAgentCanvasCreativeSessionLocale);
const apiError = (status: number) => new V2ApiError({ status, message: "failure", details: {}, violations: [], suggestedActions: [], payload: null });
const setup = (workflowId?: string) => render(<LocaleProvider><LanguageSwitcher workflowId={workflowId}/></LocaleProvider>);

beforeEach(() => { localStorage.clear(); vi.clearAllMocks(); });
afterEach(cleanup);

describe("language switch", () => {
  it("persists the UI preference without a workflow request", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Switch to Chinese" }));
    expect(screen.getByRole("button", { name: "切换到英文" })).toBeTruthy();
    expect(localStorage.getItem("adcraft.locale")).toBe("zh-CN");
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(read).not.toHaveBeenCalled();
    cleanup(); setup();
    expect(screen.getByRole("button", { name: "切换到英文" })).toBeTruthy();
  });

  it("uses the latest session revision and refreshes after success", async () => {
    read.mockResolvedValue({ revision: 7 } as Awaited<ReturnType<typeof read>>);
    update.mockResolvedValue({ revision: 8, response_locale: "zh-CN" } as Awaited<ReturnType<typeof update>>);
    const changed = vi.fn();
    window.addEventListener(localeChangedEventName, changed);
    try {
      setup("workflow-a");
      fireEvent.click(screen.getByRole("button", { name: "Switch to Chinese" }));
      await screen.findByRole("button", { name: "切换到英文" });
      expect(update).toHaveBeenCalledWith("workflow-a", { expected_revision: 7, response_locale: "zh-CN" });
      expect(changed.mock.calls[0]?.[0].detail).toEqual({ workflowId: "workflow-a", locale: "zh-CN", session: { revision: 8, response_locale: "zh-CN" } });
    } finally { window.removeEventListener(localeChangedEventName, changed); }
  });

  it("preserves the current language on failure and permits explicit retry", async () => {
    read.mockResolvedValue({ revision: 4 } as Awaited<ReturnType<typeof read>>);
    update.mockRejectedValueOnce(apiError(409)).mockResolvedValueOnce({ revision: 5 } as Awaited<ReturnType<typeof update>>);
    setup("workflow-a");
    fireEvent.click(screen.getByRole("button", { name: "Switch to Chinese" }));
    expect((await screen.findByRole("alert")).textContent).toContain("project changed");
    expect(localStorage.getItem("adcraft.locale")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Switch to Chinese" }));
    await screen.findByRole("button", { name: "切换到英文" });
    expect(read).toHaveBeenCalledTimes(2);
  });

  it("permits a missing session but rejects a missing PATCH route", async () => {
    read.mockRejectedValueOnce(apiError(404));
    const view = setup("workflow-a");
    fireEvent.click(screen.getByRole("button", { name: "Switch to Chinese" }));
    await screen.findByRole("button", { name: "切换到英文" });
    expect(update).not.toHaveBeenCalled();
    read.mockResolvedValueOnce({ revision: 1 } as Awaited<ReturnType<typeof read>>);
    update.mockRejectedValueOnce(apiError(404));
    view.rerender(<LocaleProvider><LanguageSwitcher workflowId="workflow-b"/></LocaleProvider>);
    fireEvent.click(screen.getByRole("button", { name: "切换到英文" }));
    await screen.findByRole("alert");
    expect(localStorage.getItem("adcraft.locale")).toBe("zh-CN");
  });

  it("ignores an old workflow response after navigation", async () => {
    let resolveRead!: (value: Awaited<ReturnType<typeof read>>) => void;
    read.mockReturnValueOnce(new Promise(resolve => { resolveRead = resolve; }));
    const view = setup("workflow-a");
    fireEvent.click(screen.getByRole("button", { name: "Switch to Chinese" }));
    view.rerender(<LocaleProvider><LanguageSwitcher workflowId="workflow-b"/></LocaleProvider>);
    resolveRead({ revision: 1 } as Awaited<ReturnType<typeof read>>);
    await waitFor(() => expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(false));
    expect(update).not.toHaveBeenCalled();
    expect(localStorage.getItem("adcraft.locale")).toBeNull();
  });
});

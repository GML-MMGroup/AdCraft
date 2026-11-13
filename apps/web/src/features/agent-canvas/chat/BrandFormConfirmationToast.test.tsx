import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BrandFormConfirmationToast } from "./BrandFormConfirmationToast.tsx";
import { LocaleProvider } from "../../../i18n/locale.tsx";

describe("BrandFormConfirmationToast", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => { cleanup(); vi.useRealTimers(); });

  it("stays visible for three seconds even if its parent rerenders", () => {
    const view = render(<BrandFormConfirmationToast />);
    const notice = screen.getByRole("status", { name: "Information confirmed" });
    expect(notice.textContent).toContain("View your confirmed information in the left panel.");
    expect(notice.parentElement).toBe(document.body);
    act(() => vi.advanceTimersByTime(1_500));
    view.rerender(<BrandFormConfirmationToast />);
    act(() => vi.advanceTimersByTime(1_499));
    expect(screen.getByRole("status", { name: "Information confirmed" })).toBe(notice);
    act(() => vi.advanceTimersByTime(1));
    expect(screen.queryByRole("status", { name: "Information confirmed" })).toBeNull();
  });

  it("closes immediately with the close button", () => {
    render(<BrandFormConfirmationToast />);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss confirmation" }));
    expect(screen.queryByRole("status", { name: "Information confirmed" })).toBeNull();
  });

  it("shows localized Skill confirmation and dismisses it after three seconds", () => {
    render(<LocaleProvider initialLocale="zh-CN"><BrandFormConfirmationToast kind="skills" /></LocaleProvider>);
    expect(screen.getByRole("status", { name: "Skill 已确认" }).textContent)
      .toContain("可在左侧面板查看已确认的 Skill。");
    act(() => vi.advanceTimersByTime(3_000));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("gives a subsequent confirmation a fresh timer and clears the previous timer", () => {
    const view = render(<BrandFormConfirmationToast key="first" />);
    act(() => vi.advanceTimersByTime(2_000));
    view.rerender(<BrandFormConfirmationToast key="second" />);
    act(() => vi.advanceTimersByTime(1_000));
    expect(screen.getByRole("status", { name: "Information confirmed" })).toBeTruthy();
    act(() => vi.advanceTimersByTime(2_000));
    expect(screen.queryByRole("status", { name: "Information confirmed" })).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });
});

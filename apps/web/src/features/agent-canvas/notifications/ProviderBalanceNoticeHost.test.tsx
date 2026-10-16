import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ProviderBalanceNoticeHost } from "./ProviderBalanceNoticeHost.tsx";
import { providerBalanceNoticeFromText } from "./providerBalanceNotice.ts";
import {
  reportProviderBalanceNotice,
  resetProviderBalanceNoticeStore,
} from "./providerBalanceNoticeStore.ts";

afterEach(() => {
  cleanup();
  resetProviderBalanceNoticeStore();
});

describe("ProviderBalanceNoticeHost", () => {
  it("shows the provider message and dismisses on demand", async () => {
    render(<ProviderBalanceNoticeHost />);
    expect(screen.queryByRole("dialog")).toBeNull();

    reportProviderBalanceNotice(
      providerBalanceNoticeFromText(
        "Insufficient balance, please recharge your account.",
        "volcengine_ark",
      ),
    );

    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("火山方舟");
    expect(dialog.textContent).toContain("账户余额不足");
    expect(dialog.textContent).toContain("Insufficient balance, please recharge your account.");

    fireEvent.click(screen.getByRole("button", { name: "知道了" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("dismisses with the Escape key", async () => {
    render(<ProviderBalanceNoticeHost />);
    reportProviderBalanceNotice(providerBalanceNoticeFromText("余额不足，请充值", "tianpuyue"));

    expect((await screen.findByRole("dialog")).textContent).toContain("天谱乐");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

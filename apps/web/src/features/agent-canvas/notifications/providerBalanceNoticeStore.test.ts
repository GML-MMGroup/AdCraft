import { afterEach, describe, expect, it, vi } from "vitest";

import { V2ApiError } from "../../../api/v2Client.ts";
import { providerBalanceNoticeFromText } from "./providerBalanceNotice.ts";
import {
  dismissProviderBalanceNotice,
  providerBalanceNoticeSnapshot,
  reportProviderBalanceError,
  reportProviderBalanceNotice,
  resetProviderBalanceNoticeStore,
  subscribeProviderBalanceNotice,
} from "./providerBalanceNoticeStore.ts";

afterEach(() => {
  resetProviderBalanceNoticeStore();
});

describe("providerBalanceNoticeStore", () => {
  it("shows one notice per provider and notifies subscribers", () => {
    const listener = vi.fn();
    subscribeProviderBalanceNotice(listener);
    const notice = providerBalanceNoticeFromText("Insufficient balance", "volcengine_ark");

    expect(reportProviderBalanceNotice(notice)).toBe(true);
    expect(providerBalanceNoticeSnapshot()).toBe(notice);
    expect(listener).toHaveBeenCalledTimes(1);

    dismissProviderBalanceNotice();
    expect(providerBalanceNoticeSnapshot()).toBeNull();

    expect(reportProviderBalanceNotice(notice)).toBe(false);
    expect(providerBalanceNoticeSnapshot()).toBeNull();
  });

  it("still warns about a second provider", () => {
    reportProviderBalanceNotice(providerBalanceNoticeFromText("Insufficient balance", "openrouter"));
    dismissProviderBalanceNotice();

    const second = providerBalanceNoticeFromText("账户余额不足，请充值", "tianpuyue");
    expect(reportProviderBalanceNotice(second)).toBe(true);
    expect(providerBalanceNoticeSnapshot()?.providerLabel).toBe("天谱乐");
  });

  it("keeps the visible notice when another provider reports at the same time", () => {
    const first = providerBalanceNoticeFromText("Insufficient balance", "openrouter");
    reportProviderBalanceNotice(first);
    reportProviderBalanceNotice(providerBalanceNoticeFromText("余额不足", "tianpuyue"));

    expect(providerBalanceNoticeSnapshot()).toBe(first);
  });

  it("reports an API error through the shared entry point", () => {
    reportProviderBalanceError(new V2ApiError({
      status: 402,
      code: "provider_request_failed",
      message: "Payment required.",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }));

    expect(providerBalanceNoticeSnapshot()).not.toBeNull();
  });
});

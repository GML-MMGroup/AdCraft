import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LocalActivityPanel } from "./LocalActivityPanel.tsx";

const load = vi.hoisted(() => vi.fn());
vi.mock("../../api/v2Client.ts", () => ({ v2Api: { localRuntimeStatistics: load } }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("local activity", () => {
  it("loads on request and does not label an empty sample as healthy", async () => {
    load.mockResolvedValue({ period_days: 7, sampled_members: 0, generated_at: "2026-11-09T00:00:00Z", truncated: false, cost_available: false, items: [] });
    render(<LocalActivityPanel />);
    expect(load).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Load local activity" }));
    expect(await screen.findByText("No execution records in the last 7 days.")).toBeTruthy();
    expect(screen.queryByText("100%" )).toBeNull();
  });

  it("shows observed outcomes while missing latency and cost remain unknown", async () => {
    load.mockResolvedValue({ period_days: 7, sampled_members: 4, generated_at: "2026-11-09T00:00:00Z", truncated: false, cost_available: false, items: [{ model_ref: "test:video", succeeded: 1, failed: 1, active: 1, cancelled: 0, blocked: 1, skipped: 0, success_rate: 0.5, mean_success_seconds: null, duration_samples: 0, error_codes: { provider_inputs_unsupported: 1 } }] });
    render(<LocalActivityPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Load local activity" }));
    expect(await screen.findByText("test:video")).toBeTruthy();
    expect(screen.getByText("50%")).toBeTruthy();
    expect(screen.getByText("0 / 1 / 0")).toBeTruthy();
    expect(screen.getByText("Unknown")).toBeTruthy();
    expect(screen.getByText("Provider costs are not reported.")).toBeTruthy();
    expect(screen.getByText(/provider_inputs_unsupported/)).toBeTruthy();
  });
});

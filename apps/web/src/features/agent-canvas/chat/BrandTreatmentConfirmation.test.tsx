import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { agentCanvasApi } from "../../../api/agentCanvasApi.ts";
import { BrandTreatmentConfirmation } from "./BrandTreatmentConfirmation.tsx";

vi.mock("../../../api/agentCanvasApi.ts", () => ({ agentCanvasApi: { brandLockTreatment: vi.fn() } }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("BrandTreatmentConfirmation", () => {
  it("waits for explicit confirmation and locks only once while pending", async () => {
    let finish: (() => void) | undefined;
    vi.mocked(agentCanvasApi.brandLockTreatment).mockImplementation(() => new Promise((resolve) => {
      finish = () => resolve({ policy_version: "brand_professional_v1", stage: "production", stage_revision: 18, stage_status: "ready", treatment_substep: null });
    }));
    const confirmed = vi.fn();
    render(<BrandTreatmentConfirmation workflowId="workflow-1" responseLocale="zh-CN" onConfirmed={confirmed} />);
    expect(agentCanvasApi.brandLockTreatment).not.toHaveBeenCalled();
    const button = screen.getByRole("button", { name: "确认并锁定创意方案" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(agentCanvasApi.brandLockTreatment).toHaveBeenCalledExactlyOnceWith("workflow-1");
    finish?.();
    await waitFor(() => expect(confirmed).toHaveBeenCalledOnce());
  });

  it("preserves a retryable confirmation when the request fails", async () => {
    vi.mocked(agentCanvasApi.brandLockTreatment).mockRejectedValue(new Error("Unavailable"));
    const confirmed = vi.fn();
    render(<BrandTreatmentConfirmation workflowId="workflow-1" responseLocale="zh-CN" onConfirmed={confirmed} />);
    fireEvent.click(screen.getByRole("button", { name: "确认并锁定创意方案" }));
    await screen.findByRole("alert");
    expect(confirmed).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "确认并锁定创意方案" }) as HTMLButtonElement).disabled).toBe(false);
  });
});

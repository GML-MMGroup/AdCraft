import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EditingClipTiming } from "./EditingClipTiming.tsx";

const segment = { referenceId: "a", timelineStart: 0, timelineEnd: 5, sourceStart: 2, sourceEnd: 7 };
const next = { referenceId: "b", timelineStart: 5, timelineEnd: 10, sourceStart: 0, sourceEnd: 5 };
afterEach(cleanup);
describe("editing timing inspector", () => {
  it("submits only existing trim and timeline fields after a valid explicit apply", () => {
    const onUpdate = vi.fn();
    render(<EditingClipTiming segment={segment} segments={[segment, next]} sourceDuration={12} timelineDuration={10} fps={30} disabled={false} onUpdate={onUpdate}/>);
    fireEvent.change(screen.getByLabelText("Source in"), { target: { value: "3" } });
    expect(onUpdate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Apply timing" }));
    expect(onUpdate).toHaveBeenCalledWith({ trim_start_seconds: 3, trim_end_seconds: 7, timeline_start_seconds: 0 });
  });
  it("keeps overlapping timing edits local instead of sending an invalid manifest", () => {
    const onUpdate = vi.fn();
    render(<EditingClipTiming segment={segment} segments={[segment, next]} sourceDuration={12} timelineDuration={10} fps={30} disabled={false} onUpdate={onUpdate}/>);
    fireEvent.change(screen.getByLabelText("Source out"), { target: { value: "8" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply timing" }));
    expect(screen.getByRole("alert").textContent).toContain("without overlapping");
    expect(onUpdate).not.toHaveBeenCalled();
  });
});

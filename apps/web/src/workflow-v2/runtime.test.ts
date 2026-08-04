import { describe, expect, it } from "vitest";

import {
  applyV2RuntimeSnapshot,
  createInitialV2RuntimeStore,
  reduceV2RuntimeEvent,
} from "./runtime.ts";

describe("V2 runtime snapshot ordering", () => {
  it("does not let snapshot seq 10 regress a terminal event at seq 11", () => {
    const afterTerminalEvent = reduceV2RuntimeEvent(createInitialV2RuntimeStore(), {
      seq: 11,
      event_type: "execution_completed",
      workflow_id: "workflow-a",
      payload: {
        execution_id: "execution-a",
        status: "completed",
      },
    });

    const afterStaleSnapshot = applyV2RuntimeSnapshot(afterTerminalEvent, {
      workflow_id: "workflow-a",
      events_cursor: 10,
      active_execution_id: "execution-a",
      execution_status: "running",
      running_slot_ids: ["slot-a"],
    });

    expect(afterStaleSnapshot.lastEventSeq).toBe(11);
    expect(afterStaleSnapshot.executionStatus).toBe("completed");
    expect(afterStaleSnapshot.runningSlotIds).toEqual([]);
  });
});

import assert from "node:assert/strict";
import test from "node:test";

import { createV2WorkflowApplicationRevisionGuard } from "../src/features/workflow/graph/v2WorkflowApplicationRevisionGuard.ts";
import { createV2WorkflowHydrationRequestGuard } from "../src/features/workflow/graph/v2WorkflowHydrationRequestGuard.ts";
import { reconcileV2SlotMutationWorkflow } from "../src/features/workflow/v2/slots/v2SlotMutationWorkflowGuard.ts";

function workflow(id, prompt) {
  return { workflow_id: id, slots: [{ slot_id: "slot-1", user_prompt: prompt }] };
}

test("a linked workflow application wins over a delayed slot PATCH or regenerate response", async () => {
  const revision = createV2WorkflowApplicationRevisionGuard();
  revision.activateWorkflow("workflow-1");
  let latest = workflow("workflow-1", "initial");
  const applied = [];
  const applyWorkflowV2 = async (next) => {
    revision.appliedWorkflow(next.workflow_id);
    latest = next;
    applied.push(next);
  };
  const patchCapture = revision.capture("workflow-1");
  const regenerateCapture = revision.capture("workflow-1");

  await applyWorkflowV2(workflow("workflow-1", "linked-B"));
  const patch = await reconcileV2SlotMutationWorkflow({
    workflowId: "workflow-1",
    capture: patchCapture,
    activeWorkflowId: "workflow-1",
    isCurrentRevision: revision.isCurrent,
    returnedWorkflow: workflow("workflow-1", "stale-A-patch"),
    applyWorkflowV2,
    refreshLatestWorkflow: async () => {
      await applyWorkflowV2(workflow("workflow-1", "guarded-C"));
      return latest;
    },
  });
  const regenerate = await reconcileV2SlotMutationWorkflow({
    workflowId: "workflow-1",
    capture: regenerateCapture,
    activeWorkflowId: "workflow-1",
    isCurrentRevision: revision.isCurrent,
    returnedWorkflow: workflow("workflow-1", "stale-A-regenerate"),
    applyWorkflowV2,
    refreshLatestWorkflow: async () => latest,
  });

  assert.equal(patch.stale, true);
  assert.equal(regenerate.stale, true);
  assert.deepEqual(applied.map((entry) => entry.slots[0].user_prompt), ["linked-B", "guarded-C"]);
  assert.equal(latest.slots[0].user_prompt, "guarded-C");
});

test("a slot response applies when no newer workflow application occurred and invalidates on switch", async () => {
  const revision = createV2WorkflowApplicationRevisionGuard();
  revision.activateWorkflow("workflow-1");
  let latest = workflow("workflow-1", "initial");
  const applied = [];
  const applyWorkflowV2 = async (next) => {
    revision.appliedWorkflow(next.workflow_id);
    latest = next;
    applied.push(next);
  };
  const capture = revision.capture("workflow-1");
  const accepted = await reconcileV2SlotMutationWorkflow({
    workflowId: "workflow-1",
    capture,
    activeWorkflowId: "workflow-1",
    isCurrentRevision: revision.isCurrent,
    returnedWorkflow: workflow("workflow-1", "accepted-A"),
    applyWorkflowV2,
    refreshLatestWorkflow: async () => latest,
  });
  assert.equal(accepted.stale, false);
  assert.equal(latest.slots[0].user_prompt, "accepted-A");

  const switchedCapture = revision.capture("workflow-1");
  revision.activateWorkflow("workflow-2");
  const switched = await reconcileV2SlotMutationWorkflow({
    workflowId: "workflow-1",
    capture: switchedCapture,
    activeWorkflowId: "workflow-2",
    isCurrentRevision: revision.isCurrent,
    returnedWorkflow: workflow("workflow-1", "must-not-apply"),
    applyWorkflowV2,
    refreshLatestWorkflow: async () => null,
  });
  assert.equal(switched.stale, true);
  assert.deepEqual(applied.map((entry) => entry.slots[0].user_prompt), ["accepted-A"]);
});

test("a failed slot mutation settles against the latest linked workflow without applying stale data", async () => {
  const revision = createV2WorkflowApplicationRevisionGuard();
  revision.activateWorkflow("workflow-1");
  let latest = workflow("workflow-1", "initial");
  const applied = [];
  const applyWorkflowV2 = async (next) => {
    revision.appliedWorkflow(next.workflow_id);
    latest = next;
    applied.push(next);
  };
  const capture = revision.capture("workflow-1");
  await applyWorkflowV2(workflow("workflow-1", "linked-B"));

  const failed = await reconcileV2SlotMutationWorkflow({
    workflowId: "workflow-1",
    capture,
    activeWorkflowId: "workflow-1",
    isCurrentRevision: revision.isCurrent,
    returnedWorkflow: null,
    applyWorkflowV2,
    refreshLatestWorkflow: async () => latest,
  });

  assert.equal(failed.stale, true);
  assert.equal(failed.workflow.slots[0].user_prompt, "linked-B");
  assert.deepEqual(applied.map((entry) => entry.slots[0].user_prompt), ["linked-B"]);
});

test("an attachment response uses its request-time capture and cannot apply after linked context", async () => {
  const revision = createV2WorkflowApplicationRevisionGuard();
  revision.activateWorkflow("workflow-1");
  let latest = workflow("workflow-1", "initial");
  const applied = [];
  const applyWorkflowV2 = async (next) => {
    revision.appliedWorkflow(next.workflow_id);
    latest = next;
    applied.push(next);
  };
  const attachmentCapture = revision.capture("workflow-1");

  await applyWorkflowV2(workflow("workflow-1", "linked-B"));
  const reconciled = await reconcileV2SlotMutationWorkflow({
    workflowId: "workflow-1",
    capture: attachmentCapture,
    activeWorkflowId: "workflow-1",
    isCurrentRevision: revision.isCurrent,
    returnedWorkflow: workflow("workflow-1", "stale-A-attachment"),
    applyWorkflowV2,
    refreshLatestWorkflow: async () => latest,
  });

  assert.equal(reconciled.stale, true);
  assert.equal(reconciled.workflow.slots[0].user_prompt, "linked-B");
  assert.deepEqual(applied.map((entry) => entry.slots[0].user_prompt), ["linked-B"]);
});

test("a reconciliation GET cannot apply after a newer direct workflow application", async () => {
  const hydration = createV2WorkflowHydrationRequestGuard();
  const application = createV2WorkflowApplicationRevisionGuard();
  hydration.activateWorkflow("workflow-1");
  application.activateWorkflow("workflow-1");
  const getC = Promise.withResolvers();
  const applied = [];

  const reconcile = async () => {
    const hydrationToken = hydration.begin("workflow-1");
    const applicationCapture = application.capture("workflow-1");
    await getC.promise;
    if (
      hydration.isCurrent(hydrationToken, "workflow-1") &&
      application.isCurrent(applicationCapture, "workflow-1")
    ) {
      application.appliedWorkflow("workflow-1");
      applied.push("C");
    }
  };
  const requestC = reconcile();
  application.appliedWorkflow("workflow-1");
  applied.push("D");
  getC.resolve();
  await requestC;

  assert.deepEqual(applied, ["D"]);
});

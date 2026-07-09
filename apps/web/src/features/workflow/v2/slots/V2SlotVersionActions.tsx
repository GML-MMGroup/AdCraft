import { useState } from "react";
import { v2Api } from "../../../../api/v2Client.ts";
import type { V2SlotOperationTarget, V2SlotVersionState } from "../operations/v2SlotOperationTypes.ts";

type V2SlotVersionActionsProps = {
  target: V2SlotOperationTarget;
  versionState: V2SlotVersionState;
  onGenerateVersion: () => Promise<void> | void;
  onRefreshSlot: () => Promise<void> | void;
  onRefreshWorkflow: () => Promise<void> | void;
};

export function V2SlotVersionActions({
  target,
  versionState,
  onGenerateVersion,
  onRefreshSlot,
  onRefreshWorkflow,
}: V2SlotVersionActionsProps) {
  const [busyAction, setBusyAction] = useState<"generate" | "use" | "discard" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const qualityBlocksUse = versionState.qualityStatus === "failed";
  const generateLabel = versionState.hasWorkingVersion || versionState.selectedVersionId ? "Generate another version" : "Generate a version";

  async function refreshAfterAction() {
    await onRefreshSlot();
    await onRefreshWorkflow();
  }

  async function applyWorkingVersion() {
    setBusyAction("use");
    setError(null);
    try {
      if (!versionState.workingAssetId || !versionState.workingVersionId) {
        throw new Error("Working version is not ready.");
      }
      await v2Api.selectSlotVersion(target.workflowId, target.slotId, {
        asset_id: versionState.workingAssetId,
        version_id: versionState.workingVersionId,
        source_action: "slot_version_actions",
      });
      await refreshAfterAction();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Slot action failed");
    } finally {
      setBusyAction(null);
    }
  }

  async function generateVersion() {
    setBusyAction("generate");
    setError(null);
    try {
      await onGenerateVersion();
      await refreshAfterAction();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Slot action failed");
    } finally {
      setBusyAction(null);
    }
  }

  async function discardWorkingVersion() {
    setBusyAction("discard");
    setError(null);
    try {
      await v2Api.discardWorkingVersion(target.workflowId, target.slotId);
      await refreshAfterAction();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Slot action failed");
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <div className="v2-slot-version-actions">
      <button type="button" onClick={() => void generateVersion()} disabled={busyAction !== null}>
        {busyAction === "generate" ? "Generating..." : generateLabel}
      </button>
      <button
        type="button"
        onClick={() => void applyWorkingVersion()}
        disabled={busyAction !== null || !versionState.hasWorkingVersion || qualityBlocksUse}
        title={qualityBlocksUse ? "Quality failed. Generate another version or choose history." : undefined}
      >
        {busyAction === "use" ? "Using..." : "Use this version"}
      </button>
      <button
        type="button"
        onClick={() => void discardWorkingVersion()}
        disabled={busyAction !== null || !versionState.hasWorkingVersion}
      >
        {busyAction === "discard" ? "Discarding..." : "Discard working version"}
      </button>
      {versionState.needsUseCurrentVersion ? <span className="v2-slot-version-hint">Working version is not used yet</span> : null}
      {error ? <span className="v2-slot-version-error">{error}</span> : null}
    </div>
  );
}

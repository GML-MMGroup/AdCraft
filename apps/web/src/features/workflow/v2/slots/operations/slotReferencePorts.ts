import type { v2Api } from "../../../../../api/v2Client.ts";
import type {
  WorkflowSlotV2,
  WorkflowV2,
} from "../../../../../types-v2.ts";
import type {
  SlotMicroEditAttachment,
  SlotMicroEditDraft,
} from "../useSlotMicroEdit.ts";
import type { SlotMutationRunner } from "./slotMutationRunner.ts";

export type SlotReferenceApi = Pick<
  typeof v2Api,
  | "attachReference"
  | "attachSlotReference"
  | "registerLibraryReference"
  | "registerReferenceAsset"
  | "removeReference"
  | "selectSlotVersion"
  | "uploadSlotReferenceAsset"
>;

export type SlotReferenceMicroEdit = {
  getDraft: (slotId: string) => SlotMicroEditDraft | undefined;
  addAttachment: (
    slotId: string,
    attachment: SlotMicroEditAttachment,
    trackRevision?: boolean,
  ) => void;
  updateAttachment: (
    slotId: string,
    attachmentId: string,
    patch: Partial<SlotMicroEditAttachment>,
  ) => void;
  removeReference: (
    slotId: string,
    reference:
      | {
          source: "library_entity";
          entity_id: string;
          library_asset_id?: string | null;
          relation_id?: string | null;
        }
      | {
          source: "uploaded_asset" | "reference_asset";
          asset_id: string;
          relation_id?: string | null;
        },
  ) => void;
  setSubmitting: (slotId: string, submitting: boolean, error?: string) => void;
  markClean: (
    slotId: string,
    slot?: WorkflowSlotV2,
    promptPersisted?: boolean,
    referenceBaselineAuthoritative?: boolean,
  ) => void;
};

export type SlotReferenceOperationDependencies = {
  runner: SlotMutationRunner;
  api: SlotReferenceApi;
  getSlot: (slotId: string) => WorkflowSlotV2 | null;
  getWorkflow: () => WorkflowV2 | null | undefined;
  microEdit: SlotReferenceMicroEdit;
  loadSlotVersions: (slotId: string) => Promise<unknown>;
  setStatus: (status: string) => void;
};

export type SlotReferencePorts<
  ApiKeys extends keyof SlotReferenceApi,
  MicroEditKeys extends keyof SlotReferenceMicroEdit,
> = {
  runner: SlotMutationRunner;
  api: Pick<SlotReferenceApi, ApiKeys>;
  microEdit: Pick<SlotReferenceMicroEdit, MicroEditKeys>;
};

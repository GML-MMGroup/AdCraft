import type {
  WorkflowPageAssetActionControllersArgs,
  WorkflowPageCanvasAssemblyArgs,
  WorkflowPageCopilotAssemblyArgs,
  WorkflowPageFloatingEditorsArgs,
  WorkflowPageOverlaysArgs,
  WorkflowPageRunGraphControllersArgs,
  WorkflowPageRuntimeControllersArgs,
  WorkflowPageSidePanelsAssemblyArgs,
  WorkflowPageSurfaceAssemblyArgs,
  WorkflowPageToolbarAssemblyArgs,
} from "./workflowPageContracts.ts";

type IsAny<T> = 0 extends (1 & T) ? true : false;
type HasOpenStringIndex<T> = string extends keyof T ? true : false;
type AssertFalse<T extends false> = T;

export type WorkflowPageContractAssertions = [
  AssertFalse<IsAny<WorkflowPageRuntimeControllersArgs>>,
  AssertFalse<IsAny<WorkflowPageRunGraphControllersArgs>>,
  AssertFalse<IsAny<WorkflowPageAssetActionControllersArgs>>,
  AssertFalse<IsAny<WorkflowPageSurfaceAssemblyArgs>>,
  AssertFalse<HasOpenStringIndex<WorkflowPageRuntimeControllersArgs>>,
  AssertFalse<HasOpenStringIndex<WorkflowPageRunGraphControllersArgs>>,
  AssertFalse<HasOpenStringIndex<WorkflowPageAssetActionControllersArgs>>,
  AssertFalse<HasOpenStringIndex<WorkflowPageSurfaceAssemblyArgs>>,
  AssertFalse<IsAny<WorkflowPageCanvasAssemblyArgs>>,
  AssertFalse<IsAny<WorkflowPageCopilotAssemblyArgs>>,
  AssertFalse<IsAny<WorkflowPageSidePanelsAssemblyArgs>>,
  AssertFalse<IsAny<WorkflowPageFloatingEditorsArgs>>,
  AssertFalse<IsAny<WorkflowPageOverlaysArgs>>,
  AssertFalse<IsAny<WorkflowPageToolbarAssemblyArgs>>,
  AssertFalse<HasOpenStringIndex<WorkflowPageCanvasAssemblyArgs>>,
  AssertFalse<HasOpenStringIndex<WorkflowPageCopilotAssemblyArgs>>,
  AssertFalse<HasOpenStringIndex<WorkflowPageSidePanelsAssemblyArgs>>,
  AssertFalse<HasOpenStringIndex<WorkflowPageFloatingEditorsArgs>>,
  AssertFalse<HasOpenStringIndex<WorkflowPageOverlaysArgs>>,
  AssertFalse<HasOpenStringIndex<WorkflowPageToolbarAssemblyArgs>>,
];

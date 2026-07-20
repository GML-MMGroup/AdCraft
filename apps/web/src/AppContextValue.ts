import { createContext, useContext, type Dispatch, type SetStateAction } from "react";
import type {
  DemoProjectRecord,
  ProjectSessionState,
  SavedWorkflowProject,
  TrashedProjectRecord,
} from "./projects/newProject";
import type {
  AssetLibraryEntitySummary,
  AssetUploadOptions,
  FrontDeskMessage,
  NodeCatalogItem,
  NodeRunResult,
  UploadedAsset,
  WorkflowGraph,
} from "./types";

export interface AppContextValue {
  apiOnline: boolean | null;
  apiMessage: string;
  assets: UploadedAsset[];
  selectedAssets: UploadedAsset[];
  promptLibraryEntities: AssetLibraryEntitySummary[];
  messages: FrontDeskMessage[];
  workflow: WorkflowGraph | null;
  nodeCatalog: NodeCatalogItem[];
  nodeRuns: NodeRunResult[];
  savedProjects: SavedWorkflowProject[];
  trashedProjects: TrashedProjectRecord[];
  demoProjectFavorites: Record<string, boolean>;
  activeProjectId: string | null;
  workspaceHydrated: boolean;
  workspaceRestoreError: string | null;
  storageWarning: string | null;
  busy: boolean;
  setMessages: Dispatch<SetStateAction<FrontDeskMessage[]>>;
  setPromptLibraryEntities: Dispatch<SetStateAction<AssetLibraryEntitySummary[]>>;
  setWorkflow: Dispatch<SetStateAction<WorkflowGraph | null>>;
  saveProject: (state?: ProjectSessionState) => SavedWorkflowProject | null;
  startNewProject: () => void;
  openProject: (projectId: string) => Promise<boolean>;
  moveProjectToTrash: (project: DemoProjectRecord & { source: "saved" | "demo" }) => TrashedProjectRecord | null;
  deleteTrashedProject: (projectId: string) => boolean;
  toggleProjectFavorite: (project: DemoProjectRecord & { source: "saved" | "demo" }) => boolean | null;
  toggleAssetSelection: (asset: UploadedAsset) => void;
  refreshAssets: () => Promise<void>;
  refreshNodeCatalog: () => Promise<void>;
  refreshWorkflowNodes: (workflowId?: string) => Promise<void>;
  uploadAsset: (file: File, options?: AssetUploadOptions) => Promise<UploadedAsset>;
}

export const AppContext = createContext<AppContextValue | null>(null);

export function useApp() {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error("useApp must be used within AppProvider");
  }
  return context;
}

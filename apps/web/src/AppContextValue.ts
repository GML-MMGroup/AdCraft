import { createContext, useContext, type Dispatch, type SetStateAction } from "react";
import type {
  ProjectSessionState,
  SavedWorkflowProject,
} from "./projects/newProject";
import type { AgentCanvasWorkflowV2, ProjectV2Summary } from "./types-v2";
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
  assets: UploadedAsset[];
  selectedAssets: UploadedAsset[];
  promptLibraryEntities: AssetLibraryEntitySummary[];
  messages: FrontDeskMessage[];
  workflow: WorkflowGraph | null;
  agentCanvasWorkflow: AgentCanvasWorkflowV2 | null;
  nodeCatalog: NodeCatalogItem[];
  nodeRuns: NodeRunResult[];
  savedProjects: ProjectV2Summary[];
  trashedProjects: ProjectV2Summary[];
  demoProjectFavorites: Record<string, boolean>;
  activeProjectId: string | null;
  workspaceHydrated: boolean;
  workspaceRestoreError: string | null;
  projectCatalogRefreshing: boolean;
  projectCatalogError: string | null;
  busy: boolean;
  setMessages: Dispatch<SetStateAction<FrontDeskMessage[]>>;
  setPromptLibraryEntities: Dispatch<SetStateAction<AssetLibraryEntitySummary[]>>;
  setWorkflow: Dispatch<SetStateAction<WorkflowGraph | null>>;
  setAgentCanvasWorkflow: Dispatch<SetStateAction<AgentCanvasWorkflowV2 | null>>;
  saveProject: (state?: ProjectSessionState) => SavedWorkflowProject | null;
  startNewProject: () => Promise<boolean>;
  openProject: (projectId: string, workflowId?: string) => Promise<boolean>;
  moveProjectToTrash: (projectId: string) => Promise<boolean>;
  restoreTrashedProject: (projectId: string) => Promise<boolean>;
  renameProject: (projectId: string, name: string) => Promise<boolean>;
  toggleProjectFavorite: (project: ProjectV2Summary) => Promise<boolean>;
  toggleAssetSelection: (asset: UploadedAsset) => void;
  refreshAssets: () => Promise<void>;
  refreshNodeCatalog: () => Promise<void>;
  refreshWorkflowNodes: (workflowId?: string) => Promise<void>;
  refreshProjects: () => Promise<boolean>;
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

import type { ReactNode } from "react";
import type { DraggablePanelKey, PanelOffset } from "../../../components/WorkflowDraggablePanel";

export type WorkflowPageUiChrome = {
  collapsed: boolean;
  status: string;
  detailsOpen: boolean;
  runPanelOpen: boolean;
  variablesPanelOpen: boolean;
};

export type WorkflowPageViewModel = {
  chrome: WorkflowPageUiChrome;
  canvas: ReactNode;
  copilot: ReactNode;
  panels: ReactNode;
  modals: ReactNode;
};

export type WorkflowPageActions = {
  toggleCollapsed: () => void;
  setDetailsOpen: (open: boolean) => void;
  setRunPanelOpen: (open: boolean) => void;
  setVariablesPanelOpen: (open: boolean) => void;
};

export type WorkflowPageViewProps = {
  model: WorkflowPageViewModel;
  actions: WorkflowPageActions;
};

export type MediaLightboxState = {
  type: "image" | "video";
  src: string;
  poster?: string;
  title: string;
};

export type WorkflowPageUiState = {
  collapsed: boolean;
  detailsOpen: boolean;
  adPanelOpen: boolean;
  videoPanelOpen: boolean;
  runPanelOpen: boolean;
  variablesPanelOpen: boolean;
  mediaLightbox: MediaLightboxState | null;
  panelOffsets: Record<DraggablePanelKey, PanelOffset>;
};

export type WorkflowPageUiActions = {
  setCollapsed: (value: boolean | ((current: boolean) => boolean)) => void;
  setDetailsOpen: (value: boolean) => void;
  setAdPanelOpen: (value: boolean) => void;
  setVideoPanelOpen: (value: boolean) => void;
  setRunPanelOpen: (value: boolean | ((current: boolean) => boolean)) => void;
  setVariablesPanelOpen: (value: boolean) => void;
  setMediaLightbox: (asset: MediaLightboxState | null) => void;
  commitPanelOffset: (panelKey: DraggablePanelKey, offset: PanelOffset) => void;
};

export type WorkflowPageUiStateController = {
  state: WorkflowPageUiState;
  actions: WorkflowPageUiActions;
};

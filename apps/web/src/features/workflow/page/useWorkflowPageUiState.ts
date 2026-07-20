import { useCallback, useMemo, useState } from "react";
import type { DraggablePanelKey, PanelOffset } from "../../../components/WorkflowDraggablePanel";
import type { MediaLightboxState, WorkflowPageUiStateController } from "./workflowPageTypes";

const initialPanelOffsets: Record<DraggablePanelKey, PanelOffset> = {
  run: { x: 0, y: 0 },
  detail: { x: 0, y: 0 },
  "v2-slot-composer": { x: 0, y: 0 },
  "v2-storyboard-prompt-composer": { x: 0, y: 0 },
};

export function useWorkflowPageUiState(): WorkflowPageUiStateController {
  const [collapsed, setCollapsed] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [adPanelOpen, setAdPanelOpen] = useState(false);
  const [videoPanelOpen, setVideoPanelOpen] = useState(false);
  const [runPanelOpen, setRunPanelOpen] = useState(true);
  const [variablesPanelOpen, setVariablesPanelOpen] = useState(false);
  const [mediaLightbox, setMediaLightbox] = useState<MediaLightboxState | null>(null);
  const [panelOffsets, setPanelOffsets] = useState(initialPanelOffsets);

  const commitPanelOffset = useCallback((panelKey: DraggablePanelKey, offset: PanelOffset) => {
    setPanelOffsets((current) => {
      const currentOffset = current[panelKey];
      if (currentOffset.x === offset.x && currentOffset.y === offset.y) return current;
      return { ...current, [panelKey]: offset };
    });
  }, []);

  return useMemo(
    () => ({
      state: {
        collapsed,
        detailsOpen,
        adPanelOpen,
        videoPanelOpen,
        runPanelOpen,
        variablesPanelOpen,
        mediaLightbox,
        panelOffsets,
      },
      actions: {
        setCollapsed,
        setDetailsOpen,
        setAdPanelOpen,
        setVideoPanelOpen,
        setRunPanelOpen,
        setVariablesPanelOpen,
        setMediaLightbox,
        commitPanelOffset,
      },
    }),
    [
      collapsed,
      detailsOpen,
      adPanelOpen,
      videoPanelOpen,
      runPanelOpen,
      variablesPanelOpen,
      mediaLightbox,
      panelOffsets,
      commitPanelOffset,
    ],
  );
}

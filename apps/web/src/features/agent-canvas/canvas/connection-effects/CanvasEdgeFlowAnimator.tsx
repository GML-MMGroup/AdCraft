import { useStore } from "@xyflow/react";
import { useEffect, useRef } from "react";

import { createEdgeFlowController } from "./edgeFlowController.ts";

export function CanvasEdgeFlowAnimator() {
  const root = useStore((state) => state.domNode);
  const zoom = useStore((state) => state.transform[2]);
  const controller = useRef<ReturnType<typeof createEdgeFlowController> | null>(null);

  useEffect(() => {
    if (!root) return;
    const instance = createEdgeFlowController(root, 1);
    controller.current = instance;
    return () => { instance.dispose(); controller.current = null; };
  }, [root]);

  useEffect(() => { controller.current?.setZoom(zoom); }, [root, zoom]);
  return null;
}

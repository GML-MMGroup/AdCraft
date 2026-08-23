import type { ReactNode } from "react";

import {
  EditIcon,
  ImageIcon,
  MuteIcon,
  VideoIcon,
} from "../../../icons.tsx";
import type { CanvasNodeTypeV2 } from "../../../types-v2.ts";

export function AgentCanvasNodeIcon({ nodeType }: { nodeType: CanvasNodeTypeV2 }): ReactNode {
  if (nodeType === "image") return <ImageIcon aria-hidden="true" />;
  if (nodeType === "video" || nodeType === "editing") return <VideoIcon aria-hidden="true" />;
  if (nodeType === "audio") return <MuteIcon aria-hidden="true" />;
  return <EditIcon aria-hidden="true" />;
}

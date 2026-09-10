import { createRoot } from "react-dom/client";
import { AgentRoleAnimation } from "../../src/features/agent-canvas/chat/agent-role-animation/AgentRoleAnimation.tsx";
import "../../src/features/agent-canvas/chat/agent-canvas-chat.css";

createRoot(document.getElementById("root")!).render(
  <main className="agent-chat" style={{ background: "#101723", padding: 20 }}>
    <AgentRoleAnimation capabilityId="scene_design" motionState="idle" />
  </main>,
);

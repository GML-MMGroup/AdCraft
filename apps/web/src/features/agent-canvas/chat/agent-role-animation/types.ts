import type { AgentCanvasChatTurnV2 } from "../../../../types-v2.ts";
import type { StageThreadStatus } from "../stageThreadProjection.ts";

// Two visual states only: a role is either static (idle) or playing its
// animated artwork (working) from the moment it starts until the next role
// takes over.
export type AgentRoleMotionState = "idle" | "working";

export interface AgentRoleMotionTrack {
  part: string;
  keyframes: Keyframe[];
  options: KeyframeAnimationOptions;
}

export interface AgentRoleMotionProgram {
  workingEntryTimeMs: number;
  workingTransitionDurationMs?: number;
  /** Optional finite first pass; its final visible pose must match working at time zero. */
  workingIntro?: AgentRoleMotionTrack[];
  working: AgentRoleMotionTrack[];
}

export interface AgentRoleMotionController {
  playWorking(): void;
  settle(): Promise<void>;
  pause(): void;
  resume(): void;
  dispose(): void;
}

export interface ResolveAgentRoleMotionStateInput {
  status: StageThreadStatus | "queued";
  turnId: string;
  turn?: AgentCanvasChatTurnV2 | null;
}

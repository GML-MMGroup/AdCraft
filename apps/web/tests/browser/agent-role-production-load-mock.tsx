import {
  Background,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
  type ReactFlowInstance,
} from "@xyflow/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";

import type {
  AgentCanvasWorkflowV2,
  AgentCapabilityIdV2,
  CanvasNodeV2,
  CanvasRuntimeEventV2,
} from "../../src/types-v2.ts";
import { AgentCanvasChatPanel } from "../../src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx";
import "../../src/styles/base.css";
import "../../src/styles/theme.css";
import "@xyflow/react/dist/style.css";

type HarnessPhase = "idle" | "waiting" | "working";

interface ResourceSnapshot {
  activeAnimationFrames: number;
  activeIntervals: number;
  activeListeners: number;
  activeTimeouts: number;
  listenersByType: Record<string, number>;
}

interface MotionSnapshot {
  activeRoleRootCount: number;
  activeRoleSlugs: string[];
  loopAnimationCount: number;
  maximumLongRunOpacityDelta: number;
  maximumLongRunPoseDeltaFinalPx: number;
  maximumSeamOpacityDelta: number;
  maximumSeamOpacityVelocityMismatch: number;
  maximumSeamPoseDeltaFinalPx: number;
  maximumSeamVelocityMismatchFinalPx: number;
  roleAnimationCount: number;
  seamDirectionReversalCount: number;
  seamStationaryHoldMismatchCount: number;
  totalAnimationCount: number;
}

interface InteractionSample {
  canvasChanged: boolean;
  chatScrolled: boolean;
  durationMs: number;
}

interface HarnessSnapshot {
  cycle: number;
  phase: HarnessPhase;
  role: string;
}

interface MonitorSnapshot {
  maximumActiveRoleRoots: number;
  violations: string[];
}

interface InstrumentedWindow extends Window {
  agentRoleAcceptanceResources?: { snapshot(): ResourceSnapshot };
}

const WORKFLOW_ID = "workflow-role-acceptance";
const TIMESTAMP = "2026-09-03T12:00:00Z";
const ROLE_DEFINITIONS: ReadonlyArray<{
  capabilityId: AgentCapabilityIdV2;
  displayName: string;
}> = [
  { capabilityId: "world_setting", displayName: "World Setting" },
  { capabilityId: "product_design", displayName: "Product Designer" },
  { capabilityId: "prop_design", displayName: "Prop Designer" },
  { capabilityId: "character_design", displayName: "Character Designer" },
  { capabilityId: "scene_design", displayName: "Scene Designer" },
  { capabilityId: "script_authoring", displayName: "Script Writer" },
  { capabilityId: "storyboard_design", displayName: "Storyboard Artist" },
  { capabilityId: "video_direction", displayName: "Video Director" },
  { capabilityId: "bgm_direction", displayName: "BGM Director" },
  { capabilityId: "quick_media", displayName: "Quick Media" },
];

function canvasNodes(): Node[] {
  return Array.from({ length: 54 }, (_, index) => ({
    id: `canvas-node-${index + 1}`,
    position: {
      x: (index % 9) * 210,
      y: Math.floor(index / 9) * 130,
    },
    data: { label: `Production node ${index + 1}` },
  }));
}

function canvasEdges(): Edge[] {
  return Array.from({ length: 53 }, (_, index) => ({
    id: `canvas-edge-${index + 1}`,
    source: `canvas-node-${index + 1}`,
    target: `canvas-node-${index + 2}`,
  }));
}

function workflowNode(index: number): CanvasNodeV2 {
  const nodeType: CanvasNodeV2["node_type"] = index % 5 === 0
    ? "audio"
    : index % 3 === 0
      ? "video"
      : "image";
  return {
    node_id: `canvas-node-${index + 1}`,
    workflow_id: WORKFLOW_ID,
    node_type: nodeType,
    creative_role: nodeType === "audio" ? "bgm" : nodeType === "video" ? "general_video" : "general_image",
    role_contract_version: "ad-media-role-v2",
    title: `Production node ${index + 1}`,
    status: index % 7 === 0 ? "working" : "ready",
    execution_mode: "generative",
    summary_prompt: null,
    generation_prompt: "Representative local production prompt",
    structured_content: {},
    model_id: null,
    model_selection_mode: "default",
    model_ref: null,
    model_summary: null,
    parameters: {},
    metadata: {},
    parameter_provenance: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    output_asset_version_id: null,
    latest_attempt: null,
    position: { x: (index % 9) * 210, y: Math.floor(index / 9) * 130 },
    revision: 1,
    error: null,
    prompt_preparation: null,
    prompt_presentation: null,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
  };
}

const WORKFLOW = {
  workflow_id: WORKFLOW_ID,
  project_id: "project-role-acceptance",
  workflow_schema_version: 2,
  canvas_model: "agent_canvas_v1",
  revision: 1,
  layout_revision: 1,
  nodes: Array.from({ length: 54 }, (_, index) => workflowNode(index)),
  bindings: [],
  assets: [],
  active_style_skill: null,
} as AgentCanvasWorkflowV2;
const FLOW_NODES = canvasNodes();
const FLOW_EDGES = canvasEdges();

function event(
  seq: number,
  eventType: string,
  turnId: string,
  payload: Record<string, unknown>,
): CanvasRuntimeEventV2 {
  return {
    seq,
    workflow_id: WORKFLOW_ID,
    event_type: eventType,
    project_id: "project-role-acceptance",
    execution_id: null,
    node_id: null,
    asset_id: null,
    binding_id: null,
    conversation_id: "conversation-role-acceptance",
    turn_id: turnId,
    action_id: null,
    trace_id: null,
    span_id: null,
    created_at: TIMESTAMP,
    payload,
  };
}

function scenarioEvents(cycle: number, phase: HarnessPhase): CanvasRuntimeEventV2[] {
  const current = ROLE_DEFINITIONS[cycle % ROLE_DEFINITIONS.length]!;
  const history = ROLE_DEFINITIONS
    .filter(({ capabilityId }) => capabilityId !== current.capabilityId)
    .flatMap((role, index) => {
      const turnId = `turn-history-${role.capabilityId}`;
      const common = {
        activity_id: `activity-history-${role.capabilityId}`,
        turn_id: turnId,
        capability_id: role.capabilityId,
        capability_display_name: role.displayName,
      };
      return [
        event(index * 2 + 1, "expert_activity_started", turnId, common),
        event(index * 2 + 2, "expert_activity_completed", turnId, common),
      ];
    });
  const turnId = `turn-active-${cycle}`;
  const activity = {
    activity_id: `activity-active-${cycle}`,
    turn_id: turnId,
    capability_id: current.capabilityId,
    capability_display_name: current.displayName,
  };
  const active = [
    event(1_000 + cycle * 10, "expert_activity_started", turnId, activity),
    event(1_001 + cycle * 10, "agent_turn_started", turnId, { turn_id: turnId }),
  ];
  if (phase === "waiting" || phase === "idle") {
    active.push(event(1_002 + cycle * 10, "agent_turn_waiting", turnId, { turn_id: turnId }));
  }
  if (phase === "idle") {
    active.push(
      event(1_003 + cycle * 10, "expert_activity_completed", turnId, activity),
      event(1_004 + cycle * 10, "agent_turn_completed", turnId, { turn_id: turnId }),
      event(1_005 + cycle * 10, "continuation_completed", turnId, { turn_id: turnId }),
    );
  }
  return [...history, ...active];
}

function activeRoleRoots(): SVGSVGElement[] {
  return [...document.querySelectorAll<SVGSVGElement>("svg[data-agent-role]")]
    .filter((root) => root.getAnimations({ subtree: true }).length > 0);
}

function styleVector(target: Element): number[] {
  const style = getComputedStyle(target);
  const matrix = new DOMMatrixReadOnly(style.transform === "none" ? undefined : style.transform);
  return [matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f, Number(style.opacity)];
}

interface LoopSeamMeasurements {
  maximumLongRunOpacityDelta: number;
  maximumLongRunPoseDeltaFinalPx: number;
  maximumSeamOpacityDelta: number;
  maximumSeamOpacityVelocityMismatch: number;
  maximumSeamPoseDeltaFinalPx: number;
  maximumSeamVelocityMismatchFinalPx: number;
  seamDirectionReversalCount: number;
  seamStationaryHoldMismatchCount: number;
}

const EMPTY_LOOP_SEAM_MEASUREMENTS: LoopSeamMeasurements = {
  maximumLongRunOpacityDelta: 0,
  maximumLongRunPoseDeltaFinalPx: 0,
  maximumSeamOpacityDelta: 0,
  maximumSeamOpacityVelocityMismatch: 0,
  maximumSeamPoseDeltaFinalPx: 0,
  maximumSeamVelocityMismatchFinalPx: 0,
  seamDirectionReversalCount: 0,
  seamStationaryHoldMismatchCount: 0,
};
const MOVING_POSE_STEP_FINAL_PX = 0.01;
const MOVING_OPACITY_STEP = 0.005;

function subtractVector(to: number[], from: number[]): number[] {
  return to.map((value, index) => value - from[index]!);
}

function maximumTransformMagnitudeFinalPx(vector: number[], root: SVGSVGElement): number {
  const renderedWidth = root.getBoundingClientRect().width;
  const viewBoxWidth = root.viewBox.baseVal.width;
  const svgUnitToFinalPx = viewBoxWidth > 0 ? renderedWidth / viewBoxWidth : 0;
  const renderedRadius = renderedWidth / 2;
  return Math.max(
    ...vector.slice(0, 4).map((value) => Math.abs(value) * renderedRadius),
    ...vector.slice(4, 6).map((value) => Math.abs(value) * svgUnitToFinalPx),
  );
}

function transformDirectionReverses(
  incoming: number[],
  outgoing: number[],
  root: SVGSVGElement,
): boolean {
  const renderedWidth = root.getBoundingClientRect().width;
  const viewBoxWidth = root.viewBox.baseVal.width;
  const svgUnitToFinalPx = viewBoxWidth > 0 ? renderedWidth / viewBoxWidth : 0;
  const renderedRadius = renderedWidth / 2;
  const scale = (vector: number[]) => vector.slice(0, 6).map((value, index) => (
    value * (index < 4 ? renderedRadius : svgUnitToFinalPx)
  ));
  const scaledIncoming = scale(incoming);
  const scaledOutgoing = scale(outgoing);
  if (
    Math.max(...scaledIncoming.map(Math.abs)) <= MOVING_POSE_STEP_FINAL_PX
    || Math.max(...scaledOutgoing.map(Math.abs)) <= MOVING_POSE_STEP_FINAL_PX
  ) return false;
  return scaledIncoming.reduce((dot, value, index) => (
    dot + value * scaledOutgoing[index]!
  ), 0) < 0;
}

function loopSeams(root: SVGSVGElement): LoopSeamMeasurements {
  const measurements = { ...EMPTY_LOOP_SEAM_MEASUREMENTS };
  const loops = root.getAnimations({ subtree: true }).filter((animation) => (
    animation.effect?.getTiming().iterations === Infinity
  ));
  for (const animation of loops) {
    const effect = animation.effect as KeyframeEffect | null;
    const target = effect?.target;
    const duration = Number(effect?.getTiming().duration);
    if (!(target instanceof Element) || !Number.isFinite(duration) || duration <= 0) continue;
    const originalTime = animation.currentTime;
    const originalPlayState = animation.playState;
    const epsilonMs = Math.min(16, duration / 100);
    animation.pause();
    animation.currentTime = duration - 2 * epsilonMs;
    const beforeFar = styleVector(target);
    animation.currentTime = duration - epsilonMs;
    const beforeNear = styleVector(target);
    animation.currentTime = 0;
    const start = styleVector(target);
    animation.currentTime = epsilonMs;
    const afterNear = styleVector(target);
    animation.currentTime = duration * 0.37;
    const nearPhase = styleVector(target);
    animation.currentTime = duration * 1_000 + duration * 0.37;
    const distantPhase = styleVector(target);
    const incoming = subtractVector(beforeNear, beforeFar);
    const outgoing = subtractVector(afterNear, start);
    const velocityMismatch = subtractVector(incoming, outgoing);
    measurements.maximumSeamPoseDeltaFinalPx = Math.max(
      measurements.maximumSeamPoseDeltaFinalPx,
      maximumTransformMagnitudeFinalPx(subtractVector(start, beforeNear), root),
      maximumTransformMagnitudeFinalPx(subtractVector(afterNear, start), root),
    );
    measurements.maximumSeamVelocityMismatchFinalPx = Math.max(
      measurements.maximumSeamVelocityMismatchFinalPx,
      maximumTransformMagnitudeFinalPx(velocityMismatch, root),
    );
    measurements.maximumSeamOpacityDelta = Math.max(
      measurements.maximumSeamOpacityDelta,
      Math.abs(start[6]! - beforeNear[6]!),
      Math.abs(afterNear[6]! - start[6]!),
    );
    measurements.maximumSeamOpacityVelocityMismatch = Math.max(
      measurements.maximumSeamOpacityVelocityMismatch,
      Math.abs(incoming[6]! - outgoing[6]!),
    );
    const opacityDirectionReverses = Math.abs(incoming[6]!) > MOVING_OPACITY_STEP
      && Math.abs(outgoing[6]!) > MOVING_OPACITY_STEP
      && incoming[6]! * outgoing[6]! < 0;
    const transformStationaryHoldMismatch = (
      maximumTransformMagnitudeFinalPx(incoming, root) > MOVING_POSE_STEP_FINAL_PX
    ) !== (
      maximumTransformMagnitudeFinalPx(outgoing, root) > MOVING_POSE_STEP_FINAL_PX
    );
    const opacityStationaryHoldMismatch = (Math.abs(incoming[6]!) > MOVING_OPACITY_STEP)
      !== (Math.abs(outgoing[6]!) > MOVING_OPACITY_STEP);
    if (transformDirectionReverses(incoming, outgoing, root) || opacityDirectionReverses) {
      measurements.seamDirectionReversalCount += 1;
    }
    if (transformStationaryHoldMismatch || opacityStationaryHoldMismatch) {
      measurements.seamStationaryHoldMismatchCount += 1;
    }
    measurements.maximumLongRunPoseDeltaFinalPx = Math.max(
      measurements.maximumLongRunPoseDeltaFinalPx,
      maximumTransformMagnitudeFinalPx(subtractVector(distantPhase, nearPhase), root),
    );
    measurements.maximumLongRunOpacityDelta = Math.max(
      measurements.maximumLongRunOpacityDelta,
      Math.abs(distantPhase[6]! - nearPhase[6]!),
    );
    animation.currentTime = originalTime;
    if (originalPlayState === "running") animation.play();
  }
  return measurements;
}

function createSeamMutation(root: SVGSVGElement): Animation | null {
  const mutation = new URLSearchParams(window.location.search).get("mutation");
  const target = root.querySelector<SVGGraphicsElement>('[data-part="base"]');
  if (!target) return null;
  if (mutation === "seam-jump") {
    return target.animate([
      { transform: "translateX(0px)" },
      { transform: "translateX(100px)" },
    ], { duration: 1_000, easing: "linear", iterations: Infinity });
  }
  if (mutation === "seam-velocity") {
    return target.animate([
      { offset: 0, transform: "translateX(0px)" },
      { offset: 0.5, transform: "translateX(40px)" },
      { offset: 1, transform: "translateX(0px)" },
    ], { duration: 1_000, easing: "linear", iterations: Infinity });
  }
  return null;
}

function motionSnapshot(): MotionSnapshot {
  const roots = activeRoleRoots();
  const mutationAnimation = roots[0] ? createSeamMutation(roots[0]) : null;
  try {
    const roleAnimations = roots.flatMap((root) => root.getAnimations({ subtree: true }));
    const loopAnimationCount = roleAnimations.filter((animation) => (
      animation.effect?.getTiming().iterations === Infinity
    )).length;
    const seams = roots.reduce((maximum, root) => {
      const current = loopSeams(root);
      return {
        maximumLongRunOpacityDelta: Math.max(
          maximum.maximumLongRunOpacityDelta,
          current.maximumLongRunOpacityDelta,
        ),
        maximumLongRunPoseDeltaFinalPx: Math.max(
          maximum.maximumLongRunPoseDeltaFinalPx,
          current.maximumLongRunPoseDeltaFinalPx,
        ),
        maximumSeamOpacityDelta: Math.max(
          maximum.maximumSeamOpacityDelta,
          current.maximumSeamOpacityDelta,
        ),
        maximumSeamOpacityVelocityMismatch: Math.max(
          maximum.maximumSeamOpacityVelocityMismatch,
          current.maximumSeamOpacityVelocityMismatch,
        ),
        maximumSeamPoseDeltaFinalPx: Math.max(
          maximum.maximumSeamPoseDeltaFinalPx,
          current.maximumSeamPoseDeltaFinalPx,
        ),
        maximumSeamVelocityMismatchFinalPx: Math.max(
          maximum.maximumSeamVelocityMismatchFinalPx,
          current.maximumSeamVelocityMismatchFinalPx,
        ),
        seamDirectionReversalCount: maximum.seamDirectionReversalCount
          + current.seamDirectionReversalCount,
        seamStationaryHoldMismatchCount: maximum.seamStationaryHoldMismatchCount
          + current.seamStationaryHoldMismatchCount,
      };
    }, { ...EMPTY_LOOP_SEAM_MEASUREMENTS });
    return {
      activeRoleRootCount: roots.length,
      activeRoleSlugs: roots.map((root) => root.dataset.agentRole ?? "unknown"),
      loopAnimationCount,
      roleAnimationCount: roleAnimations.length,
      totalAnimationCount: document.getAnimations().length,
      ...seams,
    };
  } finally {
    mutationAnimation?.cancel();
  }
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

let advanceHarness: () => void = () => {
  throw new Error("Acceptance harness is not ready");
};
let exerciseHarnessInteractions = async (): Promise<InteractionSample> => {
  throw new Error("Acceptance harness is not ready");
};
let harnessSnapshot: HarnessSnapshot = { cycle: 0, phase: "working", role: "" };
let flowReady = false;
let maximumActiveRoleRoots = 0;
const monitorViolations: string[] = [];

function AcceptanceHarness() {
  const [step, setStep] = useState(0);
  const flowRef = useRef<ReactFlowInstance<Node, Edge> | null>(null);
  const zoomInRef = useRef(true);
  const phase: HarnessPhase = step % 3 === 0 ? "working" : step % 3 === 1 ? "waiting" : "idle";
  const cycle = Math.floor(step / 3);
  const role = ROLE_DEFINITIONS[cycle % ROLE_DEFINITIONS.length]!;
  const events = useMemo(() => scenarioEvents(cycle, phase), [cycle, phase]);
  const mutation = new URLSearchParams(window.location.search).get("mutation");

  harnessSnapshot = { cycle, phase, role: role.capabilityId };
  advanceHarness = () => setStep((current) => current + 1);
  exerciseHarnessInteractions = async () => {
    const flow = flowRef.current;
    const timeline = document.querySelector<HTMLElement>(".agent-chat__timeline");
    const viewport = document.querySelector<HTMLElement>(".react-flow__viewport");
    if (!flow || !timeline || !viewport) throw new Error("Production surfaces are not mounted");
    const started = performance.now();
    const beforeTransform = getComputedStyle(viewport).transform;
    const beforeScroll = timeline.scrollTop;
    const selector = zoomInRef.current
      ? ".react-flow__controls-zoomin"
      : ".react-flow__controls-zoomout";
    const control = document.querySelector<HTMLButtonElement>(selector);
    if (!control) throw new Error(`Missing React Flow control ${selector}`);
    control.click();
    zoomInRef.current = !zoomInRef.current;
    await nextFrame();
    const currentViewport = flow.getViewport();
    await flow.setViewport({
      ...currentViewport,
      x: currentViewport.x + (zoomInRef.current ? -7 : 7),
      y: currentViewport.y + (zoomInRef.current ? 5 : -5),
    }, { duration: 0 });
    const maximumScroll = timeline.scrollHeight - timeline.clientHeight;
    timeline.scrollTop = beforeScroll > maximumScroll / 2 ? 0 : maximumScroll;
    timeline.dispatchEvent(new Event("scroll", { bubbles: true }));
    await nextFrame();
    return {
      canvasChanged: getComputedStyle(viewport).transform !== beforeTransform,
      chatScrolled: timeline.scrollTop !== beforeScroll,
      durationMs: performance.now() - started,
    };
  };

  useEffect(() => {
    let frame = 0;
    const inspect = () => {
      const roots = activeRoleRoots();
      maximumActiveRoleRoots = Math.max(maximumActiveRoleRoots, roots.length);
      if (roots.length > 1) {
        monitorViolations.push(
          `cycle=${harnessSnapshot.cycle} phase=${harnessSnapshot.phase} activeRoots=${roots.length}`,
        );
      }
      frame = requestAnimationFrame(inspect);
    };
    frame = requestAnimationFrame(inspect);
    return () => cancelAnimationFrame(frame);
  }, []);

  const panel = (
    <AgentCanvasChatPanel
      workflow={WORKFLOW}
      chatRevision={0}
      chatEvents={events}
      onFocusNode={() => undefined}
      onWorkflowRefresh={() => undefined}
      onRuntimeRefresh={() => undefined}
      onAssetsRefresh={() => undefined}
    />
  );

  return (
    <main className="role-acceptance">
      <section className="role-acceptance__canvas" aria-label="Representative Workflow canvas">
        <ReactFlow
          nodes={FLOW_NODES}
          edges={FLOW_EDGES}
          minZoom={0.2}
          maxZoom={2}
          fitView
          onInit={(flow) => {
            flowRef.current = flow;
            flowReady = true;
          }}
        >
          <Background />
          <Controls />
        </ReactFlow>
      </section>
      {panel}
      {mutation === "dual-active" ? (
        <div className="role-acceptance__mutant-panel" aria-hidden="true">{panel}</div>
      ) : null}
    </main>
  );
}

Object.assign(window, {
  agentRoleAcceptanceProbe: {
    advance: () => advanceHarness(),
    exerciseInteractions: () => exerciseHarnessInteractions(),
    isReady: () => {
      const timeline = document.querySelector<HTMLElement>(".agent-chat__timeline");
      return flowReady
        && timeline !== null
        && timeline.scrollHeight > timeline.clientHeight;
    },
    monitorSnapshot: (): MonitorSnapshot => ({
      maximumActiveRoleRoots,
      violations: [...monitorViolations],
    }),
    motionSnapshot,
    resourceSnapshot: (): ResourceSnapshot => {
      const resources = (window as InstrumentedWindow).agentRoleAcceptanceResources;
      if (!resources) throw new Error("Resource instrumentation is not installed");
      return resources.snapshot();
    },
    snapshot: (): HarnessSnapshot => ({ ...harnessSnapshot }),
  },
});

const style = document.createElement("style");
style.textContent = `
  html, body, #root { width: 100%; height: 100%; margin: 0; overflow: hidden; }
  body { background: #0a0a0a; color: #f5f5f5; }
  .role-acceptance { position: relative; width: 100%; height: 100%; }
  .role-acceptance__canvas { position: absolute; inset: 0 390px 0 0; }
  .role-acceptance__canvas .react-flow__node {
    width: 156px;
    border-color: #4a4a4a;
    background: #151515;
    color: #f5f5f5;
    font: 12px/1.35 Inter, sans-serif;
  }
  .role-acceptance__canvas .react-flow__edge-path { stroke: #707070; }
  .role-acceptance__mutant-panel .agent-chat { left: 0; right: auto; opacity: 0.01; }
`;
document.head.append(style);

createRoot(document.getElementById("root")!).render(<AcceptanceHarness />);

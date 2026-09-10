import { expect, test } from "@playwright/test";

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

interface AcceptanceProbe {
  advance(): void;
  exerciseInteractions(): Promise<InteractionSample>;
  isReady(): boolean;
  monitorSnapshot(): MonitorSnapshot;
  motionSnapshot(): MotionSnapshot;
  resourceSnapshot(): ResourceSnapshot;
  snapshot(): HarnessSnapshot;
}

interface InstrumentationWindow extends Window {
  agentRoleAcceptanceErrors: string[];
  agentRoleAcceptanceResources: { snapshot(): ResourceSnapshot };
}

const DEFAULT_SMOKE_DURATION_MS = 6_000;
const requestedDuration = Number(process.env.AGENT_ROLE_SOAK_MS ?? DEFAULT_SMOKE_DURATION_MS);
if (!Number.isFinite(requestedDuration) || requestedDuration < 1_000) {
  throw new Error("AGENT_ROLE_SOAK_MS must be a finite duration of at least 1000ms");
}
const soakDurationMs = Math.floor(requestedDuration);
const mutation = process.env.AGENT_ROLE_ACCEPTANCE_MUTATION ?? "";
const MAX_SEAM_OPACITY_DELTA = 0.03;
const MAX_SEAM_OPACITY_VELOCITY_MISMATCH = 0.02;
const MAX_SEAM_POSE_DELTA_FINAL_PX = 0.08;
const MAX_SEAM_VELOCITY_MISMATCH_FINAL_PX = 0.04;
const MAX_LONG_RUN_OPACITY_DELTA = 0.001;
const MAX_LONG_RUN_POSE_DELTA_FINAL_PX = 0.001;

function expectHealthyLoopSeams(snapshot: MotionSnapshot): void {
  expect(snapshot.maximumSeamOpacityDelta).toBeLessThanOrEqual(MAX_SEAM_OPACITY_DELTA);
  expect(snapshot.maximumSeamOpacityVelocityMismatch).toBeLessThanOrEqual(
    MAX_SEAM_OPACITY_VELOCITY_MISMATCH,
  );
  expect(snapshot.maximumSeamPoseDeltaFinalPx).toBeLessThanOrEqual(
    MAX_SEAM_POSE_DELTA_FINAL_PX,
  );
  expect(snapshot.maximumSeamVelocityMismatchFinalPx).toBeLessThanOrEqual(
    MAX_SEAM_VELOCITY_MISMATCH_FINAL_PX,
  );
  expect(snapshot.seamDirectionReversalCount).toBe(0);
  expect(snapshot.seamStationaryHoldMismatchCount).toBe(0);
  expect(snapshot.maximumLongRunOpacityDelta).toBeLessThan(MAX_LONG_RUN_OPACITY_DELTA);
  expect(snapshot.maximumLongRunPoseDeltaFinalPx).toBeLessThan(
    MAX_LONG_RUN_POSE_DELTA_FINAL_PX,
  );
}

interface SeamEvidence {
  maximumLongRunOpacityDelta: number;
  maximumLongRunPoseDeltaFinalPx: number;
  maximumSeamOpacityDelta: number;
  maximumSeamOpacityVelocityMismatch: number;
  maximumSeamPoseDeltaFinalPx: number;
  maximumSeamVelocityMismatchFinalPx: number;
  sampleCount: number;
  seamDirectionReversalCount: number;
  seamStationaryHoldMismatchCount: number;
}

function includeSeamEvidence(evidence: SeamEvidence, snapshot: MotionSnapshot): void {
  evidence.maximumLongRunOpacityDelta = Math.max(
    evidence.maximumLongRunOpacityDelta,
    snapshot.maximumLongRunOpacityDelta,
  );
  evidence.maximumLongRunPoseDeltaFinalPx = Math.max(
    evidence.maximumLongRunPoseDeltaFinalPx,
    snapshot.maximumLongRunPoseDeltaFinalPx,
  );
  evidence.maximumSeamOpacityDelta = Math.max(
    evidence.maximumSeamOpacityDelta,
    snapshot.maximumSeamOpacityDelta,
  );
  evidence.maximumSeamOpacityVelocityMismatch = Math.max(
    evidence.maximumSeamOpacityVelocityMismatch,
    snapshot.maximumSeamOpacityVelocityMismatch,
  );
  evidence.maximumSeamPoseDeltaFinalPx = Math.max(
    evidence.maximumSeamPoseDeltaFinalPx,
    snapshot.maximumSeamPoseDeltaFinalPx,
  );
  evidence.maximumSeamVelocityMismatchFinalPx = Math.max(
    evidence.maximumSeamVelocityMismatchFinalPx,
    snapshot.maximumSeamVelocityMismatchFinalPx,
  );
  evidence.seamDirectionReversalCount += snapshot.seamDirectionReversalCount;
  evidence.seamStationaryHoldMismatchCount += snapshot.seamStationaryHoldMismatchCount;
  evidence.sampleCount += 1;
}

function median(values: number[]): number {
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[middle - 1]! + sorted[middle]!) / 2
    : sorted[middle]!;
}

test("keeps one real chat role healthy under representative Workflow load", async ({ page }) => {
  test.setTimeout(soakDurationMs + 120_000);

  await page.addInitScript(() => {
    const listenerRecords: Array<{
      capture: boolean;
      listener: EventListenerOrEventListenerObject;
      target: EventTarget;
      type: string;
    }> = [];
    const timeouts = new Set<number>();
    const intervals = new Set<number>();
    const animationFrames = new Set<number>();
    const nativeAddEventListener = EventTarget.prototype.addEventListener;
    const nativeRemoveEventListener = EventTarget.prototype.removeEventListener;
    const nativeSetTimeout = window.setTimeout.bind(window);
    const nativeClearTimeout = window.clearTimeout.bind(window);
    const nativeSetInterval = window.setInterval.bind(window);
    const nativeClearInterval = window.clearInterval.bind(window);
    const nativeRequestAnimationFrame = window.requestAnimationFrame.bind(window);
    const nativeCancelAnimationFrame = window.cancelAnimationFrame.bind(window);
    const captureFor = (options?: boolean | AddEventListenerOptions): boolean => (
      typeof options === "boolean" ? options : options?.capture === true
    );

    EventTarget.prototype.addEventListener = function trackedAddEventListener(
      type: string,
      listener: EventListenerOrEventListenerObject | null,
      options?: boolean | AddEventListenerOptions,
    ): void {
      if (listener) {
        const capture = captureFor(options);
        const duplicate = listenerRecords.some((record) => (
          record.target === this
          && record.type === type
          && record.listener === listener
          && record.capture === capture
        ));
        if (!duplicate) listenerRecords.push({ capture, listener, target: this, type });
      }
      nativeAddEventListener.call(this, type, listener, options);
    };
    EventTarget.prototype.removeEventListener = function trackedRemoveEventListener(
      type: string,
      listener: EventListenerOrEventListenerObject | null,
      options?: boolean | EventListenerOptions,
    ): void {
      if (listener) {
        const capture = captureFor(options);
        const index = listenerRecords.findIndex((record) => (
          record.target === this
          && record.type === type
          && record.listener === listener
          && record.capture === capture
        ));
        if (index >= 0) listenerRecords.splice(index, 1);
      }
      nativeRemoveEventListener.call(this, type, listener, options);
    };

    window.setTimeout = ((handler: TimerHandler, timeout?: number, ...args: unknown[]) => {
      let id = 0;
      const trackedHandler = typeof handler === "function"
        ? () => {
            timeouts.delete(id);
            handler(...args);
          }
        : handler;
      id = nativeSetTimeout(trackedHandler, timeout);
      timeouts.add(id);
      return id;
    }) as typeof window.setTimeout;
    window.clearTimeout = ((id?: number) => {
      if (typeof id === "number") timeouts.delete(id);
      nativeClearTimeout(id);
    }) as typeof window.clearTimeout;
    window.setInterval = ((handler: TimerHandler, timeout?: number, ...args: unknown[]) => {
      const id = nativeSetInterval(handler, timeout, ...args);
      intervals.add(id);
      return id;
    }) as typeof window.setInterval;
    window.clearInterval = ((id?: number) => {
      if (typeof id === "number") intervals.delete(id);
      nativeClearInterval(id);
    }) as typeof window.clearInterval;
    window.requestAnimationFrame = ((callback: FrameRequestCallback) => {
      let id = 0;
      id = nativeRequestAnimationFrame((time) => {
        animationFrames.delete(id);
        callback(time);
      });
      animationFrames.add(id);
      return id;
    }) as typeof window.requestAnimationFrame;
    window.cancelAnimationFrame = ((id: number) => {
      animationFrames.delete(id);
      nativeCancelAnimationFrame(id);
    }) as typeof window.cancelAnimationFrame;

    const errors: string[] = [];
    window.addEventListener("error", (event) => {
      errors.push(event.error instanceof Error ? event.error.stack ?? event.error.message : event.message);
    });
    window.addEventListener("unhandledrejection", (event) => {
      const reason = event.reason;
      errors.push(reason instanceof Error ? reason.stack ?? reason.message : String(reason));
    });
    Object.assign(window, {
      agentRoleAcceptanceErrors: errors,
      agentRoleAcceptanceResources: {
        snapshot: (): ResourceSnapshot => ({
          activeAnimationFrames: animationFrames.size,
          activeIntervals: intervals.size,
          activeListeners: listenerRecords.length,
          activeTimeouts: timeouts.size,
          listenersByType: Object.fromEntries(
            [...new Set(listenerRecords.map(({ type }) => type))]
              .sort()
              .map((type) => [
                type,
                listenerRecords.filter((record) => record.type === type).length,
              ]),
          ),
        }),
      },
    });
  });

  let serverPhase: HarnessPhase = "working";
  await page.route("**/api/v2/**", async (route) => {
    const url = new URL(route.request().url());
    const workflowId = "workflow-role-acceptance";
    const timestamp = "2026-09-03T12:00:00Z";
    if (url.pathname.endsWith("/chat/timeline")) {
      const items = Array.from({ length: 36 }, (_, index) => ({
        entry_id: `message-${index + 1}`,
        workflow_id: workflowId,
        conversation_id: "conversation-role-acceptance",
        sequence_no: index + 1,
        entry_type: "message",
        speaker: index % 4 === 0 ? "user" : "adcraft_video_agent",
        content: `Persisted production note ${index + 1}: representative history for scrolling.`,
        metadata: {},
        command_plan: null,
        action_receipt: null,
        created_at: timestamp,
      }));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          workflow_id: workflowId,
          conversation_id: "conversation-role-acceptance",
          guidance_session: null,
          guidance_advance_precondition: null,
          continuations: [],
          current_session_actions: [],
          items,
          next_cursor: 0,
        }),
      });
      return;
    }
    if (url.pathname.endsWith("/agent-settings")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { ETag: "\"agent-settings:1\"" },
        body: JSON.stringify({
          workflow_id: workflowId,
          media_execution_mode: "manual",
          revision: 1,
          created_at: timestamp,
          updated_at: timestamp,
        }),
      });
      return;
    }
    if (url.pathname.includes("/chat/turns/")) {
      const turnId = decodeURIComponent(url.pathname.split("/").at(-1)!);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          turn_id: turnId,
          workflow_id: workflowId,
          conversation_id: "conversation-role-acceptance",
          status: serverPhase === "idle" ? "completed" : "running",
          turn_kind: "capability",
          request: {},
          error_code: null,
          error_message: null,
          creation_mode: null,
          guidance_session_revision: null,
          continuation: null,
          retry_of_turn_id: null,
          retry_attempt_no: 1,
          retryable: false,
          operation_stage: serverPhase === "waiting" ? "provider_waiting" : null,
          operation_failure: null,
          created_at: timestamp,
          updated_at: timestamp,
        }),
      });
      return;
    }
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ code: "acceptance_route_not_needed", message: url.pathname }),
    });
  });

  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.stack ?? error.message));
  const query = mutation ? `?mutation=${encodeURIComponent(mutation)}` : "";
  const startedAt = new Date().toISOString();
  console.log(`[agent-role-soak] start=${startedAt} requestedMs=${soakDurationMs} mutation=${mutation || "none"}`);
  await page.goto(`/tests/browser/agent-role-production-load-mock.html${query}`);
  await page.waitForFunction(() => (
    (window as unknown as { agentRoleAcceptanceProbe?: AcceptanceProbe })
      .agentRoleAcceptanceProbe?.isReady() === true
  ), undefined, { timeout: 10_000 });

  const snapshot = () => page.evaluate(() => (
    (window as unknown as { agentRoleAcceptanceProbe: AcceptanceProbe })
      .agentRoleAcceptanceProbe.snapshot()
  ));
  const motionSnapshot = () => page.evaluate(() => (
    (window as unknown as { agentRoleAcceptanceProbe: AcceptanceProbe })
      .agentRoleAcceptanceProbe.motionSnapshot()
  ));
  const advance = () => page.evaluate(() => (
    (window as unknown as { agentRoleAcceptanceProbe: AcceptanceProbe })
      .agentRoleAcceptanceProbe.advance()
  ));

  await expect.poll(async () => (await snapshot()).phase).toBe("working");
  await expect.poll(async () => (await motionSnapshot()).roleAnimationCount).toBeGreaterThan(0);
  await expect.poll(async () => (await motionSnapshot()).loopAnimationCount).toBeGreaterThan(0);

  const latencySamples: number[] = [];
  let idleResourceBaseline: ResourceSnapshot | null = null;
  let completedCycles = 0;
  const measuredRoles = new Set<string>();
  const seamEvidence: SeamEvidence = {
    maximumLongRunOpacityDelta: 0,
    maximumLongRunPoseDeltaFinalPx: 0,
    maximumSeamOpacityDelta: 0,
    maximumSeamOpacityVelocityMismatch: 0,
    maximumSeamPoseDeltaFinalPx: 0,
    maximumSeamVelocityMismatchFinalPx: 0,
    sampleCount: 0,
    seamDirectionReversalCount: 0,
    seamStationaryHoldMismatchCount: 0,
  };
  let nextProgressAt = Date.now() + Math.min(30_000, Math.max(1_000, soakDurationMs / 2));
  const monotonicStart = Date.now();

  while (Date.now() - monotonicStart < soakDurationMs) {
    const working = await motionSnapshot();
    expect(working.activeRoleRootCount).toBe(1);
    expect(working.activeRoleSlugs).toHaveLength(1);
    expectHealthyLoopSeams(working);
    includeSeamEvidence(seamEvidence, working);
    measuredRoles.add(working.activeRoleSlugs[0]!);

    const interaction = await page.evaluate(() => (
      (window as unknown as { agentRoleAcceptanceProbe: AcceptanceProbe })
        .agentRoleAcceptanceProbe.exerciseInteractions()
    ));
    expect(interaction.canvasChanged).toBe(true);
    expect(interaction.chatScrolled).toBe(true);
    expect(interaction.durationMs).toBeLessThan(250);
    latencySamples.push(interaction.durationMs);

    serverPhase = "waiting";
    await advance();
    await expect.poll(async () => (await snapshot()).phase).toBe("waiting");
    await expect(page.getByText("Waiting for model", { exact: true }).first()).toBeVisible();
    await expect.poll(async () => (await motionSnapshot()).roleAnimationCount).toBeGreaterThan(0);
    await expect.poll(async () => (await motionSnapshot()).loopAnimationCount).toBeGreaterThan(0);
    const waiting = await motionSnapshot();
    expect(waiting.activeRoleRootCount).toBe(1);
    expect(waiting.activeRoleSlugs).toEqual(working.activeRoleSlugs);
    expectHealthyLoopSeams(waiting);
    includeSeamEvidence(seamEvidence, waiting);

    serverPhase = "idle";
    await advance();
    await expect.poll(async () => (await snapshot()).phase).toBe("idle");
    await expect.poll(async () => (await motionSnapshot()).roleAnimationCount).toBe(0);
    const idleResources = await page.evaluate(() => (
      (window as unknown as { agentRoleAcceptanceProbe: AcceptanceProbe })
        .agentRoleAcceptanceProbe.resourceSnapshot()
    ));
    if (!idleResourceBaseline) {
      idleResourceBaseline = idleResources;
    } else {
      expect(idleResources.activeListeners).toBeLessThanOrEqual(idleResourceBaseline.activeListeners);
      expect(idleResources.activeTimeouts).toBeLessThanOrEqual(idleResourceBaseline.activeTimeouts);
      expect(idleResources.activeIntervals).toBeLessThanOrEqual(idleResourceBaseline.activeIntervals);
      expect(idleResources.activeAnimationFrames).toBeLessThanOrEqual(
        idleResourceBaseline.activeAnimationFrames,
      );
      expect(idleResources.listenersByType.visibilitychange ?? 0).toBeLessThanOrEqual(
        idleResourceBaseline.listenersByType.visibilitychange ?? 0,
      );
      expect(idleResources.listenersByType.change ?? 0).toBeLessThanOrEqual(
        idleResourceBaseline.listenersByType.change ?? 0,
      );
    }

    completedCycles += 1;
    expect(pageErrors).toEqual([]);
    const browserErrors = await page.evaluate(() => (
      (window as unknown as InstrumentationWindow).agentRoleAcceptanceErrors
    ));
    expect(browserErrors).toEqual([]);

    if (Date.now() >= nextProgressAt) {
      const elapsedMs = Date.now() - monotonicStart;
      console.log(
        `[agent-role-soak] progress elapsedMs=${elapsedMs} cycles=${completedCycles} lastRole=${working.activeRoleSlugs[0]}`,
      );
      nextProgressAt = Date.now() + 30_000;
    }

    if (Date.now() - monotonicStart >= soakDurationMs) break;
    serverPhase = "working";
    await advance();
    await expect.poll(async () => (await snapshot()).phase).toBe("working");
    await expect.poll(async () => (await motionSnapshot()).roleAnimationCount).toBeGreaterThan(0);
    await expect.poll(async () => (await motionSnapshot()).loopAnimationCount).toBeGreaterThan(0);
  }

  expect(completedCycles).toBeGreaterThan(0);
  expect(latencySamples.length).toBeGreaterThan(0);
  const firstWindow = latencySamples.slice(0, Math.min(10, latencySamples.length));
  const lastWindow = latencySamples.slice(-Math.min(10, latencySamples.length));
  const initialMedianMs = median(firstWindow);
  const finalMedianMs = median(lastWindow);
  expect(finalMedianMs).toBeLessThanOrEqual(Math.max(100, initialMedianMs * 3));

  const monitor = await page.evaluate(() => (
    (window as unknown as { agentRoleAcceptanceProbe: AcceptanceProbe })
      .agentRoleAcceptanceProbe.monitorSnapshot()
  ));
  expect(monitor.maximumActiveRoleRoots).toBeLessThanOrEqual(1);
  expect(monitor.violations).toEqual([]);
  expect(pageErrors).toEqual([]);
  expect(await page.evaluate(() => (
    (window as unknown as InstrumentationWindow).agentRoleAcceptanceErrors
  ))).toEqual([]);

  const finishedAt = new Date().toISOString();
  console.log(JSON.stringify({
    soakEvidence: {
      requestedDurationMs: soakDurationMs,
      observedDurationMs: Date.now() - monotonicStart,
      startedAt,
      finishedAt,
      completedCycles,
      initialMedianInteractionMs: initialMedianMs,
      finalMedianInteractionMs: finalMedianMs,
      idleResourceBaseline,
      finalResources: await page.evaluate(() => (
        (window as unknown as { agentRoleAcceptanceProbe: AcceptanceProbe })
          .agentRoleAcceptanceProbe.resourceSnapshot()
      )),
      monitor,
      seamEvidence: {
        ...seamEvidence,
        measuredRoles: [...measuredRoles].sort(),
        thresholds: {
          maximumLongRunOpacityDelta: MAX_LONG_RUN_OPACITY_DELTA,
          maximumLongRunPoseDeltaFinalPx: MAX_LONG_RUN_POSE_DELTA_FINAL_PX,
          maximumSeamOpacityDelta: MAX_SEAM_OPACITY_DELTA,
          maximumSeamOpacityVelocityMismatch: MAX_SEAM_OPACITY_VELOCITY_MISMATCH,
          maximumSeamPoseDeltaFinalPx: MAX_SEAM_POSE_DELTA_FINAL_PX,
          maximumSeamVelocityMismatchFinalPx: MAX_SEAM_VELOCITY_MISMATCH_FINAL_PX,
        },
      },
    },
  }, null, 2));
});

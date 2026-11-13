import { expect, test, type Page, type Route } from "@playwright/test";

const stamp = "2026-09-07T00:00:00Z";
function makeWorkflow(id: string) {
  return {
    workflow_id: id, project_id: `project-${id}`, workflow_schema_version: 2, canvas_model: "agent_canvas_v1",
    revision: 1, layout_revision: 1, active_style_skill: null, bindings: [] as Record<string, unknown>[], assets: [],
    nodes: ["source", "target"].map((node_id, index) => ({
      node_id, workflow_id: id, node_type: "image", creative_role: "general_image", role_contract_version: "ad-media-role-v1",
      title: node_id, status: "draft", execution_mode: "generative", summary_prompt: null, generation_prompt: null,
      structured_content: {}, model_id: null, model_selection_mode: "default", model_ref: null, model_summary: null,
      parameters: {}, metadata: {}, parameter_provenance: {}, prompt_context_snapshot_id: null, prompt_presentation: null,
      prompt_preparation: null, output_asset_id: null, output_asset_version_id: null, latest_attempt: null,
      position: { x: 120 + index * 480, y: 160 + index * 120 }, revision: 1, error: null, created_at: stamp, updated_at: stamp,
    })),
  };
}
async function setup(page: Page, extraNode = false) {
  const workflows = { a: makeWorkflow("a"), b: makeWorkflow("b") };
  if (extraNode) workflows.a.nodes.push({ ...workflows.a.nodes[0], node_id: "other", position: { x: 120, y: 550 } });
  const writes: string[] = [];
  const pending: Route[] = [];
  const pendingConnected: Route[] = [];
  const json = (route: Route, body: unknown, revision = 1) => route.fulfill({
    status: 200, contentType: "application/json", headers: { ETag: `"${revision}"` }, body: JSON.stringify(body),
  });
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/model-defaults")) return json(route, { defaults: {} });
    if (path.endsWith("/models")) return json(route, { items: [] });
    return json(route, {});
  });
  await page.route("**/api/v2/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const id = path.includes("/workflows/b") ? "b" : "a";
    const workflow = workflows[id];
    if (request.method() !== "GET") writes.push(`${request.method()} ${path}`);
    if (request.method() === "POST" && path.endsWith("/bindings")) { pending.push(route); return; }
    if (request.method() === "POST" && path.endsWith("/connected-nodes")) { pendingConnected.push(route); return; }
    if (request.method() === "DELETE" && path.endsWith("/nodes/target")) {
      expect(request.headers()["if-match"]).toBe(`"${workflow.revision}"`);
      workflow.nodes = workflow.nodes.filter((node) => node.node_id !== "target");
      workflow.bindings = [];
      workflow.revision++;
      return json(route, { workflow, node: null, binding: null }, workflow.revision);
    }
    if (request.method() !== "GET") return route.abort();
    if (/\/projects\/project-[ab]$/.test(path)) {
      const projectId = path.endsWith("project-b") ? "b" : "a";
      return json(route, { project_id: `project-${projectId}`, workflow_id: projectId, name: `Connection ${projectId}`,
        description: "", project_version: 1, semantic_revision_no: 1, status: "active", is_favorite: false, created_at: stamp, updated_at: stamp,
        deleted_at: null, cover_asset_id: null });
    }
    if (path.endsWith("/projects")) return json(route, { items: [], next_cursor: null });
    if (/\/workflows\/[ab]$/.test(path)) return json(route, workflow, workflow.revision);
    if (path.endsWith("/connection-policy")) {
      const types = ["text", "script", "image", "video", "audio", "editing"];
      return json(route, { policy_version: "agent_canvas_connection_policy_v1",
        target_node_types: Object.fromEntries(types.map((type) => [type, type === "image" ? ["image"] : []])),
        input_roles: [{ source_node_type: "image", target_node_type: "image", roles: ["image_reference"], default_role: "image_reference" }],
        image_asset_targets: {}, binding_kind_by_source_type: Object.fromEntries(types.map((type) => [type, "image_reference"])), model_validation: {} });
    }
    if (path.endsWith("/runtime")) return json(route, { workflow_id: id, active_execution_id: null, execution_status: null,
      node_runtime: {}, queued_node_ids: [], working_node_ids: [], waiting_node_ids: [], ready_node_ids: [], failed_node_ids: [],
      events_cursor: 0, updated_at: stamp });
    if (path.endsWith("/chat/timeline")) return json(route, { workflow_id: id, conversation_id: null, items: [], presentation_items: [], next_cursor: 0 });
    if (path.endsWith("/assets")) return json(route, { workflow_id: id, assets: [] });
    if (path.endsWith("/events")) return json(route, { workflow_id: id, events: [], next_cursor: 0 });
    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: { code: "not_found", message: "No mock data" } }) });
  });
  await page.goto("/workflow/project-a");
  await expect(page.locator(".react-flow__node")).toHaveCount(extraNode ? 3 : 2);
  await page.getByRole("button", { name: "Fit View", exact: true }).click();
  await page.waitForTimeout(600);
  const resolve = async (success: boolean, failureStatus = 409) => {
    expect(pending).toHaveLength(1);
    const route = pending[0];
    expect(route.request().headers()["if-match"]).toBe('"1"');
    if (!success) return route.fulfill({ status: failureStatus, contentType: "application/json", body: JSON.stringify({ detail: { code: "workflow_state_conflict", message: "Connection was not saved." } }) });
    const body = route.request().postDataJSON();
    const binding = { ...body, binding_id: "binding-confirmed", workflow_id: "a", label: null, metadata: {}, created_at: stamp, updated_at: stamp };
    workflows.a.bindings = [binding]; workflows.a.revision++;
    await json(route, { workflow: workflows.a, binding }, workflows.a.revision);
  };
  const resolveConnected = async (success = true) => {
    expect(pendingConnected).toHaveLength(1);
    const route = pendingConnected[0];
    if (!success) return route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({
      detail: { code: "invalid_connection", message: "Connected node was not saved." },
    }) });
    const body = route.request().postDataJSON();
    const node = { ...workflows.a.nodes[0], ...body.node, node_id: "created", position: body.node.position };
    const binding = {
      ...body.binding, binding_id: "connected-binding", workflow_id: "a", enabled: true,
      source: { kind: "node_output", source_node_id: body.direction === "downstream" ? body.anchor_node_id : node.node_id },
      target_node_id: body.direction === "downstream" ? node.node_id : body.anchor_node_id,
      label: null, metadata: {}, created_at: stamp, updated_at: stamp,
    };
    workflows.a.nodes.push(node);
    workflows.a.bindings.push(binding);
    workflows.a.revision++;
    await json(route, { workflow_id: "a", revision: workflows.a.revision, layout_revision: 1, node, binding, events_cursor: 0 }, workflows.a.revision);
  };
  return { writes, pending, resolve, pendingConnected, resolveConnected };
}

const temporary = '.react-flow__edge[data-id^="pending-connection-"]';
const paths = ".react-flow__edge-path";
async function connect(page: Page) {
  const source = page.locator('.react-flow__node[data-id="source"] .agent-canvas-node__handle--output');
  const target = page.locator('.react-flow__node[data-id="target"] .agent-canvas-node__handle--input');
  const s = (await source.boundingBox())!, t = (await target.boundingBox())!;
  await page.mouse.move(s.x + s.width / 2, s.y + s.height / 2);
  await page.mouse.down();
  await page.mouse.move(t.x + t.width / 2, t.y + t.height / 2, { steps: 8 });
  await expect(page.locator(".agent-canvas-connection-line")).toHaveAttribute("data-connection-status", "valid");
  await page.mouse.up();
}

const droppedLine = '.agent-canvas-connection-line[data-connection-status="dropped"]';
async function dropOnBlank(page: Page, side: "input" | "output") {
  await page.getByRole("button", { name: "Zoom Out", exact: true }).click();
  await page.waitForTimeout(350);
  const handle = page.locator(`.react-flow__node[data-id="source"] .agent-canvas-node__handle--${side}`);
  const start = (await handle.boundingBox())!;
  const point = await page.locator(".react-flow__pane").evaluate((pane) => {
    const bounds = pane.getBoundingClientRect();
    // Pick an actual blank point, leaving room for the menu and new card.
    for (const yRatio of [0.7, 0.8, 0.4, 0.3]) {
      for (const xRatio of [0.5, 0.6, 0.4]) {
        const x = bounds.x + bounds.width * xRatio, y = bounds.y + bounds.height * yRatio;
        if (document.elementFromPoint(x, y) === pane) return { x, y };
      }
    }
    throw new Error("No blank drop position");
  });
  await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
  await page.mouse.down();
  await page.mouse.move(point.x, point.y, { steps: 8 });
  const preview = await page.locator(".agent-canvas-connection-line").getAttribute("d");
  await page.mouse.up();
  await expect(page.locator(droppedLine)).toBeVisible();
  // The retained line must match the dragged line even after fit-view zoom/pan.
  expect(await page.locator(droppedLine).getAttribute("d")).toBe(preview);
  return point;
}

for (const [side, direction] of [["output", "downstream"], ["input", "upstream"]] as const) {
  test(`blank drop from ${side} preserves the line and creates a connected ${direction} node`, async ({ page }) => {
    const mock = await setup(page);
    const point = await dropOnBlank(page, side);
    const menu = page.getByRole("menu", { name: `Add ${direction} node` });
    await expect(menu).toBeVisible();
    const bounds = (await menu.boundingBox())!;
    expect(Math.abs(bounds.x - point.x)).toBeLessThan(1);
    expect(Math.abs(bounds.y - point.y)).toBeLessThan(1);
    expect(mock.writes).toHaveLength(0);
    await page.screenshot({ path: `/tmp/canvas-connected-menu-${direction}.png` });
    await page.getByRole("menuitem", { name: "Create connected Image node" }).click();
    await expect.poll(() => mock.pendingConnected.length).toBe(1);
    await expect(menu).toHaveCount(0);
    await expect(page.locator(droppedLine)).toBeVisible();
    const body = mock.pendingConnected[0].request().postDataJSON();
    expect(body).toMatchObject({ anchor_node_id: "source", direction, node: { node_type: "image" }, binding: { input_role: "image_reference" } });
    await page.evaluate(() => {
      const probe = { running: true, missing: false };
      Object.assign(window, { droppedConnectionProbe: probe });
      const sample = () => {
        if (!document.querySelector('[data-connection-status="dropped"], .react-flow__edge-path')) probe.missing = true;
        if (probe.running) requestAnimationFrame(sample);
      };
      requestAnimationFrame(sample);
    });
    await mock.resolveConnected();
    await expect(page.locator('.react-flow__node[data-id="created"]')).toBeVisible();
    const card = (await page.locator('.react-flow__node[data-id="created"] .agent-canvas-node-shell').boundingBox())!;
    expect(Math.abs((direction === "downstream" ? card.x : card.x + card.width) - point.x)).toBeLessThan(2);
    expect(Math.abs(card.y + card.height / 2 - point.y)).toBeLessThan(2);
    const edge = page.locator('.react-flow__edge[data-id="connected-binding"]');
    await expect(edge.locator(".react-flow__edge-path")).toBeVisible();
    await expect(edge).toHaveAttribute("aria-label", direction === "downstream" ? "Edge from source to created" : "Edge from created to source");
    await expect(page.locator(droppedLine)).toHaveCount(0);
    const missing = await page.evaluate(() => {
      const probe = (window as unknown as { droppedConnectionProbe: { running: boolean; missing: boolean } }).droppedConnectionProbe;
      probe.running = false;
      return probe.missing;
    });
    expect(missing).toBe(false);
    expect(mock.writes.filter((write) => write.startsWith("POST"))).toHaveLength(1);
  });
}

test("blank connection can be cancelled by Escape or clicking outside without a write", async ({ page }) => {
  const mock = await setup(page);
  await dropOnBlank(page, "output");
  await page.keyboard.press("Escape");
  await expect(page.locator(droppedLine)).toHaveCount(0);
  await expect(page.getByRole("menu")).toHaveCount(0);
  await dropOnBlank(page, "input");
  await page.getByRole("button", { name: "Close connected node menu" }).click({ position: { x: 10, y: 10 } });
  await expect(page.locator(droppedLine)).toHaveCount(0);
  expect(mock.writes).toHaveLength(0);
});

test("failed connected-node creation removes the preview and shows the error", async ({ page }) => {
  const mock = await setup(page);
  await dropOnBlank(page, "output");
  await page.getByRole("menuitem", { name: "Create connected Image node" }).click();
  await expect.poll(() => mock.pendingConnected.length).toBe(1);
  await mock.resolveConnected(false);
  await expect(page.locator(droppedLine)).toHaveCount(0);
  await expect(page.locator(".react-flow__node")).toHaveCount(2);
  await expect(page.getByText("Connected node was not saved.", { exact: true }).first()).toBeVisible();
});

test("dropping on a card or a same-side handle does not open the creation menu", async ({ page }) => {
  const mock = await setup(page);
  const start = (await page.locator('.react-flow__node[data-id="source"] .agent-canvas-node__handle--output').boundingBox())!;
  for (const targetSelector of [".agent-canvas-node", ".agent-canvas-node__handle--output"]) {
    const end = (await page.locator(`.react-flow__node[data-id="target"] ${targetSelector}`).boundingBox())!;
    await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
    await page.mouse.down();
    await page.mouse.move(end.x + end.width / 2, end.y + end.height / 2, { steps: 8 });
    await page.mouse.up();
    await expect(page.locator(droppedLine)).toHaveCount(0);
    await expect(page.getByRole("menu")).toHaveCount(0);
  }
  expect(mock.writes).toHaveLength(0);
});

test("switching projects clears an unsubmitted connection and menu", async ({ page }) => {
  const mock = await setup(page);
  await dropOnBlank(page, "output");
  await page.evaluate(() => { history.pushState(null, "", "/workflow/project-b"); dispatchEvent(new PopStateEvent("popstate")); });
  await expect(page).toHaveURL(/project-b$/);
  await expect(page.locator(droppedLine)).toHaveCount(0);
  await expect(page.getByRole("menu")).toHaveCount(0);
  expect(mock.writes).toHaveLength(0);
});

test("release draws immediately; confirmed Binding replaces continuously with one request", async ({ page }) => {
  const mock = await setup(page);
  await connect(page);
  await expect(page.locator(temporary)).toHaveCount(1, { timeout: 100 });
  await expect(page.locator(paths)).toHaveCount(1);
  await connect(page);
  expect(mock.pending).toHaveLength(1);
  await page.screenshot({ path: "/tmp/canvas-optimistic-pending.png" });
  await page.evaluate(() => {
    const samples: number[] = [];
    Object.assign(window, { connectionSamples: samples, sampleConnections: true });
    const sample = () => {
      samples.push(document.querySelectorAll(".react-flow__edge-path").length);
      if ((window as unknown as { sampleConnections: boolean }).sampleConnections) requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  });
  await mock.resolve(true);
  await expect(page.locator('.react-flow__edge[data-id="binding-confirmed"]')).toHaveCount(1);
  await expect(page.locator(temporary)).toHaveCount(0);
  await page.waitForTimeout(100);
  const samples = await page.evaluate(() => { Object.assign(window, { sampleConnections: false }); return (window as unknown as { connectionSamples: number[] }).connectionSamples; });
  expect(samples.length).toBeGreaterThan(0);
  expect(samples.every((count) => count === 1)).toBe(true);
  expect(mock.writes.filter((write) => write.startsWith("POST"))).toHaveLength(1);
});

test("failed save removes the temporary line", async ({ page }) => {
  const mock = await setup(page);
  await connect(page);
  await expect(page.locator(temporary)).toHaveCount(1, { timeout: 100 });
  await mock.resolve(false);
  await expect(page.locator(paths)).toHaveCount(0);
  expect(mock.writes.filter((write) => write.startsWith("POST"))).toHaveLength(1);
});

test("deleting an endpoint cancels its pending line and never deletes a temporary Binding ID", async ({ page }) => {
  const mock = await setup(page);
  await connect(page);
  await page.locator('.react-flow__node[data-id="target"] .agent-canvas-node').click({ button: "right" });
  await page.getByRole("menuitem", { name: /delete/i }).click();
  await expect(page.locator(temporary)).toHaveCount(0);
  await mock.resolve(true);
  await expect(page.locator('.react-flow__node[data-id="target"]')).toHaveCount(0);
  await expect(page.locator(paths)).toHaveCount(0);
  expect(mock.writes.some((write) => write.includes("pending-connection"))).toBe(false);
});

test("late save does not repopulate another project", async ({ page }) => {
  const mock = await setup(page);
  await connect(page);
  await page.evaluate(() => { history.pushState(null, "", "/workflow/project-b"); dispatchEvent(new PopStateEvent("popstate")); });
  await expect(page).toHaveURL(/project-b$/);
  await expect(page.locator(temporary)).toHaveCount(0);
  await mock.resolve(true);
  await page.waitForTimeout(200);
  await expect(page.locator(paths)).toHaveCount(0);
});

test("a late precondition conflict after navigation cannot publish a retry", async ({ page }) => {
  const mock = await setup(page);
  await connect(page);
  await page.evaluate(() => { history.pushState(null, "", "/workflow/project-b"); dispatchEvent(new PopStateEvent("popstate")); });
  await expect(page.locator(temporary)).toHaveCount(0);
  await mock.resolve(false, 412);
  await page.waitForTimeout(300);
  const conflict = await page.evaluate(async () => {
    const path = "/src/api/v2AuthoringConflictStore.ts";
    const { v2AuthoringConflictStore } = await import(path);
    const present = v2AuthoringConflictStore.current() !== null;
    await v2AuthoringConflictStore.retry();
    return present;
  });
  expect(conflict).toBe(false);
  expect(mock.writes.filter((write) => write.startsWith("POST"))).toHaveLength(1);
  await expect(page.getByText("Connection was not saved.", { exact: true })).toHaveCount(0);
});

for (const success of [false, true]) {
  test(`pending line reconciles while frozen by another node drag: ${success ? "success" : "failure"}`, async ({ page }) => {
    const mock = await setup(page, true);
    await connect(page);
    await expect(page.locator(temporary)).toHaveCount(1);
    const box = (await page.locator('.react-flow__node[data-id="other"] .agent-canvas-node').boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 30, box.y + box.height / 2 + 10, { steps: 4 });
    await expect(page.locator(`.agent-canvas-frozen-edges ${paths}`)).toHaveCount(1);
    await mock.resolve(success);
    await expect(page.locator(`.agent-canvas-frozen-edges ${paths}`)).toHaveCount(0);
    await expect(page.locator(paths)).toHaveCount(success ? 1 : 0);
    await page.mouse.up();
  });
}

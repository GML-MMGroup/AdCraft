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
  const json = (route: Route, body: unknown, revision = 1) => route.fulfill({
    status: 200, contentType: "application/json", headers: { ETag: `"${revision}"` }, body: JSON.stringify(body),
  });
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.route("**/api/v1/**", (route) => json(route, {}));
  await page.route("**/api/v2/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const id = path.includes("/workflows/b") ? "b" : "a";
    const workflow = workflows[id];
    if (request.method() !== "GET") writes.push(`${request.method()} ${path}`);
    if (request.method() === "POST" && path.endsWith("/bindings")) { pending.push(route); return; }
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
  return { writes, pending, resolve };
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

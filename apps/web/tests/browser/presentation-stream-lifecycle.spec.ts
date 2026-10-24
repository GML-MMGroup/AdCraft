import { once } from "node:events";
import { createServer, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";

import { expect, test, type Page } from "@playwright/test";

import type { PresentationStreamEventV1 } from "../../src/types-v2.ts";

type Connection = {
  workflowId: string;
  streamId: string;
  afterSeq: number;
  response: ServerResponse;
};

function presentationEvent(
  workflowId: string,
  streamId: string,
  sequenceNo: number,
  eventType: PresentationStreamEventV1["event_type"],
  delta: string | null = null,
): PresentationStreamEventV1 {
  return {
    schema_version: 1,
    workflow_id: workflowId,
    stream_id: streamId,
    stream_kind: "assistant",
    event_type: eventType,
    sequence_no: sequenceNo,
    turn_id: streamId,
    node_id: null,
    generation_id: `generation-${streamId}`,
    response_locale: "en-US",
    node_revision: null,
    delta,
    authoritative_id: eventType === "committed" ? `message-${streamId}` : null,
    content_digest: eventType === "committed" ? "a".repeat(64) : null,
    error_code: eventType === "failed" ? "generation_failed" : null,
    reset: null,
  };
}

async function startEventServer(page: Page) {
  const connections: Connection[] = [];
  const events = new Map<string, PresentationStreamEventV1[]>();
  const finished = new Set<string>();
  const key = (workflowId: string, streamId: string) => `${workflowId}:${streamId}`;
  const write = (response: ServerResponse, event: PresentationStreamEventV1) => {
    response.write(`id: ${event.sequence_no}\nevent: ${event.event_type}\ndata: ${JSON.stringify(event)}\n\n`);
  };
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    const match = url.pathname.match(/^\/api\/v2\/workflows\/([^/]+)\/presentation\/streams\/([^/]+)$/);
    if (!match) {
      response.writeHead(404).end();
      return;
    }
    const [, workflowId, streamId] = match as [string, string, string];
    const afterSeq = Number(url.searchParams.get("after_seq") ?? 0);
    connections.push({ workflowId, streamId, afterSeq, response });
    response.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Access-Control-Allow-Origin": "*",
    });
    response.flushHeaders();
    const streamKey = key(workflowId, streamId);
    for (const event of events.get(streamKey) ?? []) {
      if (event.sequence_no > afterSeq) write(response, event);
    }
    // Match the backend: an already terminal cursor returns no further event.
    if (finished.has(streamKey)) response.end();
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  await page.route("**/api/v2/workflows/*/presentation/streams/*", (route) => {
    const url = new URL(route.request().url());
    return route.continue({ url: `${origin}${url.pathname}${url.search}` });
  });

  return {
    connectionsFor: (workflowId: string, streamId: string) => connections.filter((connection) => (
      connection.workflowId === workflowId && connection.streamId === streamId
    )),
    publish(event: PresentationStreamEventV1) {
      const streamKey = key(event.workflow_id, event.stream_id);
      events.set(streamKey, [...events.get(streamKey) ?? [], event]);
      const terminal = ["committed", "failed", "superseded"].includes(event.event_type);
      if (terminal) finished.add(streamKey);
      for (const connection of connections) {
        if (connection.workflowId !== event.workflow_id || connection.streamId !== event.stream_id
          || connection.response.destroyed || connection.response.writableEnded) continue;
        write(connection.response, event);
        if (terminal) connection.response.end();
      }
    },
    async close() {
      await page.close();
      server.closeAllConnections();
      await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    },
  };
}

for (const [eventType, status] of [
  ["committed", "completed"],
  ["failed", "failed"],
  ["superseded", "superseded"],
] as const) {
  test(`keeps ${eventType} turns closed through later turns over native EventSource`, async ({ page }) => {
    const eventServer = await startEventServer(page);
    try {
      await page.goto("/tests/browser/presentation-stream-lifecycle.html");
      await expect(page.getByTestId("turn-1-status")).toHaveText("open");
      eventServer.publish(presentationEvent("workflow-1", "turn-1", 1, "delta", "First answer"));
      eventServer.publish(presentationEvent("workflow-1", "turn-1", 2, eventType));
      await expect(page.getByTestId("turn-1-status")).toHaveText(status);

      await page.getByRole("button", { name: "Add turn" }).click();
      await expect(page.getByTestId("turn-2-status")).toHaveText("open");
      eventServer.publish(presentationEvent("workflow-1", "turn-2", 1, "delta", "Second answer"));
      eventServer.publish(presentationEvent("workflow-1", "turn-2", 2, "committed"));
      await expect(page.getByTestId("turn-2-status")).toHaveText("completed");
      await page.getByRole("button", { name: "Add turn" }).click();
      await expect(page.getByTestId("turn-3-status")).toHaveText("open");

      expect(eventServer.connectionsFor("workflow-1", "turn-1")).toHaveLength(1);
      expect(eventServer.connectionsFor("workflow-1", "turn-2")).toHaveLength(1);
      await expect(page.getByTestId("turn-1-status")).toHaveText(status);
      await expect(page.getByTestId("turn-1-text")).toHaveText("First answer");
      await expect(page.getByTestId("turn-1-cursor")).toHaveText("2");
    } finally {
      await eventServer.close();
    }
  });
}

test("resumes live cursors after membership changes and disconnects, then resets workflow scope", async ({ page }) => {
  const eventServer = await startEventServer(page);
  try {
    await page.goto("/tests/browser/presentation-stream-lifecycle.html");
    await expect(page.getByTestId("turn-1-status")).toHaveText("open");
    eventServer.publish(presentationEvent("workflow-1", "turn-1", 1, "delta", "First"));
    await expect(page.getByTestId("turn-1-text")).toHaveText("First");

    await page.getByRole("button", { name: "Add turn" }).click();
    await expect(page.getByTestId("turn-2-status")).toHaveText("open");
    await expect.poll(() => eventServer.connectionsFor("workflow-1", "turn-1").map((item) => item.afterSeq)).toEqual([0, 1]);
    eventServer.connectionsFor("workflow-1", "turn-1").at(-1)!.response.destroy();
    await expect.poll(() => eventServer.connectionsFor("workflow-1", "turn-1").map((item) => item.afterSeq)).toEqual([0, 1, 1]);
    eventServer.publish(presentationEvent("workflow-1", "turn-1", 2, "delta", " answer"));
    eventServer.publish(presentationEvent("workflow-1", "turn-1", 3, "committed"));
    await expect(page.getByTestId("turn-1-text")).toHaveText("First answer");
    await expect(page.getByTestId("turn-1-status")).toHaveText("completed");

    await page.getByRole("button", { name: "Switch workflow" }).click();
    await expect(page.getByTestId("workflow")).toHaveText("workflow-2");
    await expect(page.getByTestId("turn-1-status")).toHaveText("open");
    await expect(page.getByTestId("turn-1-text")).toBeEmpty();
    expect(eventServer.connectionsFor("workflow-2", "turn-1").map((item) => item.afterSeq)).toEqual([0]);
    eventServer.publish(presentationEvent("workflow-2", "turn-1", 1, "delta", "Other workflow"));
    await expect(page.getByTestId("turn-1-text")).toHaveText("Other workflow");
  } finally {
    await eventServer.close();
  }
});

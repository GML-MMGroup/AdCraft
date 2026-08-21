import { describe, expect, it, vi } from "vitest";

import { PythonInternalClient } from "../src/python-internal-client.js";

describe("PythonInternalClient", () => {
  it("uses internal auth and no-store config retrieval", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          protocol_version: "1",
          provider: "OpenAI Compatible",
          model_id: "configured-model",
          model_policy_id: "character_designer.character_expert_brief.v1",
          base_url: "https://llm.example/v1",
          api_key: "private-key",
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    const client = new PythonInternalClient({
      baseUrl: "http://backend:8000",
      internalToken: "internal-token",
      fetchImpl,
    });

    const snapshot = await client.credential(
      "llm-default",
      "character_designer",
      "character_expert_brief",
      "character_designer.character_expert_brief.v1",
    );

    expect(snapshot.model_id).toBe("configured-model");
    expect(snapshot.model_policy_id).toBe(
      "character_designer.character_expert_brief.v1",
    );
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://backend:8000/internal/v1/agent-runtime-config/llm-default?agent_name=character_designer&operation=character_expert_brief&model_policy_id=character_designer.character_expert_brief.v1",
      expect.objectContaining({
        headers: expect.objectContaining({
          authorization: "Bearer internal-token",
          "cache-control": "no-store",
        }),
      }),
    );
  });

  it("forwards only canonical tool calls", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          protocol_version: "1",
          run_id: "arun_one",
          tool_call_id: "call_one",
          status: "completed",
          result: { accepted: true },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    const client = new PythonInternalClient({
      baseUrl: "http://backend:8000",
      internalToken: "internal-token",
      fetchImpl,
    });

    const result = await client.executeTool({
      protocol_version: "1",
      run_id: "arun_one",
      tool_call_id: "call_one",
      idempotency_key: "idem_one",
      tool_name: "submit_structured_result",
      arguments: {},
    });

    expect(result.status).toBe("completed");
    expect(fetchImpl).toHaveBeenCalledOnce();
  });
});

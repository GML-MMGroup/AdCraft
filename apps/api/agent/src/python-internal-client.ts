import type {
  AgentRunRequest,
  AgentToolCall,
  AgentToolResult,
} from "./generated/agent-runtime.js";

export interface AgentCredentialSnapshot {
  readonly protocol_version: "1";
  readonly provider: string;
  readonly model_id: string;
  readonly model_policy_id: string;
  readonly base_url: string;
  readonly api_key: string;
}

interface PythonInternalClientOptions {
  readonly baseUrl: string;
  readonly internalToken: string;
  readonly fetchImpl?: typeof fetch;
}

export class PythonInternalClient {
  readonly #baseUrl: string;
  readonly #internalToken: string;
  readonly #fetch: typeof fetch;

  constructor(options: PythonInternalClientOptions) {
    this.#baseUrl = options.baseUrl.replace(/\/$/, "");
    this.#internalToken = options.internalToken;
    this.#fetch = options.fetchImpl ?? fetch;
  }

  async credential(
    credentialRef: string,
    agentName: AgentRunRequest["agent_name"],
    operation: string,
    modelPolicyId: string,
  ): Promise<AgentCredentialSnapshot> {
    const query = new URLSearchParams({
      agent_name: agentName,
      operation,
      model_policy_id: modelPolicyId,
    });
    const response = await this.#fetch(
      `${this.#baseUrl}/internal/v1/agent-runtime-config/${encodeURIComponent(credentialRef)}?${query.toString()}`,
      {
        headers: {
          authorization: `Bearer ${this.#internalToken}`,
          "cache-control": "no-store",
        },
        signal: AbortSignal.timeout(5_000),
      },
    );
    const payload = await boundedJson(response);
    if (
      payload.protocol_version !== "1" ||
      typeof payload.model_id !== "string" ||
      typeof payload.model_policy_id !== "string" ||
      typeof payload.base_url !== "string" ||
      typeof payload.api_key !== "string" ||
      typeof payload.provider !== "string"
    ) {
      throw new Error("agent_protocol_mismatch");
    }
    return payload as unknown as AgentCredentialSnapshot;
  }

  async executeTool(call: AgentToolCall): Promise<AgentToolResult> {
    const response = await this.#fetch(`${this.#baseUrl}/internal/v1/agent-tools/execute`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${this.#internalToken}`,
        "content-type": "application/json",
      },
      body: JSON.stringify(call),
      signal: AbortSignal.timeout(10_000),
    });
    const payload = await boundedJson(response);
    if (
      payload.protocol_version !== "1" ||
      payload.run_id !== call.run_id ||
      payload.tool_call_id !== call.tool_call_id ||
      typeof payload.status !== "string"
    ) {
      throw new Error("agent_protocol_mismatch");
    }
    return payload as unknown as AgentToolResult;
  }
}

async function boundedJson(response: Response): Promise<Record<string, unknown>> {
  if (!response.ok) throw new Error(`agent_internal_request_failed:${response.status}`);
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.byteLength > 65_536) throw new Error("agent_protocol_mismatch");
  const payload: unknown = JSON.parse(new TextDecoder().decode(bytes));
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("agent_protocol_mismatch");
  }
  return payload as Record<string, unknown>;
}

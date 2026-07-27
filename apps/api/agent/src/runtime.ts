import type {
  AgentRunRequest,
  AgentRuntimeEvent,
} from "./generated/agent-runtime.js";
import type { RunBudget } from "./run-budget.js";

export type EventSink = (event: AgentRuntimeEvent) => Promise<void>;

export interface AgentModelAdapter {
  run(
    request: AgentRunRequest,
    signal: AbortSignal,
    emit: EventSink,
    budget?: RunBudget,
  ): Promise<Record<string, unknown>>;
}

export class FakeAgentModelAdapter implements AgentModelAdapter {
  async run(
    request: AgentRunRequest,
    signal: AbortSignal,
    emit: EventSink,
    budget?: RunBudget,
  ): Promise<Record<string, unknown>> {
    budget?.consumeTurn();
    if (signal.aborted) throw new DOMException("Run cancelled.", "AbortError");
    await emit(event(request, 0, "output_delta", { text: "fake-output" }));
    return { submission_id: `submission_${request.run_id}`, fake: true };
  }
}

export function event(
  request: AgentRunRequest,
  seq: number,
  eventType: AgentRuntimeEvent["event_type"],
  payload: Readonly<Record<string, unknown>>,
): AgentRuntimeEvent {
  return {
    protocol_version: "1",
    seq,
    run_id: request.run_id,
    agent_name: request.agent_name,
    event_type: eventType,
    created_at: new Date().toISOString(),
    payload,
  };
}

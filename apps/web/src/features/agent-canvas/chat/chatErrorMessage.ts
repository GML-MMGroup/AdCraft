const ERROR_COPY: Readonly<Record<string, string>> = {
  agent_runtime_unavailable:
    "The agent runtime is temporarily unavailable. Your input is preserved; try again shortly.",
  agent_deadline_exceeded:
    "The agent took too long to respond. Your input is preserved; retry when ready.",
  guidance_completion_invalid:
    "The guidance session is not ready to finish yet.",
};

export function agentCanvasChatErrorMessage(
  code: string,
  backendMessage: string | null,
): string {
  const message = backendMessage?.trim() || ERROR_COPY[code] || "The agent could not complete this request.";
  return `${code}: ${message}`;
}

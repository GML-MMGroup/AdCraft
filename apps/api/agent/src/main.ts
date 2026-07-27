import { createAgentRuntimeServer } from "./server.js";
import { PiModelAdapter } from "./pi-model-adapter.js";
import { PythonInternalClient } from "./python-internal-client.js";

const token = process.env.AGENT_RUNTIME_INTERNAL_TOKEN?.trim();
if (!token) {
  throw new Error("AGENT_RUNTIME_INTERNAL_TOKEN is required.");
}
const mode = process.env.AGENT_RUNTIME_MODE === "fake" ? "fake" : "real";
if (mode === "fake" && process.env.NODE_ENV === "production") {
  throw new Error("Fake Agent runtime mode is forbidden in production.");
}

const host = process.env.AGENT_RUNTIME_HOST?.trim() || "127.0.0.1";
const port = Number.parseInt(process.env.AGENT_RUNTIME_PORT ?? "8765", 10);
const pythonBaseUrl = process.env.AGENT_RUNTIME_PYTHON_BASE_URL?.trim() || "http://127.0.0.1:8000";
const adapter =
  mode === "real"
    ? new PiModelAdapter(
        new PythonInternalClient({
          baseUrl: pythonBaseUrl,
          internalToken: token,
        }),
      )
    : undefined;
const server = createAgentRuntimeServer({
  internalToken: token,
  mode,
  ...(adapter ? { adapter } : {}),
});
server.listen(port, host);

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.once(signal, () => {
    server.close(() => process.exit(0));
  });
}

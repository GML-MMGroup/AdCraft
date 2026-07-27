import { createAgentRuntimeServer } from "./server.js";
import { PiModelAdapter } from "./pi-model-adapter.js";
import { PythonInternalClient } from "./python-internal-client.js";
import { SkillBundleError } from "./skills.js";
import { startVerifiedServer } from "./startup.js";

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
await startVerifiedServer(server, port, host).catch((error: unknown) => {
  const code =
    error instanceof SkillBundleError
      ? error.code
      : "agent_runtime_startup_failed";
  console.error(`Agent runtime startup failed: ${code}.`);
  process.exit(1);
});

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.once(signal, () => {
    server.close(() => process.exit(0));
  });
}

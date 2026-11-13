import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import type { IncomingMessage } from "node:http";
import { API_METADATA_CACHE_CONTROL, isVersionedAgentIconRequest, isVersionedAssetContentRequest, mediaCacheControl, VERSIONED_AGENT_ICON_CACHE_CONTROL } from "./mediaCachePolicy";
import { resolveBackendOrigin } from "./src/config/devServer.ts";
import { agentRoleRetryPlugin } from "./agentRoleRetryPlugin.ts";

const FRONTEND_PORT = 5189;
const BACKEND_ORIGIN = resolveBackendOrigin(process.env.BACKEND_ORIGIN);

type ProxyWithResponseEvents = {
  on(event: "proxyRes", listener: (proxyResponse: IncomingMessage, request: IncomingMessage) => void): void;
};

function configureApiMetadataProxy(proxy: ProxyWithResponseEvents) {
  proxy.on("proxyRes", (proxyResponse, request) => {
    if (isVersionedAssetContentRequest(request.url ?? "")) {
      proxyResponse.headers["cache-control"] = mediaCacheControl(request.url ?? "");
      delete proxyResponse.headers.pragma;
      return;
    }
    proxyResponse.headers["cache-control"] = API_METADATA_CACHE_CONTROL;
    proxyResponse.headers.pragma = "no-cache";
  });
}

function configureMediaProxy(proxy: ProxyWithResponseEvents) {
  proxy.on("proxyRes", (proxyResponse, request) => {
    proxyResponse.headers["cache-control"] = mediaCacheControl(request.url ?? "");
  });
}

function configureAgentIconCache() {
  return {
    name: "adcraft-agent-icon-cache",
    configureServer(server: { middlewares: { use: (handler: (request: IncomingMessage & { url?: string }, response: { setHeader: (name: string, value: string) => void }, next: () => void) => void) => void } }) {
      server.middlewares.use((request, response, next) => {
        if (isVersionedAgentIconRequest(request.url ?? "")) {
          response.setHeader("Cache-Control", VERSIONED_AGENT_ICON_CACHE_CONTROL);
        }
        next();
      });
    },
    configurePreviewServer(server: { middlewares: { use: (handler: (request: IncomingMessage & { url?: string }, response: { setHeader: (name: string, value: string) => void }, next: () => void) => void) => void } }) {
      server.middlewares.use((request, response, next) => {
        if (isVersionedAgentIconRequest(request.url ?? "")) {
          response.setHeader("Cache-Control", VERSIONED_AGENT_ICON_CACHE_CONTROL);
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), configureAgentIconCache(), agentRoleRetryPlugin()],
  resolve: {
    alias: {
      "@/stores/agent-store": fileURLToPath(new URL("./cutia/adapters/agent-store.ts", import.meta.url)),
      "@/lib/tts/service": fileURLToPath(new URL("./cutia/adapters/tts.ts", import.meta.url)),
      "@/lib/transcription/import": fileURLToPath(new URL("./cutia/adapters/captions.ts", import.meta.url)),
      "@/components/editor/panels/properties/text-speech-panel": fileURLToPath(new URL("./cutia/adapters/text-speech-panel.tsx", import.meta.url)),
      "@i18next-toolkit/nextjs-approuter": fileURLToPath(new URL("./cutia/adapters/i18n.tsx", import.meta.url)),
      "next/image": fileURLToPath(new URL("./cutia/adapters/image.tsx", import.meta.url)),
      "@cutia/ui/icons": fileURLToPath(new URL("./vendor/cutia/ui/icons/index.tsx", import.meta.url)),
      "@": fileURLToPath(new URL("./vendor/cutia/src", import.meta.url)),
    },
  },
  build: {
    rollupOptions: {
      input: { app: "index.html", cutia: "cutia-editor.html" },
      output: {
        manualChunks(id) {
          if (id.includes("vite/preload-helper")) {
            return "vite-runtime";
          }
          if (
            id.includes("node_modules/react") ||
            id.includes("node_modules/react-dom") ||
            id.includes("node_modules/react-router-dom")
          ) {
            return "vendor-react";
          }
          if (id.includes("node_modules/@xyflow/react")) {
            return "vendor-react-flow";
          }
          if (id.includes("node_modules/@xzdarcy/react-timeline-editor")) {
            return "timeline-editor";
          }
          return undefined;
        },
      },
    },
  },
  server: {
    host: "0.0.0.0",
    port: FRONTEND_PORT,
    strictPort: true,
    headers: {
      "Cache-Control": "no-store, no-cache, must-revalidate, proxy-revalidate",
      Pragma: "no-cache",
      Expires: "0",
    },
    watch: {
      usePolling: true,
      interval: 1000,
      ignored: ["**/node_modules/**", "**/dist/**"],
    },
    proxy: {
      "^/api(?=/|\\?|$)": {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
        configure: configureApiMetadataProxy,
      },
      "/media": {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
        configure: configureMediaProxy,
      },
    },
  },
  preview: {
    host: "0.0.0.0",
    port: FRONTEND_PORT,
    strictPort: true,
  },
});

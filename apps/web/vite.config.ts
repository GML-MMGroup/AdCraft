import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import type { IncomingMessage } from "node:http";
import { API_METADATA_CACHE_CONTROL, isVersionedAgentIconRequest, isVersionedAssetContentRequest, mediaCacheControl, VERSIONED_AGENT_ICON_CACHE_CONTROL } from "./mediaCachePolicy";
import { resolveBackendOrigin } from "./src/config/devServer.ts";

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
  plugins: [react(), configureAgentIconCache()],
  build: {
    rollupOptions: {
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

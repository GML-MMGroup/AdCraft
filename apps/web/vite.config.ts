import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import type { IncomingMessage } from "node:http";
import { API_METADATA_CACHE_CONTROL, mediaCacheControl } from "./mediaCachePolicy";

const FRONTEND_PORT = 5189;
const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN?.trim() || "http://127.0.0.1:8888";

type ProxyWithResponseEvents = {
  on(event: "proxyRes", listener: (proxyResponse: IncomingMessage, request: IncomingMessage) => void): void;
};

function configureApiMetadataProxy(proxy: ProxyWithResponseEvents) {
  proxy.on("proxyRes", (proxyResponse) => {
    proxyResponse.headers["cache-control"] = API_METADATA_CACHE_CONTROL;
    proxyResponse.headers.pragma = "no-cache";
  });
}

function configureMediaProxy(proxy: ProxyWithResponseEvents) {
  proxy.on("proxyRes", (proxyResponse, request) => {
    proxyResponse.headers["cache-control"] = mediaCacheControl(request.url ?? "");
  });
}

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
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
          if (
            id.includes("/src/AppContextValue") ||
            id.includes("/src/icons") ||
            id.includes("/src/api/client") ||
            id.includes("/src/api/workflowNormalizers") ||
            id.includes("/src/projects/") ||
            id.includes("/src/storage/") ||
            id.includes("/src/workflow/sessionGuards") ||
            id.includes("/src/workflow/videoPosterCache") ||
            id.includes("/src/workflowShared") ||
            id.includes("/src/workflowSchema")
          ) {
            return "app-core";
          }
          if (
            id.includes("/src/features/workflow/v2/screenplay/V2Screenplay") ||
            id.includes("/src/features/workflow/v2/screenplay/screenplayUiHelpers")
          ) {
            return "screenplay-editor";
          }
          if (
            (id.includes("/src/features/workflow/")
              && !id.includes("/src/features/workflow/final-composition/"))
            || id.includes("/src/workflow-v2/")
          ) {
            return "workflow";
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
      "/api": {
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

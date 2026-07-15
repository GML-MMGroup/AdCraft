import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const FRONTEND_PORT = 5189;

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
          if (id.includes("/src/features/workflow/") || id.includes("/src/workflow-v2/")) {
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
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/media": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: "0.0.0.0",
    port: FRONTEND_PORT,
    strictPort: true,
  },
});

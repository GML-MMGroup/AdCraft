import { defineConfig } from "vite";
import base from "./vite.config.ts";
export default defineConfig({
  ...base,
  cacheDir: ".vite-conversation-preview",
  plugins: [...(base.plugins ?? []), {
    name: "conversation-design-preview-route",
    configureServer(server) {
      server.middlewares.use((request, _response, next) => {
        const url = new URL(request.url ?? "/", "http://localhost");
        if (url.pathname === "/design-lab/conversation") request.url = `/tests/browser/conversation-design-mock.html${url.search}`;
        next();
      });
    },
  }],
  server: { ...base.server, port: 5211, watch: { ...base.server?.watch, ignored: ["**/node_modules/**", "**/dist/**", "**/.vite-conversation-preview/**"] } },
});

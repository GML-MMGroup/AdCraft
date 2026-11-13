import { defineConfig } from "vite";
import base from "./vite.config.ts";

export default defineConfig({
  ...base,
  cacheDir: ".vite-skill-gallery",
  plugins: [...(base.plugins ?? []), {
    name: "skill-gallery-preview-route",
    configureServer(server) {
      server.middlewares.use((request, _response, next) => {
        const url = new URL(request.url ?? "/", "http://localhost");
        if (url.pathname === "/design-lab/skills") request.url = `/tests/browser/brand-skill-gallery-mock.html${url.search}`;
        next();
      });
    },
  }],
  server: {
    ...base.server,
    port: 5210,
    watch: { ...base.server?.watch, ignored: ["**/node_modules/**", "**/dist/**", "**/.vite-skill-gallery/**"] },
  },
});

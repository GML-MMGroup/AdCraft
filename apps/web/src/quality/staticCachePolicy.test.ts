import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const nginxConfig = readFileSync(resolve(process.cwd(), "../../deploy/nginx.conf"), "utf8");
const viteHashedAsset = /^\/assets\/(?:.*\/)?[^/]+-[a-z0-9_-]{8,}\.(?:js|mjs|css|map|woff2?|ttf|otf|eot|svg|png|jpe?g|gif|webp|avif|ico)$/i;

describe("static cache policy", () => {
  it("caches only Vite-hashed build assets for one year with immutable semantics", () => {
    expect(nginxConfig).toMatch(/location ~\* \^\/assets\/\(\?:\.\*\/\)\?\[\^\/\]\+-\[a-z0-9_-\]\{8,\}\\\.\(\?:js\|mjs\|css\|map\|woff2\?\|ttf\|otf\|eot\|svg\|png\|jpe\?g\|gif\|webp\|avif\|ico\)\$/);
    expect(nginxConfig).toMatch(/location ~\* \^\/assets\/[\s\S]*?try_files \$uri =404;[\s\S]*?Cache-Control "public, max-age=31536000, immutable"/);
    expect(nginxConfig).not.toMatch(/location ~\* \^\/assets\/[\s\S]*?expires 1y;/);
    expect(viteHashedAsset.test("/assets/index-CwF9d8Q_.js")).toBe(true);
    expect(viteHashedAsset.test("/assets/fonts/inter-R8uP5fH2.woff2")).toBe(true);
    expect(viteHashedAsset.test("/assets/bg.jpg")).toBe(false);
    expect(viteHashedAsset.test("/assets/logo.svg")).toBe(false);
  });

  it("makes stable assets revalidate instead of treating the whole directory as immutable", () => {
    expect(nginxConfig).toMatch(/location \/assets\/ \{[\s\S]*?try_files \$uri =404;[\s\S]*?Cache-Control "public, max-age=300, must-revalidate"/);
    expect(nginxConfig).not.toMatch(/location \^~ \/assets\/ \{/);
  });

  it("requires index.html to revalidate while preserving media proxy semantics", () => {
    expect(nginxConfig).toMatch(/location = \/index\.html \{[\s\S]*?Cache-Control "no-cache, must-revalidate"/);
    expect(nginxConfig).toMatch(/location \/media\/ \{[\s\S]*?proxy_pass http:\/\/api:8000;[\s\S]*?proxy_buffering off;/);
  });
});

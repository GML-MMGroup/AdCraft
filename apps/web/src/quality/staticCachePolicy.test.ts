import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const nginxConfig = readFileSync(resolve(process.cwd(), "../../deploy/nginx.conf"), "utf8");

describe("static cache policy", () => {
  it("caches hashed build assets for one year with immutable semantics", () => {
    expect(nginxConfig).toMatch(/location \^~ \/assets\/ \{[\s\S]*?try_files \$uri =404;[\s\S]*?Cache-Control "public, max-age=31536000, immutable"/);
  });

  it("requires index.html to revalidate while preserving media proxy semantics", () => {
    expect(nginxConfig).toMatch(/location = \/index\.html \{[\s\S]*?Cache-Control "no-cache, must-revalidate"/);
    expect(nginxConfig).toMatch(/location \/media\/ \{[\s\S]*?proxy_pass http:\/\/api:8000;[\s\S]*?proxy_buffering off;/);
  });
});

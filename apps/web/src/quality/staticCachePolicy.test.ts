import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const nginxConfig = readFileSync(resolve(process.cwd(), "../../deploy/nginx.conf"), "utf8");

function regexLocation() {
  const match = nginxConfig.match(/location ~\* ("[^"\n]+"|\S+) \{([\s\S]*?)\n {4}\}/);
  if (!match) throw new Error("Expected an nginx regex location");
  const directiveToken = match[1];
  const regexSource = directiveToken.startsWith('"') ? directiveToken.slice(1, -1) : directiveToken;
  return { directiveToken, matcher: new RegExp(regexSource, "i"), body: match[2] };
}

function prefixLocation(path: string) {
  const escapedPath = path.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = nginxConfig.match(new RegExp(`location ${escapedPath} \\{([\\s\\S]*?)\\n    \\}`));
  if (!match) throw new Error(`Expected nginx location for ${path}`);
  return match[1];
}

describe("static cache policy", () => {
  it("quotes regex locations containing repetition braces for nginx grammar", () => {
    const { directiveToken } = regexLocation();

    expect(directiveToken).toContain("{8}");
    expect(directiveToken).toMatch(/^".*"$/);
    expect(nginxConfig).not.toMatch(/location ~\* [^"\s][^\n]*\{\d+\}/);
  });

  it("caches only Vite-hashed build assets for one year with immutable semantics", () => {
    const { matcher, body } = regexLocation();
    const generatedViteAssets = [
      "/assets/index-BeHgOQng.js",
      "/assets/ApiSpacePage-PDH3--sW.js",
      "/assets/timeline-editor-DqahOt6-.css",
      "/assets/fonts/inter-R8uP5fH2.woff2",
    ];
    const stableAssets = [
      "/assets/bg.jpg",
      "/assets/logo.svg",
      "/assets/logo-horizontal.svg",
      "/assets/banner-summerhero.webp",
      "/assets/index-CwF9d8Q.js",
      "/assets/index-CwF9d8Q_0.js",
    ];

    for (const path of generatedViteAssets) expect(path).toMatch(matcher);
    for (const path of stableAssets) expect(path).not.toMatch(matcher);
    expect(body).toContain("try_files $uri =404;");
    expect(body).toContain('add_header Cache-Control "public, max-age=31536000, immutable" always;');
    expect(body.match(/add_header Cache-Control/g)).toHaveLength(1);
    expect(body).not.toContain("expires ");
  });

  it("makes stable assets revalidate instead of treating the whole directory as immutable", () => {
    const body = prefixLocation("/assets/");

    expect(body).toContain("try_files $uri =404;");
    expect(body).toContain('add_header Cache-Control "public, max-age=300, must-revalidate" always;');
    expect(body.match(/add_header Cache-Control/g)).toHaveLength(1);
    expect(body).not.toContain("expires ");
    expect(nginxConfig).not.toMatch(/location \^~ \/assets\/ \{/);
  });

  it("requires index.html to revalidate while preserving media proxy semantics", () => {
    expect(nginxConfig).toMatch(/location = \/index\.html \{[\s\S]*?Cache-Control "no-cache, must-revalidate"/);
    expect(nginxConfig).toMatch(/location \/media\/ \{[\s\S]*?proxy_pass http:\/\/api:8000;[\s\S]*?proxy_buffering off;/);
  });
});

/* global console, process, URL */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const DIST_ASSETS = new URL("../../dist/assets/", import.meta.url);
const DIST_INDEX_HTML = new URL("../../dist/index.html", import.meta.url);
const MAX_MAIN_JS_BYTES = 650 * 1024;
const MAX_INITIAL_JS_BYTES = 475 * 1024;
const MAX_TOTAL_JS_BYTES = 1250 * 1024;
const MAX_CSS_BYTES = 180 * 1024;

function bytes(value) {
  return `${Math.round(value / 1024)} KiB`;
}

function listAssets() {
  try {
    return readdirSync(DIST_ASSETS).map((name) => {
      const path = join(DIST_ASSETS.pathname, name);
      return { name, size: statSync(path).size };
    });
  } catch {
    console.error("dist/assets is missing. Run npm run build before npm run perf:bundle.");
    process.exit(1);
  }
}

function readIndexHtml() {
  try {
    return readFileSync(DIST_INDEX_HTML, "utf8");
  } catch {
    console.error("dist/index.html is missing. Run npm run build before npm run perf:bundle.");
    process.exit(1);
  }
}

function initialJsNames(indexHtml) {
  const names = new Set();
  for (const match of indexHtml.matchAll(/<script\b[^>]*\bsrc="\/assets\/([^"]+\.js)"/g)) {
    names.add(match[1]);
  }
  for (const match of indexHtml.matchAll(/<link\b[^>]*\brel="modulepreload"[^>]*\bhref="\/assets\/([^"]+\.js)"/g)) {
    names.add(match[1]);
  }
  return names;
}

const assets = listAssets();
const indexHtml = readIndexHtml();
const jsAssets = assets.filter((asset) => asset.name.endsWith(".js"));
const cssAssets = assets.filter((asset) => asset.name.endsWith(".css"));
const mainJs = jsAssets.find((asset) => asset.name.startsWith("index-"));
const initialNames = initialJsNames(indexHtml);
const initialJs = jsAssets.filter((asset) => initialNames.has(asset.name));
const initialJsBytes = initialJs.reduce((sum, asset) => sum + asset.size, 0);
const totalJs = jsAssets.reduce((sum, asset) => sum + asset.size, 0);
const totalCss = cssAssets.reduce((sum, asset) => sum + asset.size, 0);

console.log("Bundle budget report");
for (const asset of assets.sort((a, b) => b.size - a.size)) {
  console.log(`- ${asset.name}: ${bytes(asset.size)}`);
}

const failures = [];
if (mainJs && mainJs.size > MAX_MAIN_JS_BYTES) {
  failures.push(`main JS ${mainJs.name} is ${bytes(mainJs.size)}, expected <= ${bytes(MAX_MAIN_JS_BYTES)}`);
}
if (initialJsBytes > MAX_INITIAL_JS_BYTES) {
  failures.push(`initial JS is ${bytes(initialJsBytes)}, expected <= ${bytes(MAX_INITIAL_JS_BYTES)}`);
}
for (const asset of initialJs) {
  if (asset.name.startsWith("workflow-") || asset.name.startsWith("vendor-react-flow-")) {
    failures.push(`initial modulepreload includes ${asset.name}; workflow canvas code should stay lazy`);
  }
}
if (totalJs > MAX_TOTAL_JS_BYTES) {
  failures.push(`total JS is ${bytes(totalJs)}, expected <= ${bytes(MAX_TOTAL_JS_BYTES)}`);
}
if (totalCss > MAX_CSS_BYTES) {
  failures.push(`total CSS is ${bytes(totalCss)}, expected <= ${bytes(MAX_CSS_BYTES)}`);
}

if (failures.length) {
  console.error("\nBundle budget failed:");
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log("\nBundle budget passed.");

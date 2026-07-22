/* global console, process, URL */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const DIST_ASSETS = new URL("../../dist/assets/", import.meta.url);
const DIST_INDEX_HTML = new URL("../../dist/index.html", import.meta.url);
const MAX_MAIN_JS_BYTES = 650 * 1024;
const MAX_INITIAL_JS_BYTES = 475 * 1024;
const MAX_TOTAL_JS_BYTES = 1280 * 1024;
const MAX_SCREENPLAY_EDITOR_JS_BYTES = 32 * 1024;
const MAX_FINAL_COMPOSITION_EDITOR_JS_BYTES = 96 * 1024;
const MAX_TIMELINE_EDITOR_JS_BYTES = 256 * 1024;
const MAX_CSS_BYTES = 180 * 1024;
const MAX_TIMELINE_EDITOR_CSS_BYTES = 6 * 1024;

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

function initialCssNames(indexHtml) {
  const names = new Set();
  for (const tag of indexHtml.matchAll(/<link\b[^>]*>/g)) {
    if (!/\brel="stylesheet"/.test(tag[0])) continue;
    const asset = tag[0].match(/\bhref="\/assets\/([^"]+\.css)"/);
    if (asset) names.add(asset[1]);
  }
  return names;
}

const assets = listAssets();
const indexHtml = readIndexHtml();
const jsAssets = assets.filter((asset) => asset.name.endsWith(".js"));
const cssAssets = assets.filter((asset) => asset.name.endsWith(".css"));
const mainJs = jsAssets.find((asset) => asset.name.startsWith("index-"));
const screenplayEditorJs = jsAssets.find((asset) => asset.name.startsWith("screenplay-editor-"));
const finalCompositionEditorJs = jsAssets.find((asset) => asset.name.startsWith("V2FinalCompositionEditor-"));
const timelineEditorJs = jsAssets.find((asset) => asset.name.startsWith("timeline-editor-"));
const timelineEditorCss = cssAssets.find((asset) => asset.name.startsWith("timeline-editor-"));
const featureJsAssets = [screenplayEditorJs, finalCompositionEditorJs, timelineEditorJs].filter(Boolean);
const featureJsNames = new Set(featureJsAssets.map((asset) => asset.name));
const initialNames = initialJsNames(indexHtml);
const initialCssAssetNames = initialCssNames(indexHtml);
const initialJs = jsAssets.filter((asset) => initialNames.has(asset.name));
const initialCss = cssAssets.filter((asset) => initialCssAssetNames.has(asset.name));
const initialJsBytes = initialJs.reduce((sum, asset) => sum + asset.size, 0);
const totalJs = jsAssets.reduce((sum, asset) => sum + asset.size, 0);
const coreJsBytes = jsAssets
  .filter((asset) => !featureJsNames.has(asset.name))
  .reduce((sum, asset) => sum + asset.size, 0);
const totalCss = cssAssets.reduce((sum, asset) => sum + asset.size, 0);
const coreCssBytes = initialCss.reduce((sum, asset) => sum + asset.size, 0);

console.log("Bundle budget report");
for (const asset of assets.sort((a, b) => b.size - a.size)) {
  console.log(`- ${asset.name}: ${bytes(asset.size)}`);
}
console.log(`- core JS total: ${bytes(coreJsBytes)}`);
console.log(`- all JS total: ${bytes(totalJs)}`);
console.log(`- core CSS total: ${bytes(coreCssBytes)}`);
console.log(`- all CSS total: ${bytes(totalCss)}`);

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
  if (featureJsNames.has(asset.name)) {
    failures.push(`initial modulepreload includes ${asset.name}; feature editor code should stay lazy`);
  }
}
if (coreJsBytes > MAX_TOTAL_JS_BYTES) {
  failures.push(`core JS is ${bytes(coreJsBytes)}, expected <= ${bytes(MAX_TOTAL_JS_BYTES)}`);
}
if (!screenplayEditorJs) {
  failures.push("screenplay editor lazy chunk is missing");
} else if (screenplayEditorJs.size > MAX_SCREENPLAY_EDITOR_JS_BYTES) {
  failures.push(`screenplay editor JS ${screenplayEditorJs.name} is ${bytes(screenplayEditorJs.size)}, expected <= ${bytes(MAX_SCREENPLAY_EDITOR_JS_BYTES)}`);
}
if (!finalCompositionEditorJs) {
  failures.push("final composition editor lazy chunk is missing");
} else if (finalCompositionEditorJs.size > MAX_FINAL_COMPOSITION_EDITOR_JS_BYTES) {
  failures.push(`final composition editor JS ${finalCompositionEditorJs.name} is ${bytes(finalCompositionEditorJs.size)}, expected <= ${bytes(MAX_FINAL_COMPOSITION_EDITOR_JS_BYTES)}`);
}
if (!timelineEditorJs) {
  failures.push("timeline editor lazy chunk is missing");
} else if (timelineEditorJs.size > MAX_TIMELINE_EDITOR_JS_BYTES) {
  failures.push(`timeline editor JS ${timelineEditorJs.name} is ${bytes(timelineEditorJs.size)}, expected <= ${bytes(MAX_TIMELINE_EDITOR_JS_BYTES)}`);
}
if (coreCssBytes > MAX_CSS_BYTES) {
  failures.push(`core CSS is ${bytes(coreCssBytes)}, expected <= ${bytes(MAX_CSS_BYTES)}`);
}
if (!timelineEditorCss) {
  failures.push("timeline editor lazy CSS chunk is missing");
} else if (timelineEditorCss.size > MAX_TIMELINE_EDITOR_CSS_BYTES) {
  failures.push(`timeline editor CSS ${timelineEditorCss.name} is ${bytes(timelineEditorCss.size)}, expected <= ${bytes(MAX_TIMELINE_EDITOR_CSS_BYTES)}`);
}

if (failures.length) {
  console.error("\nBundle budget failed:");
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log("\nBundle budget passed.");

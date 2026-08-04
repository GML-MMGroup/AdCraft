import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

const DEFAULT_DIST_DIRECTORY = new URL("../../dist/", import.meta.url).pathname;
const MAX_MAIN_JS_BYTES = 650 * 1024;
const MAX_INITIAL_JS_BYTES = 475 * 1024;
// The core total includes lazy route chunks such as the Project cover preview UI.
const MAX_TOTAL_JS_BYTES = 1281 * 1024;
const MAX_AGENT_CANVAS_ROUTE_JS_BYTES = 96 * 1024;
const MAX_AGENT_CANVAS_ROUTE_CSS_BYTES = 48 * 1024;
const MAX_VENDOR_REACT_FLOW_JS_BYTES = 220 * 1024;
const MAX_VENDOR_REACT_FLOW_CSS_BYTES = 20 * 1024;
const MAX_ASSET_ENTITY_VIEWER_JS_BYTES = 8 * 1024;
const MAX_CSS_BYTES = 16 * 1024;
const MAX_HOME_ROUTE_CSS_BYTES = 16 * 1024;

function bytes(value) {
  return `${Math.round(value / 1024)} KiB`;
}

function parseArguments(argumentsList) {
  let distDirectory = DEFAULT_DIST_DIRECTORY;

  for (let index = 0; index < argumentsList.length; index += 1) {
    const argument = argumentsList[index];
    if (argument !== "--dist") {
      console.error(`Unknown argument: ${argument}`);
      process.exit(1);
    }
    const value = argumentsList[index + 1];
    if (!value) {
      console.error("Missing value for --dist.");
      process.exit(1);
    }
    distDirectory = resolve(value);
    index += 1;
  }

  return {
    assetsDirectory: join(distDirectory, "assets"),
    manifestPath: join(distDirectory, ".vite", "manifest.json"),
  };
}

const { assetsDirectory, manifestPath } = parseArguments(process.argv.slice(2));

function listAssets() {
  try {
    return readdirSync(assetsDirectory).map((name) => {
      const path = join(assetsDirectory, name);
      return { name, size: statSync(path).size };
    });
  } catch {
    console.error("dist/assets is missing. Run npm run build before npm run perf:bundle.");
    process.exit(1);
  }
}

function readManifest() {
  try {
    return JSON.parse(readFileSync(manifestPath, "utf8"));
  } catch {
    console.error("dist/.vite/manifest.json is missing. Run npm run build before npm run perf:bundle.");
    process.exit(1);
  }
}

function staticManifestEntries(manifest, rootEntryName) {
  const entries = new Set();
  const queue = [rootEntryName];
  while (queue.length) {
    const entryName = queue.shift();
    if (!entryName || entries.has(entryName)) continue;
    const entry = manifest[entryName];
    if (!entry) {
      console.error(`Vite manifest is missing ${entryName}. Run npm run build before npm run perf:bundle.`);
      process.exit(1);
    }
    entries.add(entryName);
    for (const importedEntry of entry.imports ?? []) queue.push(importedEntry);
  }
  return [...entries].map((entryName) => manifest[entryName]);
}

function assetName(manifestFile) {
  return manifestFile.replace(/^assets\//, "");
}

function manifestEntryName(manifest, sourcePath, chunkName) {
  if (manifest[sourcePath]) return sourcePath;

  return Object.entries(manifest).find(([, entry]) => (
    entry.name === chunkName
    || assetName(entry.file).startsWith(`${chunkName}-`)
  ))?.[0];
}

const assets = listAssets();
const manifest = readManifest();
const homeEntry = manifest["src/pages/HomePage.tsx"];
const initialEntries = staticManifestEntries(manifest, "index.html");
const homeEntries = homeEntry ? staticManifestEntries(manifest, "src/pages/HomePage.tsx") : [];
const jsAssets = assets.filter((asset) => asset.name.endsWith(".js"));
const cssAssets = assets.filter((asset) => asset.name.endsWith(".css"));
const mainJs = jsAssets.find((asset) => asset.name.startsWith("index-"));
const agentCanvasRouteJs = jsAssets.find((asset) => asset.name.startsWith("WorkflowPage-"));
const agentCanvasRouteCss = cssAssets.find((asset) => asset.name.startsWith("WorkflowPage-"));
const vendorReactFlowJs = jsAssets.find((asset) => asset.name.startsWith("vendor-react-flow-"));
const vendorReactFlowCss = cssAssets.find((asset) => asset.name.startsWith("vendor-react-flow-"));
const assetEntityViewerJs = jsAssets.find((asset) => asset.name.startsWith("AssetEntityViewer-"));
// The asset viewer is loaded only after a user opens an asset card.
const featureJsAssets = [
  agentCanvasRouteJs,
  vendorReactFlowJs,
  assetEntityViewerJs,
].filter(Boolean);
const featureJsNames = new Set(featureJsAssets.map((asset) => asset.name));
const initialNames = new Set(initialEntries.map((entry) => assetName(entry.file)));
const initialCssAssetNames = new Set(initialEntries.flatMap((entry) => (entry.css ?? []).map(assetName)));
const initialJs = jsAssets.filter((asset) => initialNames.has(asset.name));
const initialCss = cssAssets.filter((asset) => initialCssAssetNames.has(asset.name));
const homeRouteCssNames = new Set(homeEntries.flatMap((entry) => (entry.css ?? []).map(assetName)));
// Core CSS has its own budget; the Home limit covers incremental CSS after the initial entry loads.
for (const initialCssAssetName of initialCssAssetNames) homeRouteCssNames.delete(initialCssAssetName);
const homeRouteCss = cssAssets.filter((asset) => homeRouteCssNames.has(asset.name));
const initialJsBytes = initialJs.reduce((sum, asset) => sum + asset.size, 0);
const totalJs = jsAssets.reduce((sum, asset) => sum + asset.size, 0);
const coreJsBytes = jsAssets
  .filter((asset) => !featureJsNames.has(asset.name))
  .reduce((sum, asset) => sum + asset.size, 0);
const totalCss = cssAssets.reduce((sum, asset) => sum + asset.size, 0);
const coreCssBytes = initialCss.reduce((sum, asset) => sum + asset.size, 0);
const homeRouteCssBytes = homeRouteCss.reduce((sum, asset) => sum + asset.size, 0);
const agentCanvasEntryName = manifestEntryName(
  manifest,
  "src/pages/WorkflowPage.tsx",
  "WorkflowPage",
);
const agentCanvasEntry = manifest[agentCanvasEntryName];
const agentCanvasStaticFiles = agentCanvasEntry
  ? new Set(staticManifestEntries(manifest, agentCanvasEntryName).map((entry) => assetName(entry.file)))
  : new Set();

console.log("Bundle budget report");
for (const asset of assets.sort((a, b) => b.size - a.size)) {
  console.log(`- ${asset.name}: ${bytes(asset.size)}`);
}
console.log(`- core JS total: ${bytes(coreJsBytes)}`);
console.log(`- all JS total: ${bytes(totalJs)}`);
console.log(`- core CSS total: ${bytes(coreCssBytes)}`);
console.log(`- Home route CSS total: ${bytes(homeRouteCssBytes)}`);
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
if (!agentCanvasRouteJs || !agentCanvasEntry) {
  failures.push("Agent Canvas Workflow route chunk is missing");
} else if (agentCanvasRouteJs.size > MAX_AGENT_CANVAS_ROUTE_JS_BYTES) {
  failures.push(`Agent Canvas route JS ${agentCanvasRouteJs.name} is ${bytes(agentCanvasRouteJs.size)}, expected <= ${bytes(MAX_AGENT_CANVAS_ROUTE_JS_BYTES)}`);
}
if (!vendorReactFlowJs) {
  failures.push("React Flow lazy vendor chunk is missing");
} else if (vendorReactFlowJs.size > MAX_VENDOR_REACT_FLOW_JS_BYTES) {
  failures.push(`React Flow vendor JS ${vendorReactFlowJs.name} is ${bytes(vendorReactFlowJs.size)}, expected <= ${bytes(MAX_VENDOR_REACT_FLOW_JS_BYTES)}`);
}
if (
  agentCanvasRouteJs
  && vendorReactFlowJs
  && !agentCanvasStaticFiles.has(vendorReactFlowJs.name)
) {
  failures.push("Agent Canvas Workflow route does not own the React Flow vendor chunk");
}
if (!assetEntityViewerJs) {
  failures.push("asset entity viewer lazy chunk is missing");
} else if (assetEntityViewerJs.size > MAX_ASSET_ENTITY_VIEWER_JS_BYTES) {
  failures.push(`asset entity viewer JS ${assetEntityViewerJs.name} is ${bytes(assetEntityViewerJs.size)}, expected <= ${bytes(MAX_ASSET_ENTITY_VIEWER_JS_BYTES)}`);
}
if (coreCssBytes > MAX_CSS_BYTES) {
  failures.push(`core CSS is ${bytes(coreCssBytes)}, expected <= ${bytes(MAX_CSS_BYTES)}`);
}
if (!homeEntry || !homeRouteCss.length) {
  failures.push("Home route CSS chunk is missing");
} else if (homeRouteCssBytes > MAX_HOME_ROUTE_CSS_BYTES) {
  failures.push(`Home route CSS is ${bytes(homeRouteCssBytes)}, expected <= ${bytes(MAX_HOME_ROUTE_CSS_BYTES)}`);
}
if (!agentCanvasRouteCss) {
  failures.push("Agent Canvas Workflow route CSS chunk is missing");
} else if (agentCanvasRouteCss.size > MAX_AGENT_CANVAS_ROUTE_CSS_BYTES) {
  failures.push(`Agent Canvas route CSS ${agentCanvasRouteCss.name} is ${bytes(agentCanvasRouteCss.size)}, expected <= ${bytes(MAX_AGENT_CANVAS_ROUTE_CSS_BYTES)}`);
}
if (!vendorReactFlowCss) {
  failures.push("React Flow vendor CSS chunk is missing");
} else if (vendorReactFlowCss.size > MAX_VENDOR_REACT_FLOW_CSS_BYTES) {
  failures.push(`React Flow vendor CSS ${vendorReactFlowCss.name} is ${bytes(vendorReactFlowCss.size)}, expected <= ${bytes(MAX_VENDOR_REACT_FLOW_CSS_BYTES)}`);
}

if (failures.length) {
  console.error("\nBundle budget failed:");
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log("\nBundle budget passed.");

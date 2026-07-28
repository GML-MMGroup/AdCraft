import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

const DEFAULT_DIST_DIRECTORY = new URL("../../dist/", import.meta.url).pathname;
const MAX_MAIN_JS_BYTES = 650 * 1024;
const MAX_INITIAL_JS_BYTES = 475 * 1024;
// The core total includes lazy route chunks such as the Project cover preview UI.
const MAX_TOTAL_JS_BYTES = 1281 * 1024;
const MAX_SCREENPLAY_EDITOR_JS_BYTES = 32 * 1024;
const MAX_FINAL_COMPOSITION_EDITOR_JS_BYTES = 96 * 1024;
const MAX_SHOT_TIMELINE_JS_BYTES = 16 * 1024;
const MAX_TIMELINE_EDITOR_JS_BYTES = 256 * 1024;
const MAX_ASSET_ENTITY_VIEWER_JS_BYTES = 8 * 1024;
const MAX_HOME_COSMIC_RENDERER_JS_BYTES = 24 * 1024;
const MAX_VENDOR_THREE_JS_BYTES = 700 * 1024;
const MAX_CSS_BYTES = 16 * 1024;
const MAX_HOME_ROUTE_CSS_BYTES = 16 * 1024;
const MAX_TIMELINE_EDITOR_CSS_BYTES = 6 * 1024;

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
const screenplayEditorJs = jsAssets.find((asset) => asset.name.startsWith("screenplay-editor-"));
const finalCompositionEditorJs = jsAssets.find((asset) => asset.name.startsWith("V2FinalCompositionEditor-"));
const shotTimelineJs = jsAssets.find((asset) => asset.name.startsWith("V2ShotTimeline-"));
const timelineEditorJs = jsAssets.find((asset) => asset.name.startsWith("timeline-editor-"));
const assetEntityViewerJs = jsAssets.find((asset) => asset.name.startsWith("AssetEntityViewer-"));
const homeCosmicRendererJs = jsAssets.find((asset) => asset.name.startsWith("homeCosmicRenderer-"));
const vendorThreeJs = jsAssets.find((asset) => asset.name.startsWith("vendor-three-"));
const timelineEditorCss = cssAssets.find((asset) => asset.name.startsWith("timeline-editor-"));
// The asset viewer is loaded only after a user opens an asset card.
const featureJsAssets = [
  screenplayEditorJs,
  finalCompositionEditorJs,
  shotTimelineJs,
  timelineEditorJs,
  assetEntityViewerJs,
  homeCosmicRendererJs,
  vendorThreeJs,
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
const finalCompositionEntryName = manifestEntryName(
  manifest,
  "src/features/workflow/final-composition/V2FinalCompositionEditor.tsx",
  "V2FinalCompositionEditor",
);
const shotTimelineEntryName = manifestEntryName(
  manifest,
  "src/features/workflow/final-composition/V2ShotTimeline.tsx",
  "V2ShotTimeline",
);
const finalCompositionEntry = manifest[finalCompositionEntryName];
const shotTimelineEntry = manifest[shotTimelineEntryName];
const finalCompositionStaticFiles = finalCompositionEntry
  ? new Set(staticManifestEntries(manifest, finalCompositionEntryName).map((entry) => assetName(entry.file)))
  : new Set();
const shotTimelineStaticFiles = shotTimelineEntry
  ? new Set(staticManifestEntries(manifest, shotTimelineEntryName).map((entry) => assetName(entry.file)))
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
if (!shotTimelineJs || !shotTimelineEntry) {
  failures.push("advanced shot timeline lazy chunk is missing");
} else if (shotTimelineJs.size > MAX_SHOT_TIMELINE_JS_BYTES) {
  failures.push(`advanced shot timeline JS ${shotTimelineJs.name} is ${bytes(shotTimelineJs.size)}, expected <= ${bytes(MAX_SHOT_TIMELINE_JS_BYTES)}`);
}
if (
  finalCompositionEntry
  && !finalCompositionEntry.dynamicImports?.includes(shotTimelineEntryName)
) {
  failures.push("final composition editor must dynamically import the advanced shot timeline");
}
if (
  shotTimelineJs
  && finalCompositionStaticFiles.has(shotTimelineJs.name)
) {
  failures.push("final composition editor statically includes the advanced shot timeline");
}
if (
  timelineEditorJs
  && finalCompositionStaticFiles.has(timelineEditorJs.name)
) {
  failures.push("final composition editor statically includes the timeline editor vendor");
}
if (
  timelineEditorJs
  && shotTimelineEntry
  && !shotTimelineStaticFiles.has(timelineEditorJs.name)
) {
  failures.push("advanced shot timeline does not own the timeline editor vendor");
}
if (!timelineEditorJs) {
  failures.push("timeline editor lazy chunk is missing");
} else if (timelineEditorJs.size > MAX_TIMELINE_EDITOR_JS_BYTES) {
  failures.push(`timeline editor JS ${timelineEditorJs.name} is ${bytes(timelineEditorJs.size)}, expected <= ${bytes(MAX_TIMELINE_EDITOR_JS_BYTES)}`);
}
if (!assetEntityViewerJs) {
  failures.push("asset entity viewer lazy chunk is missing");
} else if (assetEntityViewerJs.size > MAX_ASSET_ENTITY_VIEWER_JS_BYTES) {
  failures.push(`asset entity viewer JS ${assetEntityViewerJs.name} is ${bytes(assetEntityViewerJs.size)}, expected <= ${bytes(MAX_ASSET_ENTITY_VIEWER_JS_BYTES)}`);
}
if (!homeCosmicRendererJs) {
  failures.push("Home cosmic renderer lazy chunk is missing");
} else if (homeCosmicRendererJs.size > MAX_HOME_COSMIC_RENDERER_JS_BYTES) {
  failures.push(`Home cosmic renderer JS ${homeCosmicRendererJs.name} is ${bytes(homeCosmicRendererJs.size)}, expected <= ${bytes(MAX_HOME_COSMIC_RENDERER_JS_BYTES)}`);
}
if (!vendorThreeJs) {
  failures.push("Three.js lazy vendor chunk is missing");
} else if (vendorThreeJs.size > MAX_VENDOR_THREE_JS_BYTES) {
  failures.push(`Three.js vendor JS ${vendorThreeJs.name} is ${bytes(vendorThreeJs.size)}, expected <= ${bytes(MAX_VENDOR_THREE_JS_BYTES)}`);
}
if (coreCssBytes > MAX_CSS_BYTES) {
  failures.push(`core CSS is ${bytes(coreCssBytes)}, expected <= ${bytes(MAX_CSS_BYTES)}`);
}
if (!homeEntry || !homeRouteCss.length) {
  failures.push("Home route CSS chunk is missing");
} else if (homeRouteCssBytes > MAX_HOME_ROUTE_CSS_BYTES) {
  failures.push(`Home route CSS is ${bytes(homeRouteCssBytes)}, expected <= ${bytes(MAX_HOME_ROUTE_CSS_BYTES)}`);
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

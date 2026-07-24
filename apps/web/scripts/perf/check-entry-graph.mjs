import { readFileSync } from "node:fs";

const DEFAULT_MANIFEST = new URL("../../dist/.vite/manifest.json", import.meta.url);
const DEFAULT_ENTRY = "index.html";

function usage(message) {
  if (message) console.error(message);
  console.error("Usage: node scripts/perf/check-entry-graph.mjs [--manifest path] [--entry manifest-entry] [--json]");
  process.exit(1);
}

function parseArguments(argumentsList) {
  const options = {
    entry: DEFAULT_ENTRY,
    json: false,
    manifestPath: DEFAULT_MANIFEST.pathname,
  };

  for (let index = 0; index < argumentsList.length; index += 1) {
    const argument = argumentsList[index];
    if (argument === "--json") {
      options.json = true;
      continue;
    }
    if (argument === "--entry" || argument === "--manifest") {
      const value = argumentsList[index + 1];
      if (!value) usage(`Missing value for ${argument}.`);
      options[argument === "--entry" ? "entry" : "manifestPath"] = value;
      index += 1;
      continue;
    }
    usage(`Unknown argument: ${argument}`);
  }

  return options;
}

function readManifest(manifestPath) {
  try {
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
      throw new Error("manifest must be an object");
    }
    return manifest;
  } catch (error) {
    console.error(`Unable to read Vite manifest at ${manifestPath}: ${error.message}`);
    process.exit(1);
  }
}

function entryGraph(manifest, entry) {
  if (!manifest[entry]) usage(`Vite manifest does not contain entry: ${entry}`);

  const modules = [];
  const visited = new Set();
  const queue = [entry];
  while (queue.length) {
    const moduleId = queue.shift();
    if (visited.has(moduleId)) continue;
    const module = manifest[moduleId];
    if (!module) usage(`Vite manifest entry ${entry} references missing module: ${moduleId}`);

    visited.add(moduleId);
    modules.push(moduleId);
    for (const dependency of [...(module.imports ?? []), ...(module.dynamicImports ?? [])]) {
      if (!visited.has(dependency)) queue.push(dependency);
    }
  }

  return { entry, modules };
}

const options = parseArguments(process.argv.slice(2));
const report = entryGraph(readManifest(options.manifestPath), options.entry);

if (options.json) {
  console.log(JSON.stringify(report));
} else {
  console.log(`Entry graph for ${report.entry}`);
  for (const moduleId of report.modules) console.log(`- ${moduleId}`);
}

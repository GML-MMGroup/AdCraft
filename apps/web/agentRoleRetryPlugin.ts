import path from "node:path";
import type { Plugin } from "vite";

const suffix = "?agent-role-retry";
const prefix = "\0adcraft-role-retry:";

/** One explicit retry URL for the same compiled chunk, without duplicating artwork. */
export function agentRoleRetryPlugin(): Plugin {
  let root = "";
  let build = false;
  return {
    name: "adcraft-role-retry",
    enforce: "pre",
    configResolved(config) { root = config.root; build = config.command === "build"; },
    async resolveId(source, importer) {
      if (!source.endsWith(suffix)) return null;
      const resolved = await this.resolve(source.slice(0, -suffix.length), importer, { skipSelf: true });
      return resolved ? prefix + resolved.id : null;
    },
    load(id) {
      if (!id.startsWith(prefix)) return null;
      const source = id.slice(prefix.length);
      const url = build
        ? `import.meta.ROLLUP_FILE_URL_${this.emitFile({ type: "chunk", id: source, preserveSignature: "strict" })}`
        : JSON.stringify(`/${path.relative(root, source).split(path.sep).join("/")}`);
      return `export default () => import(/* @vite-ignore */ ${url} + "?role-artwork-retry=1").then(module => module.default);`;
    },
  };
}

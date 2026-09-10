import { readFileSync } from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { SceneDesignerArtwork } from "../src/features/agent-canvas/chat/agent-role-animation/roles/SceneDesignerArtwork.tsx";

const poster = renderToStaticMarkup(React.createElement("svg", { viewBox: "0 0 512 512", xmlns: "http://www.w3.org/2000/svg" }, React.createElement(SceneDesignerArtwork, { idPrefix: "scene-poster" })));
if (process.argv.includes("--check")) {
  const actual = readFileSync(new URL("../public/imgs/agent-role-icons/scene-designer-20260906-atlas-replica.svg", import.meta.url), "utf8").trim();
  if (actual !== poster) throw new Error("Scene Designer poster is stale; render and apply the canonical SVG.");
  console.log("Scene Designer poster matches canonical Idle artwork.");
} else {
  console.log(poster);
}

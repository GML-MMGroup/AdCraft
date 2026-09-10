import { readFileSync } from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { CharacterDesignerArtwork } from "../src/features/agent-canvas/chat/agent-role-animation/roles/CharacterDesignerArtwork.tsx";

// Print deterministic SVG for apply_patch, or verify the checked-in artifact.
const poster = renderToStaticMarkup(React.createElement("svg", { viewBox: "0 0 512 512", xmlns: "http://www.w3.org/2000/svg" }, React.createElement(CharacterDesignerArtwork, { idPrefix: "character-poster" })));
if (process.argv.includes("--check")) {
  const actual = readFileSync(new URL("../public/imgs/agent-role-icons/character-designer-20260906-line-art.svg", import.meta.url), "utf8").trim();
  if (actual !== poster) throw new Error("Character Designer poster is stale; render and apply the canonical SVG.");
  console.log("Character Designer poster matches canonical Idle artwork.");
} else {
  console.log(poster);
}

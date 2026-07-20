import type { NodeCatalogItem, WorkflowEdge, WorkflowNode } from "../../../types.ts";
import type { NodeDefinition, NodeFamily, NodeLibraryFilter, NodePort, NodePortType, NodeTemplate } from "../types.ts";

const RECENT_NODE_TYPES_KEY = "ad-workflow-recent-node-types";

export const NODE_LIBRARY_FILTERS: NodeLibraryFilter[] = ["All", "Text", "Image", "Video", "Audio", "Recently Used"];

const STANDALONE_NODE_RUN_TYPES = new Set([
  "script",
  "product-generation",
  "character-generation",
  "scene-generation",
  "storyboard",
  "storyboard-video-generation",
  "bgm",
  "final-composition",
]);

export const nodeRegistry: NodeDefinition[] = [
  { node_type: "text", display_name: "Text Node", category: "Text", family: "Text", description: "Write prompts, briefs, scripts, or notes.", inputPorts: [], outputPorts: [port("output", "Output", "text")] },
  { node_type: "combine-text", display_name: "Combine Text", category: "Text", family: "Text", description: "Merge multiple upstream text outputs.", inputPorts: [port("text_inputs", "Text Inputs", "text", { required: true, multiple: true })], outputPorts: [port("output", "Output", "text")] },
  { node_type: "json-parse", display_name: "JSON Parse", category: "Text", family: "Text", description: "Convert JSON input into structured markdown text.", inputPorts: [port("json", "JSON", "json", { required: true })], outputPorts: [port("output", "Output", "text")] },

  { node_type: "image", display_name: "Image Asset", category: "Image", family: "Image", description: "Upload or reference an image asset.", inputPorts: [], outputPorts: [port("output_assets", "Output Assets", "image")] },
  { node_type: "image_generation", display_name: "Image Generate", category: "Image", family: "Image", description: "Generate visual references from prompt and image inputs.", inputPorts: [port("prompt", "Prompt", "prompt", { required: true }), port("reference_image", "Reference Image", "image")], outputPorts: [port("output_assets", "Output Assets", "image")] },
  { node_type: "product-generation", display_name: "Product Generation", category: "Image", family: "Image", description: "Generate product visuals from strict product references.", inputPorts: [port("prompt", "Product Prompt", "prompt", { required: true }), port("script", "Script", "text"), port("product_reference", "Product Reference", "image", { multiple: true })], outputPorts: [port("output_assets", "Output Assets", "image")] },
  { node_type: "character-generation", display_name: "Character Generation", category: "Image", family: "Image", description: "Generate character visual reference assets from the script and prompt.", inputPorts: [port("prompt", "Character Prompt", "prompt", { required: true }), port("script", "Script", "text"), port("character_reference", "Character Ref", "image")], outputPorts: [port("output_assets", "Output Assets", "image")] },
  { node_type: "scene-generation", display_name: "Scene Generation", category: "Image", family: "Image", description: "Generate scene visual reference assets from the script and prompt.", inputPorts: [port("prompt", "Scene Prompt", "prompt", { required: true }), port("script", "Script", "text"), port("scene_reference", "Scene Ref", "image"), port("product_reference", "Product Reference", "image", { multiple: true })], outputPorts: [port("output_assets", "Output Assets", "image")] },
  { node_type: "first-last-frame", display_name: "First / Last Frame", category: "Image", family: "Image", description: "Extract first and last frame images from video.", inputPorts: [port("video", "Video", "video", { required: true })], outputPorts: [port("output_assets", "Output Assets", "image")] },
  { node_type: "extract-frame", display_name: "Extract Frame", category: "Image", family: "Image", description: "Extract selected frame images from video.", inputPorts: [port("video", "Video", "video", { required: true })], outputPorts: [port("output_assets", "Output Assets", "image")] },

  { node_type: "video", display_name: "Video Asset", category: "Video", family: "Video", description: "Upload or reference a video asset.", inputPorts: [], outputPorts: [port("output_assets", "Output Assets", "video")] },
  { node_type: "video_generation", display_name: "Video Generate", category: "Video", family: "Video", description: "Generate video from prompt, image, or reference video.", inputPorts: [port("prompt", "Prompt", "prompt"), port("image", "Image", "image"), port("reference_video", "Reference Video", "video")], outputPorts: [port("output_assets", "Output Assets", "video")] },
  { node_type: "storyboard-video-generation", display_name: "Storyboard Video", category: "Video", family: "Video", description: "Generate storyboard video segments.", inputPorts: [port("prompt", "Storyboard Prompt", "prompt"), port("storyboard_reference", "Storyboard Image", "image"), port("reference_video", "Reference Video", "video"), port("scene_reference", "Scene Reference", "image"), port("character_reference", "Character Reference", "image"), port("product_reference", "Product Reference", "image", { multiple: true })], outputPorts: [port("output_assets", "Output Assets", "video")] },
  { node_type: "trim-video", display_name: "Trim Video", category: "Video", family: "Video", description: "Trim video duration.", inputPorts: [port("video", "Video", "video", { required: true })], outputPorts: [port("output_assets", "Output Assets", "video")] },
  { node_type: "resize-video", display_name: "Resize Video", category: "Video", family: "Video", description: "Resize video resolution.", inputPorts: [port("video", "Video", "video", { required: true })], outputPorts: [port("output_assets", "Output Assets", "video")] },
  { node_type: "retime-video", display_name: "Retime Video", category: "Video", family: "Video", description: "Change video speed.", inputPorts: [port("video", "Video", "video", { required: true })], outputPorts: [port("output_assets", "Output Assets", "video")] },
  { node_type: "reverse-video", display_name: "Reverse Video", category: "Video", family: "Video", description: "Reverse a video clip.", inputPorts: [port("video", "Video", "video", { required: true })], outputPorts: [port("output_assets", "Output Assets", "video")] },
  { node_type: "add-audio", display_name: "Add Audio", category: "Video", family: "Video", description: "Attach audio to a video clip.", inputPorts: [port("video", "Video", "video", { required: true }), port("audio", "Audio", "audio", { required: true })], outputPorts: [port("output_assets", "Output Assets", "video")] },

  { node_type: "audio", display_name: "Audio Asset", category: "Audio", family: "Audio", description: "Upload or reference audio.", inputPorts: [], outputPorts: [port("output_assets", "Output Assets", "audio")] },
  { node_type: "bgm", display_name: "Background Music", category: "Audio", family: "Audio", description: "Generate or choose background music.", inputPorts: [port("prompt", "Music Prompt", "prompt"), port("storyboard_reference", "Storyboard Reference", "image", { multiple: true })], outputPorts: [port("output_assets", "Output Assets", "audio")] },
  { node_type: "extract-audio", display_name: "Extract Audio", category: "Audio", family: "Audio", description: "Extract audio from a video.", inputPorts: [port("video", "Video", "video", { required: true })], outputPorts: [port("output_assets", "Output Assets", "audio")] },

  { node_type: "preview", display_name: "Preview Result", category: "Preview", family: "Preview", description: "Collect and review generated media outputs.", inputPorts: [port("image", "Image", "image", { multiple: true }), port("video", "Video", "video", { multiple: true }), port("audio", "Audio", "audio", { multiple: true }), port("text", "Text", "text", { multiple: true })], outputPorts: [port("output_assets", "Output Assets", "resource")] },
  { node_type: "final-composition", display_name: "Final Composition", category: "Preview", family: "Preview", description: "Compose video, audio, subtitles, and final output.", inputPorts: [port("input_assets", "Input Assets", "resource", { required: true, multiple: true }), port("audio", "Audio", "audio")], outputPorts: [port("output_assets", "Output Assets", "video")] },
  { node_type: "comment", display_name: "Comment", category: "Utility", family: "Comment", description: "Annotate the workflow without execution.", inputPorts: [], outputPorts: [] },
  { node_type: "group", display_name: "Group", category: "Utility", family: "Group", description: "Organize a group of related nodes.", inputPorts: [], outputPorts: [] },

  { node_type: "script", display_name: "Script Writer", category: "Text", family: "Text", description: "Generate the advertising script.", inputPorts: [], outputPorts: [port("output", "Output", "text")] },
  {
    node_type: "storyboard",
    display_name: "Storyboard",
    category: "Image",
    family: "Image",
    description: "Generate storyboard frames from script, character, and scene assets.",
    inputPorts: [
      port("prompt", "Storyboard Prompt", "prompt"),
      port("script", "Script", "text"),
      port("character_assets", "Character Assets", "image", { multiple: true }),
      port("scene_assets", "Scene Assets", "image", { multiple: true }),
      port("product_assets", "Product Assets", "image", { multiple: true }),
    ],
    outputPorts: [port("output_assets", "Output Assets", "image")],
  },
];

export const fallbackTemplates: NodeTemplate[] = nodeRegistry.map(({ node_type, display_name, category, description }) => ({
  node_type,
  display_name,
  category,
  description,
}));

export function catalogItemToTemplate(item: NodeCatalogItem): NodeTemplate {
  const definition = getNodeDefinition(item.node_type, item.category);
  return {
    node_type: item.node_type,
    display_name: item.display_name ?? item.node_type,
    category: definition.category ?? item.category ?? "Agent",
    description: item.description ?? item.node_type,
  };
}

export function getNodeDefinition(nodeType: string, fallbackCategory = "Utility"): NodeDefinition {
  const normalized = nodeType.toLowerCase();
  const exact = nodeRegistry.find((definition) => definition.node_type === normalized || definition.node_type === nodeType);
  if (exact) return exact;
  const fuzzy = nodeRegistry.find((definition) => normalized.includes(definition.node_type) || definition.node_type.includes(normalized));
  if (fuzzy) return fuzzy;
  const family = inferNodeFamily(nodeType, fallbackCategory);
  return {
    node_type: nodeType,
    display_name: humanizeNodeType(nodeType),
    category: family === "Preview" ? "Preview" : family,
    family,
    description: `${humanizeNodeType(nodeType)} node`,
    inputPorts: inferFallbackInputPorts(nodeType, family),
    outputPorts: inferFallbackOutputPorts(nodeType, family),
  };
}

function inferNodeFamily(nodeType: string, fallbackCategory = ""): NodeFamily {
  const kind = `${nodeType} ${fallbackCategory}`.toLowerCase();
  if (kind.includes("comment")) return "Comment";
  if (kind.includes("group")) return "Group";
  if (kind.includes("preview") || kind.includes("result") || kind.includes("composition") || kind.includes("final")) return "Preview";
  if (kind.includes("video")) return "Video";
  if (kind.includes("image") || kind.includes("frame")) return "Image";
  if (kind.includes("audio") || kind.includes("bgm") || kind.includes("music") || kind.includes("voice")) return "Audio";
  if (kind.includes("text") || kind.includes("script") || kind.includes("storyboard") || kind.includes("design") || kind.includes("analysis") || kind.includes("direction")) return "Text";
  return "Utility";
}

function inferFallbackInputPorts(nodeType: string, family: NodeFamily): NodePort[] {
  if (family === "Text") return nodeType.includes("requirements") ? [] : [port("input_context", "Input Context", "text")];
  if (family === "Image") return [port("prompt", "Prompt", "prompt", { required: true }), port("reference_image", "Reference Image", "image")];
  if (family === "Video") return [port("prompt", "Prompt", "prompt"), port("image", "Image", "image"), port("reference_video", "Reference Video", "video")];
  if (family === "Audio") return [port("prompt", "Prompt", "prompt")];
  if (family === "Preview") return [port("image", "Image", "image", { multiple: true }), port("video", "Video", "video", { multiple: true }), port("audio", "Audio", "audio", { multiple: true }), port("text", "Text", "text", { multiple: true })];
  return [];
}

function inferFallbackOutputPorts(nodeType: string, family: NodeFamily): NodePort[] {
  if (family === "Text") return [port("output", "Output", "text")];
  if (family === "Image") return [port("output_assets", "Output Assets", "image")];
  if (family === "Video") return [port("output_assets", "Output Assets", "video")];
  if (family === "Preview") return [port("output_assets", "Output Assets", "resource")];
  if (family === "Audio") return [port("output_assets", "Output Assets", "audio")];
  return [];
}

export function getNodeInputPorts(nodeType: string): NodePort[] {
  const definition = getNodeDefinition(nodeType);
  if (definition.inputPorts.length || definition.family === "Comment" || definition.family === "Group") return definition.inputPorts;
  const kind = nodeType.toLowerCase();
  if (kind.includes("comment") || kind.includes("group")) return [];

  if (matchesKind(kind, ["text", "prompt", "script", "brief", "requirement"])) return [];
  if (matchesKind(kind, ["image_asset", "image-node", "image_node"])) return [];
  if (matchesKind(kind, ["video_asset", "video-node", "video_node"])) return [];
  if (matchesKind(kind, ["audio_asset", "audio-node", "audio_node"])) return [];

  if (matchesKind(kind, ["combine"])) {
    return [port("text_inputs", "Text Inputs", "text", { required: true, multiple: true })];
  }
  if (matchesKind(kind, ["json_parse", "json-parse"])) {
    return [port("json", "JSON", "json", { required: true })];
  }
  if (matchesKind(kind, ["add_audio", "add-audio"])) {
    return [
      port("video", "Video", "video", { required: true }),
      port("audio", "Audio", "audio", { required: true }),
    ];
  }
  if (matchesKind(kind, ["extract_audio", "extract-audio"])) {
    return [port("video", "Video", "video", { required: true })];
  }
  if (matchesKind(kind, ["first", "last", "extract_frame", "extract-frame", "frame"])) {
    return [port("video", "Video", "video", { required: true })];
  }
  if (matchesKind(kind, ["reverse", "resize", "trim", "retime", "crop", "fps", "upscale", "enhance"])) {
    return [port("video", "Video", "video", { required: true })];
  }
  if (matchesKind(kind, ["image_generation", "image-generate", "gpt_image", "gpt-image", "text_to_image", "text-to-image"])) {
    return [
      port("prompt", "Prompt", "prompt", { required: true }),
      port("reference_image", "Reference Image", "image"),
    ];
  }
  if (matchesKind(kind, ["video_generation", "video-generate", "image_to_video", "image-to-video"])) {
    return [
      port("prompt", "Prompt", "prompt", { required: true }),
      port("image", "Image", "image"),
      port("reference_video", "Reference Video", "video"),
    ];
  }
  if (matchesKind(kind, ["storyboard"])) {
    return [
      port("script", "Script", "text"),
      port("character_specs", "Character Specs", "text"),
      port("scene_specs", "Scene Specs", "text"),
      port("image", "Image References", "image", { multiple: true }),
    ];
  }
  if (matchesKind(kind, ["preview", "result"])) {
    return [port("image", "Image", "image", { multiple: true }), port("video", "Video", "video", { multiple: true }), port("audio", "Audio", "audio", { multiple: true }), port("text", "Text", "text", { multiple: true })];
  }
  if (matchesKind(kind, ["audio", "music", "bgm", "voice"])) {
    return [port("prompt", "Prompt", "prompt")];
  }
  if (matchesKind(kind, ["image"])) {
    return [port("prompt", "Prompt", "prompt", { required: true })];
  }
  if (matchesKind(kind, ["video"])) {
    return [
      port("prompt", "Prompt", "prompt"),
      port("image", "Image", "image"),
    ];
  }

  return [port("input_context", "Input Context", "data")];
}

export function getNodeOutputPorts(nodeType: string): NodePort[] {
  const definition = getNodeDefinition(nodeType);
  if (definition.outputPorts.length || definition.family === "Comment" || definition.family === "Group") return definition.outputPorts;
  const kind = nodeType.toLowerCase();
  if (kind.includes("comment") || kind.includes("group")) return [];
  if (matchesKind(kind, ["json_parse", "json-parse"])) return [port("output", "Output", "text")];
  if (matchesKind(kind, ["combine"])) return [port("output", "Output", "text")];
  if (matchesKind(kind, ["extract_audio", "extract-audio"])) return [port("output_assets", "Output Assets", "audio")];
  if (matchesKind(kind, ["first", "last", "extract_frame", "extract-frame", "frame"])) return [port("output_assets", "Output Assets", "image")];
  if (matchesKind(kind, ["add_audio", "add-audio", "reverse", "resize", "trim", "retime", "crop", "fps", "upscale", "enhance"])) {
    return [port("output_assets", "Output Assets", "video")];
  }
  const dataType = inferNodeDataType(kind);
  const handle = ["image", "video", "audio", "resource"].includes(dataType) ? "output_assets" : "output";
  return [port(handle, handle === "output_assets" ? "Output Assets" : "Output", dataType)];
}

export function inferNodeDataType(nodeType: string): NodePortType {
  if (nodeType.includes("prompt")) return "prompt";
  if (nodeType.includes("json")) return "json";
  if (nodeType.includes("image") || nodeType.includes("frame")) return "image";
  if (nodeType.includes("video") || nodeType.includes("preview")) return "video";
  if (nodeType.includes("audio") || nodeType.includes("music") || nodeType.includes("bgm")) return "audio";
  if (nodeType.includes("resource") || nodeType.includes("asset")) return "resource";
  if (nodeType.includes("text") || nodeType.includes("script") || nodeType.includes("prompt")) return "text";
  return "data";
}

export function port(id: string, label: string, dataType: NodePortType, options: Pick<NodePort, "required" | "multiple"> = {}): NodePort {
  return { id, label, dataType, ...options };
}

function matchesKind(kind: string, tokens: string[]) {
  return tokens.some((token) => kind.includes(token));
}

export function canRunNodeStandalone(nodeType: string) {
  return STANDALONE_NODE_RUN_TYPES.has(nodeType);
}

export function dataTypeLabel(dataType: NodePortType) {
  const labels: Record<NodePortType, string> = {
    prompt: "Prompt",
    text: "Text",
    image: "Image",
    video: "Video",
    audio: "Audio",
    json: "JSON",
    resource: "Resource",
    data: "Data",
  };
  return labels[dataType];
}

export function formatPortLabel(port: NodePort) {
  return `${port.label}${port.required ? " *" : ""}${port.multiple ? " +" : ""}`;
}

export function inferLabelDataType(label: unknown): NodePortType {
  const value = typeof label === "string" ? label.toLowerCase() : "";
  if (value.includes("prompt")) return "prompt";
  if (value.includes("json")) return "json";
  if (value.includes("image") || value.includes("frame")) return "image";
  if (value.includes("video") || value.includes("clip") || value.includes("segment")) return "video";
  if (value.includes("audio") || value.includes("music") || value.includes("voice") || value.includes("bgm")) return "audio";
  if (value.includes("text") || value.includes("script") || value.includes("brief")) return "text";
  return "data";
}

export function getNodeAccentType(kind: string, outputPorts: NodePort[], inputPorts: NodePort[]): NodePortType {
  if (kind.toLowerCase().includes("prompt")) return "text";
  return outputPorts[0]?.dataType === "prompt" ? "text" : outputPorts[0]?.dataType ?? inputPorts[0]?.dataType ?? "data";
}

export function humanizeNodeType(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function loadRecentNodeTypes() {
  try {
    const value = window.localStorage.getItem(RECENT_NODE_TYPES_KEY);
    const parsed = value ? JSON.parse(value) : [];
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string").slice(0, 5) : [];
  } catch {
    return [];
  }
}

export function saveRecentNodeTypes(values: string[]) {
  window.localStorage.setItem(RECENT_NODE_TYPES_KEY, JSON.stringify(values.slice(0, 5)));
}

export function getWorkflowNodeType(node: WorkflowNode) {
  return node.node_type ?? node.type ?? node.id;
}

export function getEdgeSource(edge?: WorkflowEdge) {
  return edge?.source_node_id ?? edge?.source ?? "";
}

export function getEdgeTarget(edge?: WorkflowEdge) {
  return edge?.target_node_id ?? edge?.target ?? "";
}

export function inferNodeCategory(nodeType: string, fallback = "utility") {
  const kind = nodeType.toLowerCase();
  if (kind === "product-generation") return "image_generation";
  if (["character-generation", "scene-generation", "storyboard"].includes(kind)) return "image_generation";
  if (kind === "storyboard-video-generation") return "video_generation";
  if (kind === "bgm") return "audio_generation";
  if (kind === "final-composition") return "composition";
  if (kind.includes("image")) return "image_generation";
  if (kind.includes("video")) return kind.includes("final") || kind.includes("composition") ? "composition" : "video_generation";
  if (kind.includes("audio") || kind.includes("bgm") || kind.includes("voice")) return "audio_generation";
  if (kind.includes("composition") || kind.includes("export")) return "composition";
  if (["requirements", "analysis", "product", "creative", "direction", "script", "character", "scene", "storyboard", "text", "prompt", "design"].some((token) => kind.includes(token))) return "agent_text";
  if (["agent", "text"].some((token) => fallback.toLowerCase().includes(token))) return "agent_text";
  return fallback === "agent" ? "agent_text" : fallback;
}

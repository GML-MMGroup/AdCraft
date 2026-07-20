import type { NodeDefinition, NodePort, NodePortType } from "../types.ts";

export function port(id: string, label: string, dataType: NodePortType, options: Pick<NodePort, "required" | "multiple"> = {}): NodePort {
  return { id, label, dataType, ...options };
}

export const nodeDefinitions: NodeDefinition[] = [
  {
    node_type: "script",
    display_name: "Script",
    category: "agent_text",
    description: "Script and copy generation.",
    family: "Text",
    inputPorts: [port("prompt", "Prompt", "prompt")],
    outputPorts: [port("script", "Script", "text")],
  },
  {
    node_type: "product-generation",
    display_name: "Product Generation",
    category: "image_generation",
    description: "Product reference image generation.",
    family: "Image",
    inputPorts: [port("prompt", "Prompt", "prompt"), port("reference", "Reference", "image", { multiple: true })],
    outputPorts: [port("image", "Image", "image")],
  },
  {
    node_type: "character-generation",
    display_name: "Character Generation",
    category: "image_generation",
    description: "Character reference image generation.",
    family: "Image",
    inputPorts: [port("prompt", "Prompt", "prompt"), port("reference", "Reference", "image", { multiple: true })],
    outputPorts: [port("image", "Image", "image")],
  },
  {
    node_type: "scene-generation",
    display_name: "Scene Generation",
    category: "image_generation",
    description: "Scene reference image generation.",
    family: "Image",
    inputPorts: [port("prompt", "Prompt", "prompt"), port("reference", "Reference", "image", { multiple: true })],
    outputPorts: [port("image", "Image", "image")],
  },
  {
    node_type: "storyboard",
    display_name: "Storyboard",
    category: "image_generation",
    description: "Storyboard image and shot planning.",
    family: "Image",
    inputPorts: [port("script", "Script", "text"), port("image", "Visuals", "image", { multiple: true })],
    outputPorts: [port("storyboard", "Storyboard", "image"), port("video", "Video", "video")],
  },
  {
    node_type: "bgm",
    display_name: "BGM",
    category: "audio_generation",
    description: "Music generation.",
    family: "Audio",
    inputPorts: [port("prompt", "Prompt", "prompt")],
    outputPorts: [port("audio", "Audio", "audio")],
  },
  {
    node_type: "final-composition",
    display_name: "Final Composition",
    category: "composition",
    description: "Final video composition.",
    family: "Preview",
    inputPorts: [port("video", "Video", "video", { multiple: true }), port("audio", "Audio", "audio", { multiple: true })],
    outputPorts: [port("final", "Final Video", "video")],
  },
];

export const nodeRegistry = new Map(nodeDefinitions.map((definition) => [definition.node_type, definition]));

export function getNodeDefinition(nodeType: string): NodeDefinition {
  return nodeRegistry.get(nodeType) ?? {
    node_type: nodeType,
    display_name: humanizeNodeType(nodeType),
    category: inferNodeCategory(nodeType),
    description: `${humanizeNodeType(nodeType)} node.`,
    family: inferNodeFamily(nodeType),
    inputPorts: getNodeInputPorts(nodeType),
    outputPorts: getNodeOutputPorts(nodeType),
  };
}

export function getNodeInputPorts(nodeType: string): NodePort[] {
  const registered = nodeRegistry.get(nodeType)?.inputPorts;
  if (registered) return registered;
  const kind = nodeType.toLowerCase();
  if (kind.includes("final") || kind.includes("composition")) return [port("video", "Video", "video", { multiple: true }), port("audio", "Audio", "audio", { multiple: true })];
  if (kind.includes("image") || kind.includes("character") || kind.includes("scene") || kind.includes("storyboard")) return [port("prompt", "Prompt", "prompt"), port("reference", "Reference", "image", { multiple: true })];
  if (kind.includes("video")) return [port("prompt", "Prompt", "prompt"), port("image", "Image", "image", { multiple: true })];
  if (kind.includes("audio") || kind.includes("bgm")) return [port("prompt", "Prompt", "prompt")];
  return [port("input", "Input", "data")];
}

export function getNodeOutputPorts(nodeType: string): NodePort[] {
  const registered = nodeRegistry.get(nodeType)?.outputPorts;
  if (registered) return registered;
  const dataType = inferNodeDataType(nodeType);
  return [port(dataType, humanizeNodeType(dataType), dataType)];
}

export function inferNodeDataType(nodeType: string): NodePortType {
  const kind = nodeType.toLowerCase();
  if (kind.includes("video") || kind.includes("composition") || kind.includes("final")) return "video";
  if (kind.includes("audio") || kind.includes("bgm") || kind.includes("music")) return "audio";
  if (kind.includes("image") || kind.includes("character") || kind.includes("scene") || kind.includes("storyboard") || kind.includes("product")) return "image";
  if (kind.includes("json") || kind.includes("data")) return "json";
  if (kind.includes("prompt")) return "prompt";
  return "text";
}

function inferNodeFamily(nodeType: string): NodeDefinition["family"] {
  const dataType = inferNodeDataType(nodeType);
  if (dataType === "image") return "Image";
  if (dataType === "video") return "Video";
  if (dataType === "audio") return "Audio";
  if (dataType === "text" || dataType === "prompt") return "Text";
  return "Utility";
}

function inferNodeCategory(nodeType: string) {
  const kind = nodeType.toLowerCase();
  if (kind.includes("image") || kind.includes("character") || kind.includes("scene") || kind.includes("storyboard") || kind.includes("product")) return "image_generation";
  if (kind.includes("video")) return "video_generation";
  if (kind.includes("audio") || kind.includes("bgm")) return "audio_generation";
  if (kind.includes("composition") || kind.includes("final")) return "composition";
  return "agent_text";
}

function humanizeNodeType(value: string) {
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

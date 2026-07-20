from typing import Literal

from pydantic import BaseModel, Field

HandleValueType = Literal["text", "image", "video", "audio", "asset", "any"]


class WorkflowNodeHandle(BaseModel):
    id: str
    type: HandleValueType
    label: str


class WorkflowNodeHandles(BaseModel):
    inputs: list[WorkflowNodeHandle] = Field(default_factory=list)
    outputs: list[WorkflowNodeHandle] = Field(default_factory=list)


HANDLE_LABELS: dict[HandleValueType, str] = {
    "text": "Text",
    "image": "Image",
    "video": "Video",
    "audio": "Audio",
    "asset": "Asset",
    "any": "Any",
}

NODE_HANDLE_TYPES: dict[str, tuple[tuple[HandleValueType, ...], tuple[HandleValueType, ...]]] = {
    "requirements-analysis": ((), ("text",)),
    "product-design": (("text",), ("text",)),
    "creative-direction": (("text",), ("text",)),
    "script": (("text",), ("text",)),
    "product-generation": (("text", "image"), ("image",)),
    "character-generation": (("text", "image"), ("image",)),
    "scene-generation": (("text", "image"), ("image",)),
    "character-design": (("text",), ("text",)),
    "scene-design": (("text",), ("text",)),
    "storyboard": (("text", "image"), ("text", "image")),
    "character-image-generation": (("text", "image"), ("image",)),
    "scene-image-generation": (("text", "image"), ("image",)),
    "storyboard-image-generation": (("text", "image"), ("image",)),
    "storyboard-video-generation": (("text", "image", "video"), ("video",)),
    "bgm": (("text",), ("audio",)),
    "final-composition": (("video", "audio", "text", "asset"), ("video",)),
    "subtitle-generation": (("text",), ("text",)),
    "final-video-generation-agent": (("text", "image", "asset"), ("text",)),
    "final-video-generation": (("text", "image", "video"), ("video",)),
    "sound-effects": (("text",), ("audio",)),
    "voiceover": (("text",), ("audio",)),
    "audio-generation": (("text", "audio"), ("audio",)),
    "audio-video-sync": (("video", "audio"), ("video",)),
}


CANONICAL_PRODUCT_EDGE_HANDLES: dict[tuple[str, str], tuple[str, str]] = {
    ("script", "product-generation"): ("output:text", "input:text"),
    ("product-generation", "scene-generation"): ("output:image", "input:image"),
    ("product-generation", "storyboard"): ("output:image", "input:image"),
    ("product-generation", "storyboard-video-generation"): ("output:image", "input:image"),
    ("product-generation", "final-composition"): ("output:image", "input:asset"),
}


EDGE_HANDLE_OVERRIDES: dict[tuple[str, str], tuple[str, str]] = {
    ("requirements-analysis", "product-design"): ("output:text", "input:text"),
    ("product-design", "creative-direction"): ("output:text", "input:text"),
    ("creative-direction", "script"): ("output:text", "input:text"),
    **CANONICAL_PRODUCT_EDGE_HANDLES,
    ("script", "character-generation"): ("output:text", "input:text"),
    ("script", "scene-generation"): ("output:text", "input:text"),
    ("script", "storyboard"): ("output:text", "input:text"),
    ("character-generation", "storyboard"): ("output:image", "input:image"),
    ("scene-generation", "storyboard"): ("output:image", "input:image"),
    ("storyboard", "storyboard-video-generation"): ("output:image", "input:image"),
    ("character-generation", "storyboard-video-generation"): ("output:image", "input:image"),
    ("scene-generation", "storyboard-video-generation"): ("output:image", "input:image"),
    ("storyboard", "bgm"): ("output:text", "input:text"),
    ("script", "final-composition"): ("output:text", "input:text"),
    ("script", "character-design"): ("output:text", "input:text"),
    ("script", "scene-design"): ("output:text", "input:text"),
    ("script", "bgm"): ("output:text", "input:text"),
    ("character-design", "character-image-generation"): ("output:text", "input:text"),
    ("scene-design", "scene-image-generation"): ("output:text", "input:text"),
    ("character-image-generation", "storyboard"): ("output:image", "input:image"),
    ("scene-image-generation", "storyboard"): ("output:image", "input:image"),
    ("storyboard", "storyboard-image-generation"): ("output:text", "input:text"),
    ("character-image-generation", "storyboard-image-generation"): ("output:image", "input:image"),
    ("scene-image-generation", "storyboard-image-generation"): ("output:image", "input:image"),
    ("storyboard-image-generation", "storyboard-video-generation"): (
        "output:image",
        "input:image",
    ),
    ("character-image-generation", "storyboard-video-generation"): ("output:image", "input:image"),
    ("scene-image-generation", "storyboard-video-generation"): ("output:image", "input:image"),
    ("storyboard-video-generation", "final-composition"): ("output:video", "input:video"),
    ("bgm", "final-composition"): ("output:audio", "input:audio"),
}


LEGACY_SOURCE_HANDLES = {"", "output", "output_assets"}
LEGACY_TARGET_HANDLES = {"", "input", "input_context", "input_assets"}


def get_node_handles(node_type: str) -> WorkflowNodeHandles:
    input_types, output_types = NODE_HANDLE_TYPES.get(node_type, (("any",), ("any",)))
    return WorkflowNodeHandles(
        inputs=[_handle("input", value_type) for value_type in input_types],
        outputs=[_handle("output", value_type) for value_type in output_types],
    )


def infer_edge_handles(
    source_node_type: str,
    target_node_type: str,
    label: str | None = None,
) -> tuple[str, str]:
    if (source_node_type, target_node_type) in EDGE_HANDLE_OVERRIDES:
        return EDGE_HANDLE_OVERRIDES[(source_node_type, target_node_type)]

    source_handles = get_node_handles(source_node_type)
    target_handles = get_node_handles(target_node_type)
    source_handle = _preferred_source_handle(source_handles, label)
    target_handle = _compatible_target_handle(source_handle, target_handles, label)
    return source_handle, target_handle


def normalize_edge_handles(
    source_node_type: str,
    target_node_type: str,
    source_handle: str | None,
    target_handle: str | None,
    label: str | None = None,
) -> tuple[str, str]:
    inferred_source, inferred_target = infer_edge_handles(source_node_type, target_node_type, label)
    normalized_source = source_handle or ""
    normalized_target = target_handle or ""
    if normalized_source in LEGACY_SOURCE_HANDLES:
        normalized_source = inferred_source
    if normalized_target in LEGACY_TARGET_HANDLES:
        normalized_target = inferred_target
    if (
        (source_node_type, target_node_type) == ("storyboard", "bgm")
        and normalized_source == "output:image"
        and normalized_target == "input:text"
    ):
        normalized_source = inferred_source

    source_ids = {handle.id for handle in get_node_handles(source_node_type).outputs}
    target_ids = {handle.id for handle in get_node_handles(target_node_type).inputs}
    if normalized_source not in source_ids:
        normalized_source = inferred_source if inferred_source in source_ids else "output:any"
    if normalized_target not in target_ids:
        normalized_target = inferred_target if inferred_target in target_ids else "input:any"
    return normalized_source, normalized_target


def _handle(
    direction: Literal["input", "output"], value_type: HandleValueType
) -> WorkflowNodeHandle:
    return WorkflowNodeHandle(
        id=f"{direction}:{value_type}",
        type=value_type,
        label=HANDLE_LABELS[value_type],
    )


def _preferred_source_handle(handles: WorkflowNodeHandles, label: str | None) -> str:
    output_ids = [handle.id for handle in handles.outputs]
    label_hint = (label or "").lower()
    for value_type in ("audio", "video", "image", "text", "asset"):
        candidate = f"output:{value_type}"
        if value_type in label_hint and candidate in output_ids:
            return candidate
    return output_ids[0] if output_ids else "output:any"


def _compatible_target_handle(
    source_handle: str,
    target_handles: WorkflowNodeHandles,
    label: str | None,
) -> str:
    target_ids = [handle.id for handle in target_handles.inputs]
    source_type = source_handle.split(":", 1)[1] if ":" in source_handle else "any"
    direct_candidate = f"input:{source_type}"
    if direct_candidate in target_ids:
        return direct_candidate

    label_hint = (label or "").lower()
    for value_type in ("audio", "video", "image", "text", "asset"):
        candidate = f"input:{value_type}"
        if value_type in label_hint and candidate in target_ids:
            return candidate
    if "input:text" in target_ids:
        return "input:text"
    return target_ids[0] if target_ids else "input:any"

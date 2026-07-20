import json
import logging
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agents.front_desk import build_front_desk_agent
from app.core.config import Settings
from app.schemas.ad_workflow import AdWorkflowGenerateRequest
from app.schemas.front_desk import (
    FrontDeskChatRequest,
    FrontDeskChatResponse,
    FrontDeskIntentOutput,
    PartialAdWorkflowRequest,
)
from app.services.v2_planning_seed import build_v2_planning_seed

logger = logging.getLogger(__name__)


class FrontDeskError(RuntimeError):
    """Raised when the front desk agent cannot classify a user message."""


class FrontDeskOutputParseError(ValueError):
    """Raised when an LLM response does not contain extractable JSON."""


class FrontDeskRequestClarification(ValueError):
    """Raised when extracted ad request fields need user clarification."""

    def __init__(self, field_errors: dict[str, str]) -> None:
        self.field_errors = field_errors
        super().__init__("front desk ad request needs clarification")


SUPPORTED_AUDIO_MODES = ("none", "bgm_only", "full")
SUPPORTED_OUTPUT_RESOLUTIONS = ("480p", "720p", "1080p")
SUPPORTED_ASPECT_RATIOS = ("16:9", "9:16", "4:3", "3:4", "1:1", "21:9")
TEXT_FIELDS = (
    "product_name",
    "product_description",
    "target_audience",
    "campaign_goal",
    "desired_emotion",
    "visual_style",
    "core_selling_point",
)
REQUIRED_FIELDS = ("product_name", "product_description", "target_audience")
LIST_SEPARATOR_RE = re.compile(r"[,，、/；;]+")


class FrontDeskService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def chat(self, request: FrontDeskChatRequest) -> FrontDeskChatResponse:
        if self._settings.agno_mock_mode:
            return _mock_front_desk_response(request)

        try:
            agent = build_front_desk_agent(self._settings)
        except Exception as exc:
            _log_front_desk_error("build_agent", exc)
            raise FrontDeskError(f"build_agent_failed: {_safe_error_message(exc)}") from exc

        prompt = _build_prompt(request)
        try:
            response = agent.run(prompt)
        except Exception as exc:
            _log_front_desk_error("run_agent", exc)
            raise FrontDeskError(f"run_agent_failed: {_safe_error_message(exc)}") from exc

        try:
            raw_output = _extract_json(response.content)
        except FrontDeskOutputParseError as exc:
            _log_front_desk_error("parse_output", exc, output_preview=response.content)
            return _front_desk_output_clarification(["front_desk_output"])

        try:
            output = _parse_front_desk_intent_output(raw_output)
        except ValidationError as exc:
            field_errors = _intent_validation_field_errors(exc)
            _log_front_desk_error("validate_intent", exc, output_preview=raw_output)
            return _front_desk_output_clarification(_unique_fields(list(field_errors)))

        try:
            return _normalize_front_desk_output(output, request)
        except Exception as exc:
            _log_front_desk_error("normalize_ad_request", exc, output_preview=raw_output)
            raise FrontDeskError(
                f"normalize_ad_request_failed: {_safe_error_message(exc)}"
            ) from exc


def _mock_front_desk_response(request: FrontDeskChatRequest) -> FrontDeskChatResponse:
    message = request.message
    target_node_type = route_node_edit_intent(message)
    if target_node_type is not None:
        metadata = _front_desk_metadata_for_node(target_node_type, message)
        return FrontDeskChatResponse(
            intent="conversation",
            reply=f"已识别为修改 {target_node_type} 节点的请求。",
            workflow_action="modify_node",
            target_node_type=target_node_type,
            **metadata,
        )

    ad_keywords = (
        "广告",
        "宣传",
        "推广",
        "短片",
        "商品",
        "产品",
        "投放",
        "营销",
        "ad",
        "advertisement",
        "commercial",
        "campaign",
    )
    lowered_message = message.lower()
    if not any(keyword in lowered_message for keyword in ad_keywords):
        return FrontDeskChatResponse(
            intent="conversation",
            reply="收到。你可以直接描述产品、受众、时长和想要的广告风格。",
            conversation_mode="ordinary_conversation",
        )

    product_name = _extract_product_name(message)
    target_audience = _extract_target_audience(message)
    missing_fields = _missing_required_fields(
        PartialAdWorkflowRequest(
            product_name=product_name,
            product_description=message,
            target_audience=target_audience,
        )
    )
    if missing_fields:
        return FrontDeskChatResponse(
            intent="needs_clarification",
            reply=f"还需要补充：{', '.join(missing_fields)}。",
            missing_fields=missing_fields,
            conversation_mode="director_discussion",
        )

    duration_seconds = _extract_duration_seconds(message)
    ad_request = AdWorkflowGenerateRequest(
        product_name=product_name,
        product_description=message,
        target_audience=target_audience,
        campaign_goal="Generate an advertising short film concept",
        desired_emotion=_extract_emotion(message),
        duration_seconds=duration_seconds,
        visual_style=_extract_after_markers(message, ("风格是", "风格")),
        channels=["social"],
        output_resolution=_extract_output_resolution(message),
        aspect_ratio=_extract_aspect_ratio(message),
        selected_assets=request.selected_assets,
        asset_references=request.asset_references,
        library_entity_ids=request.library_entity_ids,
        reference_mode=request.reference_mode,
        skip_audio_agents=request.skip_audio_agents,
        audio_mode=(
            "none"
            if request.skip_audio_agents
            else request.audio_mode or _extract_audio_mode(message) or "bgm_only"
        ),
    )
    return FrontDeskChatResponse(
        intent="ready_for_workflow",
        reply="已识别为广告需求，并整理为工作流入参。",
        ad_request=ad_request,
        conversation_mode="workflow_creation",
        v2_planning_seed=(
            build_v2_planning_seed(ad_request) if request.workflow_schema_version == 2 else None
        ),
    )


def _build_prompt(request: FrontDeskChatRequest) -> str:
    schema = FrontDeskIntentOutput.model_json_schema()
    v2_seed_instruction = (
        "For this V2 workflow-creation request, include v2_planning_seed. Use canonical "
        "English schema fields only. Mark facts backed by an exact user source span, typed "
        "request field, or input asset as explicit; mark omitted optional character, scene, "
        "and storyboard-count facts as unspecified. Do not use unknown for optional facts.\n"
        if request.workflow_schema_version == 2
        else ""
    )
    return (
        "You are the Front Desk Agent for an advertising workflow backend.\n"
        "Return only valid JSON matching this JSON Schema:\n"
        f"{json.dumps(schema, ensure_ascii=False)}\n\n"
        "Classify the latest user message.\n"
        "Use intent=conversation for casual chat.\n"
        "If the user wants to modify an existing workflow node, keep intent=conversation, "
        "set workflow_action=modify_node, and set target_node_type to one of script, "
        "character-generation, scene-generation, storyboard, bgm, "
        "storyboard-video-generation, or final-composition.\n"
        "Also return Creative Director metadata when applicable: active_speaker, "
        "suggested_agent, handoff_reason, target_node_id, target_asset_id, and "
        "conversation_mode. Allowed conversation_mode values are director_discussion, "
        "specialist_handoff, node_revision, workflow_creation, workflow_execution, "
        "ordinary_conversation.\n"
        "Use intent=needs_clarification when the user likely wants an ad workflow but required "
        "fields are missing. Ask one concise follow-up question and include missing_fields.\n"
        "Use intent=ready_for_workflow only when product_name, product_description, and "
        "target_audience are known. In that case, include a complete ad_request that can be "
        "validated as AdWorkflowGenerateRequest.\n"
        "Supported ad_request values: duration_seconds must be an integer from 15 to 60; "
        "audio_mode must be one of none, bgm_only, full; output_resolution must be one of "
        "480p, 720p, 1080p; aspect_ratio must be one of 16:9, 9:16, 4:3, 3:4, 1:1, 21:9. "
        "Map user phrases before returning JSON: 横版/横屏/landscape to 16:9, "
        "竖版/竖屏/portrait/vertical to 9:16, 方形/square to 1:1, "
        "宽银幕/电影宽屏 to 21:9, 高清/HD/FHD to 1080p, 标清/SD to 480p, "
        "背景音乐/配乐/BGM to bgm_only, 静音/无声/no audio/silent to none, "
        "旁白加音乐/完整音频 to full.\n"
        "If a user provides an unsupported explicit value, use intent=needs_clarification "
        "and put the concrete field name in missing_fields; do not use ad_request as a "
        "missing field name.\n"
        "When references or channels are not provided, return [] or omit the field; "
        "do not return null. Remove null or empty items from references and channels. "
        "When no fields are missing, return missing_fields=[]; do not return null.\n"
        "Never use ready_for_workflow while asking a follow-up question.\n\n"
        f"{v2_seed_instruction}"
        "Conversation history:\n"
        f"{json.dumps([message.model_dump() for message in request.history], ensure_ascii=False)}\n\n"
        "Latest user message:\n"
        f"{request.message}"
    )


def _parse_front_desk_intent_output(raw_output: Any) -> FrontDeskIntentOutput:
    payload = _normalize_raw_front_desk_payload(raw_output)
    try:
        return FrontDeskIntentOutput.model_validate(payload)
    except ValidationError as exc:
        if not _optional_seed_validation_failed(payload, exc):
            raise
        core_payload = dict(payload)
        core_payload.pop("v2_planning_seed", None)
        return FrontDeskIntentOutput.model_validate(core_payload)


def _optional_seed_validation_failed(payload: Any, error: ValidationError) -> bool:
    if not isinstance(payload, dict) or "v2_planning_seed" not in payload:
        return False
    errors = error.errors()
    return bool(errors) and all(item.get("loc", ())[:1] == ("v2_planning_seed",) for item in errors)


def _normalize_raw_front_desk_payload(raw_output: Any) -> Any:
    if not isinstance(raw_output, dict):
        return raw_output

    payload = dict(raw_output)
    if payload.get("missing_fields") is None:
        payload["missing_fields"] = []

    ad_request = payload.get("ad_request")
    if isinstance(ad_request, dict):
        normalized_request = dict(ad_request)
        _normalize_raw_list_field(normalized_request, "references")
        _normalize_raw_list_field(normalized_request, "channels")
        payload["ad_request"] = normalized_request
    return payload


def _normalize_raw_list_field(payload: dict[str, Any], field_name: str) -> None:
    if field_name not in payload:
        return
    value = payload.get(field_name)
    if value is None:
        payload[field_name] = []
        return
    if isinstance(value, list):
        payload[field_name] = [item for item in value if item is not None]


def _normalize_front_desk_output(
    output: FrontDeskIntentOutput, request: FrontDeskChatRequest
) -> FrontDeskChatResponse:
    if output.intent in {"conversation", "needs_clarification"}:
        target_node_type = output.target_node_type or route_node_edit_intent(request.message)
        workflow_action = output.workflow_action
        if target_node_type and workflow_action is None:
            workflow_action = "modify_node"
        metadata = _front_desk_metadata_for_output(
            output,
            request.message,
            target_node_type,
            workflow_action or "conversation",
        )
        return FrontDeskChatResponse(
            intent=output.intent,
            reply=output.reply,
            missing_fields=_unique_fields(output.missing_fields),
            workflow_action=workflow_action or "conversation",
            target_node_type=target_node_type,
            **metadata,
        )

    missing_fields = _missing_required_fields(output.ad_request)
    if missing_fields:
        return FrontDeskChatResponse(
            intent="needs_clarification",
            reply=_clarification_reply(missing_fields, ""),
            missing_fields=missing_fields,
            conversation_mode="director_discussion",
        )

    assert output.ad_request is not None
    try:
        ad_request = _build_ad_workflow_request(output.ad_request, request)
    except FrontDeskRequestClarification as exc:
        return FrontDeskChatResponse(
            intent="needs_clarification",
            reply=_field_clarification_reply(exc.field_errors),
            missing_fields=_unique_fields(list(exc.field_errors)),
            conversation_mode="director_discussion",
        )
    except ValidationError as exc:
        field_errors = _field_errors_from_validation(exc)
        return FrontDeskChatResponse(
            intent="needs_clarification",
            reply=_field_clarification_reply(field_errors),
            missing_fields=_unique_fields(list(field_errors)),
            conversation_mode="director_discussion",
        )

    return FrontDeskChatResponse(
        intent="ready_for_workflow",
        reply=output.reply,
        ad_request=ad_request,
        active_speaker=output.active_speaker or "creative_director",
        suggested_agent=output.suggested_agent,
        handoff_reason=output.handoff_reason,
        target_asset_id=output.target_asset_id,
        conversation_mode=output.conversation_mode or "workflow_creation",
        v2_planning_seed=(
            output.v2_planning_seed
            if request.workflow_schema_version == 2 and output.v2_planning_seed is not None
            else (
                build_v2_planning_seed(ad_request) if request.workflow_schema_version == 2 else None
            )
        ),
    )


def _missing_required_fields(ad_request: PartialAdWorkflowRequest | None) -> list[str]:
    if ad_request is None:
        return ["product_name", "product_description", "target_audience"]

    missing_fields = []
    for field_name in ("product_name", "product_description", "target_audience"):
        value = getattr(ad_request, field_name)
        if value is None or not str(value).strip():
            missing_fields.append(field_name)
    return missing_fields


def _build_ad_workflow_request(
    partial_request: PartialAdWorkflowRequest, request: FrontDeskChatRequest
) -> AdWorkflowGenerateRequest:
    data = partial_request.model_dump(exclude_none=True)
    field_errors: dict[str, str] = {}
    _normalize_text_fields(data)
    for field_name in _missing_required_fields_from_mapping(data):
        field_errors[field_name] = _field_help(field_name)

    _normalize_duration_seconds(data, field_errors)
    _normalize_list_field(data, "references", default=[])
    _normalize_list_field(data, "channels", default=["social"])
    _normalize_output_resolution(data, field_errors)
    _normalize_aspect_ratio(data, field_errors)

    data.setdefault("campaign_goal", "Generate an advertising short film concept")
    data.setdefault("desired_emotion", "confident")
    data["selected_assets"] = [asset.model_dump(mode="json") for asset in request.selected_assets]
    data["asset_references"] = [
        reference.model_dump(mode="json") for reference in request.asset_references
    ]
    data["library_entity_ids"] = list(request.library_entity_ids)
    data["reference_mode"] = request.reference_mode
    if request.skip_audio_agents:
        data["skip_audio_agents"] = True
        data["audio_mode"] = "none"
    elif request.audio_mode is not None:
        data["audio_mode"] = request.audio_mode
    else:
        _normalize_audio_mode(data, field_errors)

    if field_errors:
        raise FrontDeskRequestClarification(field_errors)
    return AdWorkflowGenerateRequest.model_validate(data)


def _normalize_text_fields(data: dict[str, Any]) -> None:
    for field_name in TEXT_FIELDS:
        if field_name not in data:
            continue
        value = data[field_name]
        if value is None:
            data.pop(field_name, None)
            continue
        cleaned = str(value).strip()
        if cleaned:
            data[field_name] = cleaned
        else:
            data.pop(field_name, None)


def _missing_required_fields_from_mapping(data: dict[str, Any]) -> list[str]:
    missing_fields = []
    for field_name in REQUIRED_FIELDS:
        value = data.get(field_name)
        if value is None or not str(value).strip():
            missing_fields.append(field_name)
    return missing_fields


def _normalize_duration_seconds(data: dict[str, Any], field_errors: dict[str, str]) -> None:
    value = data.get("duration_seconds")
    if _is_blank(value):
        data["duration_seconds"] = 30
        return

    duration: int | None = None
    if isinstance(value, bool):
        duration = None
    elif isinstance(value, int):
        duration = value
    elif isinstance(value, str):
        duration = _coerce_duration_seconds(value)

    if duration is None or duration < 15 or duration > 60:
        field_errors["duration_seconds"] = _field_help("duration_seconds")
        data.pop("duration_seconds", None)
        return
    data["duration_seconds"] = duration


def _coerce_duration_seconds(value: str) -> int | None:
    normalized = _compact_text(value)
    if normalized == "半分钟":
        return 30
    match = re.fullmatch(
        r"(?:约|大约|around)?(\d+)(?:秒|s|sec|secs|second|seconds)?",
        normalized,
    )
    if match is None:
        return None
    return int(match.group(1))


def _normalize_list_field(
    data: dict[str, Any], field_name: str, default: list[str] | None = None
) -> None:
    value = data.get(field_name)
    items = _split_list_value(value)
    if not items and default is not None:
        data[field_name] = list(default)
        return
    data[field_name] = items


def _split_list_value(value: Any) -> list[str]:
    if _is_blank(value):
        return []
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            items.extend(_split_list_value(item))
        return items
    return [item.strip() for item in LIST_SEPARATOR_RE.split(str(value)) if item and item.strip()]


def _normalize_output_resolution(data: dict[str, Any], field_errors: dict[str, str]) -> None:
    value = data.get("output_resolution")
    if _is_blank(value):
        data.pop("output_resolution", None)
        return

    resolution = _coerce_output_resolution(value)
    if resolution is None:
        field_errors["output_resolution"] = _field_help("output_resolution")
        data.pop("output_resolution", None)
        return
    data["output_resolution"] = resolution


def _coerce_output_resolution(value: Any) -> str | None:
    normalized = _compact_text(value)
    if any(token in normalized for token in ("4k", "2160", "uhd", "超高清")):
        return None
    if "标清" in normalized or normalized == "sd":
        return "480p"
    if "全高清" in normalized or normalized in {"fhd", "fullhd"}:
        return "1080p"
    if "高清" in normalized or normalized == "hd":
        return "1080p"
    match = re.search(r"(480|720|1080)p?", normalized)
    if match is None:
        return None
    return f"{match.group(1)}p"


def _normalize_aspect_ratio(data: dict[str, Any], field_errors: dict[str, str]) -> None:
    value = data.get("aspect_ratio")
    if _is_blank(value):
        data.pop("aspect_ratio", None)
        return

    aspect_ratio = _coerce_aspect_ratio(value)
    if aspect_ratio is None:
        field_errors["aspect_ratio"] = _field_help("aspect_ratio")
        data.pop("aspect_ratio", None)
        return
    data["aspect_ratio"] = aspect_ratio


def _coerce_aspect_ratio(value: Any) -> str | None:
    normalized = _compact_text(value).replace("：", ":").replace("比", ":")
    normalized = normalized.replace("x", ":")
    exact_map = {
        "16:9": "16:9",
        "9:16": "9:16",
        "4:3": "4:3",
        "3:4": "3:4",
        "1:1": "1:1",
        "21:9": "21:9",
    }
    if normalized in exact_map:
        return exact_map[normalized]
    for ratio, mapped_ratio in exact_map.items():
        if ratio in normalized:
            return mapped_ratio
    if any(alias in normalized for alias in ("横版", "横屏", "landscape")):
        return "16:9"
    if any(alias in normalized for alias in ("竖版", "竖屏", "portrait", "vertical")):
        return "9:16"
    if any(alias in normalized for alias in ("方形", "正方形", "square")):
        return "1:1"
    if any(alias in normalized for alias in ("宽银幕", "电影宽屏")):
        return "21:9"
    return None


def _normalize_audio_mode(data: dict[str, Any], field_errors: dict[str, str]) -> None:
    value = data.get("audio_mode")
    if _is_blank(value):
        data["audio_mode"] = "bgm_only"
        return

    audio_mode = _coerce_audio_mode(value)
    if audio_mode is None:
        field_errors["audio_mode"] = _field_help("audio_mode")
        data.pop("audio_mode", None)
        return
    data["audio_mode"] = audio_mode


def _coerce_audio_mode(value: Any) -> str | None:
    normalized = _compact_text(value)
    if normalized in SUPPORTED_AUDIO_MODES:
        return normalized
    if any(
        alias in normalized
        for alias in ("不要音乐", "不要音频", "静音", "无声", "noaudio", "silent")
    ):
        return "none"
    if any(
        alias in normalized for alias in ("背景音乐", "配乐", "bgm", "只要音乐", "backgroundmusic")
    ):
        return "bgm_only"
    if any(
        alias in normalized
        for alias in ("完整音频", "旁白加音乐", "音乐和旁白", "voiceoverandmusic")
    ):
        return "full"
    return None


def _field_errors_from_validation(exc: ValidationError) -> dict[str, str]:
    field_errors: dict[str, str] = {}
    for error in exc.errors():
        loc = error.get("loc", ())
        if not loc:
            continue
        field_name = str(loc[0])
        field_errors[field_name] = _field_help(field_name)
    return field_errors or {"request_fields": "广告需求字段格式不正确"}


def _intent_validation_field_errors(exc: ValidationError) -> dict[str, str]:
    field_errors: dict[str, str] = {}
    for error in exc.errors():
        loc = error.get("loc", ())
        if len(loc) >= 2 and loc[0] == "ad_request":
            field_name = str(loc[1])
            field_errors[field_name] = _field_help(field_name)
        else:
            field_errors["front_desk_output"] = _field_help("front_desk_output")
    return field_errors or {"front_desk_output": _field_help("front_desk_output")}


def _front_desk_output_clarification(missing_fields: list[str]) -> FrontDeskChatResponse:
    return FrontDeskChatResponse(
        intent="needs_clarification",
        reply=(
            "需求已收到，但后端没有成功结构化模型输出，请再补充产品、目标人群、"
            "时长、画幅等关键信息，或稍后重试。"
        ),
        missing_fields=_unique_fields(missing_fields) or ["front_desk_output"],
    )


def _field_clarification_reply(field_errors: dict[str, str]) -> str:
    if not field_errors:
        return "还需要补充或修正广告需求中的关键信息。"
    details = [_field_help(field_name) for field_name in _unique_fields(list(field_errors))]
    return f"需求已收到，但需要补充或修正：{'；'.join(details)}。"


def _field_help(field_name: str) -> str:
    if field_name == "duration_seconds":
        return "duration_seconds 需要是 15 到 60 秒之间的整数，例如 30 或 30秒"
    if field_name == "output_resolution":
        return "output_resolution 只支持 480p、720p、1080p，也可以说 标清、高清、HD 或 FHD"
    if field_name == "aspect_ratio":
        return (
            "aspect_ratio 只支持 16:9、9:16、4:3、3:4、1:1、21:9，"
            "也可以说 横版、竖版、方形 或 宽银幕"
        )
    if field_name == "audio_mode":
        return "audio_mode 只支持 none、bgm_only、full，也可以说 静音、背景音乐、配乐或完整音频"
    if field_name == "front_desk_output":
        return "front_desk_output 需要是 Front Desk Agent 返回的结构化 JSON"
    if field_name in REQUIRED_FIELDS:
        return f"{field_name} 是必填字段，请补充具体内容"
    if field_name == "channels":
        return "channels 至少需要一个投放渠道"
    return f"{field_name} 字段格式不正确"


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _compact_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value).strip().lower())


def _log_front_desk_error(stage: str, exc: Exception, output_preview: Any | None = None) -> None:
    extra = ""
    if output_preview is not None:
        extra = f" output_preview={_safe_preview(output_preview)}"
    logger.warning(
        "front_desk_%s_failed type=%s message=%s%s",
        stage,
        type(exc).__name__,
        _safe_error_message(exc),
        extra,
    )


def _safe_error_message(exc: Exception) -> str:
    message = str(exc) or type(exc).__name__
    message = re.sub(r"(?i)(api[_-]?key\\s*[:=]\\s*)\\S+", r"\1***", message)
    message = re.sub(r"(?i)(authorization\\s*[:=]\\s*)\\S+", r"\1***", message)
    message = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "sk-***", message)
    return message[:240]


def _safe_preview(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump()
    if isinstance(value, (dict, list)):
        preview = json.dumps(value, ensure_ascii=False)
    else:
        preview = str(value)
    preview = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "sk-***", preview)
    return preview[:500]


def _clarification_reply(missing_fields: list[str], fallback_reply: str) -> str:
    if fallback_reply.strip():
        return fallback_reply
    return f"还需要补充：{', '.join(missing_fields)}。"


def _unique_fields(fields: list[str]) -> list[str]:
    return list(dict.fromkeys(field for field in fields if field))


def _front_desk_metadata_for_output(
    output: FrontDeskIntentOutput,
    message: str,
    target_node_type: str | None,
    workflow_action: str,
) -> dict[str, Any]:
    if target_node_type:
        metadata = _front_desk_metadata_for_node(target_node_type, message)
    else:
        metadata = {
            "active_speaker": "creative_director",
            "suggested_agent": None,
            "handoff_reason": None,
            "target_node_id": None,
            "target_asset_id": None,
            "conversation_mode": "ordinary_conversation",
        }
    if workflow_action == "run_node":
        metadata["conversation_mode"] = "workflow_execution"
    if output.conversation_mode:
        metadata["conversation_mode"] = output.conversation_mode
    if output.active_speaker:
        metadata["active_speaker"] = output.active_speaker
    if output.suggested_agent:
        metadata["suggested_agent"] = output.suggested_agent
    if output.handoff_reason:
        metadata["handoff_reason"] = output.handoff_reason
    if output.target_node_id:
        metadata["target_node_id"] = output.target_node_id
    if output.target_asset_id:
        metadata["target_asset_id"] = output.target_asset_id
    return metadata


def _front_desk_metadata_for_node(target_node_type: str, message: str) -> dict[str, Any]:
    suggested_agent_by_node = {
        "script": "script_writer",
        "character-generation": "character_designer",
        "scene-generation": "scene_designer",
        "storyboard": "storyboard_agent",
        "storyboard-video-generation": "video_generation_agent",
        "bgm": "sound_director",
        "final-composition": "ffmpeg_composition_service",
    }
    suggested_agent = suggested_agent_by_node.get(target_node_type)
    return {
        "active_speaker": "creative_director",
        "suggested_agent": suggested_agent,
        "handoff_reason": (
            f"User request targets {target_node_type}: {message[:120]}" if suggested_agent else None
        ),
        "target_node_id": target_node_type,
        "target_asset_id": None,
        "conversation_mode": "node_revision",
    }


def route_node_edit_intent(message: str) -> str | None:
    normalized = message.lower().replace("：", ":")
    modify_markers = ("改", "修改", "换", "调整", "重新", "更", "变成", "rerun", "change")
    if not any(marker in normalized for marker in modify_markers):
        return None
    if any(keyword in normalized for keyword in ("合成", "剪辑", "导出", "ffmpeg")):
        return "final-composition"
    if any(keyword in normalized for keyword in ("音乐", "配乐", "bgm", "background music")):
        return "bgm"
    if any(keyword in normalized for keyword in ("角色", "人物", "主角", "女性", "男性", "穿")):
        return "character-generation"
    if any(keyword in normalized for keyword in ("场景", "背景", "办公室", "街头", "环境")):
        return "scene-generation"
    if any(keyword in normalized for keyword in ("分镜", "镜头", "shot", "storyboard")):
        return "storyboard"
    if any(keyword in normalized for keyword in ("脚本", "台词", "旁白", "文案", "script", "copy")):
        return "script"
    if any(keyword in normalized for keyword in ("视频", "比例", "16:9", "9:16", "480p", "720p")):
        return "storyboard-video-generation"
    return None


def _extract_json(content: Any) -> Any:
    if isinstance(content, BaseModel):
        return content.model_dump()
    if isinstance(content, (dict, list)):
        return content
    if not isinstance(content, str):
        return content

    normalized = content.strip()
    if not normalized:
        raise FrontDeskOutputParseError("empty Front Desk output")

    try:
        return json.loads(normalized)
    except json.JSONDecodeError:
        pass

    for fenced_content in _extract_fenced_blocks(normalized):
        try:
            return json.loads(fenced_content)
        except json.JSONDecodeError:
            continue

    extracted = _extract_first_json_object(normalized)
    if extracted is not None:
        return extracted
    raise FrontDeskOutputParseError("Front Desk output did not contain valid JSON")


def _extract_fenced_blocks(content: str) -> list[str]:
    blocks = []
    for match in re.finditer(
        r"```(?:\s*json)?\s*(.*?)```", content, flags=re.IGNORECASE | re.DOTALL
    ):
        block = match.group(1).strip()
        if block:
            blocks.append(block)
    return blocks


def _extract_first_json_object(content: str) -> Any | None:
    decoder = json.JSONDecoder()
    for index, character in enumerate(content):
        if character != "{":
            continue
        try:
            parsed, _end = decoder.raw_decode(content, index)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _extract_after_markers(message: str, markers: tuple[str, ...]) -> str | None:
    for marker in markers:
        if marker in message:
            value = message.split(marker, 1)[1]
            return _clean_fragment(value)
    return None


def _extract_product_name(message: str) -> str | None:
    value = _extract_after_markers(message, ("产品是", "商品是", "给", "为"))
    if value:
        return value

    patterns = (
        r"(?:做一个|制作一个|生成一个|做|制作|生成)"
        r"(?:\s*\d+\s*(?:秒|s|sec|seconds?)的?)?(?P<value>[^，。,.;；]+?)广告",
        r"主角是(?:一[瓶个款只件台杯份张支辆])?(?P<value>[^，。,.;；]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match is None:
            continue
        return _clean_fragment(match.group("value"))
    return None


def _extract_target_audience(message: str) -> str | None:
    return _extract_after_markers(
        message,
        (
            "目标人群是",
            "目标用户是",
            "目标受众是",
            "受众是",
            "人群是",
            "面向",
        ),
    )


def _clean_fragment(value: str) -> str | None:
    separators = ("，", "。", ",", ".", "；", ";", "做", "制作", "生成")
    cleaned = value.strip(" ，。,.；;")
    for separator in separators:
        if separator in cleaned:
            cleaned = cleaned.split(separator, 1)[0].strip(" ，。,.；;")
    return cleaned[:80] if cleaned else None


def _extract_duration_seconds(message: str) -> int:
    if "半分钟" in message:
        return 30
    match = re.search(
        r"(\d+)\s*(?:秒|s|sec|secs|second|seconds)",
        message,
        flags=re.IGNORECASE,
    )
    if match is not None:
        duration = int(match.group(1))
        if 15 <= duration <= 60:
            return duration
    return 30


def _extract_output_resolution(message: str) -> str | None:
    return _coerce_output_resolution(message)


def _extract_aspect_ratio(message: str) -> str | None:
    return _coerce_aspect_ratio(message)


def _extract_audio_mode(message: str) -> str | None:
    return _coerce_audio_mode(message)


def _extract_emotion(message: str) -> str:
    for emotion in ("活力", "温馨", "高端", "搞笑", "科技", "治愈", "专业"):
        if emotion in message:
            return emotion
    return "confident"

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from pydantic import BaseModel

from app.schemas.workflow_v2_identity import (
    IDENTITY_SPEC_VERSION,
    CharacterIdentitySpec,
    ProductIdentitySpec,
    SceneIdentitySpec,
)

IdentitySpec = ProductIdentitySpec | CharacterIdentitySpec | SceneIdentitySpec


class V2IdentitySpecError(ValueError):
    def __init__(self, message: str, *, code: str = "v2_identity_spec_invalid") -> None:
        super().__init__(message)
        self.code = code


class V2ItemIdentitySpecBuilder:
    def build_product(self, brief: Any) -> ProductIdentitySpec:
        name = _clean_text(getattr(brief, "display_name", None), "Product")
        text = _combined_text(
            name,
            getattr(brief, "description", None),
            getattr(brief, "item_prompt", None),
            getattr(brief, "creative_brief", None),
        )
        category = _product_category(name, text)
        return ProductIdentitySpec(
            product_name=name,
            product_category=category,
            recognizable_features=_product_features(name, category, text),
            silhouette=_product_silhouette(name, category, text),
            material_finish=_product_material_finish(category, text),
            brand_or_packaging_cues=_product_brand_cues(name, text),
            hero_selling_points=_hero_selling_points(text),
            forbidden_content=[
                "human figures",
                "hands",
                "unrelated products",
                "narrative scene",
                "watermarks",
                "text overlays",
            ],
        )

    def build_character(self, brief: Any) -> CharacterIdentitySpec:
        item_id = _clean_text(getattr(brief, "item_id", None), "character-1")
        display_name = _clean_text(getattr(brief, "display_name", None), "Character")
        text = _combined_text(
            display_name,
            getattr(brief, "description", None),
            getattr(brief, "item_prompt", None),
            getattr(brief, "creative_brief", None),
        )
        gender_hint = _gender_hint(text)
        return CharacterIdentitySpec(
            character_id=item_id,
            display_name=display_name,
            age_impression=_age_impression(text, gender_hint),
            body_type=_body_type(text, gender_hint),
            wardrobe=_wardrobe(text, gender_hint),
            silhouette=_character_silhouette(text, gender_hint),
            facial_features=_facial_features(text, gender_hint),
            hairstyle=_hairstyle(text, gender_hint),
            performance_role=_safe_performance_role(text),
            emotion_arc=_emotion_arc(text),
            forbidden_content=[
                "product handling",
                "holding the product",
                "environment scene",
                "other characters",
                "story action",
                "storyboard blocking",
                "watermarks",
            ],
        )

    def build_scene(self, brief: Any) -> SceneIdentitySpec:
        item_id = _clean_text(getattr(brief, "item_id", None), "scene-1")
        display_name = _clean_text(getattr(brief, "display_name", None), "Scene")
        text = _combined_text(
            display_name,
            getattr(brief, "description", None),
            getattr(brief, "item_prompt", None),
            getattr(brief, "creative_brief", None),
        )
        location_type = _scene_location_type(display_name, text)
        time_of_day = _scene_time_of_day(location_type, text)
        spec = SceneIdentitySpec(
            scene_id=item_id,
            display_name=display_name,
            location_type=location_type,
            spatial_layout=_scene_layout(location_type, text),
            time_of_day=time_of_day,
            lighting=_scene_lighting(location_type, time_of_day, text),
            materials=_scene_materials(location_type, text),
            atmosphere=_scene_atmosphere(location_type, time_of_day, text),
            weather_or_surface=_scene_weather_or_surface(location_type, text),
            composition_zones=_scene_composition_zones(location_type, text),
            forbidden_content=[
                "foreground character",
                "foreground cast",
                "product placement",
                "storyboard action",
                "watermarks",
                "text overlays",
            ],
        )
        _validate_scene_spec(spec, text)
        return spec


def identity_metadata(spec: IdentitySpec) -> dict[str, Any]:
    payload = spec.model_dump(mode="json")
    return {
        "identity_spec_version": IDENTITY_SPEC_VERSION,
        "identity_spec_hash": identity_spec_hash(spec),
        "identity_spec": payload,
    }


def slot_identity_metadata(item_metadata: dict[str, Any]) -> dict[str, Any]:
    spec_hash = item_metadata.get("identity_spec_hash")
    spec_version = item_metadata.get("identity_spec_version")
    if not spec_hash or not spec_version:
        return {}
    return {
        "source_identity_spec_version": spec_version,
        "source_identity_spec_hash": spec_hash,
        "identity_spec_source": "item_identity_spec",
    }


def provider_identity_metadata(item_metadata: dict[str, Any]) -> dict[str, Any]:
    spec = item_metadata.get("identity_spec")
    spec_hash = item_metadata.get("identity_spec_hash")
    spec_version = item_metadata.get("identity_spec_version")
    if not isinstance(spec, dict) or not spec_hash or not spec_version:
        return {}
    return {
        "identity_spec": spec,
        "identity_spec_version": spec_version,
        "identity_spec_hash": spec_hash,
        "identity_spec_source": "item_identity_spec",
        "identity_spec_fields_used": _identity_spec_fields_used(spec),
    }


def asset_identity_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    spec_hash = payload.get("identity_spec_hash")
    spec_version = payload.get("identity_spec_version")
    spec_source = payload.get("identity_spec_source")
    if not spec_hash or not spec_version or spec_source != "item_identity_spec":
        return {}
    metadata = {
        "identity_spec_hash": spec_hash,
        "identity_spec_version": spec_version,
        "identity_spec_source": spec_source,
    }
    if isinstance(payload.get("identity_spec_fields_used"), list):
        metadata["identity_spec_fields_used"] = list(payload["identity_spec_fields_used"])
    return metadata


def identity_spec_hash(spec: IdentitySpec | dict[str, Any]) -> str:
    payload = spec.model_dump(mode="json") if isinstance(spec, BaseModel) else spec
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(serialized.encode("utf-8")).hexdigest()


def render_identity_slot_prompt(
    *,
    item_type: str,
    slot_type: str,
    identity_spec: dict[str, Any],
    fallback_prompt: str,
) -> str:
    if item_type == "product":
        return _render_product_prompt(slot_type, identity_spec, fallback_prompt)
    if item_type == "character":
        return _render_character_prompt(slot_type, identity_spec, fallback_prompt)
    if item_type == "scene":
        return _render_scene_prompt(slot_type, identity_spec, fallback_prompt)
    return fallback_prompt


def _render_product_prompt(
    slot_type: str,
    spec: dict[str, Any],
    fallback_prompt: str,
) -> str:
    name = _clean_text(spec.get("product_name"), "Product")
    category = _clean_text(spec.get("product_category"), "product")
    features = _join_list(spec.get("recognizable_features")) or "recognizable product features"
    cues = _join_list(spec.get("brand_or_packaging_cues")) or "clear brand or packaging cues"
    points = _join_list(spec.get("hero_selling_points")) or "premium commercial appeal"
    material = _clean_text(spec.get("material_finish"), "premium commercial finish")
    silhouette = _clean_text(spec.get("silhouette"), "distinctive product silhouette")
    forbidden = _forbidden_clause(spec.get("forbidden_content"))
    identity = (
        f"product name {name}; category {category}; recognizable features {features}; "
        f"silhouette {silhouette}; material or finish {material}; "
        f"brand or packaging cues {cues}; hero selling points {points}; {forbidden}."
    )
    if slot_type == "product_multi_view_grid":
        return (
            f"Product multi-view grid from ProductIdentitySpec: {identity} "
            "Create front, side, back, and detail views that preserve the same product identity. "
            "Use the selected product main image as visual identity reference when available."
        )
    return (
        f"Product main image from ProductIdentitySpec: {identity} "
        "Create one single hero product reference on a clean neutral background. "
        f"Base brief: {fallback_prompt}"
    )


def _render_character_prompt(
    slot_type: str,
    spec: dict[str, Any],
    fallback_prompt: str,
) -> str:
    display_name = _clean_text(spec.get("display_name"), "Character")
    age = _clean_text(spec.get("age_impression"), "adult commercial talent")
    body_type = _clean_text(spec.get("body_type"), "natural upright proportions")
    wardrobe = _clean_text(spec.get("wardrobe"), "neutral modern casual outfit")
    silhouette = _clean_text(spec.get("silhouette"), "clear upright full-body silhouette")
    facial_features = _clean_text(
        spec.get("facial_features"),
        "distinct approachable facial features",
    )
    hairstyle = _clean_text(spec.get("hairstyle"), "neat production-ready hairstyle")
    performance_role = _clean_text(spec.get("performance_role"), "brand-facing commercial subject")
    emotion_arc = _clean_text(spec.get("emotion_arc"), "calm confident expression arc")
    identity = (
        f"display name {display_name}; age impression {age}; "
        f"body type {body_type}; wardrobe {wardrobe}; silhouette {silhouette}; "
        f"facial features {facial_features}; hairstyle {hairstyle}; "
        f"performance role {performance_role}; emotion arc {emotion_arc}; "
        f"{_forbidden_clause(spec.get('forbidden_content'))}."
    )
    if slot_type == "character_three_view":
        return (
            f"Character three-view turnaround from CharacterIdentitySpec: {identity} "
            "Create front, side, and back views that preserve the same character identity. "
            "Use the selected character main image as visual identity reference when available."
        )
    return (
        f"Character main reference from CharacterIdentitySpec: {identity} "
        "Create one single full-frame neutral character reference. "
        f"Base brief: {fallback_prompt}"
    )


def _render_scene_prompt(
    slot_type: str,
    spec: dict[str, Any],
    fallback_prompt: str,
) -> str:
    materials = _join_list(spec.get("materials")) or "architectural materials"
    zones = _join_list(spec.get("composition_zones")) or "empty environment depth zones"
    location_type = _clean_text(spec.get("location_type"), "commercial environment")
    spatial_layout = _clean_text(spec.get("spatial_layout"), "readable environment layout")
    time_of_day = _clean_text(spec.get("time_of_day"), "day")
    lighting = _clean_text(spec.get("lighting"), "clean commercial lighting")
    atmosphere = _clean_text(spec.get("atmosphere"), "clean commercial atmosphere")
    surface = _clean_text(spec.get("weather_or_surface"), "clean visible surfaces")
    forbidden = _forbidden_clause(spec.get("forbidden_content"))
    identity = (
        f"location type {location_type}; spatial layout {spatial_layout}; "
        f"time of day {time_of_day}; lighting {lighting}; "
        f"materials or surfaces {materials}; atmosphere {atmosphere}; "
        f"weather or surface {surface}; composition zones {zones}; {forbidden}."
    )
    if slot_type == "scene_multi_view_grid":
        return (
            f"Scene multi-view grid from SceneIdentitySpec: {identity} "
            "Create establishing, alternate angle, detail, and background views of the same location. "
            "Use the selected scene main image as visual identity reference when available."
        )
    return (
        f"Scene main environment reference from SceneIdentitySpec: {identity} "
        "Create one single empty environment reference that locks the same location identity. "
        f"Base brief: {fallback_prompt}"
    )


def _product_category(name: str, text: str) -> str:
    normalized = f"{name} {text}".lower()
    if "fold" in normalized and ("phone" in normalized or "smartphone" in normalized):
        return "foldable smartphone"
    if "iphone" in normalized or "phone" in normalized or "smartphone" in normalized:
        return "smartphone"
    if "bottle" in normalized or "tea" in normalized or "drink" in normalized:
        return "packaged beverage"
    return "advertised product"


def _product_features(name: str, category: str, text: str) -> list[str]:
    normalized = f"{name} {category} {text}".lower()
    features = [name]
    if "smartphone" in normalized:
        features.extend(["large glass display", "camera module", "precise metal frame"])
    elif "beverage" in normalized:
        features.extend(["clear package silhouette", "readable label", "refreshing color cue"])
    else:
        features.extend(["recognizable silhouette", "clean product geometry"])
    return _unique(features)


def _product_silhouette(name: str, category: str, text: str) -> str:
    normalized = f"{name} {category} {text}".lower()
    if "foldable" in normalized:
        return "thin folding rectangular smartphone silhouette"
    if "smartphone" in normalized or "iphone" in normalized:
        return "slim rounded-rectangle smartphone silhouette"
    if "beverage" in normalized:
        return "upright packaged beverage silhouette"
    return "distinctive product silhouette"


def _product_material_finish(category: str, text: str) -> str:
    normalized = f"{category} {text}".lower()
    if "smartphone" in normalized or "iphone" in normalized:
        return "premium glass and metal finish"
    if "beverage" in normalized:
        return "glossy packaged label and translucent drink finish"
    return "premium commercial material finish"


def _product_brand_cues(name: str, text: str) -> list[str]:
    cues = [name, "clear label hierarchy", "recognizable brand cue placement"]
    if "packaging" in text.lower():
        cues.append("packaging details")
    return _unique(cues)


def _hero_selling_points(text: str) -> list[str]:
    if "camera" in text.lower() or "iphone" in text.lower():
        return ["premium camera capability", "sleek flagship design"]
    if "fold" in text.lower():
        return ["large flexible display", "portable premium design"]
    return ["hero product benefit", "premium commercial appeal"]


def _gender_hint(text: str) -> str:
    normalized = text.lower()
    if "female" in normalized or "woman" in normalized or "女" in text:
        return "female"
    if "male" in normalized or "man" in normalized or "男" in text:
        return "male"
    return "neutral"


def _age_impression(text: str, gender_hint: str) -> str:
    normalized = text.lower()
    if "middle-aged" in normalized:
        return "middle-aged adult"
    if "young" in normalized or gender_hint in {"male", "female"}:
        return f"young adult {gender_hint}" if gender_hint != "neutral" else "young adult"
    return "adult commercial talent"


def _body_type(text: str, gender_hint: str) -> str:
    if "athletic" in text.lower():
        return "athletic build"
    if gender_hint == "female":
        return "natural upright female proportions"
    if gender_hint == "male":
        return "natural upright male proportions"
    return "natural upright proportions"


def _wardrobe(text: str, gender_hint: str) -> str:
    normalized = text.lower()
    if "wardrobe" in normalized:
        return _sentence_after(text, "wardrobe") or "neutral modern casual outfit"
    if "office" in normalized:
        return "modern office-smart casual wardrobe"
    if "wearing" in normalized:
        return _sentence_after(text, "wearing") or "neutral modern casual outfit"
    del gender_hint
    return "neutral modern casual outfit"


def _character_silhouette(text: str, gender_hint: str) -> str:
    if "side profile" in text.lower():
        return "clear side profile and upright full-body silhouette"
    if gender_hint == "female":
        return "slender upright silhouette with readable shoulders and stance"
    if gender_hint == "male":
        return "structured upright silhouette with clear shoulder line"
    return "clear upright full-body silhouette"


def _facial_features(text: str, gender_hint: str) -> str:
    if gender_hint == "female":
        return "soft approachable facial features"
    if gender_hint == "male":
        return "defined approachable facial features"
    return "distinct approachable facial features"


def _hairstyle(text: str, gender_hint: str) -> str:
    normalized = text.lower()
    if "short hair" in normalized:
        return "short neat hair"
    if "long hair" in normalized:
        return "long neat hair"
    if gender_hint == "female":
        return "neat shoulder-length hair"
    if gender_hint == "male":
        return "short neat hair"
    return "neat production-ready hairstyle"


def _safe_performance_role(text: str) -> str:
    normalized = text.lower()
    if "action beat" in normalized or "blocking" in normalized or "story action" in normalized:
        return "brand-facing commercial subject"
    if "hero" in normalized:
        return "hero commercial subject"
    return "brand-facing commercial subject"


def _emotion_arc(text: str) -> str:
    normalized = text.lower()
    if "confident" in normalized:
        return "calm curiosity to confident approval"
    if "warm" in normalized:
        return "warm interest to friendly confidence"
    return "neutral attention to confident product interest"


def _scene_location_type(display_name: str, text: str) -> str:
    normalized = f"{display_name} {text}".lower()
    if ("night" in normalized and "street" in normalized) or "街道夜景" in text:
        return "night street"
    if "street" in normalized:
        return "street"
    if "office" in normalized or "办公" in text:
        return "office"
    if "kitchen" in normalized:
        return "kitchen"
    return _clean_text(display_name, "commercial environment").lower()


def _scene_time_of_day(location_type: str, text: str) -> str:
    normalized = f"{location_type} {text}".lower()
    if "night" in normalized or "夜" in text:
        return "night"
    if "morning" in normalized:
        return "morning"
    if "sunset" in normalized or "dusk" in normalized:
        return "dusk"
    return "day"


def _scene_layout(location_type: str, text: str) -> str:
    if location_type == "night street":
        return "street-level storefront corridor with sidewalk, curb line, and background facades"
    if location_type == "office":
        return "modern office workspace with desks, window wall, and open circulation lanes"
    if "kitchen" in location_type:
        return "clean kitchen workspace with counter plane and background storage"
    return _sentence_after(text, "layout") or "readable commercial environment layout"


def _scene_lighting(location_type: str, time_of_day: str, text: str) -> str:
    if location_type == "night street":
        return (
            "night lighting from neon storefronts, warm street lamps, and reflected pavement glow"
        )
    if time_of_day == "night":
        return "low-light night ambience with practical light sources"
    if location_type == "office":
        return "soft daylight mixed with clean overhead office lighting"
    return _sentence_after(text, "lighting") or "clean commercial lighting"


def _scene_materials(location_type: str, text: str) -> list[str]:
    if location_type == "night street":
        return ["rain-slick pavement", "glass storefronts", "dark building facades"]
    if location_type == "office":
        return ["glass partitions", "light desks", "matte wall surfaces"]
    if "kitchen" in location_type:
        return ["clean counter surface", "tile or stone backsplash", "matte cabinetry"]
    return ["floor plane", "background surfaces", "architectural materials"]


def _scene_atmosphere(location_type: str, time_of_day: str, text: str) -> str:
    if location_type == "night street":
        return "rainy cinematic urban night atmosphere"
    if location_type == "office":
        return "focused modern workplace atmosphere"
    if time_of_day == "night":
        return "quiet low-light night atmosphere"
    return _sentence_after(text, "atmosphere") or "clean commercial atmosphere"


def _scene_weather_or_surface(location_type: str, text: str) -> str:
    if location_type == "night street":
        return "wet pavement with rain reflections"
    if "rain" in text.lower():
        return "rain-wet surfaces"
    return "clean readable surfaces"


def _scene_composition_zones(location_type: str, text: str) -> list[str]:
    if location_type == "night street":
        return [
            "street foreground pavement zone",
            "storefront middle-ground zone",
            "dark facade background zone",
        ]
    if location_type == "office":
        return ["desk foreground zone", "open work area zone", "window background zone"]
    return ["foreground surface zone", "middle-ground environment zone", "background depth zone"]


def _validate_scene_spec(spec: SceneIdentitySpec, source_text: str) -> None:
    if "night street" in source_text.lower() or "街道夜景" in source_text:
        if spec.location_type != "night street" or spec.time_of_day != "night":
            raise V2IdentitySpecError("Night street source did not produce a night street spec.")


def _identity_spec_fields_used(spec: dict[str, Any]) -> list[str]:
    return [
        key for key, value in spec.items() if key != "spec_type" and value not in (None, "", [], {})
    ]


def _forbidden_clause(value: Any) -> str:
    if isinstance(value, list):
        clauses = [f"no {str(item).strip()}" for item in value if str(item).strip()]
        return "; ".join(clauses) if clauses else "no unrelated content"
    forbidden = str(value or "").strip()
    return f"no {forbidden}" if forbidden else "no unrelated content"


def _join_list(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _combined_text(*values: Any) -> str:
    return " ".join(str(value).strip() for value in values if str(value or "").strip())


def _clean_text(value: Any, default: str) -> str:
    text = str(value or "").strip()
    if text.lower() in {"none", "null", "undefined", "tbd", "placeholder"}:
        return default
    return text or default


def _sentence_after(text: str, marker: str) -> str | None:
    lower = text.lower()
    index = lower.find(marker.lower())
    if index < 0:
        return None
    fragment = text[index + len(marker) :].strip(" :.,;-")
    if not fragment:
        return None
    sentence = fragment.split(".")[0].split(";")[0].split(",")[0].strip(" :.,;-")
    if sentence.lower() in {
        "silhouette",
        "facial features",
        "hairstyle",
        "hair",
        "expression",
        "posture",
        "pose",
        "background",
        "visual style",
    }:
        return None
    return sentence or None


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in (item.strip() for item in values) if value))

from typing import Any


def build_default_script_beats(
    *,
    product_name: str,
    desired_emotion: str,
    duration_seconds: int,
    target_audience: str = "",
    campaign_goal: str = "",
) -> list[dict[str, Any]]:
    count = _target_beat_count(duration_seconds)
    durations = _balanced_durations(duration_seconds, count)
    templates = [
        {
            "scene_intent": "Hook the audience with a relatable need.",
            "location_hint": _audience_context(target_audience),
            "visual_action": (
                f"Show the target audience encountering the need that {product_name} solves."
            ),
            "product_action": "Keep the product teased or just outside the main focus.",
            "spoken_or_on_screen_text": f"Meet {product_name}, built for a clearer moment.",
        },
        {
            "scene_intent": "Reveal the product as the answer.",
            "location_hint": "Clean product reveal setup",
            "visual_action": f"Move from the audience problem into a crisp {product_name} reveal.",
            "product_action": "Show the product name, silhouette, materials, and hero angle clearly.",
            "spoken_or_on_screen_text": f"{product_name} makes the moment feel {desired_emotion}.",
        },
        {
            "scene_intent": "Demonstrate the core benefit in action.",
            "location_hint": "Practical product-use environment",
            "visual_action": "Show a concrete before-to-after usage moment with natural motion.",
            "product_action": "Keep the product visible while the benefit is demonstrated.",
            "spoken_or_on_screen_text": "Feel the benefit in every use.",
        },
        {
            "scene_intent": "Add lifestyle or social proof.",
            "location_hint": "A second, visually distinct lifestyle setting",
            "visual_action": "Show the product fitting naturally into the audience's day.",
            "product_action": "Show the product in hand, in use, or placed in the environment.",
            "spoken_or_on_screen_text": f"Built for {target_audience or 'your day'}.",
        },
        {
            "scene_intent": "Close with a clear call to action.",
            "location_hint": "Hero packshot or product closing setup",
            "visual_action": "Resolve the visual story with a clean product hero shot.",
            "product_action": "Place the product front and center with readable packaging or brand cues.",
            "spoken_or_on_screen_text": campaign_goal or f"Try {product_name} today.",
        },
        {
            "scene_intent": "Optional extended proof point.",
            "location_hint": "Additional visually distinct usage environment",
            "visual_action": "Show one more product benefit without repeating earlier framing.",
            "product_action": "Keep the product visible and consistent with earlier shots.",
            "spoken_or_on_screen_text": f"Keep every moment {desired_emotion}.",
        },
    ]
    if count == 6:
        selected = templates[:4] + [templates[5], templates[4]]
    else:
        selected = templates[:count]
        selected[-1] = templates[4]

    return [
        {
            "order": index,
            "duration_seconds": durations[index - 1],
            **template,
        }
        for index, template in enumerate(selected, start=1)
    ]


def script_beats_from_script(script: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("shot_beats", "beats", "script_beats"):
        value = script.get(key)
        if isinstance(value, list):
            beats = [_normalize_beat(item, index) for index, item in enumerate(value, start=1)]
            return [beat for beat in beats if beat]
    return []


def ensure_script_beat_aliases(script: dict[str, Any]) -> dict[str, Any]:
    beats = script_beats_from_script(script)
    if not beats:
        return script
    return {
        **script,
        "shot_beats": beats,
        "beats": beats,
        "script_beats": beats,
    }


def _target_beat_count(duration_seconds: int) -> int:
    if duration_seconds <= 20:
        return 4
    if duration_seconds <= 45:
        return 5
    return 6


def _balanced_durations(duration_seconds: int, count: int) -> list[int]:
    base, remainder = divmod(duration_seconds, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def _audience_context(target_audience: str) -> str:
    audience = target_audience.strip()
    return f"Relatable daily environment for {audience}" if audience else "Relatable daily context"


def _normalize_beat(value: Any, fallback_order: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    beat = dict(value)
    try:
        beat["order"] = int(beat.get("order") or fallback_order)
    except (TypeError, ValueError):
        beat["order"] = fallback_order
    try:
        beat["duration_seconds"] = int(beat.get("duration_seconds") or 0)
    except (TypeError, ValueError):
        beat["duration_seconds"] = 0
    for key in (
        "scene_intent",
        "location_hint",
        "visual_action",
        "product_action",
        "spoken_or_on_screen_text",
    ):
        beat[key] = str(beat.get(key) or "").strip()
    input_asset_ids = beat.get("input_asset_ids")
    beat["input_asset_ids"] = (
        [str(asset_id) for asset_id in input_asset_ids if str(asset_id).strip()]
        if isinstance(input_asset_ids, list)
        else []
    )
    return beat

"""Generate SceneScriptRoot from a natural-language scene description.

Two generators back the scene-3d canvas node:

* :class:`LLMSceneScriptGenerator` — the real path. Calls an
  OpenAI-compatible ``/chat/completions`` endpoint (``LLM_BASE_URL`` /
  ``LLM_API_KEY``) through ``httpx``, then validates the reply with the
  scene3d :mod:`parser`.
* :class:`TemplateSceneScriptGenerator` — the deterministic path used in
  fake/mock runtime. Builds a known-good SceneScript from a shot template.

Both generators fail with :class:`SceneScriptGenerationError` (carrying a
machine-readable ``code``) instead of returning a partial script, so the
node executor can fail closed with an explicit error.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, get_args

import httpx

from app.core.config import Settings
from app.schemas.scene_script import EnvironmentType, PropType, SceneScriptRoot
from app.services.scene3d import asset_dimensions
from app.services.scene3d.parser import parse_llm_output
from app.services.scene3d.shot_templates import generate_establishing_shot

#: Seconds; mirrors the reference video analyzer default.
DEFAULT_LLM_TIMEOUT_SECONDS = 120

#: Upper bound on the generated SceneScript reply.
DEFAULT_MAX_TOKENS = 2000


#: The kinds, spelled from the schema rather than remembered. This prompt used to
#: list seven of thirteen prop kinds and five of thirteen environment kinds by
#: hand, so more than half the vocabulary did not exist as far as the model was
#: concerned — and only a prompt edit could ever change that.
_PROP_TYPES = " | ".join(f'"{value}"' for value in get_args(PropType))
_ENVIRONMENT_TYPES = " | ".join(f'"{value}"' for value in get_args(EnvironmentType))


def _vocabulary() -> str:
    """The sizes the model needs, with the two traps spelled out.

    `scale` used to be unexplained. The model wrote `scale: 4.5` for a `pillar`
    without knowing that is a 19 m column beside a 1.75 m person, and `scale: 5`
    for a `platform` without knowing that is a 25 m slab whose top sits a metre
    up — so every character, authored at z = 0, ended up underneath it. Nothing
    caught it: the renderer produced an empty frame, so there was nothing to look
    at and no way to tell a plausible prompt from a correct one.
    """
    sizes = "\n".join(asset_dimensions.prompt_lines())
    return f"""\
Sizes, in metres. Every `scale` above 1 multiplies these, and a human is \
{asset_dimensions.REFERENCE_PERSON_HEIGHT:g} m tall — size the scene against \
that, not against the number. Each line states the largest `scale` the schema will \
accept for that kind; a scale past it is REJECTED, so these are hard limits rather \
than advice.
{sizes}
Two traps the sizes above imply:
- A `platform` is a raised DECK, not a room. Anything meant to stand beside it
  must sit outside its footprint, or it will be standing underneath the deck.
- Anything whose base is non-zero (`lantern`, `flat_roof`, `rect_table`) is held
  off the ground or stands on legs; `position` places its lowest point, not its
  centre.
"""


_SCENE_SCRIPT_SYSTEM_PROMPT = f"""\
You are a professional 3D previsualization artist. Convert the user's scene \
description into ONE SceneScript JSON object for a low-poly 3D previs \
renderer.

Output ONLY the JSON object inside a single ```json code block, no other text. \
The object must follow this shape:
{{
  "scene": {{"name": string, "environment": "indoor" | "outdoor" | "mixed", \
"lighting": "warm" | "cool" | "neutral" | "dramatic" | "soft" | "hard", \
"duration": number, "frame_rate": number}},
  "characters": [
    {{"id": string, "type": "lowpoly_human", \
"appearance": {{"color": "#RRGGBB", "height": number, "scale": number}}, \
"keyframes": [{{"frame": int, "position": [x, y, z], "rotation_y": number, \
"action": "stand" | "walk" | "sit" | "talk" | "gesture"}}]}},
    {{"id": string, "type": "door" | "crate" | "box" | "pillar", \
"appearance": {{"color": "#RRGGBB"}}, \
"keyframes": [{{"frame": int, "position": [x, y, z], "rotation_y": number, \
"action": "door_swing_open" | "spin" | "drive" | "flyover"}}]}}
  ],
  "props": [{{"id": string, "type": {_PROP_TYPES}, "position": [x, y, z], \
"scale": number, "rotation_y": number, "keyframes": [{{"frame": int, \
"position": [x, y, z], "rotation": [rx, ry, rz] in degrees, "scale": number}}]}}],
  "environment": [{{"id": string, "type": {_ENVIRONMENT_TYPES}, \
"position": [x, y, z], "scale": number, "rotation_y": number, "keyframes": [ \
{{"frame": int, "position": [x, y, z], "rotation": [rx, ry, rz] in degrees, \
"scale": number}}]}}],
  "cameras": [
    {{"id": string, "shot_type": "wide" | "medium" | "closeup" | \
"over_shoulder" | "pov", "keyframes": [{{"frame": int, \
"position": [x, y, z], "look_at": [x, y, z]}}]}}
  ],
  "shots": [{{"id": string, "camera": string, "start_frame": int, \
"end_frame": int, "description": string}}],
  "speech_bindings": []
}}

Props and environment objects move the same way: "keyframes" holds those \
frames and stays empty (or is omitted) for anything that never moves. A prop \
with keyframes moves along them, and its "position"/"rotation_y" become its \
rest pose — a keyframe overrides them while that frame is current. Use \
"rotation", the full [x, y, z] triple in degrees, for anything that turns on \
its own axis: a wheel turns about a horizontal axis, which "rotation_y" \
cannot express. A keyframe whose "frame" is past the scene's total frames \
(round(scene.duration * scene.frame_rate)) is rejected, and so is a prop that \
is both held_by a character and keyframed — a held item's position comes from \
that character's hand, so it cannot also be animated.

Hard rules:
- At least one camera and one shot. The shot's "camera" must equal a camera id.
- Every character and camera must have a keyframe at frame 0; add more \
keyframes for any described movement.
- Shot end_frame must equal round(scene.duration * scene.frame_rate) - 1.
- Positions are in meters. Z is UP: [x, y, z] is [right, forward, up]. \
Characters stand on the ground (z = 0); typical camera height is z = 1.6, \
2 to 20 meters from the subject.
- Place the camera so nothing stands between it and its subject, and so the \
subject is not a speck in the frame.
- Use 24 or 30 fps and keep duration between 2 and 10 seconds.

{_vocabulary()}"""


class SceneScriptGenerationError(RuntimeError):
    """Raised when a SceneScript cannot be generated."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class SceneScriptGenerator(Protocol):
    """Produces a validated SceneScript from a scene description."""

    def generate(self, *, description: str) -> SceneScriptRoot: ...


class LLMSceneScriptGenerator:
    """Generate a SceneScript through an OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
        timeout_seconds: float = DEFAULT_LLM_TIMEOUT_SECONDS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory
        self._timeout_seconds = timeout_seconds
        self._max_tokens = max_tokens

    def generate(self, *, description: str) -> SceneScriptRoot:
        text = description.strip()
        if not text:
            raise SceneScriptGenerationError(
                "scene3d_scene_script_missing",
                "A scene description is required before a SceneScript can be generated.",
            )
        if not self._settings.llm_api_key or not self._settings.llm_base_url:
            raise SceneScriptGenerationError(
                "scene3d_llm_unconfigured",
                "LLM is not configured: set LLM_API_KEY and LLM_BASE_URL.",
            )

        client = self._client_factory(timeout=self._timeout_seconds)
        try:
            content = self._request_completion(client, description=text)
        except SceneScriptGenerationError as exc:
            # 2026-09-29 live: a reasoning model burned its whole budget on
            # reasoning and returned an empty message — the node run died with
            # no way forward.  A rough deterministic draft the author edits is
            # strictly better than a dead end; the name says what happened
            # (degradation named, never silent).
            if "empty message" not in str(exc):
                raise
            draft = TemplateSceneScriptGenerator().generate(description=text)
            return draft.model_copy(
                update={"scene": draft.scene.model_copy(update={"name": f"【草稿】{draft.scene.name}"})}
            )
        finally:
            client.close()
        result = parse_llm_output(content)
        if not result.success or result.scene_script is None:
            raise SceneScriptGenerationError(
                "scene3d_scene_script_generation_failed",
                result.retry_feedback,
            )
        return result.scene_script

    def _request_completion(self, client: httpx.Client, *, description: str) -> str:
        model = self._settings.llm_scene_model or self._settings.llm_front_desk_model
        response = client.post(
            f"{self._settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self._settings.llm_api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _SCENE_SCRIPT_SYSTEM_PROMPT},
                    {"role": "user", "content": description},
                ],
                "max_tokens": self._max_tokens,
                "temperature": 0.3,
            },
        )
        if response.status_code != 200:
            raise SceneScriptGenerationError(
                "scene3d_scene_script_generation_failed",
                f"LLM call failed ({response.status_code}): {response.text[:200]}",
            )
        data = response.json()
        choices = data.get("choices")
        if not choices:
            raise SceneScriptGenerationError(
                "scene3d_scene_script_generation_failed",
                "LLM returned no choices.",
            )
        content: Any = choices[0].get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise SceneScriptGenerationError(
                "scene3d_scene_script_generation_failed",
                "LLM returned an empty message.",
            )
        return content


class TemplateSceneScriptGenerator:
    """Deterministically build a SceneScript from a shot template."""

    def __init__(self, *, duration: float = 5.0, frame_rate: int = 30) -> None:
        self._duration = duration
        self._frame_rate = frame_rate

    def generate(self, *, description: str) -> SceneScriptRoot:
        text = description.strip()
        if not text:
            raise SceneScriptGenerationError(
                "scene3d_scene_script_missing",
                "A scene description is required before a SceneScript can be generated.",
            )
        scene_name = text[:40] if len(text) <= 40 else f"{text[:37]}..."
        return generate_establishing_shot(
            scene_name=scene_name,
            duration=self._duration,
            frame_rate=self._frame_rate,
        )

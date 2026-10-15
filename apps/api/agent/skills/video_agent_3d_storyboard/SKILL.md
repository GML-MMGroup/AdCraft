---
skill_id: video_agent_3d_storyboard
name: Video Agent 3D Storyboard
description: Convert natural-language scene descriptions into structured SceneScript JSON for low-fidelity 3D previsualization with controllable camera, character blocking, and shot timing.
---

# Purpose

Translate a user's natural-language description of a scene into a valid `SceneScript` JSON object. The SceneScript drives a low-fidelity 3D animated previs (characters, props, environment, cameras, shots, keyframes) that is later used to guide high-fidelity video generation.

This skill does **not** render anything. It produces data only. Rendering is handled by the backend `scene3d` service (Blender headless) and the frontend Three.js preview.

# Inputs

- Natural-language scene description from the user (required)
- Optional upstream assets: script, character designs, scene designs, world setting
- Optional: desired duration, content kind (`ad` / `short_film`), style references
- `response_locale` for user-visible text

# Output Format

Output **only** a valid SceneScript JSON object wrapped in a ```json code block. No prose, no explanations, no markdown outside the code block.

The SceneScript schema (source of truth: `apps/api/app/schemas/scene_script.py`) has these top-level sections:

- `scene`: `{ name, environment, lighting, duration }`
- `characters`: array of `{ id, type, appearance, keyframes: [{ frame, position: [x,y,z], rotation_y (degrees), action }] }`
- `props`: array of `{ id, type, position, scale }`
- `environment`: array of `{ id, type, position }`
- `cameras`: array of `{ id, shot_type, keyframes: [{ frame, position: [x,y,z], look_at: [x,y,z] }] }`
- `shots`: array of `{ id, camera, start_frame, end_frame, description }`
- `speech_bindings` (optional): array of `{ character, speech_asset, mode: "bound"|"free" }`

## Required enums (do NOT use free-text values)

| field | allowed values |
|---|---|
| `scene.environment` | `indoor` \| `outdoor` \| `mixed` |
| `scene.lighting` | `warm` \| `cool` \| `neutral` \| `dramatic` \| `soft` \| `hard` |
| `scene.frame_rate` (optional, default 30) | integer 1–120 |
| `characters[].type` | `lowpoly_human` |
| `props[].type` | `round_table` \| `rect_table` \| `chair` \| `stool` \| `lantern` \| `box` \| `crate` \| `vase` \| `weapon` \| `scroll` \| `book` \| `cup` |
| `environment[].type` | `wall` \| `pillar` \| `floor` \| `gable_roof` \| `flat_roof` \| `door` \| `window` \| `stairs` \| `platform` \| `tree` \| `rock` \| `fence` \| `ground` |
| `cameras[].shot_type` | `wide` \| `medium` \| `closeup` \| `over_shoulder` \| `pov` |
| `characters[].keyframes[].action` | `stand` \| `talk` \| `walk` \| `sit` \| `gesture` |

Free-text values like `bright_warm`, `human_female`, `thermos`, `coffee_table`, or `sofa` are **rejected** — pick the nearest enum value and put the detail in `scene.name` or the shot `description` instead.

# Spatial Reasoning Rules

1. **Coordinate system**: X = right, Y = forward (away from default camera), Z = up. Origin (0,0,0) = scene center at floor level. 1 unit = 1 meter.

2. **Default camera**: wide shot at positive X, negative Y (front-right), looking toward origin. Example: position `[12, -14, 8]`, look_at `[0, -1.5, 1.3]`.

3. **Character placement**: "sits at a table" → near the table, facing it. "faces the camera" → rotation_y ≈ 180. "faces another character" → rotation_y computed to point at that character. "walks in from the door" → starts at door position (far negative Y), keyframes interpolate to destination.

4. **Distance scale**: person ≈ 1.7m tall. Table ≈ 0.75m high, 1.2m across. Conversation distance = 0.5-1.5m apart.

5. **Rotation**: rotation_y in degrees. 0 = facing +Y. 90 = facing +X. 180 = facing -Y (toward default camera). 270 = facing -X.

6. **Keyframes**: moving characters/cameras need ≥2 keyframes. Frame number = seconds × frame_rate (default 30 fps). Static objects need 1 keyframe at frame 0.

7. **Shot timing**: shots must not overlap. Each shot has start_frame and end_frame. Total duration (in frames) = last frame = `scene.duration × scene.frame_rate`. Aim for 2-4 seconds per shot.

# Cinematography Rules

Map user language to camera parameters:
- "wide shot" / "establishing" → `shot_type: "wide"`, camera 10-15m away, Z 6-10m
- "medium shot" → `shot_type: "medium"`, camera 4-7m away, Z 2-4m
- "close-up" → `shot_type: "closeup"`, camera 1.5-3m away, Z 1.5-2m, look_at character head
- "push in" / "dolly in" → camera keyframes: start far → end close, same look_at
- "pull out" / "dolly out" → camera keyframes: start close → end far
- "tracking" / "follow" → camera moves alongside moving character, look_at stays on character
- "orbit" / "arc" → camera moves in arc around subject, look_at stays on subject
- "static" / "locked off" → single camera keyframe

# Prompt Rules

- Make reasonable assumptions for ambiguous descriptions; state them in `scene.name` or shot `description`.
- Keep the scene simple enough for low-fidelity rendering: ≤5 characters, ≤8 props/environment objects, ≤5 shots.
- Ensure every character id referenced in `speech_bindings` exists in `characters`.
- Ensure every camera id referenced in `shots` exists in `cameras`.
- Ensure shot frame ranges do not overlap and cover the full duration.
- Render user-visible text (scene name, shot descriptions) in `response_locale`; keep internal identifiers and enum values in English.

# Do Not

- Do not output prose or explanations outside the JSON code block.
- Do not use coordinate values outside realistic ranges (characters at [100, 200, 50] are wrong).
- Do not use enum values not listed above — `scene.environment` must be one of `indoor`/`outdoor`/`mixed`, `scene.lighting` one of the 6 presets, `characters[].type` is always `lowpoly_human`, prop/environment types come from the fixed lists above.
- Do not output rotation_y in radians — always degrees.
- Do not create overlapping shot frame ranges.
- Do not include provider payloads, local file paths, API keys, or sibling capability prompts.
- Do not render high-fidelity descriptions — this is a low-fidelity previs; detail comes from the downstream video model.

# Examples

See `apps/api/agent/skills/video_agent_3d_storyboard/examples/` for validated few-shot examples. These are injected into the prompt at runtime.

---
skill_id: video_agent_3d_white_model
name: Video Agent 3D White-Model Design
description: Emit incremental SceneScript operation batches (add/move/rotate/scale/camera/keyframe ops plus MCP extension ops) for the white-model design mode, so a scene is built up step by step and stays previewable and editable.
---

# Purpose

Drive the **white-model design mode**: the user describes a scene idea, and you build it up as a sequence of **SceneScript operation batches**. Unlike the 3D storyboard skill (which emits one complete SceneScript), you emit *operations* — so every step is previewable in the 3D viewport, replayable, and the user can grab any object and edit it by hand at any time.

This skill does **not** render anything. The backend `scene3d` service validates and applies your batches (`SceneScriptToolService`, endpoint `POST /scene-3d/apply-operations`); rendering is Blender headless; preview is Three.js.

# Inputs

- Natural-language scene description or edit request (required). First turn = build from scratch; later turns = incremental edits ("walls taller", "add two lockers", "put the camera on the door").
- Optional: the **current SceneScript** (when editing one). When present, reference its object ids and never recreate them.
- Optional: panorama/analysis context (an image analyzer may have seeded the scene — extend it, don't restart it).
- Optional: desired duration (default 6s, 30fps).
- `response_locale` for user-visible text.

# Output Format

Output **only** a JSON object with an `operations` array, wrapped in a ```json code block. One response = one batch (2–10 operations). No prose outside the code block.

```json
{
  "operations": [
    {"op": "add_environment", "type": "floor", "position": [0, 0, 0], "scale": 8.0},
    {"op": "add_environment", "type": "wall", "position": [0, 4, 1.5], "scale": 8.0, "rotation_y": 0},
    {"op": "add_prop", "type": "crate", "position": [1.5, 1.5, 0]},
    {"op": "add_character", "position": [0, 1, 0], "color": "#E74C3C", "action": "stand"},
    {"op": "move_object", "kind": "environment", "id": "env_1", "position": [0, 5, 1.5]},
    {"op": "add_camera", "position": [6, -8, 4], "look_at": [0, 0, 1.2], "shot_type": "wide"}
  ]
}
```

## Op vocabulary (only these)

| op | required fields | optional | effect |
|---|---|---|---|
| `add_environment` | `type`, `position` | `id`, `scale`, `rotation_y` | append an environment object (ids auto-generate `env_N`) |
| `add_prop` | `type`, `position` | `id`, `scale`, `rotation_y` | append a prop (`prop_N`) |
| `add_character` | `position` | `id`, `color`, `height`, `scale`, `rotation_y`, `action` | append a character (`char_N`) with one keyframe at frame 0 |
| `add_camera` | `position`, `look_at` | `id`, `shot_type` | append a camera (`cam_N`); does NOT add a shot |
| `move_object` | `kind`, `id`, `position` | | move environment/prop/character/camera (height preserved from the object) |
| `rotate_object` | `kind`, `id`, `rotation_y` | | rotate (degrees) |
| `scale_object` | `kind`, `id`, `scale` | | uniform scale (props 0.1–10, environment 0.1–50) |
| `set_camera` | `kind: "camera"`, `id` | `position`, `look_at`, `shot_type` | retarget an existing camera |
| `add_keyframe` | `kind` (character/camera), `id`, `frame` | `position`, `rotation_y`/`look_at`, `action` | upsert the keyframe at `frame` |
| `remove_object` | `kind`, `id` | | remove (a removed character drops its speech bindings; a removed camera drops its shots) |
| `mcp_request` | `tool` | `target`, `arguments` | Blender MCP extension op (see below) |

`kind` is one of `environment | prop | character | camera`. `id` may also be passed as `target`.

## Required enums (do NOT use free-text values)

| field | allowed values |
|---|---|
| `environment[].type` | `wall` \| `pillar` \| `floor` \| `gable_roof` \| `flat_roof` \| `door` \| `window` \| `stairs` \| `platform` \| `tree` \| `rock` \| `fence` \| `ground` |
| `props[].type` | `round_table` \| `rect_table` \| `chair` \| `stool` \| `lantern` \| `box` \| `crate` \| `vase` \| `weapon` \| `scroll` \| `book` \| `cup` |
| `cameras[].shot_type` | `wide` \| `medium` \| `closeup` \| `over_shoulder` \| `pov` |
| `characters[].action` | `stand` \| `talk` \| `walk` \| `sit` \| `gesture` |
| MCP `tool` | `scene_info` \| `list_objects` \| `add_primitive` \| `transform_object` \| `set_camera` \| `add_keyframe` \| `remove_keyframe` \| `bevel` \| `subdivide` \| `boolean_union` \| `boolean_difference` \| `render_preview` |

Pick the nearest enum and put detail in the scene's `name`/shot description via `add_camera` ops. Free-text types (`sofa`, `thermos`, `locker`, `server_rack`) are **rejected** — use the nearest primitive and, if it truly needs custom geometry, one `mcp_request`.

# Batch semantics (the service enforces these)

1. **All-or-nothing**: one invalid op rejects the whole batch. Violations come back per-op — read them and resend a corrected batch.
2. **Forward references inside a batch are fine**: `{"op": "add_character"}` then `{"op": "move_object", "id": "char_1"}` works — validate against the in-progress scene.
3. **Bounds**: `|x|, |y| ≤ 50` m, `0 ≤ z ≤ 30` m; keyframe `frame` must be within `duration × fps` (default 180 frames for 6s/30fps).
4. **Chunk by area**: ≤8 environment/prop objects per batch; build floor → walls → door → props → characters → cameras in that order across batches.
5. When the current SceneScript is provided, **reference existing ids** and emit only the delta the user asked for. Do not re-emit unchanged objects — that makes the viewport replay noisy.

# MCP extension ops (use sparingly)

`mcp_request` runs a whitelisted Blender tool for geometry the primitive vocabulary can't express (`bevel`, `subdivide`, `boolean_union/difference`). Rules:
- `target` must be an object that exists (created earlier in this batch or present in the current script).
- These execute against a live Blender MCP server; without one the batch is rejected with `mcp_unavailable` — so don't make a batch *depend* on MCP for basic blocking. Use it for refinement only.
- Never emit tools outside the whitelist (e.g. code execution) — they are rejected before the wire.

# Spatial reasoning rules

1. **Coordinates**: X = right, Y = forward (away from default camera), Z = up. 1 unit = 1 m. Floor objects at z = 0; characters stand at z = 0.
2. **Scale anchors**: person 1.7 m tall; table 0.75 m high; wall default scale 1 ≈ 4 m wide × 2.2 m tall; a door needs scale ≈ 2 to actually block sightlines.
3. **Placement from language**: "corridor 8m long" → floor scale 8, walls at ±4 m on Y; "door at the far end" → door near +Y wall, then characters/camera keyframes can pass through it in low-fidelity (no door animation support).
4. **Camera framing**: wide = 10–15 m out, z 6–10; medium = 4–7 m, z 2–4; closeup = 1.5–3 m, z 1.5–2, look_at the head (~z 1.5). `look_at` targets are points, not objects.
5. **Facing**: rotation_y degrees, 0 = facing +Y (away from default camera), 180 = toward the default camera.

# Iterative flow (this is a conversation, not one shot)

Each user turn → one ops batch → the service validates → the viewport updates. If the user asks for something the vocabulary can't do (door opening animation, curved walls), say what you approximated in the next batch's object placement and keep the scene editable rather than failing.

# Do Not

- Do not emit a full SceneScript — that is the storyboard skill's contract. Emit operations.
- Do not re-emit objects that already exist unchanged.
- Do not use out-of-bounds coordinates, non-enum types, or non-whitelisted MCP tools.
- Do not emit prose, local paths, or provider payloads outside the JSON fence.

# V2 Final Composition Editor Contract

**Status:** Proposed contract for frontend and backend implementation

**Scope:** V2 workflows only. V1 Final Composition is out of scope and must not be changed as part of this work.

## 1. Product Contract

The `final-composition` node is a non-linear editing workspace for the current V2 workflow. It provides:

- A synchronized composition preview and transport controls.
- Multiple video, audio, image-overlay, and subtitle tracks.
- Video and audio clip placement, trimming, splitting, deletion, reordering, mute, volume, and fade controls.
- BGM and video import from the user's existing asset library.
- Per-video/image clip color correction with built-in presets.
- Server-side FFmpeg rendering to a new final-video asset version.

The editor opens when the user selects the Final Composition node. It is a dedicated workbench surface, not an expanded React Flow node card. The canvas remains available as context but must not be interactable through the editor surface.

## 2. Compatibility and Ownership

- The canonical editable document is the V2 timeline at `v2/workflows/{workflow_id}/final-composition/timeline.json`.
- The existing `GET`, `PATCH`, and `POST render` V2 endpoints remain the canonical mutation/render path. The legacy V2 `timeline/clips` create/delete endpoints are compatibility helpers and must not be used by the new editor.
- A successful render creates a new `final_video` asset version under `v2/runs/{workflow_id}/composition/{render_id}/final-ad-video.mp4`, preserves the previous selected version in history, and makes the new version selected.
- A failed render must not change the selected final-video version.
- `timeline.version` is optimistic-concurrency state. Every save and render operates against an explicit version.
- Timeline media is version-pinned with `source_asset_id` and `source_version_id`; a later replacement of the source asset must not change an already saved edit.

## 3. Canonical Timeline Schema

The V2 schema keeps the existing flat `tracks` and `clips` arrays. `metadata` remains available for audit data only; it must not carry unvalidated editing controls.

```json
{
  "timeline_id": "v2tl_adwf_v2_example",
  "version": 4,
  "duration_seconds": 12.5,
  "aspect_ratio": "16:9",
  "resolution": { "width": 1920, "height": 1080 },
  "fps": 24,
  "tracks": [
    {
      "track_id": "video-1",
      "track_type": "video",
      "name": "Primary video",
      "order": 1,
      "enabled": true,
      "muted": false,
      "locked": false
    },
    {
      "track_id": "audio-1",
      "track_type": "audio",
      "name": "BGM",
      "order": 10,
      "enabled": true,
      "muted": false,
      "locked": false
    }
  ],
  "clips": [
    {
      "clip_id": "clip_shot_1",
      "track_id": "video-1",
      "clip_type": "video",
      "source_asset_id": "asset_shot_1",
      "source_version_id": "ver_shot_1",
      "source_slot_id": "shot-1:shot_video_segment",
      "start_time": 0,
      "duration": 5,
      "trim_in": 0,
      "trim_out": 5,
      "enabled": true,
      "transform": {
        "x": 0,
        "y": 0,
        "scale_x": 1,
        "scale_y": 1,
        "rotation": 0,
        "opacity": 1,
        "fit": "cover"
      },
      "audio": {
        "volume": 1,
        "muted": false,
        "fade_in": 0,
        "fade_out": 0
      },
      "color": {
        "preset_id": "none",
        "brightness": 0,
        "contrast": 1,
        "saturation": 1,
        "exposure": 0,
        "temperature": 0,
        "tint": 0,
        "hue": 0
      }
    },
    {
      "clip_id": "clip_subtitle_1",
      "track_id": "subtitle-1",
      "clip_type": "subtitle",
      "start_time": 0.5,
      "duration": 2,
      "enabled": true,
      "text": "Designed for the night.",
      "style": {
        "font_size": 42,
        "color": "#FFFFFF",
        "position": "bottom_center"
      }
    }
  ],
  "render_settings": {
    "video_codec": "libx264",
    "audio_codec": "aac",
    "video_bitrate": "8000k",
    "audio_bitrate": "192k"
  }
}
```

### 3.1 Track Fields

| Field | Contract |
| --- | --- |
| `track_id` | Immutable, unique non-empty identifier. |
| `track_type` | One of `video`, `audio`, `image`, `subtitle`. Multiple tracks of every type are allowed. |
| `name` | User editable, 1-80 characters. |
| `order` | Unique positive integer. Lower visual order is composited first; higher video/image order appears above it. Audio order does not suppress other audio tracks. |
| `enabled`, `muted`, `locked` | Boolean editor state. `locked` is UI/editing protection and does not hide media from rendering. |

### 3.2 Clip Fields and Validation

| Field | Contract |
| --- | --- |
| `clip_type` | Must match the containing track type. Visual overlays use a separate `image` or `video` track. |
| `source_asset_id`, `source_version_id` | Required for `video`, `audio`, and `image`; the backend must resolve the exact version before accepting the save. |
| `start_time`, `duration`, `trim_in`, `trim_out` | Finite seconds with 0.01-second precision. `start_time >= 0`, `duration > 0`, `trim_in >= 0`, and `trim_out > trim_in` when supplied. `duration` may not exceed `trim_out - trim_in`. |
| `enabled` | Disabled clips remain in the document but produce no picture or sound. |
| `transform` | Allowed for video/image: `x` and `y` in normalized canvas coordinates `[-1, 1]`; `scale_x` and `scale_y` in `(0, 4]`; `rotation` in `[-360, 360]`; `opacity` in `[0, 1]`; `fit` is `cover` or `contain`. |
| `audio` | Allowed for video/audio: `volume` in `[0, 4]`; `fade_in` and `fade_out` in `[0, duration]`; `muted` boolean. |
| `color` | Allowed for video/image: `preset_id` is one of `none`, `warm`, `cool`, `high_contrast`, `muted`; brightness `[-1, 1]`, contrast `[0, 3]`, saturation `[0, 3]`, exposure `[-4, 4]`, temperature/tint `[-100, 100]`, hue `[-180, 180]`. |
| `text`, `style` | Required for subtitle clips. `text` is 1-1000 Unicode characters. `style.font_size` is `[12, 96]`, `style.color` is `#RRGGBB`, and `style.position` is one of `top_center`, `center`, `bottom_center`. The renderer escapes text before constructing `drawtext`. |

The backend must reject overlapping enabled clips on the same video, image, or subtitle track with `v2_timeline_track_overlap`. Overlapping audio clips are valid and are mixed. Visual overlays are achieved by placing clips on separate video/image tracks.

### 3.3 Built-in Color Presets

Presets are deterministic server-side parameter bundles. The frontend may preview them, but the server values are authoritative.

| Preset | Brightness | Contrast | Saturation | Temperature |
| --- | ---: | ---: | ---: | ---: |
| `none` | 0 | 1 | 1 | 0 |
| `warm` | 0.03 | 1.04 | 1.08 | 18 |
| `cool` | -0.02 | 1.02 | 0.96 | -18 |
| `high_contrast` | 0 | 1.22 | 1.06 | 0 |
| `muted` | 0.02 | 0.92 | 0.72 | 0 |

User-uploaded LUT files are explicitly out of this contract. They can be added later as a separate, MIME-restricted asset type after the safe built-in color pipeline is in production.

## 4. HTTP API

All endpoints use `/api/v2` and preserve the current workflow authorization model.

### 4.1 Read Timeline

`GET /workflows/{workflow_id}/final-composition/timeline`

Response additions to the existing shape:

```json
{
  "workflow_id": "adwf_v2_example",
  "node_id": "final-composition",
  "item_id": "final-composition-1",
  "source": "saved",
  "timeline": { "...": "canonical timeline" },
  "available_sources": [
    {
      "asset_id": "asset_shot_1",
      "version_id": "ver_shot_1",
      "media_type": "video",
      "display_name": "Shot 1",
      "public_url": "/media/...",
      "thumbnail_url": "/media/...",
      "duration_seconds": 5,
      "origin": "workflow"
    }
  ],
  "runtime": {}
}
```

`available_sources` contains selected storyboard videos, selected BGM, timeline-imported library assets, and any workflow-local upload already registered with V2 assets. It is informational; saving a clip must still revalidate the referenced asset/version.

### 4.2 Save Timeline

`PATCH /workflows/{workflow_id}/final-composition/timeline`

```json
{
  "expected_version": 4,
  "timeline": { "...": "canonical timeline" }
}
```

Success returns the canonical saved timeline at version `5`, `changed_clip_ids`, and runtime. A mismatched version returns HTTP 409 with `v2_timeline_version_conflict`; the frontend must reload and retain its unsaved local draft for user comparison rather than overwrite the server document.

### 4.3 Import a Resource-Library Asset for the Timeline

`POST /workflows/{workflow_id}/final-composition/timeline/sources`

```json
{
  "library_entity_id": "entity_bgm_brand_theme",
  "library_asset_id": "library_asset_bgm_1",
  "expected_media_type": "audio"
}
```

Success response:

```json
{
  "workflow_id": "adwf_v2_example",
  "source": {
    "asset_id": "asset_imported_bgm_1",
    "version_id": "ver_imported_bgm_1",
    "media_type": "audio",
    "display_name": "Brand theme",
    "public_url": "/media/...",
    "duration_seconds": 28.4,
    "origin": "asset_library"
  }
}
```

The service must register or materialize a V2 asset version, pin its version, and create a `selected_for_timeline` relation. It must reject entity/asset mismatches, unavailable versions, unsupported media, or assets outside the current user's library scope. Frontend uses the existing asset-library picker and only permits `video` and `audio` for this flow.

### 4.4 Render

`POST /workflows/{workflow_id}/final-composition/render`

```json
{
  "timeline_id": "v2tl_adwf_v2_example",
  "timeline_version": 5,
  "render_settings": {
    "video_codec": "libx264",
    "audio_codec": "aac",
    "video_bitrate": "8000k",
    "audio_bitrate": "192k"
  }
}
```

The endpoint renders only a previously saved matching timeline version. It returns the final asset/version identifiers and public URL after output verification. It must never accept FFmpeg filter text, file paths, shell arguments, arbitrary URLs, or unvalidated LUT paths from the client.

### 4.5 Error Codes

| HTTP | Code | Meaning |
| --- | --- | --- |
| 400 | `v2_timeline_invalid_clip` | Invalid numeric range, type mismatch, missing track, duplicate ids, or illegal media configuration. |
| 400 | `v2_timeline_track_overlap` | Enabled non-audio clips overlap on one track. |
| 400 | `v2_timeline_unsupported_source_media` | A library asset does not match its requested media type. |
| 404 | `v2_timeline_source_asset_missing` | The pinned source asset no longer exists. |
| 404 | `v2_timeline_source_version_missing` | The pinned source version no longer exists. |
| 404 | `v2_final_composition_not_ready` | No final-video item/slot is available yet. |
| 409 | `v2_timeline_version_conflict` | Save/render did not use the current timeline version. |
| 422 | `v2_timeline_source_not_authorized` | Library asset is not accessible to the workflow owner. |
| 400 | `v2_timeline_render_failed` | FFmpeg or post-render media validation failed. Existing final video remains selected. |

## 5. Events and Refresh Rules

The backend continues to emit these V2 events:

- `final_timeline_created`
- `final_timeline_updated`
- `final_composition_render_started`
- `final_composition_render_completed`
- `final_composition_render_failed`
- `asset_version_created`, `slot_working_version_updated`, `slot_selected_version_updated`

For `final_timeline_created` and `final_timeline_updated`, payload must include `timeline_id`, `timeline_version`, and `changed_clip_ids`. For render events, payload must include `render_id`; completion also includes final `asset_id` and `version_id`.

Frontend refresh behavior:

- Timeline update events refresh the server baseline. A clean local editor adopts it; a dirty local editor shows an external-update state and does not discard the draft.
- Render-start/complete/fail events only update Final Composition status and preview/history. They must not animate unrelated node edges or mark other nodes as running.
- Completion refreshes workflow, runtime, available sources, and final-video versions.

## 6. Renderer Contract

The V2 renderer must replace the current concat-only implementation with a validated FFmpeg filter graph:

1. Resolve every source through `V2AssetStoreService` using both asset and version identifiers.
2. Probe every source with `ffprobe`; validate duration and required streams before building the command.
3. For each video/image clip: trim to `trim_in/trim_out`, normalize timestamps, scale/pad to the chosen canvas, apply approved color filters, then position and opacity-compose by track order and `start_time`.
4. For each audio/video-audio clip: trim, delay to `start_time`, apply volume/mute/fades, and `amix` all enabled audio tracks. Loop a BGM only when its duration is shorter than its explicit timeline clip duration.
5. Generate subtitle rendering only from structured subtitle clips; no raw FFmpeg expressions come from UI text.
6. Encode to the requested validated codecs/bitrates, probe the output, then register the version only after the file and expected streams are present.

The renderer must write to the existing location:

```text
v2/runs/{workflow_id}/composition/{render_id}/final-ad-video.mp4
```

## 7. Non-Goals

- No collaborative simultaneous timeline editing beyond optimistic version conflict detection.
- No arbitrary FFmpeg command execution, external URL imports, or user-provided filter expressions.
- No user-uploaded LUT assets in this release.
- No V1 workflow editor changes.

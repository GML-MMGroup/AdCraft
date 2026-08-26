# Backend Handoff: Fixed-Duration Single-Track Editing

## 1. Purpose

The frontend Editing timeline now models one video track as a set of independently
positioned time intervals. The user can trim a clip without moving its timeline
position, or drag the whole clip to another time while leaving gaps between clips.

This document describes the backend contract required to persist and export that
model. It is intentionally limited to the existing Agent Canvas Editing APIs. It
does not ask for a new endpoint or a second editing data model.

## 2. Current Contract Gap

The current authoritative backend schema is:

`/data/wenwu.meng/adWorkflow/app/schemas/agent_canvas_editing.py`

`EditingVideoEntryV2` currently has trim and source properties, but not an absolute
timeline position. `EditingManifestV2` currently has video entries, BGM, output,
and `manifest_revision`, but not a fixed logical duration.

The frontend has prepared the following optional fields for the next backend
contract:

```json
{
  "timeline_start_seconds": 5.0
}
```

on every video entry, and:

```json
{
  "timeline_duration_seconds": 30.0
}
```

on the manifest.

Until the backend accepts and persists these fields, dragging a clip will be
rejected by the backend's `extra="forbid"` validation. The frontend must keep
showing that real error rather than storing the position only in browser state.

## 3. Schema Changes

### 3.1 `EditingVideoEntryV2`

Add:

```python
timeline_start_seconds: float | None = Field(default=None, ge=0.0)
```

Semantics:

- `timeline_start_seconds` is the start time on the single output video track.
- It is measured in output seconds, not pixels.
- It is independent from `trim_start_seconds`.
- It must not be recomputed when the user trims the left edge.
- `None` is a legacy compatibility value only. New canonical responses should
  return an explicit value for every video entry.
- The timeline end is derived, not stored:

```text
timeline_end = timeline_start_seconds + effective_clip_duration
effective_clip_duration = source_out - source_in
```

`source_out` is the existing `trim_end_seconds`, or the probed source duration
when `trim_end_seconds` is null.

### 3.2 `EditingManifestV2`

Add:

```python
timeline_duration_seconds: float | None = Field(default=None, gt=0.0)
```

Semantics:

- This is the fixed logical duration of the Editing timeline and output.
- It is established when the Editing manifest is prepared from the initially
  imported video sources.
- The initial value is the sum of the original source durations of the imported
  video inputs, before user trimming or repositioning.
- Updating trim ranges or moving clips MUST NOT reduce or increase this value.
- The value is not the sum of current trimmed clips.
- The value is not the end of the last currently placed clip.
- A gap before a clip remains part of the output duration.

For a prepared 30-second composition, the backend must continue returning
`timeline_duration_seconds: 30.0` even if the user trims all clips or leaves a
gap between them.

## 4. Canonical Validation

Validation must happen in the backend. The frontend performs the same checks for
interactive feedback, but it is not the authority.

For every enabled, resolved video entry, calculate:

```text
start = timeline_start_seconds
duration = effective_clip_duration
end = start + duration
```

The backend must enforce:

```text
start >= 0
duration > 0
end <= timeline_duration_seconds
```

Intervals use half-open semantics:

```text
[start, end)
```

Therefore two clips may touch exactly at the same timestamp, but they may not
overlap:

```text
[0, 5) and [5, 10)  # valid
[0, 5) and [4.999, 10)  # invalid
```

The backend must reject overlapping entries without modifying the node or
workflow revision. The order of `video_entries` in the JSON array must not be
used to bypass overlap validation.

Recommended stable error codes:

| Condition | Error code |
| --- | --- |
| Timeline duration is missing or invalid for a new canonical manifest | `editing_timeline_duration_invalid` |
| A clip extends outside the fixed duration | `editing_timeline_out_of_bounds` |
| Two video intervals overlap | `editing_timeline_overlap` |
| Existing workflow/node revision is stale | `editing_manifest_revision_conflict` |

If the backend keeps the existing top-level `editing_manifest_invalid` envelope,
the precise reason must still be present as a stable nested error code. The
frontend must not have to parse human-readable error messages.

## 5. Legacy Manifest Compatibility

Existing Editing nodes may have been created before these fields existed. They
must remain readable and exportable.

### 5.1 Reading legacy data

When `timeline_start_seconds` is absent for all entries:

1. Resolve the original source duration for each entry.
2. Use the existing manifest array order to calculate contiguous starts from 0.
3. Use the sum of original source durations as the fixed timeline duration.
4. Return the canonical response with explicit `timeline_start_seconds` on every
   video entry and `timeline_duration_seconds` on the manifest.

Do not use current trim durations to calculate the fixed duration.

### 5.2 Updating a legacy node

The first successful update must canonicalize the complete manifest. In
particular, if the request changes one entry but omits the optional position on
other legacy entries, the backend must preserve the existing canonical position
for those entries rather than rebuilding all positions from array order.

After canonicalization, every response and subsequent request should contain
explicit positions and a fixed duration.

This prevents a single drag of clip B from silently moving clip A or collapsing
an existing gap.

### 5.3 Persistence format

The existing JSON `structured_content` persistence can be reused. A database
table or a new endpoint is not required for these two fields, provided the
transaction atomically validates and writes the complete manifest.

## 6. Existing PATCH API

Keep using:

```text
PATCH /api/v2/workflows/{workflow_id}/nodes/{node_id}
```

The request remains a normal Editing node patch. The frontend currently sends the
manifest as the `structured_content` value, which the backend already accepts as
either a direct manifest or `{ "manifest": ... }`.

Example request body:

```json
{
  "structured_content": {
    "video_entries": [
      {
        "binding_id": "binding-video-a",
        "asset_id": null,
        "enabled": true,
        "timeline_start_seconds": 0.0,
        "trim_start_seconds": 1.0,
        "trim_end_seconds": 9.0,
        "volume": 1.0,
        "preserve_native_audio": true,
        "transition": "cut",
        "transition_duration_seconds": 0.0,
        "fit_mode": "fit"
      },
      {
        "binding_id": "binding-video-b",
        "asset_id": null,
        "enabled": true,
        "timeline_start_seconds": 12.0,
        "trim_start_seconds": 0.0,
        "trim_end_seconds": 8.0,
        "volume": 1.0,
        "preserve_native_audio": true,
        "transition": "cut",
        "transition_duration_seconds": 0.0,
        "fit_mode": "fit"
      }
    ],
    "bgm": null,
    "output": {
      "resolution": null,
      "aspect_ratio": "16:9",
      "fps": 30,
      "video_codec": "h264",
      "audio_codec": "aac",
      "container": "mp4"
    },
    "manifest_revision": 7,
    "timeline_duration_seconds": 30.0
  }
}
```

The request must continue to carry:

```http
If-Match: "<current-workflow-revision>"
```

On success, return the canonical Workflow/Node response and the new workflow
`ETag`, as the current PATCH contract does. The manifest revision should advance
only after validation and persistence succeed.

No new PATCH endpoint is needed. Do not silently accept an unknown field and drop
it; the canonical response must prove that the position was persisted.

## 7. Preview and Timeline Ordering

The backend preview must reflect absolute positions:

- Sort visual playback by `timeline_start_seconds`.
- Preserve the fixed duration even when the last clip ends early.
- Represent empty intervals as no video frames / the configured blank output,
  not as a compressed timeline.
- Keep BGM on its existing independent audio track semantics.
- Do not convert a gap into a change of trim range.

If `EditingPreviewClipV2` is used by clients independently of the manifest, it is
useful for the response to expose:

```json
{
  "timeline_start_seconds": 12.0,
  "timeline_end_seconds": 20.0
}
```

This is optional if the canonical manifest is always returned alongside preview;
it must not become a second source of truth.

`estimated_duration_seconds` should equal the fixed
`timeline_duration_seconds`, not the sum of trimmed clip durations.

## 8. Export Semantics

The existing export endpoint remains authoritative:

```text
POST /api/v2/workflows/{workflow_id}/nodes/{editing_node_id}/export
```

The renderer must consume the timeline positions as follows:

1. Use each entry's trimmed source range.
2. Place the resulting clip at `timeline_start_seconds`.
3. Leave an intentional empty video interval when there is a gap.
4. Render the output for the complete fixed timeline duration.
5. Preserve the existing BGM and source-audio rules.

The export fingerprint must include:

- every video entry identity;
- `timeline_start_seconds`;
- trim start and end;
- enabled state and per-clip audio settings;
- BGM settings;
- output settings;
- `timeline_duration_seconds`.

Changing only a clip's position must create a new logical export fingerprint.
Replaying the same position/trim manifest with the same export idempotency key
must reuse the existing accepted/export result according to the current export
authority rules.

An export must not silently sort by the old JSON array order when explicit
positions are present.

## 9. Concurrency and Idempotency

The update transaction must:

1. Check the workflow/node `If-Match` revision.
2. Parse and validate the complete manifest, including all positions.
3. Validate all referenced Bindings/Assets.
4. Validate interval overlap and fixed-duration bounds.
5. Increment the manifest/node/workflow revisions atomically.
6. Return the canonical updated response and ETag.

On a stale `If-Match`, return the existing revision-conflict envelope and make no
partial update. The frontend will refresh the canonical workflow and ask the
user to retry the drag.

Do not create a second browser-only position store. A successful drag is only
complete when the backend returns the updated canonical node.

The existing Export `Idempotency-Key` behavior remains unchanged. The current
node PATCH endpoint does not require a new idempotency header; if backend retry
semantics are added later, they must be specified as part of that API contract
instead of being inferred by the frontend.

## 10. Backend Tests Required

Add focused tests before declaring the contract live:

1. Schema accepts explicit starts and fixed duration.
2. Legacy manifests are canonicalized with contiguous starts and original source
   total duration.
3. Left Trim changes source start and clip duration but preserves timeline start.
4. Right Trim changes source end and clip duration but preserves timeline start.
5. Moving a clip into a gap persists its new start without changing other clips.
6. Moving a clip to 0 seconds is valid when it fits.
7. Moving a clip past the fixed end returns `editing_timeline_out_of_bounds`.
8. Overlapping clips return `editing_timeline_overlap` and leave all revisions and
   content unchanged.
9. Two clips that touch at one timestamp are valid.
10. A stale `If-Match` cannot overwrite a newer position.
11. Preview and export preserve gaps and the fixed output duration.
12. Changing only `timeline_start_seconds` changes the export fingerprint.
13. Exact export replay does not create a duplicate output Asset.
14. BGM remains aligned to the same fixed playhead while video gaps are present.

## 11. Acceptance Example

Given two 10-second source videos and a 30-second initial timeline:

```text
A: trim [1, 9], timeline start 0  => output [0, 8)
B: trim [0, 8], timeline start 12 => output [12, 20)
timeline duration                 => 30
```

Expected behavior:

- The ruler remains 0–30 seconds.
- Seconds 8–12 are an intentional video gap.
- Seconds 20–30 remain part of the output timeline.
- Dragging A's left Trim handle changes its source range but not its timeline
  start of 0.
- Dragging B's body to 5 seconds is rejected if it overlaps A.
- Dragging B's body to 8 seconds is accepted when it only touches A.
- Export renders a 30-second result and does not concatenate B immediately after A.


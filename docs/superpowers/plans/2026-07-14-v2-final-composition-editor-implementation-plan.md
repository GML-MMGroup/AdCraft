# V2 Final Composition Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a V2-only Final Composition workbench with multi-track video/audio/image/subtitle editing, built-in color correction, asset-library import, and safe FFmpeg rendering to the existing final-video output path.

**Architecture:** Keep `WorkflowV2Timeline` as the canonical persisted document and use optimistic `timeline.version` for every save/render. The frontend maintains a local draft with pointer-driven timeline interactions and an HTML-media preview compositor; the backend validates the structured document, resolves pinned V2 assets, and constructs the authoritative FFmpeg filter graph.

**Tech Stack:** React 19, TypeScript, Vite, `@dnd-kit/core`, `@dnd-kit/sortable`, FastAPI, Pydantic, FFmpeg/ffprobe, existing V2 asset store and runtime event service.

## Global Constraints

- Implement V2 workflows only; do not change V1 Final Composition UI or endpoints.
- Do not accept client-provided FFmpeg filters, paths, shell arguments, URLs, or arbitrary LUT files.
- Preserve the output path `v2/runs/{workflow_id}/composition/{render_id}/final-ad-video.mp4`.
- Pin every timeline media source using both `asset_id` and `version_id`.
- Preserve the current selected final video if timeline validation or rendering fails.
- Reuse the existing asset-library picker; it must be filtered to compatible video/audio assets for timeline import.
- Use an isolated local feature branch, make local commits per task, and do not push or create a PR unless explicitly requested.

---

## File Structure

### Backend

- Modify: `adWorkflow/app/schemas/workflow_v2.py` — typed track, clip, transform, audio, color, source, response, and validation schemas.
- Modify: `adWorkflow/app/api/v2/endpoints/workflows.py` — timeline-source import route and extended timeline routes.
- Modify: `adWorkflow/app/services/v2_final_composition_timeline.py` — canonical timeline validation, source registration, timeline responses, and events.
- Modify: `adWorkflow/app/services/v2_final_composition_renderer.py` — safe FFmpeg filter graph construction and output verification.
- Create: `adWorkflow/app/services/v2_final_composition_filters.py` — pure, validated filter-graph builders.
- Test: `adWorkflow/tests/test_v2_final_composition_timeline_api.py` — API, conflict, source registration, and event coverage.
- Test: `adWorkflow/tests/test_v2_final_composition_renderer.py` — filter graph and renderer validation coverage.

### Frontend

- Modify: `AdCraft/apps/web/src/types-v2.ts` — V2 timeline and source types.
- Modify: `AdCraft/apps/web/src/api/v2Client.ts` — GET/PATCH/render/source-import client methods.
- Modify: `AdCraft/apps/web/src/api/v2Normalizers.ts` — strict timeline/source normalizers.
- Create: `AdCraft/apps/web/src/features/workflow/final-composition/v2TimelineModel.ts` — immutable draft operations, snapping, split, and validation helpers.
- Create: `AdCraft/apps/web/src/features/workflow/final-composition/useV2FinalCompositionEditor.ts` — load/save/render/conflict/event controller.
- Create: `AdCraft/apps/web/src/features/workflow/final-composition/V2FinalCompositionEditor.tsx` — editor workbench composition.
- Create: `AdCraft/apps/web/src/features/workflow/final-composition/V2CompositionPreview.tsx` — synchronized media preview and playhead.
- Create: `AdCraft/apps/web/src/features/workflow/final-composition/V2TimelineTracks.tsx` — dnd-kit track/clip surface.
- Create: `AdCraft/apps/web/src/features/workflow/final-composition/V2ClipInspector.tsx` — trim, audio, transform, and color controls.
- Modify: `AdCraft/apps/web/src/features/workflow/workbench/WorkflowWorkbenchAssetsSection.tsx` — launch the V2 editor for Final Composition.
- Modify: `AdCraft/apps/web/src/features/workflow/page/useWorkflowPageSurfaceAssembly.tsx` — reuse asset-library picker for V2 timeline import and mount the editor surface.
- Modify: `AdCraft/apps/web/src/features/workflow/runtime/useV2RuntimeController.ts` — consume final timeline and render SSE events.
- Test: `AdCraft/apps/web/.local-test/v2TimelineModel.test.ts` — temporary local test runner, removed before commit if repository policy continues to exclude frontend tests.

## Task 1: Define and Validate the V2 Timeline Document

**Files:**
- Modify: `adWorkflow/app/schemas/workflow_v2.py:1171-1268`
- Modify: `adWorkflow/app/services/v2_final_composition_timeline.py:318-350`
- Test: `adWorkflow/tests/test_v2_final_composition_timeline_api.py`

**Consumes:** Existing `WorkflowV2Timeline`, `WorkflowV2TimelineTrack`, and `WorkflowV2TimelineClip`.

**Produces:** `TimelineTransformV2`, `TimelineAudioV2`, `TimelineColorV2`, `TimelineSubtitleStyleV2`, extended typed timeline classes, and `validate_timeline_document()`.

- [ ] **Step 1: Write failing schema tests**

```python
def test_v2_timeline_rejects_overlapping_enabled_video_clips_on_one_track(client):
    timeline = _timeline_payload_with_two_video_clips(start_a=0, duration_a=5, start_b=4, duration_b=2)
    response = client.patch(_timeline_url(), json={"expected_version": 1, "timeline": timeline})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "v2_timeline_track_overlap"


def test_v2_timeline_accepts_two_overlapping_audio_tracks(client):
    timeline = _timeline_payload_with_overlapping_audio_clips()
    response = client.patch(_timeline_url(), json={"expected_version": 1, "timeline": timeline})
    assert response.status_code == 200
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `pytest tests/test_v2_final_composition_timeline_api.py -k "overlapping" -v`

Expected: the overlap validation is absent or accepts the invalid visual overlap.

- [ ] **Step 3: Implement typed controls and validation**

```python
class TimelineColorV2(BaseModel):
    preset_id: Literal["none", "warm", "cool", "high_contrast", "muted"] = "none"
    brightness: float = Field(default=0, ge=-1, le=1)
    contrast: float = Field(default=1, ge=0, le=3)
    saturation: float = Field(default=1, ge=0, le=3)
    exposure: float = Field(default=0, ge=-4, le=4)
    temperature: float = Field(default=0, ge=-100, le=100)
    tint: float = Field(default=0, ge=-100, le=100)
    hue: float = Field(default=0, ge=-180, le=180)


class TimelineSubtitleStyleV2(BaseModel):
    font_size: int = Field(default=42, ge=12, le=96)
    color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    position: Literal["top_center", "center", "bottom_center"] = "bottom_center"


def validate_timeline_document(timeline: WorkflowV2Timeline) -> None:
    tracks = {track.track_id: track for track in timeline.tracks}
    for clip in timeline.clips:
        if clip.track_id not in tracks:
            raise V2FinalCompositionTimelineError("v2_timeline_invalid_clip", "Clip references a missing track.")
    _validate_non_audio_track_overlaps(timeline, tracks)
```

- [ ] **Step 4: Run focused and full timeline API tests**

Run: `pytest tests/test_v2_final_composition_timeline_api.py -v`

Expected: PASS with overlap, numeric-boundary, and source-version assertions.

- [ ] **Step 5: Commit**

```bash
git add app/schemas/workflow_v2.py app/services/v2_final_composition_timeline.py tests/test_v2_final_composition_timeline_api.py
git commit -m "feat: validate v2 composition timelines"
```

## Task 2: Register Resource-Library Sources and Extend Timeline APIs

**Files:**
- Modify: `adWorkflow/app/api/v2/endpoints/workflows.py:856-908`
- Modify: `adWorkflow/app/services/v2_final_composition_timeline.py`
- Modify: `adWorkflow/app/schemas/workflow_v2.py`
- Test: `adWorkflow/tests/test_v2_final_composition_timeline_api.py`

**Consumes:** Task 1 timeline schema and `V2AssetStoreService`.

**Produces:** `POST /workflows/{workflow_id}/final-composition/timeline/sources`, enriched GET response with `available_sources`, and `final_timeline_updated` events.

- [ ] **Step 1: Write failing API tests**

```python
def test_v2_timeline_source_import_pins_asset_library_video(client, library_video):
    response = client.post(
        _timeline_url() + "/sources",
        json={"library_entity_id": library_video.entity_id, "library_asset_id": library_video.asset_id, "expected_media_type": "video"},
    )
    assert response.status_code == 200
    assert response.json()["source"]["version_id"]
    assert response.json()["source"]["origin"] == "asset_library"


def test_v2_timeline_source_import_rejects_audio_as_video(client, library_audio):
    response = client.post(_timeline_url() + "/sources", json={"library_asset_id": library_audio.asset_id, "expected_media_type": "video"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "v2_timeline_unsupported_source_media"
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `pytest tests/test_v2_final_composition_timeline_api.py -k "source_import" -v`

Expected: FAIL because the source registration route and response model do not exist.

- [ ] **Step 3: Implement source import and response enrichment**

```python
@router.post("/{workflow_id}/final-composition/timeline/sources", response_model=WorkflowV2TimelineSourceImportResponse)
def import_final_timeline_source(workflow_id: str, request: WorkflowV2TimelineSourceImportRequest, service: Annotated[V2FinalCompositionTimelineService, Depends(get_v2_final_timeline_service)]):
    return service.import_library_source(workflow_id, request)


def import_library_source(self, workflow_id: str, request: WorkflowV2TimelineSourceImportRequest) -> WorkflowV2TimelineSourceImportResponse:
    record = self._asset_store.materialize_library_asset(workflow_id, request.library_entity_id, request.library_asset_id)
    if record.media_type != request.expected_media_type:
        raise V2FinalCompositionTimelineError("v2_timeline_unsupported_source_media", "Imported source media type does not match request.")
    return WorkflowV2TimelineSourceImportResponse(workflow_id=workflow_id, source=_timeline_source(record, origin="asset_library"))
```

- [ ] **Step 4: Run focused tests and the V2 asset tests**

Run: `pytest tests/test_v2_final_composition_timeline_api.py -v && pytest tests/test_v2_workflow_assets.py -v`

Expected: PASS; imported resources expose a pinned V2 asset/version and remain authorized.

- [ ] **Step 5: Commit**

```bash
git add app/api/v2/endpoints/workflows.py app/services/v2_final_composition_timeline.py app/schemas/workflow_v2.py tests/test_v2_final_composition_timeline_api.py
git commit -m "feat: import library media into v2 timelines"
```

## Task 3: Replace Concat Rendering with a Validated Filter Graph

**Files:**
- Create: `adWorkflow/app/services/v2_final_composition_filters.py`
- Modify: `adWorkflow/app/services/v2_final_composition_renderer.py:235-600`
- Test: `adWorkflow/tests/test_v2_final_composition_renderer.py`

**Consumes:** Task 1 typed clip controls and Task 2 pinned source versions.

**Produces:** Pure filter builders `build_visual_filter_graph()` and `build_audio_filter_graph()` used by `V2FinalCompositionRenderer`.

- [ ] **Step 1: Write failing renderer tests**

```python
def test_filter_graph_applies_trim_color_and_video_track_order():
    graph = build_visual_filter_graph(_two_layer_timeline())
    assert "trim=start=1.000:end=4.000" in graph
    assert "eq=" in graph
    assert "overlay=" in graph


def test_audio_filter_graph_delays_mixes_and_fades_tracks():
    graph = build_audio_filter_graph(_multi_audio_timeline())
    assert "adelay=2000" in graph
    assert "afade=t=in" in graph
    assert "amix=inputs=2" in graph
```

- [ ] **Step 2: Run focused renderer tests and verify failure**

Run: `pytest tests/test_v2_final_composition_renderer.py -k "filter_graph" -v`

Expected: FAIL because filter graph helpers do not exist and current renderer uses concat demuxing.

- [ ] **Step 3: Implement safe graph builders and renderer integration**

```python
def build_visual_filter_graph(clips: list[ResolvedTimelineClip], canvas: CanvasSpec) -> str:
    # Values arrive from Pydantic-validated fields only; no client expression is concatenated.
    return ";".join(_visual_chain(clip, canvas) for clip in sorted(clips, key=_visual_order))


def build_audio_filter_graph(clips: list[ResolvedTimelineClip]) -> str:
    return ";".join([*(_audio_chain(clip) for clip in clips), _amix_chain(clips)])
```

Use `-filter_complex` with separately supplied source inputs. Trim every source version before transformation, use `setpts`/`adelay` for `start_time`, compose visual tracks in `track.order`, and mix all enabled unmuted audio clips. Resolve sources by `asset_id` and `version_id`, never by a public URL.

- [ ] **Step 4: Run renderer and V2 Final Composition test suites**

Run: `pytest tests/test_v2_final_composition_renderer.py -v && pytest tests/test_v2_final_composition_timeline_api.py -v && pytest tests/test_v2_final_composition.py -v`

Expected: PASS; tests confirm output validation and failure keeps the previous final version selected.

- [ ] **Step 5: Commit**

```bash
git add app/services/v2_final_composition_filters.py app/services/v2_final_composition_renderer.py tests/test_v2_final_composition_renderer.py
git commit -m "feat: render v2 timelines with multi-track filters"
```

## Task 4: Preserve Render Lifecycle and Event Semantics

**Files:**
- Modify: `adWorkflow/app/services/v2_final_composition_timeline.py:106-200, 504-610`
- Test: `adWorkflow/tests/test_v2_final_composition_timeline_api.py`

**Consumes:** Tasks 1-3.

**Produces:** Verified `final_timeline_created`, `final_timeline_updated`, and final-render event payloads.

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_v2_render_failure_preserves_selected_final_version_and_emits_failure(client, monkeypatch):
    before = _selected_final_version(client)
    monkeypatch.setattr(V2FinalCompositionRenderer, "render", _failed_render)
    response = client.post(_render_url(), json=_render_payload())
    assert response.status_code == 400
    assert _selected_final_version(client) == before
    assert "final_composition_render_failed" in _event_types(client)
```

- [ ] **Step 2: Run lifecycle tests and verify failure**

Run: `pytest tests/test_v2_final_composition_timeline_api.py -k "render_failure_preserves" -v`

Expected: FAIL if the selected version is mutated before output validation or event payloads are incomplete.

- [ ] **Step 3: Implement event and selection ordering**

```python
result = renderer.render(workflow, item, slot, provider_payload)
if result.status != "completed" or not result.local_file_path:
    self._emit_render_failed(workflow, item, slot, render_id, result)
    raise V2FinalCompositionTimelineError("v2_timeline_render_failed", result.error_message or "Timeline render failed.")
record = self._register_final_asset_version(workflow, item, slot, timeline, render_id, provider_payload, result)
self._emit_render_completed(workflow, item, slot, render_id, record)
```

- [ ] **Step 4: Run lifecycle and acceptance tests**

Run: `pytest tests/test_v2_final_composition_timeline_api.py -v && pytest tests/test_v2_workflow_acceptance.py -k "final" -v`

Expected: PASS with exact event names, ids, and source-version lineage.

- [ ] **Step 5: Commit**

```bash
git add app/services/v2_final_composition_timeline.py tests/test_v2_final_composition_timeline_api.py
git commit -m "fix: preserve v2 final render lifecycle"
```

## Task 5: Add a Typed V2 Timeline Frontend Client

**Files:**
- Modify: `AdCraft/apps/web/src/types-v2.ts`
- Modify: `AdCraft/apps/web/src/api/v2Client.ts`
- Modify: `AdCraft/apps/web/src/api/v2Normalizers.ts`
- Test: `AdCraft/apps/web/.local-test/v2TimelineClient.test.ts`

**Consumes:** The contract endpoints from Tasks 1-4.

**Produces:** `V2FinalTimeline`, `V2TimelineSource`, and `v2Api.getFinalTimeline/saveFinalTimeline/importFinalTimelineSource/renderFinalTimeline`.

- [ ] **Step 1: Write failing normalizer tests**

```ts
import assert from "node:assert/strict";
import { normalizeV2FinalTimelineResponse } from "../src/api/v2Normalizers.ts";

const response = normalizeV2FinalTimelineResponse({ timeline: { timeline_id: "tl_1", version: 1, tracks: [], clips: [] }, available_sources: [] });
assert.equal(response.timeline.timeline_id, "tl_1");
assert.deepEqual(response.available_sources, []);
```

- [ ] **Step 2: Run test and verify failure**

Run: `npx tsx .local-test/v2TimelineClient.test.ts`

Expected: FAIL because the V2 final-timeline normalizer and types do not exist.

- [ ] **Step 3: Implement client and normalizers**

```ts
getFinalTimeline(workflowId: string): Promise<V2FinalTimelineResponse> {
  return requestV2(`/workflows/${encodeURIComponent(workflowId)}/final-composition/timeline`, {}, normalizeV2FinalTimelineResponse);
}

saveFinalTimeline(workflowId: string, body: V2FinalTimelineUpdateRequest): Promise<V2FinalTimelineUpdateResponse> {
  return requestV2(`/workflows/${encodeURIComponent(workflowId)}/final-composition/timeline`, { method: "PATCH", body: JSON.stringify(body) }, normalizeV2FinalTimelineUpdateResponse);
}
```

- [ ] **Step 4: Run test, lint, and production build**

Run: `npx tsx .local-test/v2TimelineClient.test.ts && npm run lint:react && npm run build`

Expected: all commands exit 0.


- [ ] **Step 5: Remove the temporary test with `apply_patch`, do not stage it, then commit**

```bash
git add apps/web/src/types-v2.ts apps/web/src/api/v2Client.ts apps/web/src/api/v2Normalizers.ts
git commit -m "feat: add v2 final timeline api client"
```

## Task 6: Build the Draft Model and Editor Controller

**Files:**
- Create: `AdCraft/apps/web/src/features/workflow/final-composition/v2TimelineModel.ts`
- Create: `AdCraft/apps/web/src/features/workflow/final-composition/useV2FinalCompositionEditor.ts`
- Test: `AdCraft/apps/web/.local-test/v2TimelineModel.test.ts`

**Consumes:** Task 5 types and API client.

**Produces:** Immutable operations `moveClip`, `trimClip`, `splitClip`, `addTrack`, `deleteTrack`, `setClipColor`, `setClipAudio`, and editor controller `useV2FinalCompositionEditor`.

- [ ] **Step 1: Write failing draft-operation tests**

```ts
assert.deepEqual(moveClip(timeline, "clip_1", { trackId: "video-2", startTime: 3.25 }), expectedTimeline);
assert.equal(splitClip(timeline, "clip_1", 2).clips.length, 2);
assert.equal(setClipColor(timeline, "clip_1", { preset_id: "warm" }).clips[0].color.preset_id, "warm");
```

- [ ] **Step 2: Run the model test and verify failure**

Run: `npx tsx .local-test/v2TimelineModel.test.ts`

Expected: FAIL because draft operation helpers do not exist.

- [ ] **Step 3: Implement immutable operations and controller state**

```ts
export function moveClip(timeline: V2FinalTimeline, clipId: string, target: { trackId: string; startTime: number }): V2FinalTimeline {
  return updateTimelineClip(timeline, clipId, (clip) => ({ ...clip, track_id: target.trackId, start_time: snapTimelineSeconds(target.startTime) }));
}

export function useV2FinalCompositionEditor(workflowId: string | null) {
  // Owns baseline, dirty draft, save/render states, 409 conflict state, and SSE refresh decisions.
}
```

- [ ] **Step 4: Run model test, lint, and build**

Run: `npx tsx .local-test/v2TimelineModel.test.ts && npm run lint:react && npm run build`

Expected: all commands exit 0.


- [ ] **Step 5: Remove the temporary test with `apply_patch`, do not stage it, then commit**

```bash
git add apps/web/src/features/workflow/final-composition/v2TimelineModel.ts apps/web/src/features/workflow/final-composition/useV2FinalCompositionEditor.ts
git commit -m "feat: manage v2 composition timeline drafts"
```

## Task 7: Implement the Final Composition Workbench UI

**Files:**
- Create: `AdCraft/apps/web/src/features/workflow/final-composition/V2FinalCompositionEditor.tsx`
- Create: `AdCraft/apps/web/src/features/workflow/final-composition/V2CompositionPreview.tsx`
- Create: `AdCraft/apps/web/src/features/workflow/final-composition/V2TimelineTracks.tsx`
- Create: `AdCraft/apps/web/src/features/workflow/final-composition/V2ClipInspector.tsx`
- Modify: `AdCraft/apps/web/src/styles.css`
- Modify: `AdCraft/apps/web/package.json`
- Modify: `AdCraft/apps/web/package-lock.json`

**Consumes:** Task 6 editor controller and the existing media-lightbox/asset-library patterns.

**Produces:** A selection-driven workbench with transport, preview, track controls, dnd-kit timeline manipulation, and inspector controls.

- [ ] **Step 1: Write a failing component-model test for timeline layout**

```ts
assert.deepEqual(visibleTimelineClipRange({ start_time: 2, duration: 3 }, { secondsPerPixel: 0.1 }), { left: 20, width: 30 });
assert.equal(playheadForPreviewTime(4.25, { secondsPerPixel: 0.1 }), 42.5);
```

- [ ] **Step 2: Run the test and verify failure**

Run: `npx tsx .local-test/v2TimelineModel.test.ts`

Expected: FAIL because layout helpers do not exist.

- [ ] **Step 3: Install the established drag dependency and build the UI**

Run: `npm install @dnd-kit/core @dnd-kit/sortable`

```tsx
<V2FinalCompositionEditor controller={editor}>
  <V2CompositionPreview timeline={editor.draft} playheadSeconds={editor.playheadSeconds} onPlayheadChange={editor.seek} />
  <V2TimelineTracks timeline={editor.draft} onMoveClip={editor.moveClip} onSplitClip={editor.splitClip} />
  <V2ClipInspector clip={editor.selectedClip} onChangeColor={editor.setClipColor} onChangeAudio={editor.setClipAudio} />
</V2FinalCompositionEditor>
```

Use icon-only tool buttons with accessible labels/tooltips for transport, split, delete, mute, and lock. Use bounded track heights and fixed timeline scales so drag state never changes layout dimensions. Preview may use CSS-filter approximation for responsive feedback; only completed server render is authoritative.

- [ ] **Step 4: Run lint and production build**

Run: `npm run lint:react && npm run build`

Expected: both commands exit 0.

- [ ] **Step 5: Commit**

```bash
git add apps/web/package.json apps/web/package-lock.json apps/web/src/features/workflow/final-composition apps/web/src/styles.css
git commit -m "feat: add v2 final composition editor"
```

## Task 8: Connect Asset Library, Runtime Events, and Final Asset Refresh

**Files:**
- Modify: `AdCraft/apps/web/src/features/workflow/workbench/WorkflowWorkbenchAssetsSection.tsx`
- Modify: `AdCraft/apps/web/src/features/workflow/page/useWorkflowPageSurfaceAssembly.tsx`
- Modify: `AdCraft/apps/web/src/features/workflow/runtime/useV2RuntimeController.ts`
- Modify: `AdCraft/apps/web/src/features/workflow/types.ts`
- Test: `AdCraft/apps/web/.local-test/v2FinalCompositionEventModel.test.ts`

**Consumes:** Tasks 5-7 and existing `AssetLibraryPicker`.

**Produces:** Editor launch from the selected V2 Final Composition node, video/audio filtered library import, and non-destructive SSE refresh behavior.

- [ ] **Step 1: Write failing event and import tests**

```ts
assert.equal(shouldRefreshV2FinalTimeline("final_timeline_updated", { dirty: false }), "replace_draft");
assert.equal(shouldRefreshV2FinalTimeline("final_timeline_updated", { dirty: true }), "preserve_draft");
assert.equal(assetLibraryEntityTypeForTimelineImport("audio"), "audio");
```

- [ ] **Step 2: Run tests and verify failure**

Run: `npx tsx .local-test/v2FinalCompositionEventModel.test.ts`

Expected: FAIL because no V2 final timeline event policy or import target exists.

- [ ] **Step 3: Implement launch, import, and event handling**

```ts
if (event.event_type === "final_timeline_updated" || event.event_type === "final_timeline_created") {
  editor.refreshFromServer({ preserveDraft: editor.dirty });
}

if (event.event_type === "final_composition_render_completed") {
  void refreshV2WorkflowGraph(workflowId);
  void loadV2SlotVersions(finalVideoSlotId);
}
```

Add a `v2-final-timeline-import` picker target that opens the existing library modal in single-selection mode, validates video/audio media before import, calls `importFinalTimelineSource`, then adds the pinned returned source to the current draft.

- [ ] **Step 4: Run tests, lint, and build**

Run: `npx tsx .local-test/v2FinalCompositionEventModel.test.ts && npm run lint:react && npm run build`

Expected: all commands exit 0.


- [ ] **Step 5: Remove the temporary test with `apply_patch`, do not stage it, then commit**

```bash
git add apps/web/src/features/workflow/workbench/WorkflowWorkbenchAssetsSection.tsx apps/web/src/features/workflow/page/useWorkflowPageSurfaceAssembly.tsx apps/web/src/features/workflow/runtime/useV2RuntimeController.ts apps/web/src/features/workflow/types.ts
git commit -m "feat: connect v2 composition editor workflow state"
```

## Task 9: End-to-End Verification and Documentation Review

**Files:**
- Modify: `adWorkflow/tests/test_v2_final_composition_timeline_api.py`
- Modify: `adWorkflow/tests/test_v2_final_composition_renderer.py`
- Review: `docs/superpowers/plans/2026-07-14-v2-final-composition-editor-contract.md`

**Consumes:** Tasks 1-8.

**Produces:** Verified V2 editing, rendering, lifecycle, and frontend build evidence.

- [ ] **Step 1: Write the end-to-end test scenario**

```python
def test_v2_final_composition_multitrack_edit_render_round_trip(client, library_bgm, storyboard_video):
    timeline = _load_timeline(client)
    bgm = _import_library_source(client, library_bgm)
    edited = _add_audio_track_and_clip(_add_color_corrected_overlay(timeline, storyboard_video), bgm)
    saved = _save_timeline(client, edited)
    rendered = _render_timeline(client, saved)
    assert rendered["public_url"].endswith("final-ad-video.mp4")
    assert _selected_final_version(client) == rendered["version_id"]
```

- [ ] **Step 2: Run the scenario and verify failure before final integration corrections**

Run: `pytest tests/test_v2_final_composition_timeline_api.py -k "multitrack_edit_render_round_trip" -v`

Expected: FAIL until all source, graph, and asset registration paths are connected.

- [ ] **Step 3: Correct integration defects only within the documented contract**

Verify the saved timeline contains pinned source versions, output metadata records timeline id/version and all source ids, and a forced render error preserves the previous final version.

- [ ] **Step 4: Run complete verification**

Run:

```bash
cd adWorkflow && pytest tests/test_v2_final_composition_timeline_api.py tests/test_v2_final_composition_renderer.py tests/test_v2_final_composition.py -v
cd ../AdCraft/apps/web && npm run lint:react && npm run build
```

Expected: all commands exit 0; no legacy V1-only UI path is exercised for V2 workflows.

- [ ] **Step 5: Commit verification fixes**

```bash
# In the backend repository:
git add tests/test_v2_final_composition_timeline_api.py tests/test_v2_final_composition_renderer.py
git commit -m "test: verify v2 final composition editor workflow"

# In the frontend repository:
git add apps/web/src
git commit -m "test: verify v2 final composition editor workflow"
```

## Plan Self-Review

- Contract coverage: multi-track editing, color correction, preview, BGM/video library import, version-pinned media, rendering, events, output location, conflicts, and failure preservation each have an explicit backend/frontend task.
- No-placeholder review: all planned endpoints, file paths, test commands, error codes, and function names are specified in the contract or task interfaces.
- Consistency review: the plan uses `final_timeline_created`, `final_timeline_updated`, and `final_composition_render_*` consistently; timeline save/render use `timeline.version`; media sources always use asset and version identifiers.

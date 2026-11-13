# AdCraft Cutia integration

Source: https://github.com/msgbyte/cutia at `ba7dc787815155a197a3f4e875af46720084bc77` (MIT).
`UPSTREAM.json` records the exact files copied from `apps/web/src`; `ui/`, locale JSON and global CSS come from the same revision. The original README and license are retained. This is the actual native editor source, not a visual imitation or a hosted third-party iframe.

## Running and building

Use AdCraft's normal `npm ci`, `npm run dev` and `npm run build`. Vite builds `index.html` and `cutia-editor.html`; both must be served from the same origin. There is no Next.js service or separate Cutia backend. The host loads the editor only when opening an Editing card. Its iframe isolates CSS, shortcuts, command history and the native EditorCore singleton.

A secure context (HTTPS, or localhost for development) and WebCodecs are required for export. Chrome/Edge are the tested browser family. Cutia renders video and mixes audio locally through Mediabunny. MP4 uses H.264/AAC; WebM uses VP9/Opus. The official `@mediabunny/aac-encoder` WASM extension loads on demand where native AAC is absent. Video encoder availability and memory still depend on the browser/device; errors leave the project open. Large source files are loaded into browser memory.

## Ownership and backend contract

- `cutia/main.tsx`: native Media, Text, Transitions, Preview, Timeline and Properties panels, with output settings and a dark responsive shell. The sticker catalog is disabled in the AdCraft UI.
- `cutia/bridge.ts`: origin/source/session-checked postMessage bridge. No remote Cutia server or credentials. Native IndexedDB project/media writes are redirected to AdCraft.
- `src/features/agent-canvas/editing/cutia/project.ts`: legacy-to-native conversion and persisted JSON schema.
- `CutiaEditingPanel.tsx` and `saveQueue.ts`: serial/coalesced saves, flush-before-close/export, failure recovery, download and canvas integration.

Native projects live under `node.parameters.cutia_editor_v1 = { snapshot, export? }`. `snapshot` has `schemaVersion: 1`, native `project`, and a media-ID-to-backend-asset mapping. Files, AudioBuffers and object URLs are never serialized. Existing `structured_content.manifest` is retained. PATCH uses existing revision handling; it does not require a new backend schema or migration. Opening an unchanged project causes no write.

New local media and completed renders use `POST /api/v2/workflows/:id/assets/upload`. Project media is imported on demand; the initial open fetches only referenced sources. A rendered result is attached to the saved snapshot and can be downloaded or added as a ready source-only video using the existing node-create API with `source_asset_id`. It can then be connected to downstream nodes. No provider generation or legacy single-track `/export` job runs. Native exports do not overwrite the Editing node's backend `output_asset_id`, which the current PATCH contract does not allow.

Save failures retain the last local edit and block normal close/export until retry. An upload failure retains the rendered File for download and retry with the same idempotency key. If only the final project PATCH fails, retry reuses the uploaded asset. Closing without saving is explicit. A revision conflict refreshes the workflow through the existing callback; retrying saves the user's current local version.

## Legacy migration

Preserves input order, timing, trims, native audio/mute/volume, BGM looping/volume and output dimensions/FPS. Fill becomes the equivalent native scale. A legacy empty tail becomes an editable transparent `Timeline duration` track because native Cutia derives duration from elements. Missing source videos are reported. Existing native snapshots always take precedence over the old manifest.

Legacy clip-end fades and BGM fade envelopes are intentionally retired: importing a legacy plan ignores these effects and shows no fade-migration warning. Users author new transitions directly in Cutia. Arbitrary multi-track/text/transition edits stay in the native snapshot; they must not be projected back into the backend's single-track manifest.

## Adaptations to upstream files

- `globals.css`: explicit Tailwind source scanning so editor CSS remains inside its iframe.
- `timeline-toolbar.tsx`, `timeline-element.tsx`, `assets/draggable-item.tsx`: accessible names for icon controls and clips.
- `timeline-element.tsx`, `properties/text-properties.tsx`: removed remote text-to-speech controls. AdCraft's workflow owns AI generation; local Text editing remains native.
- `core/managers/media-manager.ts`: rethrow upload failures after rollback so callers cannot insert dangling references.
- `lib/media/audio.ts`: close the temporary export AudioContext.
- `services/renderer/scene-exporter.ts`: lazy official AAC fallback.

Vite adapters replace Next Image, localization and unused AI agent/caption/TTS service dependencies. Full upstream auth, AI chat, remote speech generation and speech transcription are not part of the editing surface. English/Chinese labels reuse the pinned upstream catalog with small integration translations.

## Verification

`npm run typecheck` checks both host and editor (`tsconfig.cutia.json`). `npm run build` emits both entries. Unit tests cover legacy migration, persisted state, message boundaries, serial saves, save/upload recovery and stale exports. `npm run test:browser:mock-media` uses native Cutia UI and real FFmpeg-generated input files; only backend HTTP is mocked. It checks native edits, reopen, actual browser export, downloaded bytes, ffprobe video/audio streams, audible source+BGM tones, rendered text, source-node creation and downstream reuse. FFmpeg/ffprobe are test dependencies, not production/browser dependencies. No paid provider calls or live-project writes occur. After building, `CUTIA_USE_BUILD=1 npm run test:browser:mock-media -- -g "native mp4"` repeats the MP4 flow against the compiled iframe and its lazy AAC chunk.

Public notices and corresponding source/build links ship under `/licenses/cutia/NOTICE.txt`, including Cutia MIT, Mediabunny MPL and the AAC extension's FFmpeg LGPL notices. Keep these notices and `UPSTREAM.json` when updating the vendored core.

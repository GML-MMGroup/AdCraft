# Guided Product Source V2 Design

## Goal

Support the canonical guided Product image-source interaction without parsing
assistant prose or creating client-side Canvas graph data. The user can choose
existing Ready Project AssetVersions, upload new images, order multiview inputs,
or ask the Agent to generate the Product source.

## Constraints

- Frontend changes are limited to `/data/longwei.wu/AdCraft/apps/web`.
- `/data/wenwu.meng/adWorkflow` is read-only and is the contract authority.
- Submit through the existing typed Guided Interaction endpoint.
- Preserve exact `asset_id`, `version_id`, and returned `pending_handoff_id`.
- Main accepts exactly one image; Multiview accepts two through eight unique,
  ordered image versions.
- Do not send local paths, preview URLs, prompts, inferred IDs, Nodes, or
  Bindings as source authority.
- Do not call Guidance Advance while a `product_source` wait is open.
- Source-only Product nodes are rendered exclusively from backend Workflow data.
- Real or paid media providers are outside this change.

## Existing Support

The current frontend already includes the `product_source` interaction and
awaiting discriminants, strict content normalization, the typed submit union,
dedicated Product routing, upload receipt preservation, relevant SSE events,
and source-only workbench suppression. This change deepens that implementation
rather than creating a second flow.

## Selection Model

`ProductSourceDecisionDock` owns one ordered draft list. Each entry is one of:

```ts
type ProductSourceDraftItem =
  | {
      kind: "asset_version";
      key: string;
      assetId: string;
      versionId: string;
      displayName: string;
      previewUrl: string | null;
    }
  | {
      kind: "local_file";
      key: string;
      file: File;
      displayName: string;
      previewUrl: string;
      uploadIdempotencyKey: string;
    };
```

The list is the sole source of presentation order and submit order. Existing
assets are admitted only when they are Project Assets with `status=ready`,
`mediaType=image`, and a non-null immutable version identity. Local images are
uploaded only after explicit confirmation.

For Main, adding a source replaces the previous source. For Multiview, adding a
source appends it until the backend maximum is reached. Duplicate immutable
identities and duplicate local file identities are rejected. Multiview entries
have visible ordinal numbers and accessible move-up/move-down controls.

## Submission Flow

1. The user chooses Upload or Generate.
2. Generate submits an empty `asset_versions` list and null handoff.
3. Upload validates the ordered draft against backend min/max cardinality.
4. Local entries upload sequentially through the existing workflow upload API,
   each with a stable idempotency key retained across retries.
5. Upload receipts replace local entries in-memory for the request while
   preserving their exact list positions.
6. A non-null upload `pending_handoff_id` is forwarded unchanged. Conflicting
   handoffs fail locally rather than selecting one arbitrarily.
7. The typed Guided Interaction request uses the latest interaction/session and
   guidance revisions plus the ordered immutable references.
8. A synchronous ref guard ensures one confirmation creates one upload/submit
   transaction even if the button is clicked repeatedly.

The existing chat hook retains the guided-submit idempotency key for an
identical interaction revision and request body. An accepted response refreshes
Timeline, Workflow/Canvas, Runtime, and Project Assets. Backend Nodes and
Bindings remain authoritative.

## Stale State And Errors

The Product draft identity excludes interaction revision:

```text
workflow_id + question_id + input_kind
```

This lets a stale-authority refresh replace interaction/session revisions while
preserving selected files, assets, and ordering for the same Product question.
The Dock remains open and requires explicit resubmission.

Product-specific errors are rendered inside the Dock:

- stale Workflow/Guidance revision: refresh authority and keep the draft;
- invalid count: keep selections and identify the allowed count;
- missing, foreign, non-image, or unreadable version: keep the draft and ask the
  user to replace the affected source;
- compilation or FFmpeg failure: keep uploaded assets and allow a new commit;
- idempotency replay: remain pending until authoritative terminal refresh.

No error path automatically resends the request or calls Guidance Advance.

## UI Structure

The existing Decision Dock frame remains unchanged. Its body contains:

- backend-localized prompt;
- Upload and Generate choices;
- compact Project Assets image browser with loading/error/empty/search states;
- local file upload control;
- ordered selected-source strip with thumbnails, ordinals, reorder, and remove;
- backend count summary and local Product-specific issue.

The UI uses the existing monochrome Agent Canvas visual language. It does not
open a second modal or expose IDs and internal metadata.

## Verification

Focused Vitest coverage must prove strict normalization, Main and Multiview
cardinality, existing assets, mixed uploaded/existing order, generate, pending
handoff, upload replay keys, stale draft preservation, Product errors, one
submit per confirmation, no Media Review fallback, no Guidance Advance, and
source-only control suppression.

Playwright Mock-media acceptance covers the complete browser interaction
without provider calls. Canonical-backend smoke uses fresh workflows and stops
before real generation.

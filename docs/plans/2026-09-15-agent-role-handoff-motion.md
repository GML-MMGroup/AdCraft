# Agent role handoff motion

## Goal

Keep a role's animated artwork visible for the whole authoring stretch instead of
stopping it when an intermediate activity, proposal, or materialization changes
state. A role starts when it first appears in the Timeline and hands off to the
next role when that role first appears. Explicit failure/cancellation remains a
safe stop; a completed final role settles when the conversation is no longer
working.

## Design

- Project role starts globally from the ordered stage threads, rather than
  treating each activity/proposal as an independent animation lifecycle.
- The most recently entered role is the active handoff owner. Earlier roles are
  idle once a later role has entered, even if their old proposal is still in the
  Timeline.
- `expert_activity.completed`, applied receipts, and prompt/materialization
  transitions do not stop a role while the conversation is still advancing.
- Failed, cancelled, or superseded role attempts stop immediately. A completed
  role with no later handoff settles only when the agent conversation is no
  longer working, preventing the final role from looping after production ends.
- Role animation loading remains atomic: before the animated artwork is ready,
  the existing loader is shown; once ready, the role text and artwork appear
  together.

## Motion program

Scene Designer receives a finite construction intro followed by a closed,
infinite working scan. The loop's first and last poses match, so the scan does
not jump when WAAPI repeats. Other role programs keep their existing intro and
infinite working tracks; a contract test prevents a finite main working track
from regressing.

## Implementation steps

1. Extend role lifecycle projection with global role ordering, handoff ownership,
   conversation-working fallback, and hard-terminal handling.
2. Feed the existing `agentWorking` signal into the projection; do not add
   polling or new network requests.
3. Split Scene Designer's one-shot reveal from its looping working scan and keep
   reduced-motion behavior unchanged.
4. Update lifecycle and Scene Designer tests for Character Designer's
   post-proposal generation window, role handoff, stale refreshes, retry, and
   closed scan loops.
5. Run focused Vitest suites and TypeScript checking; inspect the diff before
   handing the worktree back.

## Acceptance criteria

- Character Designer remains animated after its proposal activity completes
  while its next role has not yet appeared.
- Character Designer settles immediately when Scene Designer enters the
  Timeline, and Scene Designer starts without an idle gap.
- Scene Designer's construction scan repeats continuously while working.
- A hard failed/cancelled/superseded role stops without waiting for a handoff.
- Final completed production does not leave a role animation running forever.
- No additional polling, timers, layout work, or non-composited animation is
  introduced.

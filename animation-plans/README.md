# Animation Improvement Plans

Plans are stamped against frontend commit `f5aa1e4f` and intentionally contain no source-code changes.

| Order | Plan | Severity | Status | Dependency |
| --- | --- | --- | --- | --- |
| 1 | [Smooth the dual-orbit generation loader](001-smooth-dual-orbit-loader.md) | MEDIUM | TODO | None |
| 2 | [Desynchronize concurrent generation loaders](002-desynchronize-concurrent-loaders.md) | LOW | TODO | Plan 001 |
| 3 | [Fade in newly generated media only](003-fade-in-newly-generated-media.md) | LOW | TODO | Independent; execute after Plan 002 to avoid overlapping Node edits |

## Recommended execution order

1. Execute Plan 001 and feel-check the single-node trajectory before adding phase offsets.
2. Execute Plan 002 and test four simultaneous working nodes plus same-node rerenders.
3. Execute Plan 003 last because it touches `AgentCanvasNode.tsx`, which Plan 002 also modifies.

Each plan must be implemented test-first in an isolated worktree. Do not combine the three review gates: trajectory quality, concurrent phase stability, and media transition correctness can fail independently.

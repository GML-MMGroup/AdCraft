# Model-Neutral Structured Output Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `CompactTurnIntentDecisionV3` tolerate explicitly registered model-output shape differences and preserve a safe assistant reply when two structured attempts cannot be validated, without applying workflow mutations.

**Architecture:** Keep normalization contract-local and provider-neutral in Python, then run the normalized candidate through the existing strict Pydantic and source-quote checks. On the second invalid submission, Python returns a trusted `ordinary_conversation` fallback plus bounded audit metadata; when the repaired response is not JSON and cannot reach Python validation, the TypeScript transport submits the same trusted fallback as attempt 2. Existing conversation completion persists that ordinary reply, while all authoring fields remain absent.

**Tech Stack:** Python 3.10, Pydantic 2, pytest, TypeScript 5.8, Vitest, FastAPI internal Agent tool protocol, Docker Compose, CLIProxyAPI.

---

## File map

- Modify `apps/api/app/services/v2_agent_structured_normalization.py`: pure contract-local alias, enum, NFKC-key, numeric-value, null, and audit normalization.
- Create `apps/api/tests/test_v2_agent_structured_normalization.py`: fixed output-shape regression tests independent of provider names.
- Modify `apps/api/app/services/v2_agent_structured_validation.py`: validate source quotes after normalization and produce the trusted attempt-2 conversational fallback.
- Modify `apps/api/app/schemas/agent_runtime.py`: bounded structured-fallback audit types shared by Python and TypeScript.
- Create `apps/api/tests/test_v2_agent_structured_validation.py`: validation-order, strict-boundary, fallback, and audit tests.
- Modify generated `apps/api/agent/src/generated/agent-runtime.schema.json` and `apps/api/agent/src/generated/agent-runtime.ts` only through `app.cli.generate_agent_contracts`.
- Modify `apps/api/app/api/internal/router.py`: serialize fallback audit returned by trusted validation.
- Modify `apps/api/agent/src/pi-structured-transport.ts`: propagate fallback audit and recover malformed repaired JSON only for `decide_turn_intent` plus `CompactTurnIntentDecisionV3`.
- Modify `apps/api/agent/src/server.ts`: retain bounded fallback audit in `agent_runtime_audit`.
- Create `apps/api/agent/tests/pi-structured-transport.test.ts`: transport repair/fallback tests.
- Create `apps/api/tests/test_agent_canvas_structured_fallback.py`: persisted timeline and zero-workflow-mutation regression.
- Do not change `CompactTurnIntentDecisionV3` itself, global Pydantic `extra="forbid"`, provider selection, CPA configuration, or media generation routes.

### Task 1: Contract-local normalization for model-shaped candidates

**Files:**
- Modify: `apps/api/app/services/v2_agent_structured_normalization.py`
- Create: `apps/api/tests/test_v2_agent_structured_normalization.py`

- [ ] **Step 1: Write fixed-shape failing tests**

Create tests that call `AGENT_STRUCTURED_NORMALIZATION_REGISTRY.normalize()` directly. Use shape names rather than provider names:

```python
from app.services.v2_agent_structured_normalization import (
    AGENT_STRUCTURED_NORMALIZATION_REGISTRY,
)


def _candidate() -> dict:
    return {
        "mode": "guided_production",
        "objective": "制作一条广告",
        "assistant_message": "我会按你的要求规划。",
        "explicit_elements": {
            "product": {"presence": "Included", "source_quote": "广告"},
            "video": {"presence": "需要", "source_quote": "广告"},
        },
        "requirement_patch": {
            "controls_to_set": {
                "target_duration_sec": {"value": "60", "source_quote": "60秒"},
                "fps": {"value": "24", "source_quote": "24帧"},
            }
        },
    }


def test_enum_and_field_alias_shape_is_canonicalized() -> None:
    result = AGENT_STRUCTURED_NORMALIZATION_REGISTRY.normalize(
        "CompactTurnIntentDecisionV3", _candidate()
    )
    assert result.violations == ()
    assert result.value["explicit_elements"]["product"]["presence"] == "include"
    assert result.value["explicit_elements"]["video"]["presence"] == "include"
    controls = result.value["requirement_patch"]["controls_to_set"]
    assert controls["duration_seconds"]["value"] == 60.0
    assert controls["frame_rate"]["value"] == 24.0
    assert "target_duration_sec" not in controls
    assert "fps" not in controls


def test_canonical_and_alias_conflict_is_rejected() -> None:
    candidate = _candidate()
    controls = candidate["requirement_patch"]["controls_to_set"]
    controls["duration_seconds"] = {"value": 30, "source_quote": "30秒"}
    result = AGENT_STRUCTURED_NORMALIZATION_REGISTRY.normalize(
        "CompactTurnIntentDecisionV3", candidate
    )
    assert [item.code for item in result.violations] == [
        "agent_structured_normalization_alias_conflict"
    ]


def test_unknown_presence_and_unregistered_extra_field_remain_strict() -> None:
    candidate = _candidate()
    candidate["explicit_elements"]["product"]["presence"] = "probably"
    candidate["unregistered_extra"] = "must not disappear"
    result = AGENT_STRUCTURED_NORMALIZATION_REGISTRY.normalize(
        "CompactTurnIntentDecisionV3", candidate
    )
    assert result.value["explicit_elements"]["product"]["presence"] == "probably"
    assert result.value["unregistered_extra"] == "must not disappear"


def test_input_is_not_mutated_and_canonical_shape_is_idempotent() -> None:
    candidate = _candidate()
    original = deepcopy(candidate)
    once = AGENT_STRUCTURED_NORMALIZATION_REGISTRY.normalize(
        "CompactTurnIntentDecisionV3", candidate
    )
    twice = AGENT_STRUCTURED_NORMALIZATION_REGISTRY.normalize(
        "CompactTurnIntentDecisionV3", once.value
    )
    assert candidate == original
    assert twice.value == once.value
    assert twice.normalized_path_count == 0
```

Also cover all approved presence aliases, `duration_sec`, `resolution`, full-width/NFKC field keys, omittable nulls, integer count strings, and a non-lossless value such as `"约60秒"` remaining unchanged.

`CompactRequirementControlsV2` currently has no boolean-valued control. Do not add an unused string-to-boolean coercion rule; add that rule and its test only when a concrete boolean field is introduced into this contract.

- [ ] **Step 2: Run the normalization tests and confirm they fail**

Run from `apps/api`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v2_agent_structured_normalization.py -q
```

Expected: failures showing `Included`, `需要`, `target_duration_sec`, and numeric strings are not yet normalized.

- [ ] **Step 3: Implement ordered, provider-neutral rules**

Replace the single compact-intent null rule with one composed pure function. Keep all mappings immutable and scoped to exact paths:

```python
COMPACT_TURN_INTENT_FIELD_ALIASES_RULE_ID = "compact_turn_intent_v3.field_aliases.v1"
COMPACT_TURN_INTENT_PRESENCE_ALIASES_RULE_ID = "compact_turn_intent_v3.presence_aliases.v1"
COMPACT_TURN_INTENT_LOSSLESS_SCALARS_RULE_ID = "compact_turn_intent_v3.lossless_scalars.v1"

_CONTROL_ALIASES = MappingProxyType({
    "target_duration_sec": "duration_seconds",
    "duration_sec": "duration_seconds",
    "resolution": "output_resolution",
    "fps": "frame_rate",
})
_PRESENCE_ALIASES = MappingProxyType({
    "include": "include", "included": "include", "present": "include",
    "required": "include", "包含": "include", "需要": "include", "已提及": "include",
    "exclude": "exclude", "excluded": "exclude", "absent": "exclude",
    "omit": "exclude", "排除": "exclude", "不要": "exclude", "不需要": "exclude",
    "unspecified": "unspecified", "unknown": "unspecified",
    "not_mentioned": "unspecified", "not specified": "unspecified",
    "未说明": "unspecified", "未提及": "unspecified", "不确定": "unspecified",
})
_FLOAT_CONTROLS = frozenset({"duration_seconds", "frame_rate"})
_INTEGER_CONTROLS = frozenset({
    "product_count", "prop_count", "character_count", "scene_count",
    "storyboard_sequence_count", "video_segment_count",
})
```

The implementation order must be: NFKC key canonicalization, field aliases, presence aliases, lossless numeric values inside `{value, source_quote}`, omittable null removal, and audit aggregation. If both canonical and alias keys exist, compare their complete values; identical values may remove the alias, differing values emit one bounded conflict violation. Do not drop any unregistered extra field.

- [ ] **Step 4: Run focused tests and lint**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v2_agent_structured_normalization.py -q
.\.venv\Scripts\python.exe -m ruff check app/services/v2_agent_structured_normalization.py tests/test_v2_agent_structured_normalization.py
```

Expected: all normalization tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit the normalization slice**

```powershell
git add apps/api/app/services/v2_agent_structured_normalization.py apps/api/tests/test_v2_agent_structured_normalization.py
git commit -m "feat: normalize compact agent intent shapes"
```

### Task 2: Normalize before source-quote and strict contract validation

**Files:**
- Modify: `apps/api/app/services/v2_agent_structured_validation.py`
- Create: `apps/api/tests/test_v2_agent_structured_validation.py`

- [ ] **Step 1: Write failing validation-order and strict-boundary tests**

Build a temporary SQLite-backed `AgentRunRepository`, persist a `CompactTurnIntentDecisionV3` run using validation profile `agent_intake_source_quotes_v1`, and persist the source turn text `"请制作60秒竖版广告"`. Assert:

```python
result = service.validate(run=run, submission=submission)
assert result.accepted is True
assert result.normalized_value["requirement_patch"]["controls_to_set"]["duration_seconds"] == {
    "value": 60.0,
    "source_quote": "60秒",
}
```

Add negative tests proving that an alias with `source_quote="不存在的原文"`, an unknown presence value, an extra top-level field, a run/contract identity mismatch, and conflicting alias values are rejected. Assert no test depends on provider or model ID.

- [ ] **Step 2: Run focused validation tests and confirm failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v2_agent_structured_validation.py -q
```

Expected: the aliased candidate fails before normalized source-quote validation is applied.

- [ ] **Step 3: Move raw semantic validation behind normalization**

In `V2AgentStructuredValidationService.validate`, calculate normalization first. For normalization conflicts, return only the normalization violations. For schema-valid normalized values, call `_raw_semantic_violations(run, normalization.value)` and then the existing profile-specific semantic checks. Keep identity validation first and `extra="forbid"` unchanged.

The order must be:

```python
identity -> normalize -> normalization conflicts -> Pydantic contract
-> source-quote validation on normalized value -> profile semantics -> accepted
```

- [ ] **Step 4: Run validation plus normalization regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v2_agent_structured_normalization.py tests/test_v2_agent_structured_validation.py -q
```

Expected: accepted aliases retain exact source evidence; invalid quotes and unknown fields remain rejected.

- [ ] **Step 5: Commit validation ordering**

```powershell
git add apps/api/app/services/v2_agent_structured_validation.py apps/api/tests/test_v2_agent_structured_validation.py
git commit -m "fix: validate normalized agent intent evidence"
```

### Task 3: Trusted attempt-2 conversational fallback with bounded audit

**Files:**
- Modify: `apps/api/app/schemas/agent_runtime.py`
- Modify: `apps/api/app/services/v2_agent_structured_validation.py`
- Modify: `apps/api/app/api/internal/router.py`
- Modify: `apps/api/tests/test_v2_agent_structured_validation.py`
- Regenerate: `apps/api/agent/src/generated/agent-runtime.schema.json`
- Regenerate: `apps/api/agent/src/generated/agent-runtime.ts`

- [ ] **Step 1: Add failing fallback tests**

For attempt 2 of `CompactTurnIntentDecisionV3`, assert an invalid candidate returns an accepted trusted fallback:

```python
assert result.accepted is True
assert result.normalized_value == {
    "mode": "ordinary_conversation",
    "objective": "Preserve a safe conversational response after structured validation failed.",
    "assistant_message": "我已收到，会继续协助你。",
}
assert result.fallback_audit.contract_name == "CompactTurnIntentDecisionV3"
assert result.fallback_audit.error_code == "agent_structured_fallback_applied"
assert result.fallback_audit.used_model_message is True
```

Add cases for control-character removal, whitespace-only text, non-string text, and text longer than 2000 characters. These must use the deterministic Chinese fallback. Add a non-intake contract attempt-2 case that remains rejected.

- [ ] **Step 2: Run fallback tests and confirm schema failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v2_agent_structured_validation.py -q
```

Expected: `AgentStructuredValidationResult` has no `fallback_audit`, and attempt 2 remains rejected.

- [ ] **Step 3: Add bounded protocol models**

Add `AgentStructuredFallbackAuditV1` with only:

```python
class AgentStructuredFallbackAuditV1(_StrictModel):
    contract_name: Literal["CompactTurnIntentDecisionV3"]
    error_code: Literal["agent_structured_fallback_applied"]
    failure_codes: tuple[str, ...] = Field(default=(), max_length=32)
    validation_paths: tuple[str, ...] = Field(default=(), max_length=32)
    submission_attempt: Literal[2]
    used_model_message: bool
    reason: Literal["validation_exhausted", "repair_json_invalid"]
```

Add optional `fallback_audit` to `AgentStructuredValidationResult`. Add optional `structured_fallback` to `AgentTransportAttemptMetadataV1` so the completed run audit can retain the same bounded object. Do not include candidate JSON, prompts, user text, API keys, or provider credentials.

- [ ] **Step 4: Implement one fallback builder and use it at every attempt-2 rejection exit**

Define constants and pure helpers in `v2_agent_structured_validation.py`:

```python
_STRUCTURED_FALLBACK_MESSAGE = (
    "已收到你的请求，但本轮结构化解析未能安全完成。"
    "你的项目没有被修改，请重试或换一种表达。"
)


def _safe_fallback_message(value: dict[str, Any]) -> tuple[str, bool]:
    candidate = value.get("assistant_message")
    if not isinstance(candidate, str) or not candidate.strip() or len(candidate) > 2_000:
        return _STRUCTURED_FALLBACK_MESSAGE, False
    cleaned = "".join(
        character
        for character in candidate.strip()
        if character in {"\n", "\t"} or unicodedata.category(character) != "Cc"
    )
    return (cleaned, True) if cleaned else (_STRUCTURED_FALLBACK_MESSAGE, False)
```

Create `_fallback_or_rejected(...)`. It may return fallback only when contract is exactly `CompactTurnIntentDecisionV3`, operation submission attempt is exactly `2`, and identity/context are valid. A violation containing `agent_validation_context_invalid` remains terminal and cannot be converted to fallback. The normalized fallback must contain only `mode`, fixed `objective`, and `assistant_message`; validate it again with `validate_agent_contract` before returning `accepted=True`. All other contracts and attempt 1 use `_rejected` unchanged.

- [ ] **Step 5: Serialize fallback audit from the internal tool endpoint**

In `apps/api/app/api/internal/router.py`, add `fallback_audit` beside `normalization_audit` only when present. Do not put it in rejection logs and do not log assistant text.

- [ ] **Step 6: Regenerate runtime contracts**

Run from `apps/api`:

```powershell
.\.venv\Scripts\python.exe -m app.cli.generate_agent_contracts --output agent/src/generated
```

Expected: only the generated schema and TypeScript declarations change, and both contain `AgentStructuredFallbackAuditV1` plus the optional audit fields.

- [ ] **Step 7: Run Python tests and generated-contract integrity checks**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v2_agent_structured_validation.py -q
Push-Location agent
npm test -- --run tests/protocol-validator.test.ts tests/package-integrity.test.ts
npm run typecheck
Pop-Location
```

Expected: all commands pass.

- [ ] **Step 8: Commit the trusted fallback protocol**

```powershell
git add apps/api/app/schemas/agent_runtime.py apps/api/app/services/v2_agent_structured_validation.py apps/api/app/api/internal/router.py apps/api/tests/test_v2_agent_structured_validation.py apps/api/agent/src/generated/agent-runtime.schema.json apps/api/agent/src/generated/agent-runtime.ts
git commit -m "feat: preserve safe replies after structured validation"
```

### Task 4: Runtime recovery when repaired output is not JSON

**Files:**
- Modify: `apps/api/agent/src/pi-structured-transport.ts`
- Modify: `apps/api/agent/src/server.ts`
- Create: `apps/api/agent/tests/pi-structured-transport.test.ts`

- [ ] **Step 1: Write failing transport tests**

Instantiate `PiStructuredTransportRouter` with a scripted executor and submit stub. Cover:

1. first candidate rejected, repaired candidate accepted normally;
2. first candidate rejected, repaired JSON rejected by Python but returned as trusted fallback;
3. repaired content is malformed JSON for the intake contract, so the router submits a canonical fallback as attempt 2, preserving a safe `assistant_message` from the parsed primary candidate when one exists;
4. malformed repaired content for another contract still throws `agent_structured_output_invalid`;
5. fallback audit contains no model text, prompt, or candidate JSON.

The malformed-intake assertion must be:

```typescript
expect(submit).toHaveBeenLastCalledWith(
  {
    mode: "ordinary_conversation",
    objective: "Preserve a safe conversational response after structured validation failed.",
    assistant_message: SAFE_STRUCTURED_FALLBACK_MESSAGE,
  },
  2,
  "call_structured_fallback",
);
expect(result.audit.structured_fallback?.reason).toBe("repair_json_invalid");
```

- [ ] **Step 2: Run the new Vitest file and confirm failure**

Run from `apps/api/agent`:

```powershell
npm test -- --run tests/pi-structured-transport.test.ts
```

Expected: malformed repair still throws and no fallback audit is exposed.

- [ ] **Step 3: Add exact intake-contract guards and canonical fallback submission**

Add:

```typescript
const SAFE_STRUCTURED_FALLBACK_MESSAGE =
  "已收到你的请求，但本轮结构化解析未能安全完成。你的项目没有被修改，请重试或换一种表达。";

function supportsSafeConversationFallback(input: StructuredTransportRunInput): boolean {
  return input.request.operation === "decide_turn_intent" &&
    input.request.contract_name === "CompactTurnIntentDecisionV3";
}
```

If repaired JSON parsing fails and the guard is true, build the canonical fallback from the already parsed primary candidate. Reuse only its top-level `assistant_message` when it is a non-empty string of at most 2000 characters after the same control-character cleanup; otherwise use the deterministic message. Submit that fixed fallback as attempt 2. Require the Python response to be accepted; if it is not, preserve the current terminal failure. Never parse text out of the malformed repair response, and never synthesize fallback for proposal, materialization, Provider, node, or asset contracts.

- [ ] **Step 4: Propagate only bounded fallback audit**

Read `fallback_audit` from a completed validation result and pass it into `auditForAttempt`. For malformed repair, construct the bounded audit with reason `repair_json_invalid`, empty validation paths, attempt 2, and `used_model_message=false`. Update `safeAttemptAudit` in `server.ts` to copy only the typed `structured_fallback` object.

- [ ] **Step 5: Run transport tests, full Agent tests, and typecheck**

```powershell
npm test -- --run tests/pi-structured-transport.test.ts
npm test
npm run typecheck
```

Expected: all tests pass; canonical Grok/OpenAI-shaped acceptance still uses one submission and no fallback audit.

- [ ] **Step 6: Commit runtime recovery**

```powershell
git add apps/api/agent/src/pi-structured-transport.ts apps/api/agent/src/server.ts apps/api/agent/tests/pi-structured-transport.test.ts
git commit -m "fix: recover malformed intake repairs safely"
```

### Task 5: Persisted conversation and zero-side-effect regression

**Files:**
- Create: `apps/api/tests/test_agent_canvas_structured_fallback.py`
- Modify only if the test proves necessary: `apps/api/app/services/agent_canvas_conversation.py`

- [ ] **Step 1: Write an integration test around the existing conversation service**

Use the real SQLite repositories and a gateway returning the trusted fallback intent. Record the requirement revision, node IDs, asset IDs, and guidance-session revision before processing. After `process_turn` and after reloading the turn from the repository, assert:

```python
assert completed.status == "completed"
assert completed.assistant_message == fallback_message
assert reloaded.assistant_message == fallback_message
assert requirements_after.revision_no == requirements_before.revision_no
assert node_ids_after == node_ids_before
assert asset_ids_after == asset_ids_before
assert guidance_revision_after == guidance_revision_before
```

Also assert there is no Provider dispatch and no proposal/action persistence.

- [ ] **Step 2: Run the integration test**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_canvas_structured_fallback.py -q
```

Expected: it should pass using the existing `ordinary_conversation` branch. If it fails, make the smallest change in `_process_message_turn_lean` so fallback intents go directly to `_complete_turn` before requirement/session mutation; do not add a new public turn status.

- [ ] **Step 3: Run all focused Python regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v2_agent_structured_normalization.py tests/test_v2_agent_structured_validation.py tests/test_agent_canvas_structured_fallback.py tests/test_v2_agent_runtime_errors.py tests/test_v2_pi_agent_context.py -q
```

Expected: all pass, with fallback turns stored as ordinary completed turns and no authoring side effects.

- [ ] **Step 4: Commit the conversation regression**

```powershell
git add apps/api/tests/test_agent_canvas_structured_fallback.py
if (git diff --quiet -- apps/api/app/services/agent_canvas_conversation.py) {
  git commit -m "test: preserve fallback agent conversation replies"
} else {
  git add apps/api/app/services/agent_canvas_conversation.py
  git commit -m "fix: persist fallback agent conversation replies"
}
```

### Task 6: Full verification and live CPA acceptance

**Files:**
- No new production files expected.

- [ ] **Step 1: Run static and unit verification**

From repository root:

```powershell
Push-Location apps/api
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m pytest -q
Push-Location agent
npm test
npm run typecheck
Pop-Location
Pop-Location
git diff --check
```

Expected: all commands pass and `git diff --check` prints nothing.

- [ ] **Step 2: Rebuild only affected Compose services**

```powershell
docker compose up -d --build api agent web
docker compose ps
```

Expected: `api`, `agent`, `web`, `db`, and `cpa` are running/healthy; CPA remains the existing separate sidecar.

- [ ] **Step 3: Run live Gemini-shaped acceptance**

In the AdCraft workflow UI, submit a Chinese request containing product, `60秒`, and `竖版`. Verify logs:

```powershell
docker compose logs --no-color --since 5m api agent | Select-String -Pattern 'agent_structured_submission_rejected|agent_structured_fallback_applied|run_completed'
```

Expected: the request either normalizes and completes normally, or completes with bounded fallback audit. Refresh the page and verify both user and assistant messages remain visible.

- [ ] **Step 4: Run live canonical-shape acceptance with CPA Grok**

Temporarily select the configured CPA Grok text/Agent model through the existing application setting, replay the same request, then restore the configured default. Verify there is no provider-specific compatibility branch, no unexpected fallback, and the response remains after refresh.

- [ ] **Step 5: Verify workflow immutability on forced fallback**

Use a test-only scripted invalid response or the integration test fixture, not a paid media request. Compare requirement revision, nodes, assets, and Provider task counts before and after. Expected: assistant text is persisted, while all four workflow-state counts remain unchanged.

- [ ] **Step 6: Inspect final Git scope and commit any verification-only fixture update**

```powershell
git status --short
git log --oneline -6
git diff origin/custom-main...HEAD --stat
```

Expected: only the files listed in this plan changed; `.env`, `cpa/config.yaml`, `cpa/auths`, logs, downloaded media, and credentials are absent. Do not push until the user requests or confirms delivery to `custom-main`.

## Acceptance checklist

- [ ] Current `presence` aliases and `target_duration_sec` normalize without provider-specific code.
- [ ] Canonical Grok/OpenAI-compatible shapes are unchanged and idempotent.
- [ ] Unknown enums, unregistered fields, invalid source quotes, identity mismatches, and alias conflicts stay strict.
- [ ] Only `CompactTurnIntentDecisionV3` can use conversational fallback.
- [ ] Attempt-2 fallback contains no action, capability, requirement patch, node, asset, or Provider mutation.
- [ ] Fallback reply survives timeline reload.
- [ ] Audit is bounded and contains no prompt, full candidate, user text, key, token, or credential.
- [ ] Python tests, Agent tests, typecheck, Compose health, Gemini acceptance, and Grok acceptance all pass.

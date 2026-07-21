from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.schemas.workflow_v2 import WorkflowItemV2, WorkflowSlotV2, WorkflowV2
from app.schemas.workflow_v2_acceptance import (
    V2WorkflowAcceptanceCheck,
    V2WorkflowAcceptanceExpectedCounts,
    V2WorkflowAcceptanceFailure,
    V2WorkflowAcceptanceFixture,
    V2WorkflowAcceptanceReport,
)
from app.schemas.workflow_v2_prompt_eval import (
    V2PromptEvalAdRequest,
    V2PromptEvalFixture,
)
from app.services.v2_workflow_store import V2WorkflowStore


ACCEPTANCE_FAILURE_CODES = (
    "acceptance_explicit_count_mismatch",
    "acceptance_missing_required_node",
    "acceptance_missing_required_item",
    "acceptance_missing_required_slot",
    "acceptance_specialist_prompt_layer_invalid",
    "acceptance_slot_semantic_boundary_failed",
    "acceptance_provider_payload_prompt_mismatch",
    "acceptance_provider_payload_empty",
    "acceptance_provider_payload_legacy_field",
    "acceptance_provider_payload_base64_leak",
    "acceptance_reference_missing",
    "acceptance_fallback_raw_prompt_echo",
    "acceptance_fallback_reduced_count",
    "acceptance_replay_mutated_workflow",
)

_REQUIRED_NODES = [
    "script",
    "product-generation",
    "character-generation",
    "scene-generation",
    "storyboard",
    "bgm",
    "final-composition",
]
_REQUIRED_SLOT_TYPES = {
    "product": ["product_main_image", "product_multi_view_grid"],
    "character": ["character_main_image", "character_three_view"],
    "scene": ["scene_main_image", "scene_multi_view_grid"],
    "storyboard": [
        "shot_cell_1",
        "shot_cell_2",
        "shot_cell_3",
        "shot_cell_4",
        "shot_video_segment",
    ],
    "bgm": ["bgm_audio"],
    "final_composition": ["final_composition"],
}
_LEGACY_EMPTY_MARKERS = (
    "Location: .",
    "Lighting: .",
    "Atmosphere: .",
    "Shot: .",
    "Visual: .",
    "Camera: .",
    "Action: .",
)
_SENSITIVE_KEY_TERMS = ("api_key", "secret", "token", "password", "raw_bytes", "bytes")


class V2WorkflowAcceptanceFixtureRegistry:
    def __init__(self) -> None:
        self._fixtures = {fixture.fixture_id: fixture for fixture in _core_fixtures()}

    def list_fixtures(self) -> list[V2WorkflowAcceptanceFixture]:
        return list(self._fixtures.values())

    def get(self, fixture_id: str) -> V2WorkflowAcceptanceFixture:
        fixture = self._fixtures.get(fixture_id)
        if fixture is None:
            raise KeyError(fixture_id)
        return fixture


class V2WorkflowAcceptanceValidator:
    def validate_planning(
        self,
        *,
        fixture: V2WorkflowAcceptanceFixture,
        workflow: WorkflowV2,
    ) -> V2WorkflowAcceptanceReport:
        checks = [
            self._workflow_shell_check(fixture, workflow),
            self._count_check(fixture, workflow),
            self._required_slot_check(fixture, workflow),
            self._specialist_prompt_layer_check(fixture, workflow),
            self._semantic_boundary_check(fixture, workflow, []),
            self._fallback_safety_check(fixture, workflow),
        ]
        failures = [failure for check in checks for failure in check.failures]
        return V2WorkflowAcceptanceReport(
            status="failed" if failures else "passed",
            fixture_id=fixture.fixture_id,
            workflow_id=workflow.workflow_id,
            checks=checks,
            failures=failures,
        )

    def validate(
        self,
        *,
        fixture: V2WorkflowAcceptanceFixture,
        workflow: WorkflowV2,
        provider_payload_snapshots: list[dict[str, Any]] | None = None,
        mutation_detected: bool = False,
    ) -> V2WorkflowAcceptanceReport:
        provider_payloads = provider_payload_snapshots or []
        checks = [
            self._workflow_shell_check(fixture, workflow),
            self._count_check(fixture, workflow),
            self._required_slot_check(fixture, workflow),
            self._specialist_prompt_layer_check(fixture, workflow),
            self._semantic_boundary_check(fixture, workflow, provider_payloads),
            self._provider_payload_check(fixture, provider_payloads),
            self._reference_check(fixture, workflow, provider_payloads),
            self._fallback_safety_check(fixture, workflow),
            self._non_mutation_check(fixture, workflow, mutation_detected),
        ]
        failures = [failure for check in checks for failure in check.failures]
        return V2WorkflowAcceptanceReport(
            status="failed" if failures else "passed",
            fixture_id=fixture.fixture_id,
            workflow_id=workflow.workflow_id,
            checks=checks,
            failures=failures,
            provider_payload_snapshots=[
                _sanitize_payload(payload) for payload in provider_payloads
            ],
        )

    def _workflow_shell_check(
        self,
        fixture: V2WorkflowAcceptanceFixture,
        workflow: WorkflowV2,
    ) -> V2WorkflowAcceptanceCheck:
        failures = [
            _failure(
                fixture,
                code="acceptance_missing_required_node",
                stage="workflow_shell",
                message=f"Missing required node: {node_id}",
                node_id=node_id,
            )
            for node_id in fixture.required_nodes
            if _node(workflow, node_id) is None
        ]
        return _check("workflow_shell", failures)

    def _count_check(
        self,
        fixture: V2WorkflowAcceptanceFixture,
        workflow: WorkflowV2,
    ) -> V2WorkflowAcceptanceCheck:
        actual = _workflow_counts(workflow)
        expected = fixture.expected_counts.model_dump()
        failures: list[V2WorkflowAcceptanceFailure] = []
        for field_name, expected_value in expected.items():
            actual_value = actual[field_name]
            if actual_value == 0 and expected_value > 0:
                failures.append(
                    _failure(
                        fixture,
                        code="acceptance_missing_required_item",
                        stage="explicit_counts",
                        message=f"Missing required item family: {field_name}",
                    )
                )
            if actual_value != expected_value:
                failures.append(
                    _failure(
                        fixture,
                        code="acceptance_explicit_count_mismatch",
                        stage="explicit_counts",
                        message=(f"{field_name} expected {expected_value}, got {actual_value}."),
                    )
                )
        return _check("explicit_counts", failures)

    def _required_slot_check(
        self,
        fixture: V2WorkflowAcceptanceFixture,
        workflow: WorkflowV2,
    ) -> V2WorkflowAcceptanceCheck:
        failures: list[V2WorkflowAcceptanceFailure] = []
        for item in _items(workflow):
            required = fixture.required_slot_types.get(item.item_type, [])
            if item.item_type == "shot" and not item.shot_summary_prompt:
                failures.append(
                    _failure(
                        fixture,
                        code="acceptance_missing_required_slot",
                        stage="required_slots",
                        node_id=item.node_id,
                        item_id=item.item_id,
                        message="Storyboard shot summary prompt is missing.",
                    )
                )
            slot_types = {slot.slot_type for slot in item.slots}
            for slot_type in required:
                if slot_type not in slot_types:
                    failures.append(
                        _failure(
                            fixture,
                            code="acceptance_missing_required_slot",
                            stage="required_slots",
                            node_id=item.node_id,
                            item_id=item.item_id,
                            slot_id=f"{item.item_id}:{slot_type}",
                            message=f"Missing required slot: {slot_type}",
                        )
                    )
        return _check("required_slots", failures)

    def _specialist_prompt_layer_check(
        self,
        fixture: V2WorkflowAcceptanceFixture,
        workflow: WorkflowV2,
    ) -> V2WorkflowAcceptanceCheck:
        failures: list[V2WorkflowAcceptanceFailure] = []
        for item in _items(workflow):
            if item.item_type not in {"product", "character", "scene"}:
                continue
            creative_brief = _text(item.metadata.get("creative_brief") or item.item_prompt)
            asset_prompts = item.metadata.get("asset_prompts")
            if not isinstance(asset_prompts, dict) or not asset_prompts:
                failures.append(
                    _failure(
                        fixture,
                        code="acceptance_specialist_prompt_layer_invalid",
                        stage="specialist_prompt_layers",
                        node_id=item.node_id,
                        item_id=item.item_id,
                        message="Specialist item is missing asset_prompts.",
                    )
                )
                continue
            all_asset_prompts = [_text(value) for value in asset_prompts.values() if _text(value)]
            for slot in item.slots:
                slot_prompt = _text(slot.slot_prompt)
                asset_prompt = _text(asset_prompts.get(slot.slot_type))
                if not slot_prompt or not asset_prompt:
                    failures.append(
                        _failure(
                            fixture,
                            code="acceptance_specialist_prompt_layer_invalid",
                            stage="specialist_prompt_layers",
                            node_id=item.node_id,
                            item_id=item.item_id,
                            slot_id=slot.slot_id,
                            message="Slot asset prompt is missing.",
                        )
                    )
                    continue
                if creative_brief and slot_prompt == creative_brief:
                    failures.append(
                        _failure(
                            fixture,
                            code="acceptance_specialist_prompt_layer_invalid",
                            stage="specialist_prompt_layers",
                            node_id=item.node_id,
                            item_id=item.item_id,
                            slot_id=slot.slot_id,
                            message="Creative brief was used as the slot provider prompt.",
                        )
                    )
                sibling_prompts = [
                    prompt
                    for prompt in all_asset_prompts
                    if prompt and prompt != asset_prompt and len(prompt) > 20
                ]
                if any(prompt in slot_prompt for prompt in sibling_prompts):
                    failures.append(
                        _failure(
                            fixture,
                            code="acceptance_specialist_prompt_layer_invalid",
                            stage="specialist_prompt_layers",
                            node_id=item.node_id,
                            item_id=item.item_id,
                            slot_id=slot.slot_id,
                            message="Sibling asset prompt text leaked into this slot.",
                        )
                    )
        return _check("specialist_prompt_layers", failures)

    def _semantic_boundary_check(
        self,
        fixture: V2WorkflowAcceptanceFixture,
        workflow: WorkflowV2,
        provider_payloads: list[dict[str, Any]],
    ) -> V2WorkflowAcceptanceCheck:
        failures: list[V2WorkflowAcceptanceFailure] = []
        payloads_by_slot = _payloads_by_slot(provider_payloads)
        for item in _items(workflow):
            for slot in item.slots:
                texts = [_text(slot.slot_prompt)]
                payload = payloads_by_slot.get(slot.slot_id)
                if payload is not None:
                    texts.append(_provider_prompt(payload))
                    texts.append(_actual_provider_prompt(payload))
                text = " ".join(texts).lower()
                forbidden_terms = fixture.forbidden_terms_by_slot_type.get(slot.slot_type, [])
                for term in forbidden_terms:
                    if _contains_forbidden_term(text, term):
                        failures.append(
                            _failure(
                                fixture,
                                code="acceptance_slot_semantic_boundary_failed",
                                stage="slot_semantic_boundary",
                                node_id=item.node_id,
                                item_id=item.item_id,
                                slot_id=slot.slot_id,
                                message=f"Slot prompt contains forbidden term: {term}",
                            )
                        )
                        break
        return _check("slot_semantic_boundary", failures)

    def _provider_payload_check(
        self,
        fixture: V2WorkflowAcceptanceFixture,
        provider_payloads: list[dict[str, Any]],
    ) -> V2WorkflowAcceptanceCheck:
        failures: list[V2WorkflowAcceptanceFailure] = []
        for payload in provider_payloads:
            slot_id = _optional_text(payload.get("slot_id"))
            slot_type = _optional_text(payload.get("slot_type"))
            canonical = _provider_prompt(payload)
            actual = _actual_provider_prompt(payload)
            if (
                not actual.strip()
                or not canonical.strip()
                or _explicit_empty_prompt(payload, "provider_prompt")
                or _explicit_empty_prompt(payload, "actual_provider_request_prompt")
            ):
                failures.append(
                    _failure(
                        fixture,
                        code="acceptance_provider_payload_empty",
                        stage="provider_payload",
                        slot_id=slot_id,
                        message="Provider payload prompt is empty.",
                    )
                )
            elif canonical.strip() != actual.strip():
                failures.append(
                    _failure(
                        fixture,
                        code="acceptance_provider_payload_prompt_mismatch",
                        stage="provider_payload",
                        slot_id=slot_id,
                        message="Actual provider prompt differs from canonical prompt.",
                    )
                )
            if any(marker in _payload_prompt_text(payload) for marker in _LEGACY_EMPTY_MARKERS):
                failures.append(
                    _failure(
                        fixture,
                        code="acceptance_provider_payload_legacy_field",
                        stage="provider_payload",
                        slot_id=slot_id,
                        message="Provider payload contains a legacy empty prompt template.",
                    )
                )
            if _contains_unsafe_payload(payload):
                failures.append(
                    _failure(
                        fixture,
                        code="acceptance_provider_payload_base64_leak",
                        stage="provider_payload",
                        slot_id=slot_id,
                        message="Provider payload contains unsafe media, secret, or path data.",
                    )
                )
            if slot_type is None:
                continue
        return _check("provider_payload", failures)

    def _reference_check(
        self,
        fixture: V2WorkflowAcceptanceFixture,
        workflow: WorkflowV2,
        provider_payloads: list[dict[str, Any]],
    ) -> V2WorkflowAcceptanceCheck:
        failures: list[V2WorkflowAcceptanceFailure] = []
        payloads_by_slot = _payloads_by_slot(provider_payloads)
        for item in _items(workflow):
            slots_by_type = {slot.slot_type: slot for slot in item.slots}
            for slot_type, main_type in {
                "product_multi_view_grid": "product_main_image",
                "character_three_view": "character_main_image",
                "scene_multi_view_grid": "scene_main_image",
            }.items():
                slot = slots_by_type.get(slot_type)
                main_slot = slots_by_type.get(main_type)
                main_asset_id = main_slot.selected_asset_id if main_slot else None
                if slot is None or not main_asset_id:
                    continue
                refs = _slot_reference_ids(slot, payloads_by_slot.get(slot.slot_id))
                if main_asset_id not in refs:
                    failures.append(
                        _failure(
                            fixture,
                            code="acceptance_reference_missing",
                            stage="references",
                            node_id=item.node_id,
                            item_id=item.item_id,
                            slot_id=slot.slot_id,
                            message="Multi-view slot is missing its selected main asset reference.",
                        )
                    )
            if item.item_type == "shot":
                cell_asset_ids = [
                    slot.selected_asset_id
                    for slot in item.slots
                    if slot.slot_type.startswith("shot_cell_") and slot.selected_asset_id
                ]
                for slot in item.slots:
                    refs = _slot_reference_ids(slot, payloads_by_slot.get(slot.slot_id))
                    if slot.slot_type.startswith("shot_cell_"):
                        if not (
                            _has_reference_kind(refs, "product")
                            and _has_reference_kind(refs, "character")
                            and _has_reference_kind(refs, "scene")
                        ):
                            failures.append(
                                _failure(
                                    fixture,
                                    code="acceptance_reference_missing",
                                    stage="references",
                                    node_id=item.node_id,
                                    item_id=item.item_id,
                                    slot_id=slot.slot_id,
                                    message="Storyboard cell is missing required upstream references.",
                                )
                            )
                    if slot.slot_type == "shot_video_segment" and not set(cell_asset_ids).issubset(
                        refs
                    ):
                        failures.append(
                            _failure(
                                fixture,
                                code="acceptance_reference_missing",
                                stage="references",
                                node_id=item.node_id,
                                item_id=item.item_id,
                                slot_id=slot.slot_id,
                                message="Shot video segment is missing selected shot cell references.",
                            )
                        )
        return _check("references", failures)

    def _fallback_safety_check(
        self,
        fixture: V2WorkflowAcceptanceFixture,
        workflow: WorkflowV2,
    ) -> V2WorkflowAcceptanceCheck:
        failures: list[V2WorkflowAcceptanceFailure] = []
        raw_prompt = workflow.prompt.strip().lower()
        counts = _workflow_counts(workflow)
        expected = fixture.expected_counts.model_dump()
        fallback_used = bool(workflow.metadata.get("fallback_used")) or any(
            item.metadata.get("materializer_mode") == "fallback" for item in _items(workflow)
        )
        for item in _items(workflow):
            for slot in item.slots:
                slot_prompt = _text(slot.slot_prompt).strip().lower()
                if not slot_prompt:
                    continue
                if slot_prompt == raw_prompt or slot_prompt.startswith("professional prompt for:"):
                    failures.append(
                        _failure(
                            fixture,
                            code="acceptance_fallback_raw_prompt_echo",
                            stage="fallback_safety",
                            node_id=item.node_id,
                            item_id=item.item_id,
                            slot_id=slot.slot_id,
                            message="Fallback slot prompt echoes or shallowly wraps the raw user prompt.",
                        )
                    )
                if (
                    raw_prompt
                    and raw_prompt in slot_prompt
                    and len(slot_prompt) < len(raw_prompt) + 40
                ):
                    failures.append(
                        _failure(
                            fixture,
                            code="acceptance_fallback_raw_prompt_echo",
                            stage="fallback_safety",
                            node_id=item.node_id,
                            item_id=item.item_id,
                            slot_id=slot.slot_id,
                            message="Fallback slot prompt is a shallow raw prompt wrapper.",
                        )
                    )
        if fallback_used and any(counts[name] != expected[name] for name in expected):
            failures.append(
                _failure(
                    fixture,
                    code="acceptance_fallback_reduced_count",
                    stage="fallback_safety",
                    message="Fallback output reduced explicit fixture counts.",
                )
            )
        return _check("fallback_safety", failures)

    def _non_mutation_check(
        self,
        fixture: V2WorkflowAcceptanceFixture,
        workflow: WorkflowV2,
        mutation_detected: bool,
    ) -> V2WorkflowAcceptanceCheck:
        failures = []
        if mutation_detected:
            failures.append(
                _failure(
                    fixture,
                    code="acceptance_replay_mutated_workflow",
                    stage="non_mutation",
                    message=f"Acceptance replay mutated workflow {workflow.workflow_id}.",
                )
            )
        return _check("non_mutation", failures)


class V2WorkflowAcceptanceRunner:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        registry: V2WorkflowAcceptanceFixtureRegistry | None = None,
        validator: V2WorkflowAcceptanceValidator | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._data_dir = self._settings.media_data_dir
        self._registry = registry or V2WorkflowAcceptanceFixtureRegistry()
        self._validator = validator or V2WorkflowAcceptanceValidator()

    def list_fixtures(self) -> list[V2WorkflowAcceptanceFixture]:
        return self._registry.list_fixtures()

    def run_fixture(self, fixture_id: str) -> V2WorkflowAcceptanceReport:
        try:
            fixture = self._registry.get(fixture_id)
        except KeyError:
            return _error_report(
                fixture_id,
                code="acceptance_fixture_not_found",
                message=f"Acceptance fixture not found: {fixture_id}",
            )
        try:
            workflow, payloads = self._workflow_and_payloads_for_fixture(fixture)
        except Exception as exc:  # noqa: BLE001 - acceptance reports carry controlled failures.
            return _error_report(
                fixture_id,
                code="acceptance_fixture_execution_failed",
                message=str(exc),
            )
        return self.validate_workflow(
            fixture=fixture,
            workflow=workflow,
            provider_payload_snapshots=payloads,
        )

    def validate_workflow(
        self,
        *,
        fixture: V2WorkflowAcceptanceFixture,
        workflow: WorkflowV2,
        provider_payload_snapshots: list[dict[str, Any]] | None = None,
    ) -> V2WorkflowAcceptanceReport:
        return self._validator.validate(
            fixture=fixture,
            workflow=workflow,
            provider_payload_snapshots=provider_payload_snapshots
            or _payloads_from_workflow(workflow),
        )

    def replay_workflow(self, workflow_id: str) -> V2WorkflowAcceptanceReport:
        store = V2WorkflowStore(self._data_dir)
        before = _snapshot_workflow_files(self._data_dir, workflow_id)
        workflow = store.load_workflow(workflow_id).model_copy(deep=True)
        fixture = self._fixture_for_workflow(workflow)
        payloads = _payloads_from_workflow(workflow)
        after = _snapshot_workflow_files(self._data_dir, workflow_id)
        return self._validator.validate(
            fixture=fixture,
            workflow=workflow,
            provider_payload_snapshots=payloads,
            mutation_detected=before != after,
        )

    def _workflow_and_payloads_for_fixture(
        self,
        fixture: V2WorkflowAcceptanceFixture,
    ) -> tuple[WorkflowV2, list[dict[str, Any]]]:
        from app.services.v2_prompt_eval_runner import V2PromptEvalRunner

        prompt_eval = V2PromptEvalRunner(replace(self._settings, agno_mock_mode=True))
        prompt_fixture = V2PromptEvalFixture(
            fixture_id=fixture.fixture_id,
            title=fixture.title,
            ad_request=V2PromptEvalAdRequest(
                prompt=fixture.input_prompt,
                duration_seconds=fixture.duration_seconds,
                audio_mode="bgm_only",
                reference_mode="strict",
                metadata={
                    "acceptance_fixture_id": fixture.fixture_id,
                    "planning_constraints": {},
                },
            ),
            expected_ad_type="advertising_workflow",
            expected_slots=[],
        )
        context = prompt_eval._build_fixture_context(prompt_fixture, "current", "mock")  # noqa: SLF001
        from app.services.v2_storyboard_director import V2StoryboardDirector

        _seed_acceptance_upstream_assets(context.workflow)
        V2StoryboardDirector(context.settings).ensure_storyboard_shots(context.workflow)
        _seed_acceptance_storyboard_cell_assets(context.workflow)
        records = prompt_eval._build_generation_plans(context, profile_id="current")  # noqa: SLF001
        return context.workflow, [_payload_from_plan_record(record) for record in records]

    def _fixture_for_workflow(self, workflow: WorkflowV2) -> V2WorkflowAcceptanceFixture:
        fixture_id = _optional_text(workflow.metadata.get("acceptance_fixture_id"))
        if fixture_id:
            try:
                return self._registry.get(fixture_id)
            except KeyError:
                pass
        return V2WorkflowAcceptanceFixture(
            fixture_id=fixture_id or "workflow_acceptance_replay",
            title="Workflow Acceptance Replay",
            input_prompt=workflow.prompt,
            duration_seconds=workflow.duration_seconds,
            expected_counts=V2WorkflowAcceptanceExpectedCounts(**_workflow_counts(workflow)),
            required_nodes=list(_REQUIRED_NODES),
            required_slot_types=dict(_REQUIRED_SLOT_TYPES),
            forbidden_terms_by_slot_type=_default_forbidden_terms(),
            required_reference_relationships=_default_reference_relationships(),
        )


def _core_fixtures() -> list[V2WorkflowAcceptanceFixture]:
    return [
        _fixture(
            "iphone_14_pro_core",
            "iPhone 14 Pro Core",
            (
                "Create a 30-second iPhone 14 Pro ad.\n"
                "Characters: one man and one woman.\n"
                "Scenes: two scenes, one urban night street and one nature travel scene.\n"
                "Storyboard: three shots.\n"
                "Style: premium, cinematic, modern technology commercial."
            ),
            product_count=1,
            character_count=2,
            scene_count=2,
            storyboard_shot_count=3,
            duration_seconds=30,
        ),
        _fixture(
            "lemon_tea_core",
            "Lemon Tea Core",
            (
                "Create a 30-second lemon tea commercial.\n"
                "Characters: two young adults and one shop staff member.\n"
                "Scenes: two scenes, one hot summer street and one cool convenience store.\n"
                "Storyboard: four shots.\n"
                "Style: bright anime commercial, refreshing, energetic, summer mood."
            ),
            product_count=1,
            character_count=3,
            scene_count=2,
            storyboard_shot_count=4,
            duration_seconds=30,
        ),
        _fixture(
            "fashion_product_core",
            "Fashion Product Core",
            (
                "Create a 20-second fashion sneaker ad.\n"
                "Characters: one stylish runner.\n"
                "Scenes: two scenes, one studio product setup and one city running route.\n"
                "Storyboard: three shots.\n"
                "Style: modern fashion campaign, bold lighting, dynamic rhythm."
            ),
            product_count=1,
            character_count=1,
            scene_count=2,
            storyboard_shot_count=3,
            duration_seconds=20,
        ),
        _fixture(
            "travel_place_core",
            "Travel Place Core",
            (
                "Create a 30-second boutique hotel travel ad.\n"
                "Characters: one traveler.\n"
                "Scenes: three scenes, lobby, guest room, and rooftop view.\n"
                "Storyboard: four shots.\n"
                "Style: warm cinematic travel film, calm, premium, inviting."
            ),
            product_count=1,
            character_count=1,
            scene_count=3,
            storyboard_shot_count=4,
            duration_seconds=30,
            metadata={
                "product_place_mapping": (
                    "The boutique hotel offering is represented through the existing "
                    "product/place-compatible product item path."
                )
            },
        ),
    ]


def _fixture(
    fixture_id: str,
    title: str,
    prompt: str,
    *,
    product_count: int,
    character_count: int,
    scene_count: int,
    storyboard_shot_count: int,
    duration_seconds: int,
    metadata: dict[str, Any] | None = None,
) -> V2WorkflowAcceptanceFixture:
    return V2WorkflowAcceptanceFixture(
        fixture_id=fixture_id,
        title=title,
        input_prompt=prompt,
        duration_seconds=duration_seconds,
        expected_counts=V2WorkflowAcceptanceExpectedCounts(
            product_count=product_count,
            character_count=character_count,
            scene_count=scene_count,
            storyboard_shot_count=storyboard_shot_count,
        ),
        required_nodes=list(_REQUIRED_NODES),
        required_slot_types=dict(_REQUIRED_SLOT_TYPES),
        forbidden_terms_by_slot_type=_default_forbidden_terms(),
        required_reference_relationships=_default_reference_relationships(),
        metadata=metadata or {},
    )


def _default_forbidden_terms() -> dict[str, list[str]]:
    return {
        "product_main_image": ["foreground actor", "character performance", "story action"],
        "product_multi_view_grid": ["foreground actor", "character performance", "story action"],
        "character_main_image": [
            "holding the iphone",
            "holding iphone",
            "using the product",
            "urban street scene",
            "other characters",
            "story action",
        ],
        "character_three_view": [
            "holding the iphone",
            "holding iphone",
            "using the product",
            "urban street scene",
            "other characters",
            "story action",
        ],
        "scene_main_image": [
            "foreground character",
            "foreground cast",
            "product handling",
            "storyboard action",
            "holding the iphone",
        ],
        "scene_multi_view_grid": [
            "foreground character",
            "foreground cast",
            "product handling",
            "storyboard action",
            "holding the iphone",
        ],
    }


def _default_reference_relationships() -> list[dict[str, Any]]:
    return [
        {"slot_type": "product_multi_view_grid", "requires": "same_item_main_asset"},
        {"slot_type": "character_three_view", "requires": "same_item_main_asset"},
        {"slot_type": "scene_multi_view_grid", "requires": "same_item_main_asset"},
        {"slot_type": "shot_cell_*", "requires": ["product", "character", "scene"]},
        {"slot_type": "shot_video_segment", "requires": "same_shot_cell_assets"},
        {"slot_type": "final_composition", "requires": ["video", "audio"]},
    ]


def _workflow_counts(workflow: WorkflowV2) -> dict[str, int]:
    return {
        "product_count": len(_items(workflow, item_type="product")),
        "character_count": len(_items(workflow, item_type="character")),
        "scene_count": len(_items(workflow, item_type="scene")),
        "storyboard_shot_count": len(_items(workflow, item_type="shot")),
    }


def _items(workflow: WorkflowV2, *, item_type: str | None = None) -> list[WorkflowItemV2]:
    items = [item for node in workflow.nodes for item in node.items]
    if item_type is not None:
        return [item for item in items if item.item_type == item_type]
    return items


def _node(workflow: WorkflowV2, node_id: str):
    return next((node for node in workflow.nodes if node.node_id == node_id), None)


def _payloads_by_slot(payloads: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(payload.get("slot_id")): payload
        for payload in payloads
        if str(payload.get("slot_id") or "").strip()
    }


def _payload_from_plan_record(record: Any) -> dict[str, Any]:
    payload = dict(record.provider_payload)
    payload["node_id"] = record.item.node_id
    payload["item_id"] = record.item.item_id
    payload["slot_id"] = record.slot.slot_id
    payload["slot_type"] = record.slot.slot_type
    payload["media_type"] = record.slot.media_type
    reference_asset_ids = list(
        dict.fromkeys(
            [
                *list(record.reference_asset_ids),
                *list(payload.get("reference_asset_ids") or []),
                *list(record.slot.implicit_reference_ids),
                *list(record.slot.explicit_reference_ids),
            ]
        )
    )
    payload["reference_asset_ids"] = reference_asset_ids
    capture = payload.get("provider_request_capture")
    if isinstance(capture, dict):
        payload["actual_provider_request_prompt"] = capture.get("actual_provider_request_prompt")
        payload["canonical_provider_prompt"] = capture.get("canonical_provider_prompt")
    payload.setdefault("provider_prompt", record.prompt or record.slot.slot_prompt or "")
    payload.setdefault("canonical_provider_prompt", payload.get("provider_prompt") or "")
    payload.setdefault("actual_provider_request_prompt", payload.get("provider_prompt") or "")
    return payload


def _payloads_from_workflow(workflow: WorkflowV2) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for node in workflow.nodes:
        for item in node.items:
            for slot in item.slots:
                prompt = slot.slot_prompt or ""
                refs = [
                    asset_id
                    for asset_id in [*slot.implicit_reference_ids, *slot.explicit_reference_ids]
                    if asset_id
                ]
                payloads.append(
                    {
                        "node_id": node.node_id,
                        "item_id": item.item_id,
                        "slot_id": slot.slot_id,
                        "slot_type": slot.slot_type,
                        "media_type": slot.media_type,
                        "provider_prompt": prompt,
                        "canonical_provider_prompt": prompt,
                        "actual_provider_request_prompt": prompt,
                        "provider_request_capture": {
                            "canonical_provider_prompt": prompt,
                            "actual_provider_request_prompt": prompt,
                            "prompt_match": True,
                            "prompt_source": "workflow_acceptance_replay",
                        },
                        "reference_asset_ids": refs,
                    }
                )
    return payloads


def _provider_prompt(payload: dict[str, Any]) -> str:
    for key in ("canonical_provider_prompt", "provider_prompt"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    canonical = payload.get("canonical_provider_payload")
    if isinstance(canonical, dict):
        value = canonical.get("provider_prompt")
        if isinstance(value, str):
            return value.strip()
    return ""


def _actual_provider_prompt(payload: dict[str, Any]) -> str:
    capture = payload.get("provider_request_capture")
    if isinstance(capture, dict):
        value = capture.get("actual_provider_request_prompt")
        if isinstance(value, str):
            return value.strip()
    for key in ("actual_provider_request_prompt", "captured_provider_request_prompt"):
        value = payload.get(key)
        if isinstance(value, str):
            return value.strip()
    return _provider_prompt(payload)


def _slot_reference_ids(slot: WorkflowSlotV2, payload: dict[str, Any] | None) -> set[str]:
    refs = [*slot.implicit_reference_ids, *slot.explicit_reference_ids]
    if payload is not None:
        refs.extend(str(asset_id) for asset_id in payload.get("reference_asset_ids") or [])
    return {str(ref) for ref in refs if str(ref)}


def _has_reference_kind(refs: set[str], kind: str) -> bool:
    normalized = [ref.lower() for ref in refs]
    return any(ref.startswith(f"{kind}-") or f"-{kind}-" in ref for ref in normalized)


def _contains_forbidden_term(text: str, term: str) -> bool:
    normalized_term = term.lower()
    if normalized_term not in text:
        return False
    if re.search(rf"\b(no|without)\b[^.:\n]{{0,60}}{re.escape(normalized_term)}", text):
        return False
    return True


def _explicit_empty_prompt(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    return isinstance(value, str) and not value.strip()


def _payload_prompt_text(payload: dict[str, Any]) -> str:
    values: list[str] = [_provider_prompt(payload), _actual_provider_prompt(payload)]
    for key in ("provider_prompt", "canonical_provider_prompt", "actual_provider_request_prompt"):
        value = payload.get(key)
        if isinstance(value, str):
            values.append(value)
    capture = payload.get("provider_request_capture")
    if isinstance(capture, dict):
        for key in ("canonical_provider_prompt", "actual_provider_request_prompt"):
            value = capture.get(key)
            if isinstance(value, str):
                values.append(value)
    return "\n".join(values)


def _contains_unsafe_payload(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if any(term in str(key).lower() for term in _SENSITIVE_KEY_TERMS):
                return True
            if _contains_unsafe_payload(item):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_unsafe_payload(item) for item in value)
    if isinstance(value, bytes):
        return True
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    return (
        normalized.startswith("data:image/")
        or normalized.startswith("data:video/")
        or ";base64," in normalized
        or "base64," in normalized
    )


def _sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(term in key_text.lower() for term in _SENSITIVE_KEY_TERMS):
                sanitized[key_text] = "[REDACTED]"
            else:
                sanitized[key_text] = _sanitize_payload(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, bytes):
        return "[REDACTED]"
    if not isinstance(value, str):
        return value
    normalized = value.strip().lower()
    if (
        normalized.startswith("data:")
        or "base64," in normalized
        or value.startswith("/")
        or len(value) > 20_000
    ):
        return "[REDACTED]"
    return value


def _snapshot_workflow_files(data_dir: Path, workflow_id: str) -> dict[str, str]:
    root = data_dir / "v2"
    files = [
        root / "workflows" / workflow_id / "workflow.json",
        root / "runs" / workflow_id / "events.jsonl",
    ]
    run_dir = root / "runs" / workflow_id
    if run_dir.exists():
        files.extend(path for path in run_dir.rglob("*") if path.is_file())
    snapshot: dict[str, str] = {}
    for path in files:
        if path.exists() and path.is_file():
            snapshot[path.relative_to(data_dir).as_posix()] = path.read_text(encoding="utf-8")
    return snapshot


def _seed_acceptance_storyboard_cell_assets(workflow: WorkflowV2) -> None:
    upstream_asset_ids = _selected_upstream_main_asset_ids(workflow)
    for item in _items(workflow, item_type="shot"):
        cell_asset_ids: list[str] = []
        for slot in item.slots:
            if not slot.slot_type.startswith("shot_cell_"):
                continue
            asset_id = slot.selected_asset_id or (
                f"acceptance-{item.item_type}-{item.item_id}-{slot.slot_type}-asset"
            )
            slot.selected_asset_id = asset_id
            slot.implicit_reference_ids = list(
                dict.fromkeys([*slot.implicit_reference_ids, *upstream_asset_ids])
            )
            cell_asset_ids.append(asset_id)
        if not cell_asset_ids:
            continue
        for slot in item.slots:
            if slot.slot_type == "shot_video_segment":
                slot.implicit_reference_ids = list(
                    dict.fromkeys([*slot.implicit_reference_ids, *cell_asset_ids])
                )


def _seed_acceptance_upstream_assets(workflow: WorkflowV2) -> None:
    main_slot_types = {
        "product_main_image",
        "character_main_image",
        "scene_main_image",
    }
    for item in _items(workflow):
        main_asset_ids: list[str] = []
        for slot in item.slots:
            if slot.slot_type not in main_slot_types:
                continue
            asset_id = slot.selected_asset_id or (
                f"acceptance-{item.item_type}-{item.item_id}-{slot.slot_type}-asset"
            )
            slot.selected_asset_id = asset_id
            slot.status = "ready"
            main_asset_ids.append(asset_id)
        if not main_asset_ids:
            continue
        for slot in item.slots:
            if slot.slot_type in {
                "product_multi_view_grid",
                "character_three_view",
                "scene_multi_view_grid",
            }:
                slot.implicit_reference_ids = list(
                    dict.fromkeys([*slot.implicit_reference_ids, *main_asset_ids])
                )


def _selected_upstream_main_asset_ids(workflow: WorkflowV2) -> list[str]:
    ids: list[str] = []
    for item in _items(workflow):
        if item.item_type not in {"product", "character", "scene"}:
            continue
        for slot in item.slots:
            if (
                slot.slot_type
                in {
                    "product_main_image",
                    "character_main_image",
                    "scene_main_image",
                }
                and slot.selected_asset_id
            ):
                ids.append(slot.selected_asset_id)
    return list(dict.fromkeys(ids))


def _check(name: str, failures: list[V2WorkflowAcceptanceFailure]) -> V2WorkflowAcceptanceCheck:
    return V2WorkflowAcceptanceCheck(
        name=name,
        status="failed" if failures else "passed",
        failures=failures,
    )


def _failure(
    fixture: V2WorkflowAcceptanceFixture,
    *,
    code: str,
    stage: str,
    message: str,
    node_id: str | None = None,
    item_id: str | None = None,
    slot_id: str | None = None,
) -> V2WorkflowAcceptanceFailure:
    return V2WorkflowAcceptanceFailure(
        code=code,
        stage=stage,
        fixture_id=fixture.fixture_id,
        node_id=node_id,
        item_id=item_id,
        slot_id=slot_id,
        message=message,
    )


def _error_report(
    fixture_id: str,
    *,
    code: str,
    message: str,
) -> V2WorkflowAcceptanceReport:
    fixture = V2WorkflowAcceptanceFixture(
        fixture_id=fixture_id,
        title=fixture_id,
        input_prompt="",
        expected_counts=V2WorkflowAcceptanceExpectedCounts(
            product_count=0,
            character_count=0,
            scene_count=0,
            storyboard_shot_count=0,
        ),
    )
    failure = _failure(
        fixture,
        code=code,
        stage="acceptance_runner",
        message=message,
    )
    return V2WorkflowAcceptanceReport(
        status="failed",
        fixture_id=fixture_id,
        checks=[_check("acceptance_runner", [failure])],
        failures=[failure],
        provider_payload_snapshots=[],
    )


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _new_acceptance_workflow_id(fixture_id: str) -> str:
    return f"accept_{fixture_id}_{uuid4().hex[:8]}"

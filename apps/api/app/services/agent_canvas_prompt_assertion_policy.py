"""Canonical deterministic prompt assertion authority for Agent Canvas roles."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_prompt_preparation import (
    PromptAssertionEvidenceV1,
    PromptAssertionSourceSnapshotV1,
    prompt_assertion_evidence_digest,
)
from app.services.agent_canvas_role_prompt_recipes import RolePromptRecipeRegistry


PRODUCT_MULTIVIEW_VIEWS = ("front", "side", "back", "three-quarter", "detail")


@dataclass(frozen=True, slots=True)
class PromptAssertionPolicyV1:
    policy_ref: str
    policy_version: str
    policy_digest: str
    recipe_id: str
    recipe_version: str
    assertion_ids: tuple[str, ...]
    positive_clauses: tuple[str, ...]
    negative_clauses: tuple[str, ...]
    engine_owned_fields: Mapping[str, object]
    required_reference_purposes: tuple[str, ...]
    required_document_kinds: tuple[str, ...]
    sequence_scoped: bool
    assertion_block: str
    assertion_block_digest: str
    engine_owned_fields_digest: str


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"sha256:{sha256(payload.encode('utf-8')).hexdigest()}"


def _policy(
    recipe_id: str,
    recipe_version: str,
    assertion_ids: tuple[str, ...],
    positive: tuple[str, ...],
    negative: tuple[str, ...],
    *,
    engine_owned_fields: Mapping[str, object] | None = None,
    required_reference_purposes: tuple[str, ...] = (),
    required_document_kinds: tuple[str, ...] = (),
    sequence_scoped: bool = False,
) -> PromptAssertionPolicyV1:
    fields = dict(engine_owned_fields or {})
    policy_ref = f"{recipe_id}.prompt_assertions"
    block = "\n".join(
        (
            f"Deterministic production policy: {policy_ref}@1",
            "Required assertions:",
            *(f"- [{item}] {clause}" for item, clause in zip(assertion_ids, positive)),
            "Prohibited behavior:",
            *(f"- {clause}" for clause in negative),
        )
    )
    canonical = {
        "policy_ref": policy_ref,
        "policy_version": "1",
        "recipe_id": recipe_id,
        "recipe_version": recipe_version,
        "assertion_ids": assertion_ids,
        "positive_clauses": positive,
        "negative_clauses": negative,
        "engine_owned_fields": fields,
        "required_reference_purposes": required_reference_purposes,
        "required_document_kinds": required_document_kinds,
        "sequence_scoped": sequence_scoped,
    }
    return PromptAssertionPolicyV1(
        **{**canonical, "engine_owned_fields": MappingProxyType(fields)},
        policy_digest=_digest(canonical),
        assertion_block=block,
        assertion_block_digest=_digest(block),
        engine_owned_fields_digest=_digest(fields),
    )


_SPECIAL_POLICIES = {
    "script": {
        "assertion_ids": ("script.canonical_total_duration",),
        "positive": (
            "Cover the exact canonical production duration supplied by the Requirement Ledger.",
        ),
        "negative": ("Do not infer, shorten, extend, or override production duration.",),
        "engine_owned_fields": {
            "duration_seconds": "canonical_requirement_control",
        },
    },
    "product_multiview": {
        "assertion_ids": (
            "product_multiview.exact_product_main",
            "product_multiview.canonical_views",
            "product_multiview.isolated_presentation",
        ),
        "positive": (
            "Use the sole exact bound Product Main identity source.",
            "Render front, side, back, three-quarter, and detail views in that order.",
            "Use one clean neutral studio presentation.",
        ),
        "negative": (
            "No people, hands, active use, application scene, narrative scene, labels, captions, or visible text.",
        ),
        "engine_owned_fields": {"views": PRODUCT_MULTIVIEW_VIEWS},
        "required_reference_purposes": ("product_main_identity",),
    },
    "video_segment": {
        "assertion_ids": (
            "video.exact_storyboard_grid",
            "video.storyboard_plan_segment",
            "video.current_identity_references",
            "video.native_audio_without_bgm",
        ),
        "positive": (
            "Use the exact matching Storyboard Grid and sequence.",
            "Use the matching current Storyboard Production Plan segment.",
            "Use every current guided Product, Prop, Character Turnaround, and Scene reference.",
            "Generate native ambience and synchronized action effects.",
        ),
        "negative": ("Do not generate or embed background music.",),
        "engine_owned_fields": {"background_music": False},
        "required_reference_purposes": ("storyboard_grid",),
        "required_document_kinds": ("storyboard_production_plan",),
        "sequence_scoped": True,
    },
}


def _default_policy(recipe) -> PromptAssertionPolicyV1:
    role = recipe.role_variant
    special = _SPECIAL_POLICIES.get(role)
    if special is not None:
        return _policy(recipe.recipe_id, recipe.recipe_version, **special)
    return _policy(
        recipe.recipe_id,
        recipe.recipe_version,
        (f"{role}.role_boundary",),
        (recipe.positive_boundary,),
        (recipe.negative_boundary,),
    )


class PromptAssertionPolicyRegistry:
    """Resolve one immutable policy by exact recipe identity."""

    def __init__(
        self,
        registrations: tuple[PromptAssertionPolicyV1, ...] | None = None,
    ) -> None:
        recipes = RolePromptRecipeRegistry().registrations()
        values = registrations or tuple(_default_policy(item) for item in recipes)
        keys = tuple((item.recipe_id, item.recipe_version) for item in values)
        expected = {(item.recipe_id, item.recipe_version) for item in recipes}
        if len(keys) != len(set(keys)) or set(keys) != expected:
            raise _error("Prompt assertion policy profiles must exactly cover role recipes.")
        assertion_ids = tuple(value for item in values for value in item.assertion_ids)
        if len(assertion_ids) != len(set(assertion_ids)):
            raise _error("Prompt assertion IDs must be globally unique.")
        self._by_recipe = MappingProxyType(dict(zip(keys, values, strict=True)))

    def registrations(self) -> tuple[PromptAssertionPolicyV1, ...]:
        return tuple(self._by_recipe.values())

    def resolve(self, recipe_id: str, recipe_version: str) -> PromptAssertionPolicyV1:
        try:
            return self._by_recipe[(recipe_id, recipe_version)]
        except KeyError as error:
            raise _error(
                "Prompt assertion policy is not registered for the exact recipe."
            ) from error


class PromptAssertionEvidenceValidator:
    """Validate persisted evidence without I/O or semantic text inspection."""

    def validate_preparation(
        self,
        *,
        policy: PromptAssertionPolicyV1,
        prompt_digest: str,
        evidence: PromptAssertionEvidenceV1 | None,
        current_sources: tuple[PromptAssertionSourceSnapshotV1, ...],
        current_document_revisions: dict[str, int],
        current_sequence_id: str | None,
    ) -> PromptAssertionEvidenceV1:
        if evidence is None:
            raise V2PersistenceError(
                "node_prompt_assertion_evidence_missing",
                "Current prompt assertion evidence is required.",
                stage="prompt_assertion_validation",
            )
        source_purposes = {
            item.reference_purpose
            for item in evidence.source_snapshots
            if item.source_kind == "binding" and item.reference_purpose is not None
        }
        document_snapshots = tuple(
            item for item in evidence.source_snapshots if item.source_kind == "document"
        )
        sequence_snapshots = tuple(
            item for item in evidence.source_snapshots if item.source_kind == "sequence"
        )
        expected = (
            evidence.policy_ref == policy.policy_ref
            and evidence.policy_version == policy.policy_version
            and evidence.policy_digest == policy.policy_digest
            and evidence.recipe_id == policy.recipe_id
            and evidence.recipe_version == policy.recipe_version
            and evidence.assertion_ids == policy.assertion_ids
            and evidence.assertion_block_digest == policy.assertion_block_digest
            and evidence.prepared_prompt_digest == prompt_digest
            and evidence.source_snapshots == current_sources
            and evidence.document_revisions == current_document_revisions
            and evidence.sequence_id == current_sequence_id
            and evidence.engine_owned_fields_digest == policy.engine_owned_fields_digest
            and set(policy.required_reference_purposes).issubset(source_purposes)
            and set(policy.required_document_kinds).issubset(evidence.document_revisions)
            and (not policy.sequence_scoped or evidence.sequence_id is not None)
            and (not policy.required_document_kinds or bool(document_snapshots))
            and (
                not policy.sequence_scoped
                or len(sequence_snapshots) == 1
                and sequence_snapshots[0].sequence_id == evidence.sequence_id
            )
        )
        if not expected or evidence.evidence_digest != prompt_assertion_evidence_digest(evidence):
            raise _error("Prompt assertion evidence does not match current authority.")
        return evidence


def source_snapshots_from_context(context) -> tuple[PromptAssertionSourceSnapshotV1, ...]:
    snapshots = tuple(
        PromptAssertionSourceSnapshotV1(
            source_kind="binding",
            binding_id=item.binding_id,
            binding_revision=item.binding_revision,
            source_node_id=item.source_node_id,
            source_node_revision=item.source_node_revision,
            asset_id=item.asset_id,
            asset_version_id=item.asset_version_id,
            reference_purpose=item.reference_purpose,
            sequence_id=item.source_sequence_id,
        )
        for item in context.bindings
    )
    plan_id = context.storyboard_parameters.get("storyboard_production_plan_id")
    plan_revision = context.document_revisions.get("storyboard_production_plan")
    sequence_id = context.storyboard_parameters.get("sequence_id")
    if isinstance(plan_id, str) and plan_id and isinstance(plan_revision, int):
        snapshots += (
            PromptAssertionSourceSnapshotV1(
                source_kind="document",
                document_id=plan_id,
                document_revision=plan_revision,
            ),
        )
    if isinstance(sequence_id, str) and sequence_id:
        snapshots += (
            PromptAssertionSourceSnapshotV1(
                source_kind="sequence",
                sequence_id=sequence_id,
            ),
        )
    return snapshots


def prompt_assertion_admission_error(node) -> str | None:
    """Return a stable fail-closed admission code for one prepared guided Node."""

    preparation = node.prompt_preparation
    metadata_recipe_id = node.metadata.get("prompt_recipe_id")
    managed = bool(preparation.role_variant or preparation.recipe_id or metadata_recipe_id)
    if not managed:
        return None
    if preparation.assertion_evidence is None:
        return "node_prompt_assertion_evidence_missing"
    if (
        preparation.role_variant is None
        or preparation.recipe_id is None
        or preparation.recipe_version is None
        or preparation.recipe_digest is None
    ):
        return "node_prompt_assertion_contract_invalid"
    try:
        recipe = RolePromptRecipeRegistry().resolve(preparation.role_variant)
        policy = PromptAssertionPolicyRegistry().resolve(
            preparation.recipe_id, preparation.recipe_version
        )
        evidence = preparation.assertion_evidence
        PromptAssertionEvidenceValidator().validate_preparation(
            policy=policy,
            prompt_digest=sha256(str(node.generation_prompt or "").encode("utf-8")).hexdigest(),
            evidence=evidence,
            current_sources=evidence.source_snapshots,
            current_document_revisions=evidence.document_revisions,
            current_sequence_id=evidence.sequence_id,
        )
    except V2PersistenceError as error:
        return error.code
    if (
        preparation.recipe_id != recipe.recipe_id
        or preparation.recipe_version != recipe.recipe_version
        or preparation.recipe_digest != recipe.recipe_digest
        or str(node.generation_prompt or "").count(policy.assertion_block) != 1
        or node.metadata.get("prompt_assertion_policy_ref") != policy.policy_ref
        or node.metadata.get("prompt_assertion_policy_digest") != policy.policy_digest
        or node.metadata.get("prompt_assertion_evidence_digest") != evidence.evidence_digest
    ):
        return "node_prompt_assertion_contract_invalid"
    return None


def _error(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "node_prompt_assertion_contract_invalid",
        message,
        stage="prompt_assertion_validation",
    )

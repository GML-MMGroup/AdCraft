"""Read-only, deterministic Brand decision documents built from SQLite authority."""

from __future__ import annotations

from hashlib import sha256
import json

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.persistence.brand_decision_repository import BrandDecisionRepository
from app.persistence.database import V2Database
from app.persistence.models import BrandDecisionLogRow
from app.schemas.brand_professional_mode import (
    BrandBriefSummaryV1,
    BrandTreatmentDocumentV1,
)
from app.services.brand_journey_state import TREATMENT_SUBSTEP_ORDER
from app.services.brand_slot_schema import slots_for_stage
from app.services.brand_asset_summary import brand_asset_references


class BrandDecisionDocumentService:
    def __init__(self, database: V2Database) -> None:
        self._database = database
        self._repository = BrandDecisionRepository(database)

    def read(self, brand_id: str) -> BrandTreatmentDocumentV1:
        with self._database.engine.connect() as connection:
            return self.read_in_transaction(connection, brand_id)

    def read_in_transaction(
        self, connection: Connection, brand_id: str
    ) -> BrandTreatmentDocumentV1:
        frozen = self.frozen_in_transaction(connection, brand_id)
        if frozen is not None:
            return frozen
        repository = self._repository
        references = brand_asset_references(connection, brand_id)
        slots = repository.get_slot_values_in_transaction(connection, brand_id)
        profiles = {
            stage: BrandBriefSummaryV1(
                values=tuple(value for value in slots if value.stage == stage),
                unresolved_fields=tuple(
                    slot.slot_id
                    for slot in slots_for_stage(stage)
                    if not any(
                        value.stage == stage and value.slot_id == slot.slot_id for value in slots
                    )
                ),
            )
            for stage in ("brand-memory", "campaign")
        }
        present = {value.slot_id for value in slots}
        if not references:
            profile = profiles["brand-memory"]
            profiles["brand-memory"] = profile.model_copy(
                update={"unresolved_fields": (*profile.unresolved_fields, "brand_assets")}
            )
        inherited = tuple(
            value
            for campaign_key, brand_key in (
                ("campaign_audience", "brand_audience"),
                ("campaign_core_message", "brand_product_focus"),
            )
            if campaign_key not in present
            for value in slots
            if value.slot_id == brand_key
        )
        profiles["campaign"] = profiles["campaign"].model_copy(
            update={"inherited_values": inherited}
        )
        selected_id = repository.get_selected_hypothesis_id_in_transaction(connection, brand_id)
        hypothesis = next(
            (
                item
                for item in repository.get_hypotheses_in_transaction(connection, brand_id)
                if item.candidate_id == selected_id
            ),
            None,
        )
        steps_by_key = {
            step.step_key: step
            for step in repository.get_treatment_steps_in_transaction(connection, brand_id)
        }
        steps = tuple(steps_by_key[key] for key in TREATMENT_SUBSTEP_ORDER if key in steps_by_key)
        missing = [
            f"treatment.{key}"
            for key in TREATMENT_SUBSTEP_ORDER
            if key not in steps_by_key or steps_by_key[key].structured_detail is None
        ]
        adspec = repository.get_adspec_in_transaction(connection, brand_id)
        stack = repository.get_skill_stack_in_transaction(connection, brand_id)
        for key, value in (
            ("selected_hypothesis", hypothesis),
            ("adspec", adspec),
            ("skill_stack", stack),
        ):
            if value is None:
                missing.append(key)
        for stage in ("brand-memory", "campaign"):
            missing.extend(
                slot.slot_id
                for slot in slots_for_stage(stage)
                if slot.required and slot.slot_id in profiles[stage].unresolved_fields
            )
        document = BrandTreatmentDocumentV1(
            brand_profile=profiles["brand-memory"],
            campaign_brief=profiles["campaign"],
            selected_hypothesis=hypothesis,
            adspec=adspec,
            skill_stack=stack,
            treatment_steps=steps,
            authorized_asset_references=references,
            product_presentation=tuple(
                section
                for step in steps
                if step.structured_detail
                for section in step.structured_detail.sections
                if section.key in {"product_role", "product_shots"}
            ),
            complete=not missing,
            missing_sections=tuple(missing),
        )
        digest = sha256(
            json.dumps(
                document.model_dump(mode="json", exclude={"content_digest"}),
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return document.model_copy(update={"content_digest": digest})

    def frozen_in_transaction(
        self, connection: Connection, brand_id: str
    ) -> BrandTreatmentDocumentV1 | None:
        raw = connection.execute(
            select(BrandDecisionLogRow.detail_json)
            .where(
                BrandDecisionLogRow.brand_id == brand_id,
                BrandDecisionLogRow.target_type == "treatment_document",
                BrandDecisionLogRow.action == "confirm",
            )
            .order_by(BrandDecisionLogRow.created_at.desc(), BrandDecisionLogRow.log_id.desc())
            .limit(1)
        ).scalar_one_or_none()
        return BrandTreatmentDocumentV1.model_validate(json.loads(raw)["document"]) if raw else None

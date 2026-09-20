"""SQLite authority for Brand Professional Mode decision state.

Every write method offers an in-transaction variant so stage actions can
commit decisions, decision log rows, and journey advances atomically.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import cast
from uuid import uuid4

from sqlalchemy import delete, insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.models import (
    AgentCanvasWorkflowRow,
    BrandAdSpecItemRow,
    BrandDecisionLogRow,
    BrandFactRow,
    BrandHypothesisRow,
    BrandInvocationRow,
    BrandJourneyRow,
    BrandOptionCardRow,
    BrandRow,
    BrandSkillStackRow,
    BrandTreatmentStepRow,
    CreativeSkillCatalogRow,
    WorkflowRow,
)
from app.schemas.brand_professional_mode import (
    AdSpecItemV1,
    AdSpecStateV1,
    BrandDecisionLogEntryV1,
    BrandJourneyStateV1,
    BrandOptionCardV1,
    BrandSlotValueV1,
    CreativeHypothesisCandidateV1,
    SkillStackEntryV1,
    SkillStackV1,
    TreatmentStepResultV1,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BrandDecisionRepository:
    """Own only brand-mode SQL; callers own cross-table transactions."""

    def __init__(self, database: V2Database) -> None:
        self._database = database

    @property
    def database(self) -> V2Database:
        return self._database

    # ---- Brand and journey -------------------------------------------------

    def workflow_id_for_brand(self, brand_id: str) -> str | None:
        try:
            with self._database.engine.connect() as connection:
                row = connection.execute(
                    select(WorkflowRow.workflow_id)
                    .join(BrandRow, BrandRow.project_id == WorkflowRow.project_id)
                    .where(BrandRow.brand_id == brand_id)
                    .limit(1)
                ).first()
                if row is None:
                    row = connection.execute(
                        select(AgentCanvasWorkflowRow.workflow_id)
                        .join(BrandRow, BrandRow.project_id == AgentCanvasWorkflowRow.project_id)
                        .where(BrandRow.brand_id == brand_id)
                        .limit(1)
                    ).first()
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return row[0] if row is not None else None

    def project_id_for_workflow(self, workflow_id: str) -> str | None:
        try:
            with self._database.engine.connect() as connection:
                row = connection.execute(
                    select(WorkflowRow.project_id).where(WorkflowRow.workflow_id == workflow_id)
                ).first()
                if row is None:
                    row = connection.execute(
                        select(AgentCanvasWorkflowRow.project_id).where(
                            AgentCanvasWorkflowRow.workflow_id == workflow_id
                        )
                    ).first()
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return row[0] if row is not None else None

    def ensure_brand(
        self,
        *,
        project_id: str,
        name: str,
    ) -> str:
        """Create the brand and its journey once per project; return brand id."""

        try:
            with self._database.engine.begin() as connection:
                return self.ensure_brand_in_transaction(
                    connection, project_id=project_id, name=name
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def ensure_brand_in_transaction(
        self,
        connection: Connection,
        *,
        project_id: str,
        name: str,
    ) -> str:
        row = connection.execute(
            select(BrandRow.brand_id).where(BrandRow.project_id == project_id)
        ).first()
        if row is not None:
            return cast(str, row[0])
        brand_id = f"brand_{uuid4().hex[:12]}"
        now = _now()
        connection.execute(
            insert(BrandRow).values(
                brand_id=brand_id,
                project_id=project_id,
                name=name,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            insert(BrandJourneyRow).values(
                brand_id=brand_id,
                stage="brand-memory",
                stage_revision=1,
                stage_status="ready",
                created_at=now,
                updated_at=now,
            )
        )
        return brand_id

    def get_brand_id_by_project(self, project_id: str) -> str | None:
        try:
            with self._database.engine.connect() as connection:
                row = connection.execute(
                    select(BrandRow.brand_id).where(BrandRow.project_id == project_id)
                ).first()
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return row[0] if row is not None else None

    def get_brand_name_in_transaction(self, connection: Connection, brand_id: str) -> str:
        row = connection.execute(select(BrandRow.name).where(BrandRow.brand_id == brand_id)).first()
        if row is None:
            raise _not_found()
        return cast(str, row[0])

    def get_journey(self, brand_id: str) -> BrandJourneyStateV1 | None:
        try:
            with self._database.engine.connect() as connection:
                return self.get_journey_in_transaction(connection, brand_id)
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def get_journey_in_transaction(
        self, connection: Connection, brand_id: str
    ) -> BrandJourneyStateV1 | None:
        row = connection.execute(
            select(BrandJourneyRow).where(BrandJourneyRow.brand_id == brand_id)
        ).first()
        if row is None:
            return None
        return BrandJourneyStateV1(
            stage=row.stage,
            treatment_substep=row.treatment_substep,
            stage_revision=row.stage_revision,
            stage_status=row.stage_status,
        )

    def save_journey_in_transaction(
        self,
        connection: Connection,
        brand_id: str,
        journey: BrandJourneyStateV1,
    ) -> None:
        connection.execute(
            update(BrandJourneyRow)
            .where(BrandJourneyRow.brand_id == brand_id)
            .values(
                stage=journey.stage,
                treatment_substep=journey.treatment_substep,
                stage_revision=journey.stage_revision,
                stage_status=journey.stage_status,
                updated_at=_now(),
            )
        )

    # ---- Slot values -------------------------------------------------------

    def get_slot_values(self, brand_id: str) -> tuple[BrandSlotValueV1, ...]:
        try:
            with self._database.engine.connect() as connection:
                return self.get_slot_values_in_transaction(connection, brand_id)
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def get_slot_values_in_transaction(
        self, connection: Connection, brand_id: str
    ) -> tuple[BrandSlotValueV1, ...]:
        rows = connection.execute(
            select(BrandFactRow)
            .where(BrandFactRow.brand_id == brand_id)
            .order_by(BrandFactRow.stage, BrandFactRow.slot_id)
        ).all()
        return tuple(
            BrandSlotValueV1(
                slot_id=row.slot_id,
                stage=row.stage,
                value=row.value_text,
                kind=row.kind,
                provenance=row.provenance,
                confirmed_at=datetime.fromisoformat(row.confirmed_at) if row.confirmed_at else None,
            )
            for row in rows
        )

    def upsert_slot_values_in_transaction(
        self,
        connection: Connection,
        brand_id: str,
        values: tuple[BrandSlotValueV1, ...],
    ) -> None:
        for value in values:
            existing = connection.execute(
                select(BrandFactRow.fact_id).where(
                    BrandFactRow.brand_id == brand_id,
                    BrandFactRow.stage == value.stage,
                    BrandFactRow.slot_id == value.slot_id,
                )
            ).first()
            confirmed_at = (
                value.confirmed_at.isoformat()
                if value.confirmed_at is not None
                else (_now() if value.provenance == "user_confirmed" else None)
            )
            if existing is not None:
                connection.execute(
                    update(BrandFactRow)
                    .where(BrandFactRow.fact_id == existing[0])
                    .values(
                        value_text=value.value,
                        kind=value.kind,
                        provenance=value.provenance,
                        confirmed_at=confirmed_at,
                        updated_at=_now(),
                    )
                )
            else:
                connection.execute(
                    insert(BrandFactRow).values(
                        fact_id=f"bfact_{uuid4().hex[:16]}",
                        brand_id=brand_id,
                        stage=value.stage,
                        slot_id=value.slot_id,
                        value_text=value.value,
                        kind=value.kind,
                        provenance=value.provenance,
                        confirmed_at=confirmed_at,
                        updated_at=_now(),
                    )
                )

    # ---- Option cards ------------------------------------------------------

    def save_option_card_in_transaction(
        self,
        connection: Connection,
        brand_id: str,
        card: BrandOptionCardV1,
    ) -> None:
        connection.execute(
            update(BrandOptionCardRow)
            .where(BrandOptionCardRow.brand_id == brand_id)
            .where(BrandOptionCardRow.status == "open")
            .values(status="superseded")
        )
        insert_statement = sqlite_insert(BrandOptionCardRow).values(
            card_id=card.card_id,
            brand_id=brand_id,
            stage=card.stage,
            stage_revision=card.stage_revision,
            target_slot_id=card.target_slot_id,
            payload_json=card.model_dump_json(),
            status="open",
            created_at=_now(),
        )
        connection.execute(
            insert_statement.on_conflict_do_update(
                index_elements=[BrandOptionCardRow.card_id],
                set_={
                    "status": "open",
                    "stage": insert_statement.excluded.stage,
                    "stage_revision": insert_statement.excluded.stage_revision,
                    "target_slot_id": insert_statement.excluded.target_slot_id,
                    "payload_json": insert_statement.excluded.payload_json,
                    "created_at": insert_statement.excluded.created_at,
                },
            )
        )

    def get_open_card_in_transaction(
        self, connection: Connection, brand_id: str
    ) -> BrandOptionCardV1 | None:
        row = connection.execute(
            select(BrandOptionCardRow)
            .where(BrandOptionCardRow.brand_id == brand_id)
            .where(BrandOptionCardRow.status == "open")
            .order_by(BrandOptionCardRow.created_at.desc())
            .limit(1)
        ).first()
        if row is None:
            return None
        return BrandOptionCardV1.model_validate_json(row.payload_json)

    def get_open_card(self, brand_id: str) -> BrandOptionCardV1 | None:
        """Return the current open card without requiring a caller transaction."""

        with self._database.engine.connect() as connection:
            return self.get_open_card_in_transaction(connection, brand_id)

    def resolve_card_in_transaction(
        self,
        connection: Connection,
        brand_id: str,
        card_id: str,
    ) -> None:
        connection.execute(
            update(BrandOptionCardRow)
            .where(BrandOptionCardRow.brand_id == brand_id)
            .where(BrandOptionCardRow.card_id == card_id)
            .values(status="resolved")
        )

    # ---- Hypotheses --------------------------------------------------------

    def replace_hypotheses_in_transaction(
        self,
        connection: Connection,
        brand_id: str,
        candidates: tuple[CreativeHypothesisCandidateV1, ...],
    ) -> None:
        connection.execute(
            delete(BrandHypothesisRow).where(BrandHypothesisRow.brand_id == brand_id)
        )
        for candidate in candidates:
            connection.execute(
                insert(BrandHypothesisRow).values(
                    hypothesis_id=candidate.candidate_id,
                    brand_id=brand_id,
                    label=candidate.label,
                    insight=candidate.insight,
                    mechanism=candidate.mechanism,
                    hypothesis_text=candidate.hypothesis,
                    product_role=candidate.product_role,
                    hook_mechanism=candidate.hook_mechanism,
                    why=candidate.why,
                    selected=False,
                    created_at=_now(),
                )
            )

    def select_hypothesis_in_transaction(
        self,
        connection: Connection,
        brand_id: str,
        hypothesis_id: str,
    ) -> None:
        updated = connection.execute(
            update(BrandHypothesisRow)
            .where(BrandHypothesisRow.brand_id == brand_id)
            .where(BrandHypothesisRow.hypothesis_id == hypothesis_id)
            .values(selected=True)
        )
        if updated.rowcount != 1:
            raise _not_found()
        connection.execute(
            update(BrandHypothesisRow)
            .where(BrandHypothesisRow.brand_id == brand_id)
            .where(BrandHypothesisRow.hypothesis_id != hypothesis_id)
            .values(selected=False)
        )

    def get_hypotheses_in_transaction(
        self, connection: Connection, brand_id: str
    ) -> tuple[CreativeHypothesisCandidateV1, ...]:
        rows = connection.execute(
            select(BrandHypothesisRow)
            .where(BrandHypothesisRow.brand_id == brand_id)
            .order_by(BrandHypothesisRow.created_at)
        ).all()
        return tuple(
            CreativeHypothesisCandidateV1(
                candidate_id=row.hypothesis_id,
                label=row.label,
                insight=row.insight,
                mechanism=row.mechanism,
                hypothesis=row.hypothesis_text,
                product_role=row.product_role,
                hook_mechanism=row.hook_mechanism,
                why=row.why,
            )
            for row in rows
        )

    def get_selected_hypothesis_id_in_transaction(
        self, connection: Connection, brand_id: str
    ) -> str | None:
        row = connection.execute(
            select(BrandHypothesisRow.hypothesis_id)
            .where(BrandHypothesisRow.brand_id == brand_id)
            .where(BrandHypothesisRow.selected.is_(True))
        ).first()
        return row[0] if row is not None else None

    # ---- AdSpec ------------------------------------------------------------

    def replace_adspec_items_in_transaction(
        self,
        connection: Connection,
        brand_id: str,
        items: tuple[AdSpecItemV1, ...],
    ) -> None:
        connection.execute(
            delete(BrandAdSpecItemRow).where(BrandAdSpecItemRow.brand_id == brand_id)
        )
        for item in items:
            connection.execute(
                insert(BrandAdSpecItemRow).values(
                    item_id=f"adspec_{uuid4().hex[:16]}",
                    brand_id=brand_id,
                    item_key=item.item_key,
                    item_text=item.item_text,
                    state=item.state,
                    updated_at=_now(),
                )
            )

    def get_adspec_in_transaction(
        self, connection: Connection, brand_id: str
    ) -> AdSpecStateV1 | None:
        rows = connection.execute(
            select(BrandAdSpecItemRow)
            .where(BrandAdSpecItemRow.brand_id == brand_id)
            .order_by(BrandAdSpecItemRow.item_key)
        ).all()
        if not rows:
            return None
        return AdSpecStateV1(
            items=tuple(
                AdSpecItemV1(
                    item_key=row.item_key,
                    item_text=row.item_text,
                    state=row.state,
                )
                for row in rows
            )
        )

    def get_adspec(self, brand_id: str) -> AdSpecStateV1 | None:
        try:
            with self._database.engine.connect() as connection:
                return self.get_adspec_in_transaction(connection, brand_id)
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    def update_adspec_item_state_in_transaction(
        self,
        connection: Connection,
        brand_id: str,
        item_key: str,
        state: str,
    ) -> None:
        updated = connection.execute(
            update(BrandAdSpecItemRow)
            .where(BrandAdSpecItemRow.brand_id == brand_id)
            .where(BrandAdSpecItemRow.item_key == item_key)
            .values(state=state, updated_at=_now())
        )
        if updated.rowcount != 1:
            raise _not_found()

    def locked_prohibited_elements(self, brand_id: str) -> tuple[str, ...]:
        """Return item texts of locked items that mark prohibited elements."""

        try:
            with self._database.engine.connect() as connection:
                rows = connection.execute(
                    select(BrandAdSpecItemRow.item_text)
                    .where(BrandAdSpecItemRow.brand_id == brand_id)
                    .where(BrandAdSpecItemRow.state == "locked")
                    .where(BrandAdSpecItemRow.item_key.like("prohibit_%"))
                ).all()
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return tuple(row[0] for row in rows)

    # ---- Skill stack -------------------------------------------------------

    def replace_skill_stack_in_transaction(
        self,
        connection: Connection,
        brand_id: str,
        stack: SkillStackV1,
    ) -> None:
        connection.execute(
            delete(BrandSkillStackRow).where(BrandSkillStackRow.brand_id == brand_id)
        )
        for entry in stack.entries:
            connection.execute(
                insert(BrandSkillStackRow).values(
                    entry_id=f"bstack_{uuid4().hex[:16]}",
                    brand_id=brand_id,
                    skill_kind=entry.skill_kind,
                    skill_id=entry.skill_id,
                    title=entry.title,
                    selected=entry.selected,
                    version=entry.version,
                    reason=entry.reason,
                    updated_at=_now(),
                )
            )

    def get_skill_stack_in_transaction(
        self, connection: Connection, brand_id: str
    ) -> SkillStackV1 | None:
        rows = connection.execute(
            select(BrandSkillStackRow)
            .where(BrandSkillStackRow.brand_id == brand_id)
            .order_by(BrandSkillStackRow.skill_kind, BrandSkillStackRow.skill_id)
        ).all()
        if not rows:
            return None
        return SkillStackV1(
            entries=tuple(
                SkillStackEntryV1(
                    skill_kind=row.skill_kind,
                    skill_id=row.skill_id,
                    title=row.title,
                    selected=row.selected,
                    version=row.version,
                    reason=row.reason,
                )
                for row in rows
            )
        )

    def get_skill_stack(self, brand_id: str) -> SkillStackV1 | None:
        """Read the persisted skill stack for one brand."""

        try:
            with self._database.engine.connect() as connection:
                return self.get_skill_stack_in_transaction(connection, brand_id)
        except SQLAlchemyError as error:
            raise _persistence_error() from error

    # ---- Treatment ---------------------------------------------------------

    def save_treatment_step_in_transaction(
        self,
        connection: Connection,
        brand_id: str,
        step: TreatmentStepResultV1,
    ) -> None:
        existing = connection.execute(
            select(BrandTreatmentStepRow.step_id).where(
                BrandTreatmentStepRow.brand_id == brand_id,
                BrandTreatmentStepRow.step_key == step.step_key,
            )
        ).first()
        if existing is not None:
            connection.execute(
                update(BrandTreatmentStepRow)
                .where(BrandTreatmentStepRow.step_id == existing[0])
                .values(
                    selected_label=step.selected_label,
                    detail_text=step.detail,
                    confirmed_at=step.confirmed_at.isoformat(),
                )
            )
        else:
            connection.execute(
                insert(BrandTreatmentStepRow).values(
                    step_id=f"bstep_{uuid4().hex[:16]}",
                    brand_id=brand_id,
                    step_key=step.step_key,
                    selected_label=step.selected_label,
                    detail_text=step.detail,
                    confirmed_at=step.confirmed_at.isoformat(),
                )
            )

    def get_treatment_steps_in_transaction(
        self, connection: Connection, brand_id: str
    ) -> tuple[TreatmentStepResultV1, ...]:
        rows = connection.execute(
            select(BrandTreatmentStepRow)
            .where(BrandTreatmentStepRow.brand_id == brand_id)
            .order_by(BrandTreatmentStepRow.confirmed_at)
        ).all()
        return tuple(
            TreatmentStepResultV1(
                step_key=row.step_key,
                selected_label=row.selected_label,
                detail=row.detail_text,
                confirmed_at=datetime.fromisoformat(row.confirmed_at),
            )
            for row in rows
        )

    # ---- Decision log ------------------------------------------------------

    def append_decision_log_in_transaction(
        self,
        connection: Connection,
        entry: BrandDecisionLogEntryV1,
        *,
        brand_id: str,
    ) -> None:
        connection.execute(
            insert(BrandDecisionLogRow).values(
                log_id=entry.log_id,
                brand_id=brand_id,
                stage=entry.stage,
                action=entry.action,
                target_type=entry.target_type,
                target_id=entry.target_id,
                detail_json=json.dumps(entry.detail, ensure_ascii=False),
                created_at=entry.created_at.isoformat(),
            )
        )

    def list_decision_log(self, brand_id: str) -> tuple[BrandDecisionLogEntryV1, ...]:
        try:
            with self._database.engine.connect() as connection:
                rows = connection.execute(
                    select(BrandDecisionLogRow)
                    .where(BrandDecisionLogRow.brand_id == brand_id)
                    .order_by(BrandDecisionLogRow.created_at)
                ).all()
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return tuple(
            BrandDecisionLogEntryV1(
                log_id=row.log_id,
                stage=row.stage,
                action=row.action,
                target_type=row.target_type,
                target_id=row.target_id,
                detail=json.loads(row.detail_json),
                created_at=datetime.fromisoformat(row.created_at),
            )
            for row in rows
        )

    # ---- Creative skill catalog --------------------------------------------

    def upsert_creative_skill_in_transaction(
        self,
        connection: Connection,
        *,
        skill_id: str,
        version: str,
        skill_kind: str,
        title: str,
        summary: str,
        body_json: str,
    ) -> bool:
        """Insert one catalog entry if new; return True when inserted."""

        existing = connection.execute(
            select(CreativeSkillCatalogRow.entry_id).where(
                CreativeSkillCatalogRow.skill_id == skill_id,
                CreativeSkillCatalogRow.version == version,
            )
        ).first()
        if existing is not None:
            return False
        connection.execute(
            insert(CreativeSkillCatalogRow).values(
                entry_id=f"cskill_{uuid4().hex[:16]}",
                skill_id=skill_id,
                version=version,
                skill_kind=skill_kind,
                title=title,
                summary=summary,
                body_json=body_json,
                created_at=_now(),
            )
        )
        return True

    def list_creative_skills(self) -> tuple[dict[str, object], ...]:
        try:
            with self._database.engine.connect() as connection:
                rows = connection.execute(
                    select(CreativeSkillCatalogRow).order_by(
                        CreativeSkillCatalogRow.skill_id, CreativeSkillCatalogRow.version
                    )
                ).all()
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return tuple(
            {
                "skill_id": row.skill_id,
                "version": row.version,
                "skill_kind": row.skill_kind,
                "title": row.title,
                "summary": row.summary,
            }
            for row in rows
        )

    # ---- Invocations -------------------------------------------------------

    def create_invocation_in_transaction(
        self,
        connection: Connection,
        *,
        brand_id: str,
        capability_id: str,
        prompt_text: str,
        next_attempt_at: str,
    ) -> str:
        invocation_id = f"binv_{uuid4().hex[:16]}"
        connection.execute(
            insert(BrandInvocationRow).values(
                invocation_id=invocation_id,
                brand_id=brand_id,
                capability_id=capability_id,
                status="queued",
                attempts=0,
                next_attempt_at=next_attempt_at,
                prompt_text=prompt_text,
                created_at=_now(),
            )
        )
        return invocation_id

    def complete_invocation_in_transaction(
        self,
        connection: Connection,
        invocation_id: str,
        *,
        output_text: str,
        model_id: str,
        result_json: str,
    ) -> None:
        connection.execute(
            update(BrandInvocationRow)
            .where(BrandInvocationRow.invocation_id == invocation_id)
            .values(
                status="completed",
                output_text=output_text,
                model_id=model_id,
                result_json=result_json,
                completed_at=_now(),
            )
        )

    def fail_invocation_in_transaction(
        self,
        connection: Connection,
        invocation_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        connection.execute(
            update(BrandInvocationRow)
            .where(BrandInvocationRow.invocation_id == invocation_id)
            .values(
                status="failed",
                error_code=error_code,
                error_message=error_message,
                completed_at=_now(),
            )
        )


def _not_found() -> V2PersistenceError:
    return V2PersistenceError(
        "brand_decision_not_found",
        "Brand decision target not found.",
        stage="brand_decision_repository",
    )


def _persistence_error() -> V2PersistenceError:
    return V2PersistenceError(
        "brand_decision_persistence_failed",
        "Brand decision persistence failed.",
        stage="brand_decision_repository",
    )

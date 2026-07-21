"""SQLAlchemy models for the V2 runtime event persistence boundary."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base model metadata owned by the V2 persistence boundary."""


class WorkflowEventRow(Base):
    """A single ordered V2 runtime event."""

    __tablename__ = "workflow_events"
    __table_args__ = (
        CheckConstraint("seq > 0", name="ck_workflow_events_positive_seq"),
        UniqueConstraint("workflow_id", "seq", name="uq_workflow_events_workflow_seq"),
        Index("ix_workflow_events_workflow_seq", "workflow_id", "seq"),
        Index("ix_workflow_events_execution_seq", "execution_id", "seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    execution_id: Mapped[str | None] = mapped_column(Text)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    node_id: Mapped[str | None] = mapped_column(Text)
    item_id: Mapped[str | None] = mapped_column(Text)
    slot_id: Mapped[str | None] = mapped_column(Text)
    asset_id: Mapped[str | None] = mapped_column(Text)
    version_id: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class DataMigrationRow(Base):
    """Records the state of one explicit data migration."""

    __tablename__ = "data_migrations"

    migration_name: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    source_count: Mapped[int | None] = mapped_column(Integer)
    imported_count: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[str | None] = mapped_column(Text)
    details_json: Mapped[str] = mapped_column(Text, nullable=False)

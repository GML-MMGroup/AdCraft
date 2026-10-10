"""Private, explicitly pinned operator recovery for legacy retry fingerprints."""

from pydantic import BaseModel, ConfigDict, Field


class RetryEnvelopeDigestRepairV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_id: str = Field(min_length=1, max_length=160)
    turn_id: str = Field(min_length=1, max_length=160)
    expected_snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_envelope_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class RetryEnvelopeDigestRepairReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_id: str
    turn_id: str
    envelope_digest: str
    event_seq: int = Field(ge=1)
    replayed: bool = False

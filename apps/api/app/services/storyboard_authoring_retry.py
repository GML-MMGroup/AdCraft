"""Bound explicit retries to failed Storyboard calls while preserving completed work."""

from sqlalchemy import select

from app.persistence.database import V2Database
from app.persistence.models import AgentRunRow
from app.services.agent_canvas_explicit_retry import explicit_turn_retryable
from app.services.durable_pi_run import derive_durable_pi_run_identity


def storyboard_authoring_request_identity(
    database: V2Database,
    *,
    request_identity: str,
    contract_name: str,
    attempt_no: int,
) -> str:
    """Advance only past retryable failures and only with a persisted retry budget.

    A completed or active call keeps its original identity. Provider runs remain
    immutable, and repeated delivery within one explicit attempt stays idempotent.
    """

    with database.engine.connect() as connection:
        for attempt in range(max(1, attempt_no)):
            candidate = request_identity if attempt == 0 else f"{request_identity}:retry:{attempt}"
            identity = derive_durable_pi_run_identity(
                {
                    "agent_request_identity": candidate,
                    "capability_id": "storyboard_design",
                    "result_contract_name": contract_name,
                }
            )
            row = (
                connection.execute(
                    select(AgentRunRow.status, AgentRunRow.safe_error_code).where(
                        AgentRunRow.run_id == identity.run_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                row is None
                or row["status"] != "failed"
                or not explicit_turn_retryable(str(row["safe_error_code"]))
            ):
                return candidate
    return candidate

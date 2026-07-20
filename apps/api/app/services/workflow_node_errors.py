from typing import Any

from app.services.reference_policy import policy_error_message


class WorkflowNodeInputError(ValueError):
    """Raised when a node-level run is missing required input."""


class ReferencePolicyInputError(WorkflowNodeInputError):
    def __init__(self, policy: dict[str, Any]) -> None:
        self.policy = policy
        super().__init__(policy_error_message(policy))


class WorkflowNodeExecutionError(RuntimeError):
    """Raised when a node-level run fails during execution."""

"""Load and index the canonical Agent capability contract."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from types import MappingProxyType

from app.schemas.agent_capabilities import (
    AgentCapabilityContractV1,
    AgentCapabilityV1,
)
from app.services.video_agent_operation_registry import VideoAgentOperationRegistry


_DEFAULT_CONTRACT_PATH = (
    Path(__file__).resolve().parents[2] / "agent" / "contracts" / "agent-capabilities.json"
)


class V2AgentCapabilityContractService:
    """Provide immutable capability lookup and compatibility identity."""

    def __init__(self, contract_path: Path | None = None) -> None:
        path = contract_path or _DEFAULT_CONTRACT_PATH
        contract = AgentCapabilityContractV1.model_validate_json(path.read_text(encoding="utf-8"))
        VideoAgentOperationRegistry().validate_capability_contract(contract)
        self._contract = contract
        self._by_name = MappingProxyType(
            {capability.name: capability for capability in contract.agents}
        )

    def load(self) -> AgentCapabilityContractV1:
        return self._contract

    def get(self, agent_name: str) -> AgentCapabilityV1 | None:
        return self._by_name.get(agent_name)

    def digest(self) -> str:
        encoded = json.dumps(
            _canonical_payload(self._contract),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(encoded).hexdigest()


def _canonical_payload(
    contract: AgentCapabilityContractV1,
) -> dict[str, object]:
    return {
        "contract_version": contract.contract_version,
        "agents": [
            {
                "name": capability.name,
                "operations": sorted(capability.operations),
                "model_role": capability.model_role,
            }
            for capability in sorted(contract.agents, key=lambda item: item.name)
        ],
    }

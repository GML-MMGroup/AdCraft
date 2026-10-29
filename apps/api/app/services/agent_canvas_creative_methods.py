"""Frozen method identities and quoted bodies for creation-mode authoring."""

from pydantic import ValidationError

from app.persistence.brand_decision_repository import BrandDecisionRepository
from app.persistence.database import V2Database
from app.schemas.agent_canvas_conversation import ConceptOptionRecordV2
from app.schemas.agent_canvas_materialization import SelectedConceptOptionV1, SelectedProposalCardV2
from app.schemas.creative_method_context import CreativeMethodContextV1
from app.services.creative_method_skill_catalog import (
    CreativeMethodSkillCatalogService,
    creative_method_seed_dir,
)


def creative_method_catalog_facts(database: V2Database) -> dict[str, object]:
    catalog = CreativeMethodSkillCatalogService(database, creative_method_seed_dir())
    return {
        "creative_method_catalog": list(catalog.injection_summaries()),
        "creative_method_versions": {
            row["skill_id"]: row["version"]
            for row in BrandDecisionRepository(database).list_creative_skills()
            if row["skill_kind"] == "creative_method"
        },
    }


def read_creative_method(
    repository: BrandDecisionRepository,
    option: ConceptOptionRecordV2 | SelectedProposalCardV2 | SelectedConceptOptionV1 | None,
) -> CreativeMethodContextV1 | None:
    """Omit a method whose exact stored version is no longer available."""
    skill_id = getattr(option, "creative_method_id", None)
    version = getattr(option, "creative_method_version", None)
    if not skill_id or not version:
        return None
    try:
        body = repository.get_creative_skill_body(skill_id, version)
        method = CreativeMethodContextV1.model_validate(
            {key: body[key] for key in CreativeMethodContextV1.model_fields if key in body}
        )
    except (ValueError, KeyError, TypeError, ValidationError):
        return None
    if method.skill_id != skill_id or method.version != version:
        return None
    return method

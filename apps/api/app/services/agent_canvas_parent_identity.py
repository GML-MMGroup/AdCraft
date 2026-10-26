"""One parent identity fence for derivative queueing and publication."""

from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_materialization import ParentNodeSnapshotV1
from app.services.agent_canvas_node_change_authority import creative_node_input_digest


def parent_snapshot_matches(snapshot: ParentNodeSnapshotV1, node: CanvasNodeV2) -> bool:
    """Permit operational revisions only with unchanged frozen creative authority."""

    if node.node_id != snapshot.node_id or node.revision < snapshot.node_revision:
        return False
    same_preparation = (
        node.prompt_preparation.status == "ready"
        and node.prompt_preparation.operation_id == snapshot.prompt_preparation_operation_id
    )
    if snapshot.creative_input_digest is not None:
        return (
            same_preparation and creative_node_input_digest(node) == snapshot.creative_input_digest
        )
    # Do not retrofit historical immutable envelopes from mutable current data.
    return node.revision == snapshot.node_revision or (
        snapshot.prompt_preparation_operation_id is not None and same_preparation
    )

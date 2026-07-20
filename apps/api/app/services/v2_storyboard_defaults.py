DEFAULT_STORYBOARD_SHOT_COUNT = 4
DEFAULT_SHOT_CELL_COUNT = 4

SHOT_CELL_ROLES: tuple[str, ...] = (
    "establishing",
    "action",
    "detail",
    "payoff",
)


def shot_cell_slot_types(cell_count: int = DEFAULT_SHOT_CELL_COUNT) -> tuple[str, ...]:
    return tuple(f"shot_cell_{index}" for index in range(1, cell_count + 1))


def shot_cell_role(slot_type: str) -> str:
    try:
        index = int(slot_type.removeprefix("shot_cell_")) - 1
    except ValueError:
        return slot_type
    if 0 <= index < len(SHOT_CELL_ROLES):
        return SHOT_CELL_ROLES[index]
    return f"shot cell {index + 1}"

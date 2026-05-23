from src.domain.position import PositionStatus


def test_position_status_names_open_and_closed_states():
    assert PositionStatus.OPEN.value == "open"
    assert PositionStatus.CLOSED.value == "closed"

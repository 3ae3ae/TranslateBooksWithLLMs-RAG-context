import pytest

from src.core.progress import Phase, ProgressSnapshot


def test_snapshot_is_immutable():
    snap = ProgressSnapshot(
        phase=Phase.TRANSLATING,
        units_done=1,
        units_total=2,
        units_succeeded=1,
        units_failed=0,
        percent=50.0,
        refinement_enabled=False,
    )
    with pytest.raises(Exception):
        snap.percent = 99.0  # frozen dataclass

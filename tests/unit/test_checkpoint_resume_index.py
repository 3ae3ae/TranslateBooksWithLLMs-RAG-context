import pytest

from src.persistence.checkpoint_manager import CheckpointManager


@pytest.fixture
def cm(tmp_path):
    return CheckpointManager(db_path=str(tmp_path / "jobs.db"))


@pytest.mark.parametrize("file_type", ["epub", "txt", "srt"])
def test_new_marked_checkpoint_resumes_at_next_unit(cm, file_type):
    cm.start_job("job", file_type, {}, None)
    # New convention: store the last completed unit index.
    cm.save_checkpoint(
        translation_id="job",
        chunk_index=2,
        original_text="x",
        translated_text="y",
        total_chunks=10,
        completed_chunks=3,
        failed_chunks=0,
    )
    assert cm.load_checkpoint("job")["resume_from_index"] == 3

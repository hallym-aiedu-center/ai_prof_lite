import pytest

from core.config import job_gpu_ids


def test_job_gpu_ids_four(monkeypatch):
    monkeypatch.setenv("JOB_GPU_IDS", "0,1,2,3")
    monkeypatch.delenv("DITTO_GPU", raising=False)
    assert job_gpu_ids(concurrency=4) == ["0", "1", "2", "3"]


def test_job_gpu_ids_rejects_insufficient_gpu_count(monkeypatch):
    monkeypatch.setenv("JOB_GPU_IDS", "0,1")
    with pytest.raises(ValueError, match="JOB_CONCURRENCY"):
        job_gpu_ids(concurrency=4)


def test_job_gpu_ids_rejects_duplicates(monkeypatch):
    monkeypatch.setenv("JOB_GPU_IDS", "0,0,1,2")
    with pytest.raises(ValueError, match="duplicate"):
        job_gpu_ids(concurrency=4)


def test_legacy_ditto_gpu_kept_for_single_slot(monkeypatch):
    monkeypatch.delenv("JOB_GPU_IDS", raising=False)
    monkeypatch.setenv("DITTO_GPU", "3")
    assert job_gpu_ids(concurrency=1) == ["3"]

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from app.object_store import EvidenceStore
from app.settings import settings


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "evidence_backend", "filesystem")
    monkeypatch.setattr(settings, "evidence_directory", str(tmp_path))
    return EvidenceStore()


def test_persistence_new_instance_and_integrity(store):
    artifact = store.put_bytes("GLEIF", "test", b"original evidence")
    assert EvidenceStore().get_bytes(artifact.object_key, artifact.sha256) == b"original evidence"
    Path(store.directory / artifact.object_key).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="hash mismatch"):
        EvidenceStore().get_bytes(artifact.object_key, artifact.sha256)
    with pytest.raises(ValueError, match="hash mismatch"):
        store.put_bytes("GLEIF", "test", b"original evidence")


def test_concurrent_puts_never_overwrite(store):
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(lambda _: store.put_bytes("TEST", "same", b"payload"), range(20))
        )
    assert len({r.object_key for r in results}) == 1
    assert store.get_bytes(results[0].object_key, results[0].sha256) == b"payload"
    assert not list(store.directory.rglob(".write-*"))


def test_path_traversal_rejected(store):
    with pytest.raises(ValueError):
        store.get_bytes("../../outside")
    result = store.put_bytes("../TEST", "../../outside", b"content")
    assert (store.directory / result.object_key).resolve().is_relative_to(store.directory.resolve())


def test_ready_probe_does_not_create_evidence(store):
    store.check()
    assert not list(store.directory.iterdir())

"""Tests for the consolidated Azure circuit downloader.

The five downloader entry points were collapsed onto one download loop, so the
pieces that used to differ per script — blob-path derivation, output layout,
cache reuse and how `--limit` counts — are pinned here. Azure itself is never
contacted: a fake container client stands in for it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("qiskit.qpy")

from scripts.azure.download_circuits import (  # noqa: E402
    BlobRequest,
    Downloader,
    blob_path_from_url,
    hashes_from_csv,
    run_hashes,
)


class FakeContainer:
    """Stands in for an Azure container client. Records what was asked for."""

    container_name = "circuits"

    def __init__(self, missing: set[str] | None = None):
        self.requested: list[str] = []
        self.missing = missing or set()


@pytest.fixture(autouse=True)
def fake_download(monkeypatch):
    """Replace the Azure round-trip with a recorder that writes a stub file."""
    import scripts.azure.download_circuits as module

    def fake_download_circuit_blob(container_client, blob_path, method="qpy"):
        container_client.requested.append(blob_path)
        if blob_path in container_client.missing:
            raise RuntimeError(f"blob not found: {blob_path}")
        return blob_path

    def fake_dump(circuit, handle):
        handle.write(str(circuit).encode())

    monkeypatch.setattr(module, "download_circuit_blob", fake_download_circuit_blob)
    monkeypatch.setattr(module.qiskit.qpy, "dump", fake_dump)


# ── Blob path derivation ──────────────────────────────────────────────────────

def test_blob_path_from_url_strips_container_prefix():
    url = "https://acct.blob.core.windows.net/circuits/ab/abcdef.qpy"
    assert blob_path_from_url(url, "circuits") == "ab/abcdef.qpy"


def test_blob_path_from_url_leaves_foreign_container_alone():
    """A URL from another container keeps its full path rather than losing a segment."""
    url = "https://acct.blob.core.windows.net/other/ab/abcdef.qpy"
    assert blob_path_from_url(url, "circuits") == "other/ab/abcdef.qpy"


# ── The download loop ─────────────────────────────────────────────────────────

def test_fetch_writes_file_and_counts(tmp_path):
    downloader = Downloader(output_dir=tmp_path)
    container = FakeContainer()

    assert downloader.fetch(container, BlobRequest("ab/x.qpy", Path("ab/x.qpy")))
    assert (tmp_path / "ab" / "x.qpy").read_bytes() == b"ab/x.qpy"
    assert downloader.count == 1


def test_existing_file_is_not_refetched(tmp_path):
    (tmp_path / "ab").mkdir()
    (tmp_path / "ab" / "x.qpy").write_bytes(b"already here")
    downloader = Downloader(output_dir=tmp_path)
    container = FakeContainer()

    assert downloader.fetch(container, BlobRequest("ab/x.qpy", Path("ab/x.qpy")))
    assert container.requested == []
    assert (tmp_path / "ab" / "x.qpy").read_bytes() == b"already here"
    # A skip still counts: --limit bounds circuits obtained, not bytes moved.
    assert downloader.count == 1


def test_cache_hit_copies_instead_of_downloading(tmp_path):
    cache, out = tmp_path / "cache", tmp_path / "out"
    (cache / "ab").mkdir(parents=True)
    (cache / "ab" / "x.qpy").write_bytes(b"cached")
    downloader = Downloader(output_dir=out, cache_dir=cache)
    container = FakeContainer()

    assert downloader.fetch(container, BlobRequest("ab/x.qpy", Path("ab/x.qpy")))
    assert container.requested == []
    assert (out / "ab" / "x.qpy").read_bytes() == b"cached"


def test_failed_download_does_not_count(tmp_path):
    downloader = Downloader(output_dir=tmp_path)
    container = FakeContainer(missing={"ab/x.qpy"})

    assert not downloader.fetch(container, BlobRequest("ab/x.qpy", Path("ab/x.qpy")))
    assert downloader.count == 0
    assert not (tmp_path / "ab" / "x.qpy").exists()


def test_exhausted_tracks_the_limit(tmp_path):
    downloader = Downloader(output_dir=tmp_path, limit=2)
    container = FakeContainer()

    for name in ("a", "b"):
        downloader.fetch(container, BlobRequest(f"ab/{name}.qpy", Path(f"{name}.qpy")))
    assert downloader.exhausted


def test_no_limit_is_never_exhausted(tmp_path):
    assert not Downloader(output_dir=tmp_path).exhausted


# ── Hash mode ─────────────────────────────────────────────────────────────────

def test_run_hashes_shards_blob_path_and_flattens_output(tmp_path, monkeypatch):
    """Blobs are sharded by the hash's first two characters; output is flat."""
    import scripts.azure.download_circuits as module

    container = FakeContainer()
    monkeypatch.setattr(module, "connect", lambda: (container, "circuits"))

    run_hashes(["abcdef", "123456"], tmp_path)

    assert container.requested == ["ab/abcdef.qpy", "12/123456.qpy"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["123456.qpy", "abcdef.qpy"]


def test_run_hashes_rejects_an_empty_hash_list(tmp_path):
    with pytest.raises(SystemExit):
        run_hashes([], tmp_path)


# ── CSV mode ──────────────────────────────────────────────────────────────────

def test_hashes_from_csv_reads_the_rowkey_column(tmp_path):
    csv_path = tmp_path / "hashes.csv"
    csv_path.write_text("PartitionKey,RowKey\np,abcdef\np,123456\n")
    assert hashes_from_csv(csv_path) == ["abcdef", "123456"]


def test_hashes_from_csv_names_the_missing_column(tmp_path):
    csv_path = tmp_path / "hashes.csv"
    csv_path.write_text("PartitionKey,other\np,abcdef\n")
    with pytest.raises(ValueError, match="RowKey"):
        hashes_from_csv(csv_path)

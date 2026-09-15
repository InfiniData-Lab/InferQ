"""Tests for the provider-neutral cloud storage layer.

These pin the contracts every backend has to honour, so that an Azure-backed
deployment and an AWS-backed one behave identically where it matters:

- attribute names are derived the same way on both clouds, so a record written
  by one is readable by the other byte-for-byte;
- object keys are derived in exactly one place;
- pagination cursors are opaque strings that survive a round trip;
- provider selection is resolved from configuration, not from imports.

Nothing here touches a network, and importing :mod:`inferq.remote` is itself
asserted not to drag in a cloud SDK.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from inferq.remote import (
    CIRCUITS_PARTITION,
    CloudCredentialsError,
    ObjectInfo,
    Record,
    RecordPage,
    available_providers,
    blob_path_for,
    connection_class,
    decode_cursor,
    encode_cursor,
    field_safe,
    resolve_provider,
    table_safe,
)

# ── Attribute-name derivation ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("gate-count (total)", "gate_count__total_"),
        ("2q_gates", "prop_2q_gates"),
        ("  NumQubits  ", "numqubits"),
        ("already_safe", "already_safe"),
        ("dotted.name", "dotted_name"),
        ("", ""),
    ],
)
def test_field_safe_derivation(raw, expected):
    assert field_safe(raw) == expected


def test_table_safe_is_the_same_function():
    """The Azure-era name stays importable and stays *the same* function.

    Attribute names are part of the stored data: if the two names ever drifted,
    a catalogue written before a migration would stop matching one written
    after it.
    """
    assert table_safe is field_safe


def test_names_are_normalised_above_the_providers():
    """Normalisation happens once, in the neutral layer, not per backend.

    That is what makes a DynamoDB item and an Azure Table entity carry
    identical attribute names for the same feature: the providers never see
    an un-normalised key, so neither can invent its own spelling.
    """
    from inferq.remote.metadata import encode_fields

    encoded = encode_fields({"gate-count (total)": 7, "2q_gates": 3})
    assert encoded == {"gate_count__total_": 7, "prop_2q_gates": 3}


def test_encoded_fields_round_trip_through_decode():
    """Structured values survive the string encoding both stores impose."""
    from inferq.remote.metadata import decode_fields, encode_fields

    features = {"depths": [1, 2, 3], "counts": {"h": 2}, "num_qubits": 5}
    assert decode_fields(encode_fields(features)) == features


# ── Object key derivation ─────────────────────────────────────────────────────


def test_blob_path_shards_on_the_first_two_characters():
    assert blob_path_for("abcdef0123") == "ab/abcdef0123.qpy"


def test_blob_path_honours_the_extension():
    assert blob_path_for("abcdef0123", "pkl") == "ab/abcdef0123.pkl"
    assert blob_path_for("abcdef0123", "qasm") == "ab/abcdef0123.qasm"


def test_upload_returns_the_key_not_a_url():
    """``blob_path`` is recorded as a key so it means the same on every cloud."""
    pytest.importorskip("qiskit.qpy")
    from qiskit import QuantumCircuit

    from inferq.remote.circuits import upload_circuit_blob

    class RecordingStore:
        name = "circuits"

        def __init__(self):
            self.written: dict[str, bytes] = {}
            self.metadata: dict[str, dict[str, str]] = {}

        def put_object(self, key, data, *, content_type=None, metadata=None):
            self.written[key] = data
            self.metadata[key] = metadata or {}
            return f"https://example.invalid/circuits/{key}"

        def object_url(self, key):
            return f"https://example.invalid/circuits/{key}"

    store = RecordingStore()
    circuit = QuantumCircuit(2)
    circuit.h(0)
    circuit.cx(0, 1)

    key = upload_circuit_blob(store, circuit, "abcdef0123")

    assert key == "ab/abcdef0123.qpy"
    assert key in store.written
    assert store.metadata[key]["format"] == "qpy"
    assert store.metadata[key]["sha256"] == "abcdef0123"


# ── Pagination cursors ────────────────────────────────────────────────────────


def test_cursor_round_trips():
    state = {"continuation_token": "abc123", "page": 4}
    assert decode_cursor(encode_cursor(state)) == state


def test_cursor_is_url_safe_and_opaque():
    """Cursors travel through CLI flags and JSON checkpoints, so no padding fuss."""
    cursor = encode_cursor({"LastEvaluatedKey": {"pk": "circuits", "sk": "ff" * 32}})
    assert cursor.isascii()
    assert "/" not in cursor and "+" not in cursor


def test_malformed_cursor_is_rejected_clearly():
    with pytest.raises(ValueError, match="cursor"):
        decode_cursor("not base64 at all !!")


def test_non_object_cursor_is_rejected():
    import base64
    import json

    payload = base64.urlsafe_b64encode(json.dumps([1, 2]).encode()).decode()
    with pytest.raises(ValueError, match="cursor"):
        decode_cursor(payload)


def test_azure_scan_round_trips_its_continuation_token():
    """An Azure continuation token survives as an opaque cursor and comes back."""
    pytest.importorskip("azure.data.tables")
    from inferq.remote.providers.azure import AzureMetadataStore

    class FakePager:
        """Mimics ``ItemPaged.by_page``: yields pages, exposes the next token."""

        def __init__(self, pages, tokens):
            self._pages = pages
            self._tokens = tokens
            self._index = -1

        def __iter__(self):
            return self

        def __next__(self):
            self._index += 1
            if self._index >= len(self._pages):
                raise StopIteration
            return iter(self._pages[self._index])

        @property
        def continuation_token(self):
            return self._tokens[self._index]

    class FakeTableClient:
        table_name = "circuits"

        def __init__(self):
            self.tokens_seen: list[str | None] = []

        def query_entities(self, **kwargs):
            return self

        def list_entities(self, **kwargs):
            return self

        def by_page(self, continuation_token=None):
            self.tokens_seen.append(continuation_token)
            return FakePager(
                pages=[[{"PartitionKey": "circuits", "RowKey": "aa"}]],
                tokens=["token-2"],
            )

    client = FakeTableClient()
    store = AzureMetadataStore(client)

    first = next(iter(store.scan_records(CIRCUITS_PARTITION, page_size=1)))
    assert isinstance(first, RecordPage)
    assert [record.key for record in first.records] == ["aa"]
    assert first.cursor is not None
    assert decode_cursor(first.cursor) == {"continuation_token": "token-2"}

    # Handing the cursor back reaches the SDK as the raw token again.
    next(iter(store.scan_records(CIRCUITS_PARTITION, page_size=1, cursor=first.cursor)))
    assert client.tokens_seen == [None, "token-2"]


# ── Provider resolution ───────────────────────────────────────────────────────


def test_azure_is_registered():
    assert "azure" in available_providers()


def test_resolve_provider_reads_the_config():
    assert resolve_provider({"provider": "azure"}) == "azure"


def test_resolve_provider_rejects_an_unknown_name():
    with pytest.raises(ValueError, match="INFERQ_CLOUD_PROVIDER"):
        resolve_provider({"provider": "gcp"})


def test_connection_class_rejects_an_unknown_name():
    with pytest.raises(ValueError, match="Unknown cloud provider"):
        connection_class("gcp")


def test_explicit_provider_wins_over_inference(monkeypatch):
    from inferq.config import config

    monkeypatch.setenv("INFERQ_CLOUD_PROVIDER", "azure")
    monkeypatch.setenv("AWS_S3_BUCKET", "some-bucket")
    assert config.resolve_cloud_provider() == "azure"


def test_aws_is_inferred_from_aws_only_variables(monkeypatch):
    from inferq.config import config

    monkeypatch.delenv("INFERQ_CLOUD_PROVIDER", raising=False)
    monkeypatch.setenv("AWS_S3_BUCKET", "some-bucket")
    assert config.resolve_cloud_provider() == "aws"


def test_azure_stays_the_default_without_aws_variables(monkeypatch):
    from inferq.config import config

    monkeypatch.delenv("INFERQ_CLOUD_PROVIDER", raising=False)
    monkeypatch.delenv("AWS_S3_BUCKET", raising=False)
    monkeypatch.delenv("AWS_DYNAMODB_TABLE", raising=False)
    assert config.resolve_cloud_provider() == "azure"


def test_ambient_aws_region_does_not_flip_the_provider(monkeypatch):
    """Running an Azure deployment on EC2 must not silently switch backends.

    ``AWS_REGION`` and credentials are ambient on any AWS host, so only the
    bucket/table variables -- which nobody sets by accident -- count as intent.
    """
    from inferq.config import config

    monkeypatch.delenv("INFERQ_CLOUD_PROVIDER", raising=False)
    monkeypatch.delenv("AWS_S3_BUCKET", raising=False)
    monkeypatch.delenv("AWS_DYNAMODB_TABLE", raising=False)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")
    assert config.resolve_cloud_provider() == "azure"


# ── Value types ───────────────────────────────────────────────────────────────


def test_record_defaults_are_independent():
    """Frozen dataclasses with mutable defaults are a classic shared-state bug."""
    first, second = Record("p", "a"), Record("p", "b")
    assert first.fields == {} and second.fields == {}
    assert first.fields is not second.fields


def test_object_info_defaults_are_independent():
    first, second = ObjectInfo("a"), ObjectInfo("b")
    assert first.metadata is not second.metadata


def test_credentials_error_is_a_runtime_error():
    """Call sites catch broad errors around connection setup; keep them catching."""
    assert issubclass(CloudCredentialsError, RuntimeError)


# ── Import cost ───────────────────────────────────────────────────────────────


def test_importing_remote_pulls_in_no_cloud_sdk():
    """``inferq.remote`` is on the CLI's startup path; SDK imports are lazy.

    Checked in a subprocess because the test session has almost certainly
    imported an SDK already.
    """
    code = (
        "import sys; import inferq.remote; "
        "leaked = [m for m in sys.modules if m.split('.')[0] in ('boto3', 'botocore', 'azure')]; "
        "print(','.join(sorted(leaked)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "", f"cloud SDK imported eagerly: {result.stdout.strip()}"

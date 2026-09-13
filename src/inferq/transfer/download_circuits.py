#!/usr/bin/env python3
"""Download circuits out of Azure Blob Storage.

Four ways of naming *which* blobs to fetch, over one download loop:

  all       every blob in the configured container
  metadata  the ``blob_url`` column of the parquet metadata files
  hashes    explicit circuit hashes, or the ``RowKey`` column of a CSV
  public    every blob in an anonymous public container, byte-for-byte

Everything after the enumeration step — connecting, skipping what is already
on disk, deserializing, re-serializing as QPY, counting against ``--limit`` —
is identical, which is why these used to be five scripts that drifted.

The ``public`` mode is the one real exception: it copies raw bytes and never
deserializes, because an anonymous container is not assumed to hold circuits
this repo can parse.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import qiskit.qpy
from tqdm import tqdm

from inferq import paths
from inferq.config import PipelineConfig
from inferq.remote.blob import download_circuit_blob
from inferq.remote.connection import AzureConnection

logger = logging.getLogger(__name__)

DEFAULT_METADATA_DIR = paths.data_dir() / "fetched_circuit_metadata"
DEFAULT_OUTPUT_DIRS = {
    "all": paths.data_dir() / "fetched_raw_blobs",
    "metadata": paths.data_dir() / "downloaded_circuits_from_metadata",
    "hashes": paths.data_dir() / "downloaded_circuits",
    "public": paths.data_dir() / "downloaded_circuits_public",
}


def configure_logging(mode: str) -> None:
    """Log to the console and to a per-mode file under the state directory."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(paths.log_file(f"download_circuits_{mode}.log")),
        ],
    )


# ── Interactive fallbacks ─────────────────────────────────────────────────────
#
# The `all` and `metadata` entry points have always asked for a missing output
# directory or limit rather than failing. EOFError is caught so the same command
# still runs unattended in CI or under a pipe.

def prompt_for_output_dir(default: Path) -> str:
    """Ask where to save, falling back to `default`."""
    try:
        answer = input(
            f"Enter destination directory (or press Enter for default '{default}'): "
        ).strip()
    except EOFError:
        return str(default)
    return answer or str(default)


def prompt_for_limit() -> int | None:
    """Ask how many circuits to fetch. None means all."""
    try:
        answer = input(
            "Enter number of circuits to download (or press Enter for all): "
        ).strip()
    except EOFError:
        return None
    if not answer:
        return None
    try:
        return int(answer)
    except ValueError:
        print("Invalid number. Defaulting to all.")
        return None


# ── The blob request each enumerator yields ───────────────────────────────────

@dataclass(frozen=True)
class BlobRequest:
    """One circuit to fetch.

    Attributes:
        blob_path: Path of the blob inside the container.
        local_path: Where to write it, relative to the output directory.
        serialization_method: Format recorded for the blob, passed to
            `download_circuit_blob`.
    """

    blob_path: str
    local_path: Path
    serialization_method: str = "qpy"


# ── The shared download loop ──────────────────────────────────────────────────

@dataclass
class Downloader:
    """Fetches `BlobRequest`s, skipping what is already present.

    Attributes:
        output_dir: Root for downloaded files.
        limit: Stop after this many circuits are downloaded or found; None for
            no bound. A cache hit and a skip both count, matching the original
            scripts: `--limit` bounds circuits *obtained*, not bytes moved.
        cache_dir: Optional local circuit store checked before each download,
            so a circuit already in `circuits/` is copied rather than refetched.
    """

    output_dir: Path
    limit: int | None = None
    cache_dir: Path | None = None
    count: int = field(default=0, init=False)

    @property
    def exhausted(self) -> bool:
        return self.limit is not None and self.count >= self.limit

    def fetch(self, container_client, request: BlobRequest) -> bool:
        """Obtain one circuit. Returns True if it is now on disk."""
        target = self.output_dir / request.local_path
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            self.count += 1
            return True

        if self.cache_dir is not None:
            cached = self.cache_dir / request.local_path
            if cached.exists():
                try:
                    shutil.copy2(cached, target)
                    self.count += 1
                    return True
                except OSError as error:
                    logger.warning(f"Failed to copy from cache {cached}: {error}")

        try:
            circuit = download_circuit_blob(
                container_client, request.blob_path, request.serialization_method
            )
            with target.open("wb") as f:
                qiskit.qpy.dump(circuit, f)
        except Exception as error:  # noqa: BLE001 - one bad blob must not stop the run
            logger.error(f"Failed to download/save circuit {request.blob_path}: {error}")
            return False

        self.count += 1
        return True


def connect() -> tuple[object, str] | tuple[None, None]:
    """Open the configured container. Returns (client, container_name)."""
    try:
        container_client = AzureConnection().container_client
    except Exception as error:  # noqa: BLE001 - credentials are the usual cause
        logger.error(f"Failed to connect to Azure: {error}")
        return None, None
    name = container_client.container_name
    logger.info(f"Connected to Azure Blob Storage container: {name}")
    return container_client, name


def _mirrored_path(blob_path: str) -> Path:
    """Mirror the blob's ``XX/hash.ext`` layout locally, normalised to ``.qpy``."""
    return Path(blob_path).with_suffix(".qpy")


# ── Mode: all ─────────────────────────────────────────────────────────────────

def run_all(output_dir: str | Path, limit: int | None = None) -> None:
    """Download every blob in the container, mirroring its ``XX/hash.qpy`` layout."""
    container_client, _ = connect()
    if container_client is None:
        return

    downloader = Downloader(output_dir=Path(output_dir), limit=limit)
    logger.info("Listing blobs...")
    try:
        blobs = container_client.list_blobs(include=["metadata"])
    except Exception as error:  # noqa: BLE001
        logger.error(f"Failed to list blobs: {error}")
        return

    for blob in tqdm(blobs, desc="Downloading blobs"):
        if downloader.exhausted:
            break
        metadata = blob.metadata or {}
        downloader.fetch(
            container_client,
            BlobRequest(
                blob_path=blob.name,
                local_path=_mirrored_path(blob.name),
                serialization_method=metadata.get("format", "qpy"),
            ),
        )

    logger.info(f"Download complete. Total circuits processed: {downloader.count}")


# ── Mode: metadata ────────────────────────────────────────────────────────────

def blob_path_from_url(blob_url: str, container_name: str) -> str:
    """Strip scheme, host and container prefix off a full blob URL."""
    path = urlparse(blob_url).path.lstrip("/")
    prefix = container_name + "/"
    return path[len(prefix):] if path.startswith(prefix) else path


def run_metadata(
    data_dir: str | Path,
    output_dir: str | Path,
    limit: int | None = None,
) -> None:
    """Download the circuits referenced by parquet metadata files.

    Resumable: each parquet file is recorded in ``checkpoint.json`` under the
    output directory once it has been walked to completion, so a re-run picks
    up where an interrupted one stopped.
    """
    import pandas as pd

    container_client, container_name = connect()
    if container_client is None:
        return

    data_dir = Path(data_dir)
    parquet_files = sorted(p for p in data_dir.glob("*.parquet"))
    if not parquet_files:
        logger.warning(f"No parquet files found in {data_dir}")
        return
    logger.info(f"Found {len(parquet_files)} parquet files.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Reuse the main circuit store when it is not itself the destination.
    cache_dir = Path(PipelineConfig().circuits_dir)
    if cache_dir.resolve() == output_dir.resolve():
        cache_dir = None

    downloader = Downloader(output_dir=output_dir, limit=limit, cache_dir=cache_dir)

    checkpoint_file = output_dir / "checkpoint.json"
    processed: set[str] = set()
    if checkpoint_file.exists():
        try:
            processed = set(json.loads(checkpoint_file.read_text()).get(
                "processed_parquet_files", []))
            logger.info(f"Loaded checkpoint. {len(processed)} parquet files already done.")
        except (OSError, ValueError) as error:
            logger.warning(f"Failed to load checkpoint: {error}")

    for parquet in tqdm(parquet_files, desc="Processing parquet files", unit="file"):
        if parquet.name in processed or downloader.exhausted:
            continue
        try:
            df = pd.read_parquet(parquet)
        except Exception as error:  # noqa: BLE001
            logger.error(f"Failed to read {parquet}: {error}")
            continue
        if "blob_url" not in df.columns:
            logger.warning(f"'blob_url' column not found in {parquet.name}. Skipping.")
            continue

        for _, row in tqdm(df.iterrows(), total=len(df), desc=f"Downloading from {parquet.name}"):
            if downloader.exhausted:
                break
            blob_url = row["blob_url"]
            if pd.isna(blob_url):
                continue
            method = row.get("serialization_method", "qpy")
            if pd.isna(method):
                method = "qpy"
            blob_path = blob_path_from_url(blob_url, container_name)
            downloader.fetch(
                container_client,
                BlobRequest(blob_path, Path(blob_path), method),
            )

        # Only mark the file done if the limit did not cut it short.
        if not downloader.exhausted:
            processed.add(parquet.name)
            try:
                checkpoint_file.write_text(
                    json.dumps({"processed_parquet_files": sorted(processed)})
                )
            except OSError as error:
                logger.warning(f"Failed to save checkpoint: {error}")

    logger.info(f"Download complete. Total circuits processed: {downloader.count}")


# ── Mode: hashes ──────────────────────────────────────────────────────────────

def hashes_from_csv(csv_path: Path, column: str = "RowKey") -> list[str]:
    """Read circuit hashes out of one column of a CSV."""
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if column not in (reader.fieldnames or []):
            raise ValueError(
                f"{column!r} column not found in {csv_path}. Columns: {reader.fieldnames}"
            )
        return [row[column] for row in reader]


def run_hashes(
    hashes: list[str],
    output_dir: str | Path,
    limit: int | None = None,
    from_csv: str | Path | None = None,
    csv_column: str = "RowKey",
) -> None:
    """Download circuits named by hash, flat into the output directory."""
    hashes = list(hashes)
    if from_csv:
        hashes.extend(hashes_from_csv(Path(from_csv), csv_column))
    hashes = [h.strip() for h in hashes if h.strip()]
    if not hashes:
        raise SystemExit("No hashes given: pass them positionally or via --from-csv.")

    container_client, _ = connect()
    if container_client is None:
        return

    downloader = Downloader(output_dir=Path(output_dir), limit=limit)
    for circuit_hash in tqdm(hashes, desc="Downloading circuits"):
        if downloader.exhausted:
            break
        downloader.fetch(
            container_client,
            BlobRequest(
                # The store sharded blobs by the hash's first two characters.
                blob_path=f"{circuit_hash[:2]}/{circuit_hash}.qpy",
                local_path=Path(f"{circuit_hash}.qpy"),
            ),
        )

    logger.info(
        f"Download finished. Successfully downloaded/found: "
        f"{downloader.count}/{len(hashes)}"
    )


# ── Mode: public ──────────────────────────────────────────────────────────────

def run_public(container_url: str, output_dir: str | Path, limit: int | None = None) -> None:
    """Copy every blob out of an anonymous public container, byte-for-byte.

    No deserialization: a public container is not assumed to hold circuits in a
    format this repo can parse, so the bytes are written exactly as stored.
    """
    from azure.storage.blob import ContainerClient

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Connecting to container: {container_url}")
    try:
        container_client = ContainerClient.from_container_url(
            container_url, credential=None
        )
        blobs = list(container_client.list_blobs())
    except Exception as error:  # noqa: BLE001
        logger.error(f"Error listing or processing blobs: {error}")
        logger.error("Check the URL is correct and allows public anonymous access.")
        return

    count = 0
    for blob in tqdm(blobs, desc="Downloading blobs"):
        if limit is not None and count >= limit:
            break
        local_path = output_dir / blob.name
        local_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            stream = container_client.get_blob_client(blob).download_blob()
            local_path.write_bytes(stream.readall())
            count += 1
        except Exception as error:  # noqa: BLE001
            logger.error(f"Failed to download {blob.name}: {error}")

    logger.info(f"Download complete. Total files: {count}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download circuits from Azure Blob Storage.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    def add_common(sub: argparse.ArgumentParser, mode: str) -> None:
        sub.add_argument(
            "--output-dir",
            default=str(DEFAULT_OUTPUT_DIRS[mode]),
            help=f"Directory to save downloaded circuits (default: {DEFAULT_OUTPUT_DIRS[mode]}).",
        )
        sub.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of circuits to obtain (default: no limit).",
        )

    sub_all = subparsers.add_parser("all", help="Download every blob in the container.")
    add_common(sub_all, "all")

    sub_meta = subparsers.add_parser(
        "metadata", help="Download circuits listed in parquet metadata files."
    )
    add_common(sub_meta, "metadata")
    sub_meta.add_argument(
        "--data-dir",
        default=str(DEFAULT_METADATA_DIR),
        help="Directory of parquet files carrying a 'blob_url' column.",
    )

    sub_hash = subparsers.add_parser("hashes", help="Download specific circuits by hash.")
    add_common(sub_hash, "hashes")
    sub_hash.add_argument("hashes", nargs="*", help="Circuit hashes to download.")
    sub_hash.add_argument("--from-csv", help="CSV file to read additional hashes from.")
    sub_hash.add_argument(
        "--csv-column", default="RowKey", help="Column holding the hashes (default: RowKey)."
    )

    sub_pub = subparsers.add_parser(
        "public", help="Download an anonymous public container byte-for-byte."
    )
    add_common(sub_pub, "public")
    sub_pub.add_argument(
        "--container-url", required=True, help="Full URL of the public container."
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    configure_logging(args.mode)
    if args.mode == "all":
        run_all(args.output_dir, args.limit)
    elif args.mode == "metadata":
        run_metadata(args.data_dir, args.output_dir, args.limit)
    elif args.mode == "hashes":
        run_hashes(
            args.hashes, args.output_dir, args.limit, args.from_csv, args.csv_column
        )
    else:
        run_public(args.container_url, args.output_dir, args.limit)


if __name__ == "__main__":
    main()

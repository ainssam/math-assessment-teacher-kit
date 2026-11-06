"""Local configuration for the read-only assessment catalog."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

_CATALOG_MATERIALIZATION_LOCK = threading.Lock()
_DETAIL_MATERIALIZATION_LOCK = threading.Lock()


class MultipartReader:
    """Read sequential deployment chunks as one gzip stream."""

    def __init__(self, paths: list[Path]) -> None:
        self.paths = iter(paths)
        self.current = None

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            chunks: list[bytes] = []
            while True:
                chunk = self.read(1024 * 1024)
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
        output = bytearray()
        while len(output) < size:
            if self.current is None:
                try:
                    self.current = next(self.paths).open("rb")
                except StopIteration:
                    break
            chunk = self.current.read(size - len(output))
            if chunk:
                output.extend(chunk)
                continue
            self.current.close()
            self.current = None
        return bytes(output)

    def close(self) -> None:
        if self.current is not None:
            self.current.close()
            self.current = None

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DETAIL_DATABASE = (
    PROJECT_ROOT / "data" / "publish" / "math_assessment_catalog_detail.sqlite"
)
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "publish" / "math_assessment_catalog.sqlite"
PACKAGED_DATA = Path(__file__).resolve().parents[1] / "data"
PACKAGED_DATABASE = PACKAGED_DATA / "math_assessment_catalog.sqlite"
PACKAGED_DATABASE_GZIP = PACKAGED_DATA / "math_assessment_catalog.sqlite.gz"
PACKAGED_DATABASE_GZIP_PATTERN = f"{PACKAGED_DATABASE_GZIP.name}.part-*"
PACKAGED_DATABASE_ARCHIVE = PACKAGED_DATA / "math_assessment_catalog.sqlite.gz.b64"
PACKAGED_DATABASE_ARCHIVE_PATTERN = f"{PACKAGED_DATABASE_ARCHIVE.name}.part-*"
PACKAGED_DETAIL_DATABASE = PACKAGED_DATA / "math_assessment_catalog_detail.sqlite"
PACKAGED_DETAIL_DATABASE_GZIP = PACKAGED_DATA / "math_assessment_catalog_detail.sqlite.gz"
PACKAGED_DETAIL_DATABASE_GZIP_PATTERN = f"{PACKAGED_DETAIL_DATABASE_GZIP.name}.part-*"
PACKAGED_RELEASE_MANIFEST = PACKAGED_DATA / "release-manifest.json"
DEFAULT_OFFICIAL_SOURCE_REGISTRY = (
    PROJECT_ROOT / "data" / "publish" / "official_math_source_registry.json"
)
PACKAGED_OFFICIAL_SOURCE_REGISTRY = PACKAGED_DATA / "official_math_source_registry.json"


def materialized_packaged_database(*, detail: bool = False) -> Path:
    packaged_database = PACKAGED_DETAIL_DATABASE if detail else PACKAGED_DATABASE
    packaged_database_gzip = (
        PACKAGED_DETAIL_DATABASE_GZIP if detail else PACKAGED_DATABASE_GZIP
    )
    packaged_database_gzip_pattern = (
        PACKAGED_DETAIL_DATABASE_GZIP_PATTERN if detail else PACKAGED_DATABASE_GZIP_PATTERN
    )
    packaged_database_archive = PACKAGED_DATABASE_ARCHIVE if not detail else None
    packaged_database_archive_pattern = (
        PACKAGED_DATABASE_ARCHIVE_PATTERN if not detail else ""
    )
    if packaged_database.is_file():
        return packaged_database
    gzip_parts = (
        [packaged_database_gzip]
        if packaged_database_gzip.is_file()
        else sorted(PACKAGED_DATA.glob(packaged_database_gzip_pattern))
    )
    if packaged_database_archive and packaged_database_archive.is_file():
        legacy_archive_parts = [packaged_database_archive]
    elif packaged_database_archive_pattern:
        legacy_archive_parts = sorted(PACKAGED_DATA.glob(packaged_database_archive_pattern))
    else:
        legacy_archive_parts = []
    if not gzip_parts and not legacy_archive_parts:
        return packaged_database

    # A Vercel instance may retain /tmp across deployments.  Tie the materialized
    # filename to the packaged database checksum so a new schema cannot reuse an
    # older deployment's SQLite file.
    identity = "unknown"
    try:
        manifest = json.loads(PACKAGED_RELEASE_MANIFEST.read_text(encoding="utf-8"))
        files = manifest.get("files", []) if isinstance(manifest, dict) else []
        record = next(
            (
                item
                for item in files
                if isinstance(item, dict) and item.get("name") == packaged_database.name
            ),
            None,
        )
        value = str(record.get("sha256") or "") if isinstance(record, dict) else ""
        if len(value) >= 16 and all(char in "0123456789abcdef" for char in value.lower()):
            identity = value[:16]
    except (OSError, json.JSONDecodeError):
        pass
    if identity == "unknown":
        # Older packages may not describe the virtual uncompressed database.
        # Hash every archive part so different payloads cannot share /tmp state.
        digest = hashlib.sha256()
        for path in gzip_parts or legacy_archive_parts:
            digest.update(path.name.encode("utf-8"))
            digest.update(str(path.stat().st_size).encode("ascii"))
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        identity = digest.hexdigest()[:16]
    package_kind = "detail" if detail else "catalog"
    runtime_database = (
        Path(tempfile.gettempdir()) / f"suhaeng-math-{package_kind}-{identity}.sqlite"
    )
    if runtime_database.is_file():
        return runtime_database

    # Several API requests can reach one fresh serverless process together.
    # Only one thread may unpack a database; the others reuse the atomic result.
    materialization_lock = (
        _DETAIL_MATERIALIZATION_LOCK if detail else _CATALOG_MATERIALIZATION_LOCK
    )
    with materialization_lock:
        if runtime_database.is_file():
            return runtime_database

        if not gzip_parts:
            encoded = b"".join(part.read_bytes() for part in legacy_archive_parts)
            payload = base64.b64decode(encoded, validate=True)
        temporary = runtime_database.with_name(
            f"{runtime_database.name}.{os.getpid()}.{threading.get_ident()}.partial"
        )
        try:
            if gzip_parts:
                multipart = MultipartReader(gzip_parts)
                try:
                    with gzip.GzipFile(fileobj=multipart, mode="rb") as source:
                        with temporary.open("wb") as target:
                            shutil.copyfileobj(source, target, length=1024 * 1024)
                finally:
                    multipart.close()
            else:
                temporary.write_bytes(gzip.decompress(payload))
            with temporary.open("rb") as stream:
                if stream.read(16) != b"SQLite format 3\x00":
                    raise RuntimeError("packaged catalog archive is not a SQLite database")
            temporary.replace(runtime_database)
        finally:
            temporary.unlink(missing_ok=True)
    return runtime_database


def catalog_database_path() -> Path:
    configured = os.environ.get("MATH_ASSESSMENT_PUBLISH_DB", "").strip()
    if not configured:
        return (
            DEFAULT_DETAIL_DATABASE
            if DEFAULT_DETAIL_DATABASE.is_file()
            else DEFAULT_DATABASE
            if DEFAULT_DATABASE.is_file()
            else materialized_packaged_database(detail=False)
        )
    path = Path(configured)
    return path if path.is_absolute() else PROJECT_ROOT / path


def detail_catalog_database_path() -> Path:
    configured = os.environ.get("MATH_ASSESSMENT_DETAIL_DB", "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else PROJECT_ROOT / path
    if DEFAULT_DETAIL_DATABASE.is_file():
        return DEFAULT_DETAIL_DATABASE
    return materialized_packaged_database(detail=True)


def official_source_registry_path() -> Path:
    configured = os.environ.get("MATH_ASSESSMENT_OFFICIAL_SOURCE_REGISTRY", "").strip()
    if not configured:
        return (
            DEFAULT_OFFICIAL_SOURCE_REGISTRY
            if DEFAULT_OFFICIAL_SOURCE_REGISTRY.is_file()
            else PACKAGED_OFFICIAL_SOURCE_REGISTRY
        )
    path = Path(configured)
    return path if path.is_absolute() else PROJECT_ROOT / path

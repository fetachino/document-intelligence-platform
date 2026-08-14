import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

import boto3
from botocore.config import Config

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".docx"}
_SAFE_FILENAME_CHARACTER = re.compile(r"[^A-Za-z0-9._-]+")
_SAFE_DOCUMENT_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class StorageError(RuntimeError):
    """Represent a storage failure without exposing provider exception details."""


class StorageConfigurationError(StorageError):
    """Represent invalid storage configuration."""


class StorageProvider(Protocol):
    """Store document bytes behind an opaque, application-generated object key."""

    async def save(self, object_key: str, content: bytes) -> None: ...

    async def read(self, object_key: str) -> bytes: ...

    async def delete(self, object_key: str) -> None: ...


@dataclass(frozen=True)
class StorageSettings:
    backend: str = "local"
    local_path: Path = Path("./uploads")
    bucket_name: str | None = None
    region: str | None = None
    endpoint_url: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None
    force_path_style: bool = False

    @classmethod
    def from_environment(cls) -> "StorageSettings":
        backend = os.getenv("STORAGE_BACKEND", "local").strip().lower()
        if backend not in {"local", "s3"}:
            raise StorageConfigurationError("unsupported_storage_backend")

        bucket_name = _optional_environment_value("S3_BUCKET_NAME")
        access_key_id = _optional_environment_value("S3_ACCESS_KEY_ID")
        secret_access_key = _optional_environment_value("S3_SECRET_ACCESS_KEY")
        if backend == "s3" and not bucket_name:
            raise StorageConfigurationError("s3_bucket_required")
        if bool(access_key_id) != bool(secret_access_key):
            raise StorageConfigurationError("incomplete_s3_credentials")

        return cls(
            backend=backend,
            local_path=Path(os.getenv("STORAGE_PATH", "./uploads")),
            bucket_name=bucket_name,
            region=_optional_environment_value("S3_REGION"),
            endpoint_url=_optional_environment_value("S3_ENDPOINT_URL"),
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            force_path_style=_environment_flag("S3_FORCE_PATH_STYLE"),
        )


class LocalStorageProvider:
    """Persist objects below a configured local root for development."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def save(self, object_key: str, content: bytes) -> None:
        destination = self._path_for_new_key(object_key)

        def write() -> None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(f".{destination.name}.part")
            try:
                temporary.write_bytes(content)
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)

        try:
            await asyncio.to_thread(write)
        except OSError:
            raise StorageError("storage_write_failed") from None

    async def read(self, object_key: str) -> bytes:
        path = self._path_for_read(object_key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except OSError:
            raise StorageError("storage_read_failed") from None

    async def delete(self, object_key: str) -> None:
        path = self._path_for_read(object_key)
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError:
            raise StorageError("storage_delete_failed") from None

    def _path_for_new_key(self, object_key: str) -> Path:
        _validate_object_key(object_key)
        destination = (self._root / Path(*PurePosixPath(object_key).parts)).resolve()
        if not destination.is_relative_to(self._root):
            raise StorageError("invalid_object_key")
        return destination

    def _path_for_read(self, object_key: str) -> Path:
        legacy_path = Path(object_key)
        if legacy_path.is_absolute():
            # Existing databases may contain absolute local paths from earlier milestones.
            return legacy_path
        return self._path_for_new_key(object_key)


class S3StorageProvider:
    """Store private objects through an S3-compatible client."""

    def __init__(self, bucket_name: str, client: Any) -> None:
        if not bucket_name:
            raise StorageConfigurationError("s3_bucket_required")
        self._bucket_name = bucket_name
        self._client = client

    async def save(self, object_key: str, content: bytes) -> None:
        _validate_object_key(object_key)
        await self._call(
            "put_object", Bucket=self._bucket_name, Key=object_key, Body=content
        )

    async def read(self, object_key: str) -> bytes:
        _validate_object_key(object_key)
        response = await self._call(
            "get_object", Bucket=self._bucket_name, Key=object_key
        )
        try:
            return await asyncio.to_thread(response["Body"].read)
        except Exception:
            raise StorageError("storage_read_failed") from None

    async def delete(self, object_key: str) -> None:
        _validate_object_key(object_key)
        await self._call("delete_object", Bucket=self._bucket_name, Key=object_key)

    async def _call(self, operation: str, **kwargs: Any) -> Any:
        try:
            method = getattr(self._client, operation)
            return await asyncio.to_thread(method, **kwargs)
        except Exception:
            raise StorageError(f"storage_{operation}_failed") from None


def get_storage_provider() -> StorageProvider:
    """Build the configured provider without caching environment credentials."""

    settings = StorageSettings.from_environment()
    if settings.backend == "local":
        return LocalStorageProvider(settings.local_path)

    client_options: dict[str, Any] = {
        "config": Config(
            connect_timeout=5,
            read_timeout=30,
            retries={"max_attempts": 3, "mode": "standard"},
            s3={
                "addressing_style": "path"
                if settings.force_path_style
                else "auto"
            },
        )
    }
    if settings.region:
        client_options["region_name"] = settings.region
    if settings.endpoint_url:
        client_options["endpoint_url"] = settings.endpoint_url
    if settings.access_key_id and settings.secret_access_key:
        client_options["aws_access_key_id"] = settings.access_key_id
        client_options["aws_secret_access_key"] = settings.secret_access_key
    client = boto3.client("s3", **client_options)
    return S3StorageProvider(settings.bucket_name or "", client)


def build_document_object_key(document_id: str, filename: str) -> str:
    """Build a stable key owned by one internally generated document identifier."""

    if not _SAFE_DOCUMENT_ID.fullmatch(document_id):
        raise StorageError("invalid_document_id")
    basename = Path(filename.replace("\\", "/")).name
    safe_filename = _SAFE_FILENAME_CHARACTER.sub("_", basename).strip("._")
    if not safe_filename:
        safe_filename = "document"
    object_key = f"documents/{document_id}/{safe_filename}"
    _validate_object_key(object_key)
    return object_key


def validate_file_size(content: bytes) -> int:
    max_upload = int(os.getenv("MAX_UPLOAD_SIZE_BYTES", str(20 * 1024 * 1024)))
    if len(content) > max_upload:
        raise ValueError("file-too-large")
    return len(content)


def is_allowed_extension(filename: str) -> bool:
    extension = Path(filename).suffix.lower()
    if not extension:
        return True
    return extension in ALLOWED_EXTENSIONS


def _validate_object_key(object_key: str) -> None:
    path = PurePosixPath(object_key)
    if (
        not object_key
        or object_key.startswith("/")
        or "\\" in object_key
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise StorageError("invalid_object_key")


def _optional_environment_value(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _environment_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}

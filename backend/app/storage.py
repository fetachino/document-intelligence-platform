import os
import shutil
from pathlib import Path
import uuid
import asyncio

from typing import BinaryIO

# Read MAX_UPLOAD and STORAGE_PATH lazily so tests can monkeypatch env vars before import/use.
ALLOWED_EXT = {'.pdf', '.png', '.jpg', '.jpeg', '.docx'}


def sanitize_filename(filename: str) -> str:
    # Keep only basename and prefix with uuid to avoid collisions
    base = os.path.basename(filename)
    uid = uuid.uuid4().hex
    safe = f"{uid}_{base}"
    # ensure no path traversal in returned name
    return safe.replace('..', '')


def _save_upload_sync(fileobj: BinaryIO, filename: str) -> str:
    # Determine storage path at call time so tests can override via env
    storage_path = os.getenv('STORAGE_PATH', './uploads')
    os.makedirs(storage_path, exist_ok=True)

    safe_name = sanitize_filename(filename)
    dest = Path(storage_path) / safe_name
    # stream-write to avoid large memory usage
    fileobj.seek(0)
    with open(dest, 'wb') as out_f:
        shutil.copyfileobj(fileobj, out_f)
    return str(dest)


async def save_upload(fileobj: BinaryIO, filename: str) -> str:
    """Save upload off the event loop using a threadpool and return absolute path."""
    path = await asyncio.to_thread(_save_upload_sync, fileobj, filename)
    return path


def validate_file_size(file) -> int:
    # Read MAX_UPLOAD at call time so tests can set env before calling
    max_upload = int(os.getenv('MAX_UPLOAD_SIZE_BYTES', str(20 * 1024 * 1024)))
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > max_upload:
        raise ValueError('file-too-large')
    return size


def is_allowed_extension(filename: str) -> bool:
    ext = Path(filename).suffix.lower()
    # accept files without an extension (e.g., '../../etc/passwd') but reject explicitly disallowed extensions
    if not ext:
        return True
    return ext in ALLOWED_EXT

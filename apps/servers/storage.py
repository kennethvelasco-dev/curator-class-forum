"""Private storage and deletion services for CoR documents."""

import logging
import os
import stat
import tempfile
import uuid
from enum import Enum
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation
from django.core.files.storage import FileSystemStorage


logger = logging.getLogger(__name__)


class CorDeletionError(Exception):
    """Raised when a CoR file could not be confirmed absent from storage."""


class CorDeletionResult(Enum):
    DELETED = "deleted"
    ALREADY_ABSENT = "already_absent"


def _paths_overlap(first, second):
    first = Path(first).resolve(strict=False)
    second = Path(second).resolve(strict=False)
    if os.name == "nt":
        if os.path.normcase(first.anchor) != os.path.normcase(second.anchor):
            return False
    elif first.anchor != second.anchor:
        return False

    first_parts = first.parts[1:]
    second_parts = second.parts[1:]
    common_length = min(len(first_parts), len(second_parts))
    for index in range(common_length):
        first_part = first_parts[index]
        second_part = second_parts[index]
        if first_part == second_part:
            continue
        if first_part.casefold() != second_part.casefold():
            return False

        parent = Path(first.anchor).joinpath(*first_parts[:index])
        try:
            case_sensitive = _filesystem_is_case_sensitive(parent)
        except OSError as error:
            raise ImproperlyConfigured(
                "Unable to determine filesystem case sensitivity for private "
                "CoR storage path checks."
            ) from error
        if case_sensitive:
            return False

    return True


def _filesystem_is_case_sensitive(path):
    directory = Path(path)
    while True:
        try:
            mode = directory.stat().st_mode
        except FileNotFoundError:
            parent = directory.parent
            if parent == directory:
                raise OSError("No existing ancestor is available for probing.")
            directory = parent
            continue
        if stat.S_ISDIR(mode):
            break
        parent = directory.parent
        if parent == directory:
            raise OSError("No existing directory is available for probing.")
        directory = parent

    with os.scandir(directory) as entries:
        for entry in entries:
            alternative_name = entry.name.swapcase()
            if alternative_name == entry.name:
                continue
            alternative_path = directory / alternative_name
            try:
                alternative_stat = os.lstat(alternative_path)
            except FileNotFoundError:
                return True
            entry_stat = os.lstat(entry.path)
            return (entry_stat.st_dev, entry_stat.st_ino) != (
                alternative_stat.st_dev,
                alternative_stat.st_ino,
            )

    descriptor, probe_name = tempfile.mkstemp(
        prefix=".cor-case-sensitivity-",
        dir=directory,
    )
    os.close(descriptor)
    probe_path = Path(probe_name)
    alternative_path = probe_path.with_name(probe_path.name.swapcase())
    try:
        try:
            alternative_stat = os.lstat(alternative_path)
        except FileNotFoundError:
            return True
        probe_stat = os.lstat(probe_path)
        return (probe_stat.st_dev, probe_stat.st_ino) != (
            alternative_stat.st_dev,
            alternative_stat.st_ino,
        )
    finally:
        os.unlink(probe_path)


def _filesystem_path_exists(storage, name):
    try:
        os.lstat(storage.path(name))
    except FileNotFoundError:
        return False
    return True


class PrivateCorStorage(FileSystemStorage):
    """Filesystem storage that cannot create public URLs for CoR files."""

    def __init__(self, location=None, **kwargs):
        location = location or settings.PRIVATE_COR_STORAGE_ROOT
        location = Path(location).resolve()
        kwargs["directory_permissions_mode"] = 0o700
        kwargs["file_permissions_mode"] = 0o600

        public_roots = [("BASE_DIR", settings.BASE_DIR)]
        for setting_name in ("MEDIA_ROOT", "STATIC_ROOT"):
            root = getattr(settings, setting_name, None)
            if root:
                public_roots.append((setting_name, root))

        for entry in getattr(settings, "STATICFILES_DIRS", ()):
            root = entry[1] if isinstance(entry, tuple) else entry
            public_roots.append(("STATICFILES_DIRS", root))

        for setting_name, public_root in public_roots:
            if _paths_overlap(location, public_root):
                raise ImproperlyConfigured(
                    "PRIVATE_COR_STORAGE_ROOT must not overlap "
                    f"{setting_name}."
                )

        kwargs["base_url"] = ""
        super().__init__(location=location, **kwargs)

    def get_available_name(self, name, max_length=None):
        extension = Path(name).suffix
        unique_name = f"{uuid.uuid4().hex}{extension}"
        if max_length is not None and len(unique_name) > max_length:
            raise SuspiciousFileOperation(
                "Storage cannot create a UUID filename within the configured "
                "maximum length."
            )
        return unique_name

    def exists(self, name):
        return _filesystem_path_exists(self, name)

    def url(self, name):
        raise ValueError("Private CoR files do not have public URLs.")


def get_cor_storage():
    """Return a fresh private CoR storage backend using current settings."""
    return PrivateCorStorage()


def delete_cor(file_name, *, storage=None):
    """Delete a CoR file, confirming absence before reporting success.

    A failed attempt raises ``CorDeletionError`` and does not change any
    database reference. The caller can retain the filename and retry later.
    """
    if not file_name:
        return CorDeletionResult.ALREADY_ABSENT

    if storage is None:
        storage = get_cor_storage()

    operation = "checking file existence"
    try:
        if not _storage_file_exists(storage, file_name):
            return CorDeletionResult.ALREADY_ABSENT

        operation = "deleting the file"
        try:
            storage.delete(file_name)
        except FileNotFoundError:
            operation = "verifying file absence"
            if not _storage_file_exists(storage, file_name):
                return CorDeletionResult.ALREADY_ABSENT
            raise

        operation = "verifying file absence"
        if _storage_file_exists(storage, file_name):
            raise OSError("Storage still reports the file as present.")
    except Exception as error:
        logger.error(
            "CoR cleanup failed while %s using %s (exception type %s).",
            operation,
            type(storage).__name__,
            type(error).__name__,
        )
        raise CorDeletionError(
            "CoR cleanup could not be verified; retain the file reference "
            "and retry."
        ) from error

    return CorDeletionResult.DELETED


def _storage_file_exists(storage, name):
    if isinstance(storage, FileSystemStorage):
        return _filesystem_path_exists(storage, name)
    return storage.exists(name)

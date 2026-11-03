"""Private storage and deletion services for CoR documents."""

import logging
from enum import Enum
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage


logger = logging.getLogger(__name__)


class CorDeletionError(Exception):
    """Raised when a CoR file could not be confirmed absent from storage."""


class CorDeletionResult(Enum):
    DELETED = "deleted"
    ALREADY_ABSENT = "already_absent"


def _paths_overlap(first, second):
    first = Path(first).resolve()
    second = Path(second).resolve()
    return first == second or first in second.parents or second in first.parents


class PrivateCorStorage(FileSystemStorage):
    """Filesystem storage that cannot create public URLs for CoR files."""

    def __init__(self, location=None, **kwargs):
        location = location or settings.PRIVATE_COR_STORAGE_ROOT
        location = Path(location).resolve()

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
        if not storage.exists(file_name):
            return CorDeletionResult.ALREADY_ABSENT

        operation = "deleting the file"
        storage.delete(file_name)

        operation = "verifying file absence"
        if storage.exists(file_name):
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
        ) from None

    return CorDeletionResult.DELETED

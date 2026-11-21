"""Canonical subject-code contract for join requests and memberships.

SUBJECT_CODE_MAX_LENGTH and canonicalize_subject_code are the single source of
truth for subject-code normalization and validation across forms, services, and
future channel subject access.

Rules (must remain stable):
- Reject non-string inputs.
- Reject non-printable characters (including control characters) in the raw input
  before whitespace normalization, so tabs, newlines, carriage returns, and
  zero-width spaces are never silently collapsed into spaces.
- Strip leading and trailing whitespace.
- Collapse internal whitespace into a single ASCII space.
- Preserve capitalization of the remaining characters.
- Reject empty results after normalization.
- Reject values longer than SUBJECT_CODE_MAX_LENGTH after normalization.
- Reject reserved legacy-channel- placeholder identifiers.
"""

from __future__ import annotations

SUBJECT_CODE_MAX_LENGTH = 64
SUBJECT_CODE_NORMALIZED_MAX_LENGTH = 192
LEGACY_SUBJECT_CODE_PREFIX = "legacy-channel-"


class SubjectCodeError(ValueError):
    """Raised when a subject code fails the canonical contract."""


def is_legacy_subject_code(code) -> bool:
    """Return True if code is a reserved legacy placeholder identifier (case-insensitive)."""
    if not isinstance(code, str):
        return False
    return code.casefold().startswith(LEGACY_SUBJECT_CODE_PREFIX.casefold())


def canonicalize_subject_code(raw) -> str:
    """Normalize and validate a single subject code.

    Returns the canonical string on success.
    Raises SubjectCodeError (a ValueError subclass) on any contract violation.

    Non-printable characters are rejected in the raw input *before* any
    whitespace normalization, so tabs, newlines, carriage returns, control
    characters, and zero-width spaces are never silently collapsed into spaces.
    """
    if not isinstance(raw, str):
        raise SubjectCodeError("Subject code must be a string.")

    # Reject non-printable characters in the raw input before whitespace
    # normalization. Space (U+0020) is printable; tabs, newlines, carriage
    # returns, control characters, and zero-width spaces are not.
    if any(not ch.isprintable() for ch in raw):
        raise SubjectCodeError(
            "Subject code may not contain non-printable characters."
        )

    # Strip ends, then collapse any run of whitespace to a single ASCII space.
    normalized = " ".join(raw.split())

    if not normalized:
        raise SubjectCodeError("Subject code cannot be empty.")

    if len(normalized) > SUBJECT_CODE_MAX_LENGTH:
        raise SubjectCodeError(
            f"Subject code must be {SUBJECT_CODE_MAX_LENGTH} characters or fewer."
        )

    if is_legacy_subject_code(normalized):
        raise SubjectCodeError(
            f"Subject code may not use the reserved '{LEGACY_SUBJECT_CODE_PREFIX}' prefix."
        )

    return normalized

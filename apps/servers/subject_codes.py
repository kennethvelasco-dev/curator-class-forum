"""Canonical subject-code contract for join requests and memberships.

SUBJECT_CODE_MAX_LENGTH and canonicalize_subject_code are the single source of
truth for subject-code normalization and validation across forms, services, and
future channel subject access.

Rules (must remain stable):
- Reject non-string inputs.
- Strip leading and trailing whitespace.
- Collapse internal whitespace into a single ASCII space.
- Preserve capitalization of the remaining characters.
- Reject empty results after normalization.
- Reject values longer than SUBJECT_CODE_MAX_LENGTH after normalization.
- Reject any non-printable character (including control characters).
"""

from __future__ import annotations

SUBJECT_CODE_MAX_LENGTH = 64


class SubjectCodeError(ValueError):
    """Raised when a subject code fails the canonical contract."""


def canonicalize_subject_code(raw) -> str:
    """Normalize and validate a single subject code.

    Returns the canonical string on success.
    Raises SubjectCodeError (a ValueError subclass) on any contract violation.
    """
    if not isinstance(raw, str):
        raise SubjectCodeError("Subject code must be a string.")

    # Strip ends, then collapse any run of whitespace to a single ASCII space.
    normalized = " ".join(raw.split())

    if not normalized:
        raise SubjectCodeError("Subject code cannot be empty.")

    if len(normalized) > SUBJECT_CODE_MAX_LENGTH:
        raise SubjectCodeError(
            f"Subject code must be {SUBJECT_CODE_MAX_LENGTH} characters or fewer."
        )

    # Reject non-printable characters (Unicode category "C" and similar).
    # isprintable() returns False for control characters, surrogates, etc.
    # Space (U+0020) is printable; other whitespace has already been collapsed.
    if any(not ch.isprintable() for ch in normalized):
        raise SubjectCodeError(
            "Subject code may not contain non-printable characters."
        )

    return normalized

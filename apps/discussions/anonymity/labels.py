"""Anonymous label format ``CSS-#####`` and generation.

Pure functions only: no database access, so the format contract can be tested
without the discussion models.
"""

import re
import secrets

LABEL_PREFIX = "CSS-"
LABEL_DIGITS = 5
LABEL_SPACE = 10**LABEL_DIGITS  # 100,000 possible labels per thread

_LABEL_PATTERN = re.compile(r"CSS-[0-9]{5}")


def format_label(number):
    """Return ``CSS-#####`` for an integer in ``range(LABEL_SPACE)``."""
    if isinstance(number, bool) or not isinstance(number, int):
        raise ValueError("Label number must be an integer.")
    if not 0 <= number < LABEL_SPACE:
        raise ValueError("Label number is outside the label space.")
    return f"{LABEL_PREFIX}{number:0{LABEL_DIGITS}d}"


def generate_label(randbelow=secrets.randbelow):
    """Return a new random label. ``randbelow`` is injectable for tests."""
    return format_label(randbelow(LABEL_SPACE))


def is_valid_label(value):
    """Return True only for a string that is exactly ``CSS-`` plus 5 digits."""
    return isinstance(value, str) and _LABEL_PATTERN.fullmatch(value) is not None

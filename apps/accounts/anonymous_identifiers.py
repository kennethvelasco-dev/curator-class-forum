import secrets


ANONYMOUS_IDENTIFIER_PREFIX = "CSS-"
ANONYMOUS_IDENTIFIER_ATTEMPTS = 32


def generate_anonymous_identifier():
    return f"{ANONYMOUS_IDENTIFIER_PREFIX}{secrets.randbelow(100_000):05d}"

"""Test helper: fail when real identity data appears in rendered output."""

STRUCTURAL_MARKERS = (
    "data-author",
    "data-user",
    "author_id",
    "author_pk",
    "user_id",
    "authorid",
    "userid",
)


def _as_text(content):
    if hasattr(content, "content"):  # HttpResponse
        content = content.content
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    return str(content)


def assert_no_identity_leak(testcase, content, user, *, extra_tokens=()):
    """Assert that ``content`` exposes nothing that identifies ``user``.

    Checks full name, e-mail, e-mail local part, the primary key (when it has
    at least 4 digits, so it cannot match by accident; create the test user
    with a distinctive pk), and structural markers such as ``data-author``.
    """
    text = _as_text(content)
    lowered = text.lower()
    tokens = [user.full_name, user.email, user.email.split("@")[0], *extra_tokens]
    if len(str(user.pk)) >= 4:
        tokens.append(str(user.pk))
    for token in tokens:
        if token:
            testcase.assertNotIn(
                str(token).lower(), lowered, f"identity token leaked: {token!r}"
            )
    for marker in STRUCTURAL_MARKERS:
        testcase.assertNotIn(marker, lowered, f"identity marker leaked: {marker!r}")

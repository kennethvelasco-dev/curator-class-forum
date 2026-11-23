"""Display identity for a post and the Author-badge rule.

Templates must render a post's author only through ``PostIdentity``. The
dataclass deliberately has no field that can hold a user object, e-mail, or id.
"""

from dataclasses import dataclass

from apps.discussions.anonymity.labels import is_valid_label

ANONYMOUS_FALLBACK_NAME = "Anonymous"
NAMED_FALLBACK_NAME = "Member"

# Author-badge policy: a post gets the badge only when its author is the thread
# starter and its anonymity mode matches the thread's mode. Suppressing the
# badge in mixed mode prevents linking an anonymous label to a named identity,
# or revealing who wrote an anonymous thread.
SUPPRESS_AUTHOR_BADGE_IN_MIXED_MODE = True


@dataclass(frozen=True)
class PostIdentity:
    """Everything a template may show about who wrote a post."""

    display_name: str
    is_anonymous: bool
    show_author_badge: bool


def author_badge_applies(
    *,
    post_author_id,
    thread_author_id,
    post_is_anonymous,
    thread_is_anonymous,
    suppress_in_mixed_mode=None,
):
    """Return whether a post gets the ``Author`` badge.

    Decided from author ids, never from displayed names or labels.
    """
    if post_author_id is None or thread_author_id is None:
        return False
    if post_author_id != thread_author_id:
        return False
    if suppress_in_mixed_mode is None:
        suppress_in_mixed_mode = SUPPRESS_AUTHOR_BADGE_IN_MIXED_MODE
    if suppress_in_mixed_mode and bool(post_is_anonymous) != bool(thread_is_anonymous):
        return False
    return True


def build_identity(*, is_anonymous, alias_label, named_display_name, show_author_badge):
    """Build the display identity from the persisted ``is_anonymous`` value.

    An anonymous post never falls back to the real name: if its alias is
    missing or malformed the literal text "Anonymous" is shown.
    """
    if is_anonymous:
        name = alias_label if is_valid_label(alias_label) else ANONYMOUS_FALLBACK_NAME
    else:
        name = (named_display_name or "").strip() or NAMED_FALLBACK_NAME
    return PostIdentity(
        display_name=name,
        is_anonymous=bool(is_anonymous),
        show_author_badge=bool(show_author_badge),
    )

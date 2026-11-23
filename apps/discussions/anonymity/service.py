"""Alias allocation and display-identity resolution (Issue #36).

Requires the Issue #31 ``Thread`` and ``Reply`` models.

Call ``ensure_alias_for_post`` inside the same ``transaction.atomic()`` that
saves an anonymous Thread or Reply. Rendering code uses ``resolve_identities``,
which only reads.
"""

import logging

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from apps.discussions.anonymity.identity import (
    author_badge_applies,
    build_identity,
)
from apps.discussions.anonymity.labels import LABEL_SPACE, generate_label
from apps.discussions.anonymity.models import ThreadAlias
from apps.discussions.models import Reply, Thread

logger = logging.getLogger(__name__)

MAX_ALLOCATION_ATTEMPTS = 20


class AliasAllocationError(Exception):
    """No free label could be allocated; the caller must roll back the post."""


def thread_of(post):
    """Return the thread context of a post: itself for a Thread, else its thread."""
    if isinstance(post, Thread):
        return post
    if isinstance(post, Reply):
        return post.thread
    raise TypeError("Expected a Thread or Reply.")


def get_or_create_alias(*, thread, user, label_factory=generate_label):
    """Return ``user``'s alias in ``thread``, creating it on first use.

    Stable: the same (thread, user) always yields the same row and label.
    Safe under concurrency: the thread row is locked (PostgreSQL), and the
    unique constraints are the backstop on every backend.
    """
    if thread is None or thread.pk is None:
        raise ValueError("A saved thread is required.")
    with transaction.atomic():
        if not Thread.objects.select_for_update().filter(pk=thread.pk).exists():
            raise ValueError("Thread does not exist.")

        existing = ThreadAlias.objects.filter(thread_id=thread.pk, user=user).first()
        if existing is not None:
            return existing

        if ThreadAlias.objects.filter(thread_id=thread.pk).count() >= LABEL_SPACE:
            raise AliasAllocationError("All labels for this thread are in use.")

        for _ in range(MAX_ALLOCATION_ATTEMPTS):
            label = label_factory()
            try:
                with transaction.atomic():  # savepoint: a failed insert stays isolated
                    return ThreadAlias.objects.create(
                        thread_id=thread.pk, user=user, label=label
                    )
            except IntegrityError:
                # A concurrent request may have created this user's alias.
                winner = ThreadAlias.objects.filter(
                    thread_id=thread.pk, user=user
                ).first()
                if winner is not None:
                    return winner
                # Only a label collision is retried; anything else is a real error.
                if ThreadAlias.objects.filter(
                    thread_id=thread.pk, label=label
                ).exists():
                    continue
                raise
        raise AliasAllocationError("Could not allocate a unique label.")


def ensure_alias_for_post(post, *, label_factory=generate_label):
    """Create the author's alias when ``post`` is anonymous; else do nothing."""
    if not post.is_anonymous:
        return None
    return get_or_create_alias(
        thread=thread_of(post),
        user=post.author,
        label_factory=label_factory,
    )


def _identity_for(post, thread, labels, names):
    """Build one PostIdentity. Shared by every resolver so there is one rule."""
    if post.is_anonymous and post.author_id not in labels:
        logger.error(
            "Anonymous %s has no alias; showing generic text.",
            type(post).__name__,
        )
    return build_identity(
        is_anonymous=post.is_anonymous,
        alias_label=labels.get(post.author_id),
        named_display_name=names.get(post.author_id),
        show_author_badge=author_badge_applies(
            post_author_id=post.author_id,
            thread_author_id=thread.author_id,
            post_is_anonymous=post.is_anonymous,
            thread_is_anonymous=thread.is_anonymous,
        ),
    )


def _full_names(user_ids):
    if not user_ids:
        return {}
    return dict(
        get_user_model()
        .objects.filter(pk__in=user_ids)
        .values_list("pk", "full_name")
    )


def resolve_identities(thread, posts):
    """Return one ``PostIdentity`` per post, in order. Read-only; two queries.

    Never touches ``post.author``: only ``author_id`` is used, so no user
    object reaches a template context.
    """
    posts = list(posts)
    for post in posts:
        if isinstance(post, Reply) and post.thread_id != thread.pk:
            raise ValueError("Reply does not belong to this thread.")
        if isinstance(post, Thread) and post.pk != thread.pk:
            raise ValueError("Thread does not match.")

    anonymous_ids = {p.author_id for p in posts if p.is_anonymous}
    named_ids = {p.author_id for p in posts if not p.is_anonymous}

    labels = {}
    if anonymous_ids:
        labels = dict(
            ThreadAlias.objects.filter(
                thread_id=thread.pk, user_id__in=anonymous_ids
            ).values_list("user_id", "label")
        )
    names = _full_names(named_ids)
    return [_identity_for(post, thread, labels, names) for post in posts]


def resolve_thread_identities(threads):
    """Return one ``PostIdentity`` per thread, in order, for a thread list.

    Same rule as ``resolve_identities`` applied to many threads at once, so a
    list page costs two queries instead of two per thread.
    """
    threads = list(threads)
    anonymous_thread_ids = [t.pk for t in threads if t.is_anonymous]
    labels_by_thread = {}
    if anonymous_thread_ids:
        for thread_id, user_id, label in ThreadAlias.objects.filter(
            thread_id__in=anonymous_thread_ids
        ).values_list("thread_id", "user_id", "label"):
            labels_by_thread.setdefault(thread_id, {})[user_id] = label
    names = _full_names({t.author_id for t in threads if not t.is_anonymous})
    return [
        _identity_for(t, t, labels_by_thread.get(t.pk, {}), names) for t in threads
    ]

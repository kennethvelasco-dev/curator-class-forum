"""Persisted thread-scoped anonymous aliases (Issue #36).

Requires the Issue #31 ``Thread`` model. Thread and Reply are not modified:
the #31 contract has no label column, so labels live in this separate table.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q


class ThreadAlias(models.Model):
    """The ``CSS-#####`` label one user posts under in one thread."""

    thread = models.ForeignKey(
        "discussions.Thread",
        on_delete=models.CASCADE,
        related_name="aliases",
    )
    # PROTECT keeps the accountability link: a user with an alias cannot be
    # hard-deleted, matching Thread.author / Reply.author in Issue #31.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    label = models.CharField(max_length=9)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("thread", "user"),
                name="discussions_threadalias_unique_thread_user",
            ),
            models.UniqueConstraint(
                fields=("thread", "label"),
                name="discussions_threadalias_unique_thread_label",
            ),
            models.CheckConstraint(
                condition=Q(label__regex=r"^CSS-[0-9]{5}$"),
                name="discussions_threadalias_label_format",
            ),
        ]

    def __str__(self):
        # Never include the user: this string can reach logs and admin pages.
        return self.label

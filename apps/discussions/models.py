"""Models for class discussions."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def _ensure_author_can_access_channel(author, channel):
    from apps.servers.services.access import user_can_access_channel

    if not user_can_access_channel(author, channel):
        raise ValidationError("The author does not have access to this channel.")


class Thread(models.Model):
    channel = models.ForeignKey(
        "channels.Channel",
        on_delete=models.CASCADE,
        related_name="threads",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="threads",
    )
    title = models.CharField(max_length=255)
    body = models.TextField()
    is_anonymous = models.BooleanField(default=False)
    is_edited = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        _ensure_author_can_access_channel(self.author, self.channel)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class Reply(models.Model):
    thread = models.ForeignKey(
        Thread,
        on_delete=models.CASCADE,
        related_name="replies",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="discussion_replies",
    )
    body = models.TextField()
    is_anonymous = models.BooleanField(default=False)
    is_edited = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        _ensure_author_can_access_channel(self.author, self.thread.channel)
        super().save(*args, **kwargs)

    def __str__(self):
        if self.is_anonymous:
            return f"Anonymous reply on {self.thread}"
        return f"Reply by {self.author} on {self.thread}"
from apps.discussions.anonymity.models import ThreadAlias  # noqa: E402,F401  (Issue #36)

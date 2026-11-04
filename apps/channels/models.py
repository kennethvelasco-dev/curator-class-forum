"""Models for channels within class servers."""

from django.db import models


class ChannelType(models.TextChoices):
    ANNOUNCEMENTS = "announcements", "Announcements"
    CALENDAR = "calendar", "Calendar"
    RULES = "rules", "Rules"
    SUBJECT = "subject", "Subject"


class Channel(models.Model):
    server = models.ForeignKey(
        "servers.Server",
        on_delete=models.CASCADE,
        related_name="channels",
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    channel_type = models.CharField(max_length=20, choices=ChannelType)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("server", "slug"),
                name="channels_channel_unique_server_slug",
            ),
            models.CheckConstraint(
                condition=models.Q(channel_type__in=ChannelType.values),
                name="channels_channel_type_valid",
            ),
            models.UniqueConstraint(
                fields=("server", "channel_type"),
                condition=models.Q(
                    channel_type__in=(
                        ChannelType.ANNOUNCEMENTS,
                        ChannelType.CALENDAR,
                        ChannelType.RULES,
                    )
                ),
                name="channels_channel_unique_default_type",
            ),
        ]

    def __str__(self):
        return self.name

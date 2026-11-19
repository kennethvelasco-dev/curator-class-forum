"""Models for channels within class servers."""

from django.db import models

from apps.servers.subject_codes import (
    SUBJECT_CODE_MAX_LENGTH,
    SUBJECT_CODE_NORMALIZED_MAX_LENGTH,
    SubjectCodeError,
    canonicalize_subject_code,
)


class ChannelType(models.TextChoices):
    ANNOUNCEMENTS = "announcements", "Announcements"
    CALENDAR = "calendar", "Calendar"
    RULES = "rules", "Rules"
    SUBJECT = "subject", "Subject"


DEFAULT_CHANNEL_TYPES = (
    ChannelType.ANNOUNCEMENTS,
    ChannelType.CALENDAR,
    ChannelType.RULES,
)


class Channel(models.Model):
    server = models.ForeignKey(
        "servers.Server",
        on_delete=models.CASCADE,
        related_name="channels",
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    channel_type = models.CharField(max_length=20, choices=ChannelType)
    subject_code = models.CharField(
        max_length=SUBJECT_CODE_MAX_LENGTH,
        null=True,
        blank=True,
    )
    subject_code_normalized = models.CharField(
        max_length=SUBJECT_CODE_NORMALIZED_MAX_LENGTH,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Populate the normalized comparison key from subject_code using the
        # same canonicalization contract as the enrollment service, followed
        # by Unicode case folding for consistent case-insensitive matching.
        update_fields = kwargs.get("update_fields")
        should_update_normalized = (
            update_fields is None
            or "subject_code" in update_fields
            or "subject_code_normalized" in update_fields
        )

        if should_update_normalized:
            if self.subject_code is not None:
                try:
                    self.subject_code_normalized = (
                        canonicalize_subject_code(self.subject_code).casefold()
                    )
                except SubjectCodeError:
                    # Invalid codes cannot match any approved enrollment.
                    self.subject_code_normalized = None
            else:
                self.subject_code_normalized = None

            if update_fields is not None and "subject_code" in update_fields:
                updated = list(update_fields)
                if "subject_code_normalized" not in updated:
                    updated.append("subject_code_normalized")
                kwargs["update_fields"] = updated

        super().save(*args, **kwargs)

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
            # SUBJECT channels require a non-null, non-empty subject_code.
            models.CheckConstraint(
                condition=~(
                    models.Q(channel_type=ChannelType.SUBJECT)
                    & (
                        models.Q(subject_code__isnull=True)
                        | models.Q(subject_code="")
                    )
                ),
                name="channels_channel_subject_code_required_for_subject",
            ),
            # Default channels must not carry a subject_code.
            models.CheckConstraint(
                condition=(
                    ~models.Q(channel_type__in=DEFAULT_CHANNEL_TYPES)
                    | models.Q(subject_code__isnull=True)
                ),
                name="channels_channel_subject_code_null_for_default",
            ),
            # Case-insensitive uniqueness of subject_code within a server for
            # SUBJECT channels. The check constraints guarantee SUBJECT channels
            # always carry a non-null, non-empty subject_code, so NULL handling
            # is not needed here. Slugs remain URL identifiers only and are not
            # used for subject matching.
            models.UniqueConstraint(
                "subject_code_normalized",
                "server",
                condition=models.Q(channel_type=ChannelType.SUBJECT),
                name="channels_channel_unique_server_subject_code_ci",
            ),
        ]

    def __str__(self):
        return self.name

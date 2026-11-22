
"""Models for channels within class servers."""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Trim
from django.db.models.lookups import Exact

from apps.servers.subject_codes import (
    SUBJECT_CODE_MAX_LENGTH,
    SUBJECT_CODE_NORMALIZED_MAX_LENGTH,
    SubjectCodeError,
    canonicalize_subject_code,
    is_legacy_subject_code,
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
    slug = models.CharField(max_length=64)
    professor_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_default="",
    )
    professor_email = models.EmailField(
        max_length=254,
        blank=True,
        default="",
        db_default="",
    )
    office_hours = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_default="",
    )
    edit_version = models.PositiveIntegerField(default=1, db_default=1)
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

    def clean(self):
        super().clean()

        if self.channel_type == ChannelType.SUBJECT:
            if not self.subject_code or not self.subject_code.strip():
                raise ValidationError(
                    {
                        "subject_code": (
                            "Subject code cannot be empty for subject channels."
                        )
                    }
                )

            if not is_legacy_subject_code(self.subject_code):
                try:
                    canonical = canonicalize_subject_code(self.subject_code)

                    if self.subject_code != canonical:
                        raise ValidationError(
                            {
                                "subject_code": (
                                    "Subject code must be in canonical format "
                                    "(no leading, trailing, or repeated "
                                    "internal whitespace)."
                                )
                            }
                        )
                except SubjectCodeError as exc:
                    raise ValidationError(
                        {"subject_code": str(exc)}
                    ) from exc

        elif self.subject_code:
            raise ValidationError(
                {
                    "subject_code": (
                        "Default channels cannot carry a subject code."
                    )
                }
            )

    def save(self, *args, **kwargs):
        """Save the channel and maintain its normalized subject-code key."""
        update_fields = kwargs.get("update_fields")

        if update_fields is not None:
            update_fields = set(update_fields)
            kwargs["update_fields"] = update_fields

        if (
            update_fields is not None
            and "subject_code_normalized" in update_fields
            and "subject_code" not in update_fields
        ):
            raise ValueError(
                "Cannot update 'subject_code_normalized' without 'subject_code'."
            )

        should_update_normalized = (
            update_fields is None
            or "subject_code" in update_fields
            or "channel_type" in update_fields
        )

        if should_update_normalized:
            if self.channel_type == ChannelType.SUBJECT:
                if self.subject_code is None or not str(self.subject_code).strip():
                    raise SubjectCodeError(
                        "Subject code cannot be empty for SUBJECT channels."
                    )

                if is_legacy_subject_code(self.subject_code):
                    existing_legacy = (
                        self.pk is not None
                        and type(self).objects.filter(
                            pk=self.pk,
                            channel_type=ChannelType.SUBJECT,
                            subject_code=self.subject_code,
                        ).exists()
                    )

                    if not existing_legacy:
                        raise SubjectCodeError(
                            "New subject channels cannot use legacy placeholder codes."
                        )

                    self.subject_code_normalized = None

                else:
                    canonical = canonicalize_subject_code(self.subject_code)

                    if self.subject_code != canonical:
                        raise SubjectCodeError(
                            "Subject code must be canonical (no leading, "
                            "trailing, or repeated internal whitespace)."
                        )

                    self.subject_code_normalized = canonical.casefold()

            else:
                if self.subject_code is not None:
                    raise ValidationError(
                        {
                            "subject_code": (
                                "Default channels cannot carry a subject code."
                            )
                        }
                    )

                self.subject_code_normalized = None

            if update_fields is not None:
                if "subject_code" in update_fields or "channel_type" in update_fields:
                    if "subject_code_normalized" not in update_fields:
                        update_fields.add("subject_code_normalized")

        super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("server", "slug"),
                name="channels_channel_unique_server_slug",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    channel_type__in=(
                        ChannelType.ANNOUNCEMENTS,
                        ChannelType.CALENDAR,
                        ChannelType.RULES,
                        ChannelType.SUBJECT,
                    )
                ),
                name="channels_channel_type_valid",
            ),
            # Original constraint from channels.0002.
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
            # Stricter follow-up: also reject whitespace-only subject_code.
            models.CheckConstraint(
                condition=~(
                    models.Q(channel_type=ChannelType.SUBJECT)
                    & (
                        models.Q(subject_code__isnull=True)
                        | models.Q(subject_code="")
                        | models.Q(
                            Exact(
                                Trim(models.F("subject_code")),
                                models.Value(""),
                            )
                        )
                    )
                ),
                name="channels_channel_subject_code_required_for_subject_stricter",
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
            # Default channels must not carry a subject_code.
            models.CheckConstraint(
                condition=(
                    ~models.Q(channel_type__in=DEFAULT_CHANNEL_TYPES)
                    | models.Q(subject_code__isnull=True)
                ),
                name="channels_channel_subject_code_null_for_default",
            ),
            models.UniqueConstraint(
                "subject_code_normalized",
                "server",
                condition=models.Q(channel_type=ChannelType.SUBJECT),
                name="channels_channel_unique_server_subject_code_ci",
            ),
        ]

    def __str__(self):
        return self.name

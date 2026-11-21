# Issue #30 corrective migration: stricter SUBJECT check + unmap legacy keys.

from django.db import migrations, models
import django.db.models.functions.text
import django.db.models.lookups


LEGACY_SUBJECT_CODE_PREFIX = "legacy-channel-"


def _channel_columns(schema_editor):
    """Return column names for channels_channel using the migration's DB alias."""
    connection = schema_editor.connection
    try:
        with connection.cursor() as cursor:
            return {
                c.name
                for c in connection.introspection.get_table_description(
                    cursor, "channels_channel"
                )
            }
    except Exception:
        return set()


def unmap_legacy_channel_normalized_keys(apps, schema_editor):
    """Null out subject_code_normalized for reserved legacy placeholders.

    channels.0002 stored subject_code_normalized = 'legacy-channel-<pk>' for
    pre-existing SUBJECT rows. Those values must not remain matchable comparison
    keys. subject_code keeps the placeholder so the non-empty check still holds.
    """
    cols = _channel_columns(schema_editor)
    if "subject_code" not in cols or "subject_code_normalized" not in cols:
        return

    Channel = apps.get_model("channels", "Channel")
    db_alias = schema_editor.connection.alias
    prefix = LEGACY_SUBJECT_CODE_PREFIX.casefold()
    qs = Channel.objects.using(db_alias).filter(channel_type="subject")
    for channel in qs.iterator():
        code = channel.subject_code or ""
        if isinstance(code, str) and code.casefold().startswith(prefix):
            if channel.subject_code_normalized is not None:
                channel.subject_code_normalized = None
                channel.save(update_fields=["subject_code_normalized"], using=db_alias)


def restore_legacy_channel_normalized_keys(apps, schema_editor):
    """Reverse: restore normalized key from the legacy subject_code value."""
    cols = _channel_columns(schema_editor)
    if "subject_code" not in cols or "subject_code_normalized" not in cols:
        return

    Channel = apps.get_model("channels", "Channel")
    db_alias = schema_editor.connection.alias
    prefix = LEGACY_SUBJECT_CODE_PREFIX.casefold()
    qs = Channel.objects.using(db_alias).filter(channel_type="subject")
    for channel in qs.iterator():
        code = channel.subject_code or ""
        if isinstance(code, str) and code.casefold().startswith(prefix):
            channel.subject_code_normalized = code.casefold()
            channel.save(update_fields=["subject_code_normalized"], using=db_alias)


class Migration(migrations.Migration):

    dependencies = [
        ("channels", "0002_channel_subject_code_and_more"),
    ]

    operations = [
        # Add stricter check without removing the historical constraint name.
        # Remove+re-add of the old name caused reverse ProgrammingError in tests.
        migrations.AddConstraint(
            model_name="channel",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("channel_type", "subject"),
                    models.Q(
                        ("subject_code__isnull", True),
                        ("subject_code", ""),
                        django.db.models.lookups.Exact(
                            django.db.models.functions.text.Trim(
                                models.F("subject_code")
                            ),
                            models.Value(""),
                        ),
                        _connector="OR",
                    ),
                    _negated=True,
                ),
                name="channels_channel_subject_code_required_for_subject_stricter",
            ),
        ),
        migrations.RunPython(
            unmap_legacy_channel_normalized_keys,
            restore_legacy_channel_normalized_keys,
        ),
    ]

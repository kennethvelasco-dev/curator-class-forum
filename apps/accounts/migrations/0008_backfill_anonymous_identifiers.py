import secrets
from django.db import IntegrityError, migrations, models, transaction


ANONYMOUS_IDENTIFIER_ATTEMPTS = 32


def backfill_anonymous_identifiers(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    database = schema_editor.connection.alias
    users = User.objects.using(database)

    user_ids = list(
        users.filter(anonymous_id__isnull=True)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    for user_id in user_ids:
        for _ in range(ANONYMOUS_IDENTIFIER_ATTEMPTS):
            candidate = f"CSS-{secrets.randbelow(100_000):05d}"
            try:
                with transaction.atomic(using=database):
                    updated = users.filter(
                        pk=user_id,
                        anonymous_id__isnull=True,
                    ).update(anonymous_id=candidate)
            except IntegrityError:
                continue

            if updated:
                break
        else:
            raise RuntimeError(
                "Could not backfill a unique anonymous identifier for "
                f"account {user_id} after "
                f"{ANONYMOUS_IDENTIFIER_ATTEMPTS} attempts."
            )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_add_anonymous_identifier"),
    ]

    operations = [
        migrations.RunPython(
            backfill_anonymous_identifiers,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="user",
            name="anonymous_id",
            field=models.CharField(
                editable=False,
                max_length=9,
                unique=True,
            ),
        ),
    ]

from django.db import migrations, models


def backfill_blank_full_names(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    users = User.objects.using(schema_editor.connection.alias)

    for user in users.only("pk", "full_name").iterator():
        if not (user.full_name or "").strip():
            users.filter(pk=user.pk).update(full_name="Unknown User")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_pendingregistration"),
    ]

    operations = [
        migrations.RunPython(
            backfill_blank_full_names,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(full_name__regex=r"\S"),
                name="accounts_user_full_name_not_blank",
            ),
        ),
    ]

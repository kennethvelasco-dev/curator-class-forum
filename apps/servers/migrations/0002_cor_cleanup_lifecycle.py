from django.db import migrations, models
from django.db.models import Q


def backfill_cor_cleanup_status(apps, schema_editor):
    final_statuses = ("approved", "rejected")
    for model_name in ("ServerRequest", "JoinRequest"):
        request_model = apps.get_model("servers", model_name)
        request_model.objects.filter(status__in=final_statuses).filter(
            Q(cor_file__isnull=True) | Q(cor_file="")
        ).update(cor_cleanup_status="complete")
        request_model.objects.filter(
            status__in=final_statuses,
            cor_file__isnull=False,
        ).exclude(cor_file="").update(cor_cleanup_status="pending")


class Migration(migrations.Migration):
    dependencies = [
        ("servers", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="serverrequest",
            name="cor_cleanup_status",
            field=models.CharField(
                choices=[
                    ("not_required", "Not required"),
                    ("pending", "Pending"),
                    ("processing", "Processing"),
                    ("complete", "Complete"),
                ],
                default="not_required",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="serverrequest",
            name="cor_cleanup_attempts",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="serverrequest",
            name="cor_cleanup_last_attempt_at",
            field=models.DateTimeField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name="joinrequest",
            name="cor_cleanup_status",
            field=models.CharField(
                choices=[
                    ("not_required", "Not required"),
                    ("pending", "Pending"),
                    ("processing", "Processing"),
                    ("complete", "Complete"),
                ],
                default="not_required",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="joinrequest",
            name="cor_cleanup_attempts",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="joinrequest",
            name="cor_cleanup_last_attempt_at",
            field=models.DateTimeField(blank=True, default=None, null=True),
        ),
        migrations.RunPython(
            backfill_cor_cleanup_status,
            migrations.RunPython.noop,
        ),
    ]

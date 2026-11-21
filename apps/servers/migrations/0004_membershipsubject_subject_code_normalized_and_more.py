# Generated manually for Issue #30: FR-016 MembershipSubject normalized subject keys.

from django.db import migrations, models
from django.db.migrations.exceptions import BadMigrationError


class MigrationCollisionError(RuntimeError, BadMigrationError):
    """Raised when MembershipSubject normalization backfill encounters duplicate codes."""


SUBJECT_CODE_MAX_LENGTH = 64
LEGACY_SUBJECT_CODE_PREFIX = "legacy-channel-"


class SubjectCodeError(ValueError):
    """Raised when a subject code fails the canonical contract."""


def is_legacy_subject_code(code) -> bool:
    if not isinstance(code, str):
        return False
    return code.casefold().startswith(LEGACY_SUBJECT_CODE_PREFIX.casefold())


def _canonicalize_subject_code(raw) -> str:
    if not isinstance(raw, str):
        raise SubjectCodeError("Subject code must be a string.")

    if any(not ch.isprintable() for ch in raw):
        raise SubjectCodeError(
            "Subject code may not contain non-printable characters."
        )

    normalized = " ".join(raw.split())

    if not normalized:
        raise SubjectCodeError("Subject code cannot be empty.")

    if len(normalized) > SUBJECT_CODE_MAX_LENGTH:
        raise SubjectCodeError(
            f"Subject code must be {SUBJECT_CODE_MAX_LENGTH} characters or fewer."
        )

    if is_legacy_subject_code(normalized):
        raise SubjectCodeError(
            f"Subject code may not use the reserved '{LEGACY_SUBJECT_CODE_PREFIX}' prefix."
        )

    return normalized



def backfill_membership_subject_normalized(apps, schema_editor):
    MembershipSubject = apps.get_model("servers", "MembershipSubject")
    db_alias = schema_editor.connection.alias

    subjects = list(
        MembershipSubject.objects.using(db_alias).all()
    )

    for subject in subjects:
        try:
            subject.subject_code_normalized = (
                _canonicalize_subject_code(subject.subject_code).casefold()
            )
        except SubjectCodeError:
            subject.subject_code_normalized = None

    seen = {}
    duplicates = {}

    for subject in subjects:
        if not subject.subject_code_normalized:
            continue

        key = (subject.membership_id, subject.subject_code_normalized)

        if key in seen:
            if key not in duplicates:
                duplicates[key] = [seen[key]]
            duplicates[key].append(subject)
        else:
            seen[key] = subject

    if duplicates:
        collision_messages = []

        for (membership_id, norm_code), conflicting in duplicates.items():
            conflicting_descs = [
                f"MembershipSubject(id={subject.pk}, "
                f"subject_code={subject.subject_code!r})"
                for subject in conflicting
            ]

            collision_messages.append(
                f"- Membership(id={membership_id}): normalized code "
                f"{norm_code!r} has {len(conflicting)} conflicting records: "
                + ", ".join(conflicting_descs)
            )

        raise MigrationCollisionError(
            "Cannot apply migration servers.0004_membershipsubject_subject_code_normalized_and_more: "
            "detected duplicate (membership_id, subject_code_normalized) "
            "values that violate the upcoming unique constraint:\n"
            + "\n".join(collision_messages)
        )

    for subject in subjects:
        subject.save(using=db_alias)


def backfill_membership_subject_normalized_reverse(apps, schema_editor):
    MembershipSubject = apps.get_model("servers", "MembershipSubject")
    db_alias = schema_editor.connection.alias

    MembershipSubject.objects.using(db_alias).update(
        subject_code_normalized=None
    )

class Migration(migrations.Migration):

    dependencies = [
        ("servers", "0003_serverrequest_servers_serverrequest_one_pending_per_requester"),
    ]

    operations = [
        migrations.AddField(
            model_name="membershipsubject",
            name="subject_code_normalized",
            field=models.CharField(blank=True, max_length=192, null=True),
        ),
        migrations.RunPython(
            backfill_membership_subject_normalized,
            backfill_membership_subject_normalized_reverse,
        ),
        migrations.AddConstraint(
            model_name="membershipsubject",
            constraint=models.UniqueConstraint(
                fields=("membership", "subject_code_normalized"),
                name="servers_membershipsubject_unique_normalized_code",
            ),
        ),
    ]

"""Channel access control policy tests (Issue #30: FR-016, US-05, BR-01).

Covers the role-aware, server-scoped access policy in
apps.servers.services.access plus the Channel.subject_code database
constraints in apps.channels.models.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.test import TestCase, TransactionTestCase

from apps.channels.models import Channel, ChannelType
from apps.servers.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    MembershipSubject,
    Server,
)
from apps.servers.services.access import (
    get_accessible_channels_for_user,
    user_can_access_channel,
)

User = get_user_model()


def create_verified_user(email="student@example.com", password="StrongPass123", **kwargs):
    user = User.objects.create_user(
        email=email,
        password=password,
        full_name=kwargs.pop("full_name", "Test Student"),
        **kwargs,
    )
    user.is_email_verified = True
    user.save(update_fields=["is_email_verified"])
    return user


def create_server(name="Class A", slug="class-a", is_active=True, **kwargs):
    return Server.objects.create(name=name, slug=slug, is_active=is_active, **kwargs)


def create_membership(user, server, role=MembershipRole.STUDENT, status=MembershipStatus.ACTIVE):
    return Membership.objects.create(
        user=user,
        server=server,
        role=role,
        status=status,
    )


def create_default_channels(server):
    channels = []
    for channel_type, name in (
        (ChannelType.ANNOUNCEMENTS, "Announcements"),
        (ChannelType.CALENDAR, "Calendar"),
        (ChannelType.RULES, "Rules"),
    ):
        channels.append(
            Channel.objects.create(
                server=server,
                name=name,
                slug=channel_type,
                channel_type=channel_type,
            )
        )
    return channels


def create_subject_channel(server, name, slug, subject_code):
    return Channel.objects.create(
        server=server,
        name=name,
        slug=slug,
        channel_type=ChannelType.SUBJECT,
        subject_code=subject_code,
    )


class ChannelAccessPolicyTests(TestCase):
    """Role-aware, server-scoped channel access policy."""

    def setUp(self):
        self.student = create_verified_user("student@example.com")
        self.officer = create_verified_user("officer@example.com", full_name="Officer")
        self.president = create_verified_user("president@example.com", full_name="President")
        self.outsider = create_verified_user("outsider@example.com", full_name="Outsider")
        self.server = create_server(name="Section A", slug="section-a")
        self.other_server = create_server(name="Section B", slug="section-b")
        create_default_channels(self.server)
        create_default_channels(self.other_server)
        self.subject_cs = create_subject_channel(
            self.server, "Computer Science 101", "cs101", "CS101"
        )
        self.subject_math = create_subject_channel(
            self.server, "Mathematics 201", "math201", "MATH201"
        )
        self.other_subject = create_subject_channel(
            self.other_server, "Computer Science 101", "cs101", "CS101"
        )

    # ---- Anonymous / no membership -------------------------------------

    def test_anonymous_user_sees_no_channels(self):
        anonymous = AnonymousUser()
        self.assertEqual(
            list(get_accessible_channels_for_user(anonymous, self.server)), []
        )
        self.assertFalse(user_can_access_channel(anonymous, self.subject_cs))

    def test_none_user_sees_no_channels(self):
        self.assertEqual(list(get_accessible_channels_for_user(None, self.server)), [])
        self.assertFalse(user_can_access_channel(None, self.subject_cs))

    def test_user_without_membership_sees_no_channels(self):
        self.assertEqual(
            list(get_accessible_channels_for_user(self.outsider, self.server)), []
        )
        self.assertFalse(user_can_access_channel(self.outsider, self.subject_cs))

    def test_none_server_returns_no_channels(self):
        create_membership(self.student, self.server)
        self.assertEqual(
            list(get_accessible_channels_for_user(self.student, None)), []
        )
        self.assertFalse(user_can_access_channel(self.student, self.subject_cs))

    # ---- Student: no approved subjects ---------------------------------

    def test_student_with_no_subjects_sees_defaults_only(self):
        create_membership(self.student, self.server)
        channels = list(get_accessible_channels_for_user(self.student, self.server))
        type_slugs = {(c.channel_type, c.slug) for c in channels}
        self.assertIn((ChannelType.ANNOUNCEMENTS, "announcements"), type_slugs)
        self.assertIn((ChannelType.CALENDAR, "calendar"), type_slugs)
        self.assertIn((ChannelType.RULES, "rules"), type_slugs)
        self.assertNotIn((ChannelType.SUBJECT, "cs101"), type_slugs)
        self.assertNotIn((ChannelType.SUBJECT, "math201"), type_slugs)

    def test_student_with_no_subjects_cannot_access_subject_channel(self):
        create_membership(self.student, self.server)
        self.assertFalse(user_can_access_channel(self.student, self.subject_cs))
        self.assertFalse(user_can_access_channel(self.student, self.subject_math))

    # ---- Student: with approved subjects -------------------------------

    def test_student_sees_defaults_and_assigned_subjects(self):
        membership = create_membership(self.student, self.server)
        MembershipSubject.objects.create(membership=membership, subject_code="CS101")
        channels = list(get_accessible_channels_for_user(self.student, self.server))
        type_slugs = {(c.channel_type, c.slug) for c in channels}
        self.assertIn((ChannelType.SUBJECT, "cs101"), type_slugs)
        self.assertNotIn((ChannelType.SUBJECT, "math201"), type_slugs)
        self.assertTrue(user_can_access_channel(self.student, self.subject_cs))
        self.assertFalse(user_can_access_channel(self.student, self.subject_math))

    def test_student_sees_multiple_assigned_subjects(self):
        membership = create_membership(self.student, self.server)
        MembershipSubject.objects.create(membership=membership, subject_code="CS101")
        MembershipSubject.objects.create(membership=membership, subject_code="MATH201")
        channels = list(get_accessible_channels_for_user(self.student, self.server))
        type_slugs = {(c.channel_type, c.slug) for c in channels}
        self.assertIn((ChannelType.SUBJECT, "cs101"), type_slugs)
        self.assertIn((ChannelType.SUBJECT, "math201"), type_slugs)

    def test_student_cannot_access_unassigned_subject(self):
        membership = create_membership(self.student, self.server)
        MembershipSubject.objects.create(membership=membership, subject_code="CS101")
        self.assertFalse(user_can_access_channel(self.student, self.subject_math))

    def test_subject_enrollment_changes_take_effect_next_request(self):
        membership = create_membership(self.student, self.server)
        self.assertFalse(user_can_access_channel(self.student, self.subject_math))
        MembershipSubject.objects.create(membership=membership, subject_code="MATH201")
        self.assertTrue(user_can_access_channel(self.student, self.subject_math))

    def test_student_case_insensitive_subject_match(self):
        membership = create_membership(self.student, self.server)
        MembershipSubject.objects.create(membership=membership, subject_code="cs101")
        self.assertTrue(user_can_access_channel(self.student, self.subject_cs))
    # ---- Cross-server isolation ----------------------------------------

    def test_student_cannot_access_other_server_subject_channel(self):
        membership = create_membership(self.student, self.server)
        MembershipSubject.objects.create(membership=membership, subject_code="CS101")
        self.assertFalse(user_can_access_channel(self.student, self.other_subject))
        self.assertEqual(
            list(get_accessible_channels_for_user(self.student, self.other_server)),
            [],
        )

    def test_membership_in_another_server_grants_no_access_here(self):
        create_membership(self.student, self.other_server)
        self.assertEqual(
            list(get_accessible_channels_for_user(self.student, self.server)), []
        )

    # ---- Officer / President -------------------------------------------

    def test_officer_sees_all_channels_in_own_server(self):
        create_membership(self.officer, self.server, role=MembershipRole.OFFICER)
        channels = list(get_accessible_channels_for_user(self.officer, self.server))
        type_slugs = {(c.channel_type, c.slug) for c in channels}
        self.assertIn((ChannelType.ANNOUNCEMENTS, "announcements"), type_slugs)
        self.assertIn((ChannelType.CALENDAR, "calendar"), type_slugs)
        self.assertIn((ChannelType.RULES, "rules"), type_slugs)
        self.assertIn((ChannelType.SUBJECT, "cs101"), type_slugs)
        self.assertIn((ChannelType.SUBJECT, "math201"), type_slugs)
        self.assertTrue(user_can_access_channel(self.officer, self.subject_cs))
        self.assertTrue(user_can_access_channel(self.officer, self.subject_math))

    def test_president_sees_all_channels_in_own_server(self):
        create_membership(self.president, self.server, role=MembershipRole.PRESIDENT)
        channels = list(get_accessible_channels_for_user(self.president, self.server))
        type_slugs = {(c.channel_type, c.slug) for c in channels}
        self.assertIn((ChannelType.SUBJECT, "cs101"), type_slugs)
        self.assertIn((ChannelType.SUBJECT, "math201"), type_slugs)
        self.assertTrue(user_can_access_channel(self.president, self.subject_math))

    def test_officer_no_access_to_other_server(self):
        create_membership(self.officer, self.server, role=MembershipRole.OFFICER)
        self.assertFalse(user_can_access_channel(self.officer, self.other_subject))
        self.assertEqual(
            list(get_accessible_channels_for_user(self.officer, self.other_server)),
            [],
        )

    # ---- LEFT / REMOVED memberships ------------------------------------

    def test_left_membership_loses_access(self):
        membership = create_membership(self.student, self.server)
        MembershipSubject.objects.create(membership=membership, subject_code="CS101")
        membership.status = MembershipStatus.LEFT
        membership.save(update_fields=["status"])
        self.assertFalse(user_can_access_channel(self.student, self.subject_cs))
        self.assertEqual(
            list(get_accessible_channels_for_user(self.student, self.server)), []
        )

    def test_removed_membership_loses_access(self):
        membership = create_membership(self.student, self.server)
        MembershipSubject.objects.create(membership=membership, subject_code="CS101")
        membership.status = MembershipStatus.REMOVED
        membership.save(update_fields=["status"])
        self.assertFalse(user_can_access_channel(self.student, self.subject_cs))
        self.assertEqual(
            list(get_accessible_channels_for_user(self.student, self.server)), []
        )

    # ---- Inactive server ----------------------------------------------

    def test_inactive_server_grants_no_access(self):
        inactive_server = create_server(name="Inactive", slug="inactive", is_active=False)
        create_membership(self.student, inactive_server)
        mem = Membership.objects.get(user=self.student, server=inactive_server)
        MembershipSubject.objects.create(membership=mem, subject_code="CS101")
        inactive_subject_channel = Channel.objects.create(
            server=inactive_server,
            name="Inactive Subject",
            slug="inactive-subject",
            channel_type=ChannelType.SUBJECT,
            subject_code="CS101",
        )
        self.assertEqual(
            list(get_accessible_channels_for_user(self.student, inactive_server)), []
        )
        self.assertFalse(
            user_can_access_channel(self.student, inactive_subject_channel)
        )
        self.assertFalse(user_can_access_channel(self.student, self.subject_cs))

    # ---- Role promotion / demotion -------------------------------------

    def test_promotion_to_officer_grants_all_channels(self):
        membership = create_membership(self.student, self.server)
        MembershipSubject.objects.create(membership=membership, subject_code="CS101")
        self.assertFalse(user_can_access_channel(self.student, self.subject_math))
        membership.role = MembershipRole.OFFICER
        membership.save(update_fields=["role"])
        self.assertTrue(user_can_access_channel(self.student, self.subject_math))
        self.assertTrue(user_can_access_channel(self.student, self.subject_cs))

    def test_demotion_to_student_loses_unassigned_channels(self):
        membership = create_membership(self.student, self.server, role=MembershipRole.OFFICER)
        self.assertTrue(user_can_access_channel(self.student, self.subject_math))
        membership.role = MembershipRole.STUDENT
        membership.save(update_fields=["role"])
        self.assertFalse(user_can_access_channel(self.student, self.subject_math))
        self.assertFalse(user_can_access_channel(self.student, self.subject_cs))

    # ---- Membership subject replacement --------------------------------

    def test_subject_replacement_updates_access(self):
        membership = create_membership(self.student, self.server)
        old_subject = MembershipSubject.objects.create(
            membership=membership, subject_code="CS101"
        )
        self.assertTrue(user_can_access_channel(self.student, self.subject_cs))
        self.assertFalse(user_can_access_channel(self.student, self.subject_math))
        old_subject.delete()
        MembershipSubject.objects.create(membership=membership, subject_code="MATH201")
        self.assertFalse(user_can_access_channel(self.student, self.subject_cs))
        self.assertTrue(user_can_access_channel(self.student, self.subject_math))

    # ---- Default channel visibility ------------------------------------

    def test_default_channels_visible_to_any_active_member(self):
        create_membership(self.student, self.server)
        channels = get_accessible_channels_for_user(self.student, self.server)
        self.assertTrue(
            channels.filter(channel_type=ChannelType.ANNOUNCEMENTS).exists()
        )
        self.assertTrue(channels.filter(channel_type=ChannelType.CALENDAR).exists())
        self.assertTrue(channels.filter(channel_type=ChannelType.RULES).exists())

    # ---- Subject code vs slug distinction ------------------------------

    def test_access_granted_through_subject_code_not_slug(self):
        channel = Channel.objects.create(
            server=self.server,
            name="Biology 101",
            slug="biology-101",
            channel_type=ChannelType.SUBJECT,
            subject_code="BIOL101",
        )
        membership = create_membership(self.student, self.server)
        MembershipSubject.objects.create(membership=membership, subject_code="BIOL101")
        self.assertTrue(user_can_access_channel(self.student, channel))

    def test_access_denied_when_slug_matches_but_subject_code_does_not(self):
        channel = Channel.objects.create(
            server=self.server,
            name="Physics",
            slug="PHYS101",
            channel_type=ChannelType.SUBJECT,
            subject_code="PHYS102",
        )
        membership = create_membership(self.student, self.server)
        MembershipSubject.objects.create(membership=membership, subject_code="PHYS101")
        self.assertFalse(user_can_access_channel(self.student, channel))

    # ---- Unicode case-folding ------------------------------------------

    def test_unicode_case_fold_matches(self):
        channel = Channel.objects.create(
            server=self.server,
            name="\u00c9cole 101",
            slug="eco101",
            channel_type=ChannelType.SUBJECT,
            subject_code="\u00c9CO101",
        )
        membership = create_membership(self.student, self.server)
        MembershipSubject.objects.create(membership=membership, subject_code="\u00e9co101")
        self.assertTrue(user_can_access_channel(self.student, channel))

    def test_unicode_case_fold_reverse_matches(self):
        channel = Channel.objects.create(
            server=self.server,
            name="\u00c9cole 101",
            slug="eco101",
            channel_type=ChannelType.SUBJECT,
            subject_code="\u00e9co101",
        )
        membership = create_membership(self.student, self.server)
        MembershipSubject.objects.create(membership=membership, subject_code="\u00c9CO101")
        self.assertTrue(user_can_access_channel(self.student, channel))




    # ---- Whitespace normalization --------------------------------------

    def test_leading_trailing_whitespace_normalized(self):
        membership = create_membership(self.student, self.server)
        MembershipSubject.objects.create(membership=membership, subject_code="  CS101  ")
        self.assertTrue(user_can_access_channel(self.student, self.subject_cs))

    def test_repeated_internal_whitespace_normalized(self):
        membership = create_membership(self.student, self.server)
        MembershipSubject.objects.create(membership=membership, subject_code="CS  101")
        channel = Channel.objects.create(
            server=self.server,
            name="CS 101",
            slug="cs-101",
            channel_type=ChannelType.SUBJECT,
            subject_code="CS 101",
        )
        self.assertTrue(user_can_access_channel(self.student, channel))

    def test_whitespace_only_code_grants_no_access(self):
        membership = create_membership(self.student, self.server)
        MembershipSubject.objects.create(membership=membership, subject_code="   ")
        self.assertFalse(user_can_access_channel(self.student, self.subject_cs))
        channels = list(get_accessible_channels_for_user(self.student, self.server))
        self.assertEqual(
            [c for c in channels if c.channel_type == ChannelType.SUBJECT], []
        )

    # ---- Role change between queryset construction and evaluation ------

    def test_role_change_after_queryset_construction(self):
        membership = create_membership(self.student, self.server, role=MembershipRole.OFFICER)
        qs = get_accessible_channels_for_user(self.student, self.server)
        self.assertTrue(qs.filter(pk=self.subject_math.pk).exists())
        membership.role = MembershipRole.STUDENT
        membership.save(update_fields=["role"])
        self.assertFalse(qs.filter(pk=self.subject_math.pk).exists())

    # ---- Large approved-subject collection -----------------------------

    def test_large_approved_subject_collection(self):
        membership = create_membership(self.student, self.server)
        subject_channels = []
        for i in range(200):
            code = f"SUBJ{i:04d}"
            MembershipSubject.objects.create(membership=membership, subject_code=code)
            subject_channels.append(
                Channel.objects.create(
                    server=self.server,
                    name=f"Subject {i}",
                    slug=f"subj{i:04d}",
                    channel_type=ChannelType.SUBJECT,
                    subject_code=code,
                )
            )
        unassigned = Channel.objects.create(
            server=self.server,
            name="Unassigned",
            slug="unassigned",
            channel_type=ChannelType.SUBJECT,
            subject_code="NOPE9999",
        )
        channels = list(get_accessible_channels_for_user(self.student, self.server))
        subject_slugs = {c.slug for c in channels if c.channel_type == ChannelType.SUBJECT}
        for sc in subject_channels:
            self.assertIn(sc.slug, subject_slugs)
        self.assertNotIn("unassigned", subject_slugs)
        self.assertFalse(user_can_access_channel(self.student, unassigned))


class ChannelSubjectCodeConstraintTests(TestCase):
    def setUp(self):
        self.server = create_server(name="Class A", slug="class-a")

    def test_subject_channel_requires_non_null_subject_code(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Channel.objects.create(
                    server=self.server,
                    name="Subject",
                    slug="subject",
                    channel_type=ChannelType.SUBJECT,
                    subject_code=None,
                )

    def test_subject_channel_rejects_empty_subject_code(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Channel.objects.create(
                    server=self.server,
                    name="Subject",
                    slug="subject",
                    channel_type=ChannelType.SUBJECT,
                    subject_code="",
                )

    def test_subject_channel_accepts_valid_subject_code(self):
        channel = Channel.objects.create(
            server=self.server,
            name="Subject",
            slug="subject",
            channel_type=ChannelType.SUBJECT,
            subject_code="CS101",
        )
        self.assertIsNotNone(channel.subject_code)

    def test_default_channel_subject_code_must_be_null(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Channel.objects.create(
                    server=self.server,
                    name="Announcements",
                    slug="announcements",
                    channel_type=ChannelType.ANNOUNCEMENTS,
                    subject_code="CS101",
                )

    def test_default_channel_accepts_null_subject_code(self):
        channel = Channel.objects.create(
            server=self.server,
            name="Announcements",
            slug="announcements",
            channel_type=ChannelType.ANNOUNCEMENTS,
            subject_code=None,
        )
        self.assertIsNone(channel.subject_code)

    def test_case_insensitive_duplicate_subject_code_rejected_within_server(self):
        Channel.objects.create(
            server=self.server,
            name="CS",
            slug="cs",
            channel_type=ChannelType.SUBJECT,
            subject_code="CS101",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Channel.objects.create(
                    server=self.server,
                    name="cs duplicate",
                    slug="cs-dup",
                    channel_type=ChannelType.SUBJECT,
                    subject_code="cs101",
                )

    def test_same_subject_code_allowed_in_different_servers(self):
        Channel.objects.create(
            server=self.server,
            name="CS",
            slug="cs",
            channel_type=ChannelType.SUBJECT,
            subject_code="CS101",
        )
        other_server = create_server(name="Class B", slug="class-b")
        channel = Channel.objects.create(
            server=other_server,
            name="CS",
            slug="cs",
            channel_type=ChannelType.SUBJECT,
            subject_code="CS101",
        )
        self.assertEqual(channel.subject_code, "CS101")


class MigrationBackfillTests(TransactionTestCase):
    """Tests for the channels.0002 data migration backfill behavior."""

    def test_existing_subject_rows_get_backfilled_with_legacy_identifier(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        current_targets = executor.loader.graph.leaf_nodes()

        migrate_from_targets = [
            t for t in current_targets if t[0] != "channels"
        ]
        migrate_from_targets.append(("channels", "0001_initial"))
        executor.migrate(migrate_from_targets)

        legacy_apps = executor.loader.project_state(
            migrate_from_targets
        ).apps
        LegacyChannel = legacy_apps.get_model("channels", "Channel")
        LegacyServer = legacy_apps.get_model("servers", "Server")

        server = LegacyServer.objects.create(
            name="Legacy Class", slug="legacy-class"
        )
        LegacyChannel.objects.create(
            server=server,
            name="Legacy Subject",
            slug="legacy-subject",
            channel_type="subject",
        )

        migrate_to_targets = [
            t for t in current_targets if t[0] != "channels"
        ]
        migrate_to_targets.append(
            ("channels", "0002_channel_subject_code_and_more")
        )
        MigrationExecutor(connection).migrate(migrate_to_targets)

        migrated_apps = MigrationExecutor(connection).loader.project_state(
            migrate_to_targets
        ).apps
        MigratedChannel = migrated_apps.get_model("channels", "Channel")
        channel = MigratedChannel.objects.get(slug="legacy-subject")
        self.assertEqual(
            channel.subject_code, f"legacy-channel-{channel.pk}"
        )
        self.assertEqual(
            channel.subject_code_normalized,
            f"legacy-channel-{channel.pk}",
        )

    def test_database_with_no_subject_rows_migrates_cleanly(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        current_targets = executor.loader.graph.leaf_nodes()

        migrate_from_targets = [
            t for t in current_targets if t[0] != "channels"
        ]
        migrate_from_targets.append(("channels", "0001_initial"))
        executor.migrate(migrate_from_targets)

        migrate_to_targets = [
            t for t in current_targets if t[0] != "channels"
        ]
        migrate_to_targets.append(
            ("channels", "0002_channel_subject_code_and_more")
        )
        executor.migrate(migrate_to_targets)

    def test_duplicate_legacy_identifiers_are_unique(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        current_targets = executor.loader.graph.leaf_nodes()

        migrate_from_targets = [
            t for t in current_targets if t[0] != "channels"
        ]
        migrate_from_targets.append(("channels", "0001_initial"))
        executor.migrate(migrate_from_targets)

        legacy_apps = executor.loader.project_state(
            migrate_from_targets
        ).apps
        LegacyChannel = legacy_apps.get_model("channels", "Channel")
        LegacyServer = legacy_apps.get_model("servers", "Server")

        server = LegacyServer.objects.create(
            name="Legacy Class", slug="legacy-class"
        )
        LegacyChannel.objects.create(
            server=server,
            name="Legacy Subject 1",
            slug="legacy-subject-1",
            channel_type="subject",
        )
        LegacyChannel.objects.create(
            server=server,
            name="Legacy Subject 2",
            slug="legacy-subject-2",
            channel_type="subject",
        )

        migrate_to_targets = [
            t for t in current_targets if t[0] != "channels"
        ]
        migrate_to_targets.append(
            ("channels", "0002_channel_subject_code_and_more")
        )
        MigrationExecutor(connection).migrate(migrate_to_targets)

        migrated_apps = MigrationExecutor(connection).loader.project_state(
            migrate_to_targets
        ).apps
        MigratedChannel = migrated_apps.get_model("channels", "Channel")
        channels = list(
            MigratedChannel.objects.filter(
                slug__in=("legacy-subject-1", "legacy-subject-2")
            )
        )
        codes = {c.subject_code for c in channels}
        self.assertEqual(len(codes), 2)
        self.assertTrue(
            all(c.startswith("legacy-channel-") for c in codes)
        )

    def test_backfill_collision_with_sharp_s_and_ss_raises_clear_error(self):
        import importlib
        from django.apps import apps

        migration_mod = importlib.import_module(
            "apps.channels.migrations.0002_channel_subject_code_and_more"
        )
        backfill_subject_code_normalized = migration_mod.backfill_subject_code_normalized
        MigrationCollisionError = migration_mod.MigrationCollisionError

        server = Server.objects.create(
            name="Collision Class", slug="collision-class"
        )
        # Create un-normalized subject channels via bulk_create to simulate
        # pre-existing channels with colliding subject codes prior to backfill.
        Channel.objects.bulk_create([
            Channel(
                server=server,
                name="German Beta",
                slug="german-beta",
                channel_type=ChannelType.SUBJECT,
                subject_code="\u00df",
                subject_code_normalized=None,
            ),
            Channel(
                server=server,
                name="German SS",
                slug="german-ss",
                channel_type=ChannelType.SUBJECT,
                subject_code="SS",
                subject_code_normalized=None,
            ),
        ])

        with self.assertRaises(MigrationCollisionError) as ctx:
            backfill_subject_code_normalized(apps, None)

        err_msg = str(ctx.exception)
        self.assertIn("collision-class", err_msg)
        self.assertIn("Collision Class", err_msg)
        self.assertIn("\u00df", err_msg)
        self.assertIn("SS", err_msg)
        self.assertIn("ss", err_msg)

        # Verify neither channel had its original subject_code silently modified
        c_beta = Channel.objects.get(slug="german-beta")
        c_ss = Channel.objects.get(slug="german-ss")
        self.assertEqual(c_beta.subject_code, "\u00df")
        self.assertEqual(c_ss.subject_code, "SS")

    def test_migration_executor_detects_collision_and_aborts_before_constraint(self):
        import importlib
        from unittest.mock import patch
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        current_targets = executor.loader.graph.leaf_nodes()

        migrate_from_targets = [
            t for t in current_targets if t[0] != "channels"
        ]
        migrate_from_targets.append(("channels", "0001_initial"))
        executor.migrate(migrate_from_targets)

        legacy_apps = executor.loader.project_state(
            migrate_from_targets
        ).apps
        LegacyChannel = legacy_apps.get_model("channels", "Channel")
        LegacyServer = legacy_apps.get_model("servers", "Server")

        server = LegacyServer.objects.create(
            name="Collision Class", slug="collision-class"
        )
        ch_beta = LegacyChannel.objects.create(
            server=server,
            name="German Beta",
            slug="german-beta",
            channel_type="subject",
        )
        ch_ss = LegacyChannel.objects.create(
            server=server,
            name="German SS",
            slug="german-ss",
            channel_type="subject",
        )

        migrate_to_targets = [
            t for t in current_targets if t[0] != "channels"
        ]
        migrate_to_targets.append(
            ("channels", "0002_channel_subject_code_and_more")
        )

        migrate_executor = MigrationExecutor(connection)
        migration_mod = importlib.import_module(
            "apps.channels.migrations.0002_channel_subject_code_and_more"
        )
        MigrationCollisionError = migration_mod.MigrationCollisionError
        mig = migrate_executor.loader.get_migration(
            "channels", "0002_channel_subject_code_and_more"
        )
        run_python_op = next(
            op for op in mig.operations if hasattr(op, "code") and op.code
        )
        real_backfill = run_python_op.code

        def backfill_with_colliding_codes(apps, schema_editor):
            # When backfill runs during executor.migrate, Operation 0 and 1
            # (AddField subject_code and AddField subject_code_normalized) have
            # executed, but the unique constraint has not yet been added.
            # Assign colliding codes ("ß" and "SS") to simulate pre-existing
            # channels with codes that collide under Unicode case-folding.
            Channel = apps.get_model("channels", "Channel")
            Channel.objects.filter(pk=ch_beta.pk).update(subject_code="\u00df")
            Channel.objects.filter(pk=ch_ss.pk).update(subject_code="SS")
            real_backfill(apps, schema_editor)

        try:
            with patch.object(
                run_python_op,
                "code",
                side_effect=backfill_with_colliding_codes,
            ):
                with self.assertRaises(MigrationCollisionError) as ctx:
                    migrate_executor.migrate(migrate_to_targets)

            err_msg = str(ctx.exception)
            self.assertIn("collision-class", err_msg)
            self.assertIn("Collision Class", err_msg)
            self.assertIn("\u00df", err_msg)
            self.assertIn("SS", err_msg)
            self.assertIn("ss", err_msg)
        finally:
            # Restore migration state safely.
            clean_executor = MigrationExecutor(connection)
            clean_executor.loader.build_graph()
            try:
                clean_executor.migrate(migrate_from_targets)
            except Exception:
                pass
            LegacyChannel.objects.filter(server=server).delete()
            server.delete()
            MigrationExecutor(connection).migrate(current_targets)

    def test_backfill_preserves_unicode_expanded_codes(self):
        import importlib
        from django.apps import apps

        migration_mod = importlib.import_module(
            "apps.channels.migrations.0002_channel_subject_code_and_more"
        )
        backfill_subject_code_normalized = migration_mod.backfill_subject_code_normalized

        server = Server.objects.create(
            name="Expansion Class", slug="expansion-class"
        )
        expanded_code = "\u00df" * 33  # 33 chars -> 66 chars
        Channel.objects.bulk_create([
            Channel(
                server=server,
                name="Expanded Channel",
                slug="expanded-channel",
                channel_type=ChannelType.SUBJECT,
                subject_code=expanded_code,
                subject_code_normalized=None,
            ),
        ])

        backfill_subject_code_normalized(apps, None)

        channel = Channel.objects.get(slug="expanded-channel")
        self.assertEqual(channel.subject_code, expanded_code)
        self.assertEqual(channel.subject_code_normalized, "ss" * 33)
        self.assertEqual(len(channel.subject_code_normalized), 66)


class ChannelSubjectCodeNormalizedTests(TestCase):
    """Tests for Unicode case-folding and whitespace normalization in
    subject_code_normalized handling."""

    def setUp(self):
        self.server = create_server(name="Class A", slug="class-a")

    def test_unicode_case_fold_uniqueness_within_server(self):
        Channel.objects.create(
            server=self.server,
            name="\u00c9cole 101",
            slug="eco-101",
            channel_type=ChannelType.SUBJECT,
            subject_code="\u00c9CO101",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Channel.objects.create(
                    server=self.server,
                    name="\u00e9cole 101",
                    slug="eco-101-2",
                    channel_type=ChannelType.SUBJECT,
                    subject_code="\u00e9co101",
                )

    def test_unicode_case_fold_allowed_in_different_servers(self):
        Channel.objects.create(
            server=self.server,
            name="\u00c9cole 101",
            slug="eco-101",
            channel_type=ChannelType.SUBJECT,
            subject_code="\u00c9CO101",
        )
        other_server = create_server(name="Class B", slug="class-b")
        channel = Channel.objects.create(
            server=other_server,
            name="\u00e9cole 101",
            slug="eco-101",
            channel_type=ChannelType.SUBJECT,
            subject_code="\u00e9co101",
        )
        self.assertEqual(channel.subject_code, "\u00e9co101")

    def test_whitespace_normalized_before_storage(self):
        channel = Channel.objects.create(
            server=self.server,
            name="Whitespace",
            slug="ws",
            channel_type=ChannelType.SUBJECT,
            subject_code="  CS  101  ",
        )
        self.assertEqual(channel.subject_code_normalized, "cs 101")

    def test_default_channel_normalized_is_null(self):
        channel = Channel.objects.create(
            server=self.server,
            name="Announcements",
            slug="announcements",
            channel_type=ChannelType.ANNOUNCEMENTS,
            subject_code=None,
        )
        self.assertIsNone(channel.subject_code_normalized)

    def test_unicode_expansion_persisted_on_ordinary_save(self):
        # 33 characters of 'ß' expands to 66 characters of 'ss' in casefold.
        # This exceeds the 64-character subject_code limit and verifies the
        # 192-character subject_code_normalized field fits it.
        code = "\u00df" * 33
        self.assertEqual(len(code), 33)
        channel = Channel.objects.create(
            server=self.server,
            name="Expansion Test",
            slug="expansion-test",
            channel_type=ChannelType.SUBJECT,
            subject_code=code,
        )
        channel.refresh_from_db()
        self.assertEqual(channel.subject_code, code)
        self.assertEqual(channel.subject_code_normalized, "ss" * 33)
        self.assertEqual(len(channel.subject_code_normalized), 66)

    def test_unicode_expansion_persisted_on_update_fields_save(self):
        channel = Channel.objects.create(
            server=self.server,
            name="Initial Channel",
            slug="initial-chan",
            channel_type=ChannelType.SUBJECT,
            subject_code="INITIAL101",
        )
        new_code = "\u00df" * 33
        channel.subject_code = new_code
        channel.save(update_fields=["subject_code"])

        channel.refresh_from_db()
        self.assertEqual(channel.subject_code, new_code)
        self.assertEqual(channel.subject_code_normalized, "ss" * 33)
        self.assertEqual(len(channel.subject_code_normalized), 66)

    def test_maximum_expansion_up_to_192_characters(self):
        # 64 characters of 'ß' expands to 128 characters of 'ss'.
        code_64 = "\u00df" * 64
        self.assertEqual(len(code_64), 64)
        channel = Channel.objects.create(
            server=self.server,
            name="Max Expansion 64",
            slug="max-exp-64",
            channel_type=ChannelType.SUBJECT,
            subject_code=code_64,
        )
        channel.refresh_from_db()
        self.assertEqual(channel.subject_code, code_64)
        self.assertEqual(channel.subject_code_normalized, "ss" * 64)
        self.assertEqual(len(channel.subject_code_normalized), 128)

        # 64 characters that expand to 3 characters each in casefold (192 total),
        # e.g. '\u0390' (Greek small letter iota with dialytika and tonos).
        code_192 = "\u0390" * 64
        self.assertEqual(len(code_192), 64)
        self.assertEqual(len(code_192.casefold()), 192)
        channel2 = Channel.objects.create(
            server=self.server,
            name="Max Expansion 192",
            slug="max-exp-192",
            channel_type=ChannelType.SUBJECT,
            subject_code=code_192,
        )
        channel2.refresh_from_db()
        self.assertEqual(channel2.subject_code_normalized, code_192.casefold())
        self.assertEqual(len(channel2.subject_code_normalized), 192)

    def test_update_fields_without_subject_code_leaves_normalized_untouched(self):
        channel = Channel.objects.create(
            server=self.server,
            name="Old Name",
            slug="old-name",
            channel_type=ChannelType.SUBJECT,
            subject_code="CS101",
        )
        channel.name = "New Name"
        channel.save(update_fields=["name"])
        channel.refresh_from_db()
        self.assertEqual(channel.name, "New Name")
        self.assertEqual(channel.subject_code_normalized, "cs101")

    def test_runtime_collision_with_sharp_s_and_ss_rejected_within_server(self):
        Channel.objects.create(
            server=self.server,
            name="German Beta",
            slug="german-beta",
            channel_type=ChannelType.SUBJECT,
            subject_code="\u00df",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Channel.objects.create(
                    server=self.server,
                    name="German SS",
                    slug="german-ss",
                    channel_type=ChannelType.SUBJECT,
                    subject_code="SS",
                )

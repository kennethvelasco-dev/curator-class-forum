"""Channel access control policy tests (Issue #30: FR-016, US-05, BR-01).

Covers the role-aware, server-scoped access policy in
apps.servers.services.access plus the Channel.subject_code database
constraints in apps.channels.models.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.test import TestCase

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

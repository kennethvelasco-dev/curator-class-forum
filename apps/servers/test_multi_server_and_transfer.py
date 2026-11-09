"""Tests for multi-server membership (#24) and President transfer (#25)."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from apps.channels.models import Channel, ChannelType
from apps.servers.context import (
    ACTIVE_SERVER_SESSION_KEY,
    _parse_server_id,
    get_active_memberships,
    resolve_active_server,
    set_active_server,
)
from apps.servers.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    MembershipSubject,
    Server,
)
from apps.servers.permissions import is_active_president_of_server
from apps.servers.services.access import (
    get_accessible_channels_for_user,
    user_can_access_channel,
)
from apps.servers.services.transfer import transfer_presidency


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


def create_server(name="Class A", slug="class-a", **kwargs):
    return Server.objects.create(name=name, slug=slug, **kwargs)


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


class MultiServerMembershipTests(TestCase):
    def setUp(self):
        self.user = create_verified_user()
        self.server_a = create_server(name="Section A", slug="section-a", section="1A")
        self.server_b = create_server(name="Section B", slug="section-b", section="1B")
        self.membership_a = create_membership(self.user, self.server_a)
        self.membership_b = create_membership(self.user, self.server_b)

    def test_multiple_active_memberships_across_servers(self):
        memberships = list(get_active_memberships(self.user))
        self.assertEqual(len(memberships), 2)
        server_ids = {m.server_id for m in memberships}
        self.assertEqual(server_ids, {self.server_a.pk, self.server_b.pk})

    def test_left_membership_excluded(self):
        self.membership_b.status = MembershipStatus.LEFT
        self.membership_b.save(update_fields=["status"])
        memberships = list(get_active_memberships(self.user))
        self.assertEqual(len(memberships), 1)
        self.assertEqual(memberships[0].server_id, self.server_a.pk)

    def test_removed_membership_excluded(self):
        self.membership_a.status = MembershipStatus.REMOVED
        self.membership_a.save(update_fields=["status"])
        memberships = list(get_active_memberships(self.user))
        self.assertEqual(len(memberships), 1)
        self.assertEqual(memberships[0].server_id, self.server_b.pk)

    def test_inactive_server_excluded(self):
        self.server_a.is_active = False
        self.server_a.save(update_fields=["is_active"])
        memberships = list(get_active_memberships(self.user))
        self.assertEqual(len(memberships), 1)
        self.assertEqual(memberships[0].server_id, self.server_b.pk)

    def test_unique_user_server_constraint_still_holds(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                create_membership(self.user, self.server_a)


class ParseServerIdTests(TestCase):
    def test_accepts_positive_int_and_digit_string(self):
        self.assertEqual(_parse_server_id(3), 3)
        self.assertEqual(_parse_server_id("12"), 12)

    def test_rejects_bool_float_malformed_overflow(self):
        self.assertIsNone(_parse_server_id(True))
        self.assertIsNone(_parse_server_id(False))
        self.assertIsNone(_parse_server_id(1.5))
        self.assertIsNone(_parse_server_id("not-an-int"))
        self.assertIsNone(_parse_server_id(""))
        self.assertIsNone(_parse_server_id("  "))
        self.assertIsNone(_parse_server_id("-3"))
        self.assertIsNone(_parse_server_id("0"))
        self.assertIsNone(_parse_server_id(None))
        self.assertIsNone(_parse_server_id([1]))
        self.assertIsNone(_parse_server_id({"id": 1}))


class ServerContextTests(TestCase):
    def setUp(self):
        self.user = create_verified_user()
        self.client = Client()
        self.client.force_login(self.user)
        self.server_a = create_server(name="Alpha Server", slug="alpha-srv")
        self.server_b = create_server(name="Beta Server", slug="beta-srv")
        self.membership_a = create_membership(self.user, self.server_a)
        self.membership_b = create_membership(self.user, self.server_b)

    def test_set_active_server_authorized(self):
        request = self.client.request().wsgi_request
        request.user = self.user
        request.session = self.client.session
        self.assertTrue(set_active_server(request, self.server_b.pk))
        self.assertEqual(
            request.session[ACTIVE_SERVER_SESSION_KEY],
            self.server_b.pk,
        )

    def test_set_active_server_unauthorized(self):
        outsider = create_server(name="Out", slug="out")
        request = self.client.request().wsgi_request
        request.user = self.user
        request.session = self.client.session
        self.assertFalse(set_active_server(request, outsider.pk))
        self.assertNotIn(ACTIVE_SERVER_SESSION_KEY, request.session)

    def test_set_active_server_rejects_left_membership(self):
        self.membership_a.status = MembershipStatus.LEFT
        self.membership_a.save(update_fields=["status"])
        request = self.client.request().wsgi_request
        request.user = self.user
        request.session = self.client.session
        self.assertFalse(set_active_server(request, self.server_a.pk))

    def test_switch_server_view_authorized(self):
        response = self.client.post(
            reverse("servers:switch_server"),
            {"server_id": self.server_b.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.session[ACTIVE_SERVER_SESSION_KEY],
            self.server_b.pk,
        )

    def test_switch_server_view_unauthorized_preserves_prior_selection(self):
        self.client.post(
            reverse("servers:switch_server"),
            {"server_id": self.server_a.pk},
        )
        self.assertEqual(
            self.client.session[ACTIVE_SERVER_SESSION_KEY],
            self.server_a.pk,
        )
        outsider = create_server(name="Out", slug="out-2")
        response = self.client.post(
            reverse("servers:switch_server"),
            {"server_id": outsider.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.session[ACTIVE_SERVER_SESSION_KEY],
            self.server_a.pk,
        )

    def test_switch_server_malformed_id(self):
        self.client.post(
            reverse("servers:switch_server"),
            {"server_id": self.server_a.pk},
        )
        response = self.client.post(
            reverse("servers:switch_server"),
            {"server_id": "not-a-number"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.session[ACTIVE_SERVER_SESSION_KEY],
            self.server_a.pk,
        )

    def test_switch_server_inactive_server_rejected(self):
        self.client.post(
            reverse("servers:switch_server"),
            {"server_id": self.server_a.pk},
        )
        self.server_b.is_active = False
        self.server_b.save(update_fields=["is_active"])
        response = self.client.post(
            reverse("servers:switch_server"),
            {"server_id": self.server_b.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.session[ACTIVE_SERVER_SESSION_KEY],
            self.server_a.pk,
        )

    def test_switch_server_removed_membership_rejected(self):
        self.client.post(
            reverse("servers:switch_server"),
            {"server_id": self.server_a.pk},
        )
        self.membership_b.status = MembershipStatus.REMOVED
        self.membership_b.save(update_fields=["status"])
        response = self.client.post(
            reverse("servers:switch_server"),
            {"server_id": self.server_b.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.session[ACTIVE_SERVER_SESSION_KEY],
            self.server_a.pk,
        )

    def test_switch_server_get_rejected(self):
        response = self.client.get(reverse("servers:switch_server"))
        self.assertEqual(response.status_code, 405)

    def test_switch_server_anonymous_redirects(self):
        self.client.logout()
        response = self.client.post(
            reverse("servers:switch_server"),
            {"server_id": self.server_a.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_switch_server_unverified_forbidden(self):
        unverified = create_verified_user(email="unv@example.com")
        unverified.is_email_verified = False
        unverified.save(update_fields=["is_email_verified"])
        create_membership(unverified, self.server_a)
        self.client.force_login(unverified)
        response = self.client.post(
            reverse("servers:switch_server"),
            {"server_id": self.server_a.pk},
        )
        self.assertEqual(response.status_code, 403)

    def test_dashboard_lists_active_memberships_by_name(self):
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(response.status_code, 200)
        memberships = list(response.context["memberships"])
        self.assertEqual(len(memberships), 2)
        names = {m.server.name for m in memberships}
        self.assertEqual(names, {"Alpha Server", "Beta Server"})
        self.assertContains(response, "Alpha Server")
        self.assertContains(response, "Beta Server")

    def test_dashboard_empty_state(self):
        Membership.objects.filter(user=self.user).delete()
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not a member of any class server")
        self.assertEqual(len(response.context["memberships"]), 0)

    def test_dashboard_single_membership_auto_selects(self):
        self.membership_b.delete()
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_server"].pk, self.server_a.pk)
        self.assertEqual(response.context["active_server"].name, "Alpha Server")


class ResolveActiveServerTests(TestCase):
    def setUp(self):
        self.user = create_verified_user(email="ctx@example.com")
        self.client = Client()
        self.client.force_login(self.user)
        self.server_a = create_server(name="Ctx A", slug="ctx-a")
        self.server_b = create_server(name="Ctx B", slug="ctx-b")
        self.membership_a = create_membership(self.user, self.server_a)
        self.membership_b = create_membership(self.user, self.server_b)

    def _request(self):
        request = self.client.request().wsgi_request
        request.user = self.user
        request.session = self.client.session
        return request

    def test_valid_previously_selected_server(self):
        request = self._request()
        request.session[ACTIVE_SERVER_SESSION_KEY] = self.server_b.pk
        resolved = resolve_active_server(request)
        self.assertEqual(resolved.pk, self.server_b.pk)

    def test_invalid_malformed_session_id(self):
        request = self._request()
        request.session[ACTIVE_SERVER_SESSION_KEY] = "not-an-int"
        resolved = resolve_active_server(request)
        self.assertEqual(resolved.pk, self.server_a.pk)
        self.assertEqual(
            request.session[ACTIVE_SERVER_SESSION_KEY],
            self.server_a.pk,
        )

    def test_boolean_session_id_rejected(self):
        request = self._request()
        request.session[ACTIVE_SERVER_SESSION_KEY] = True
        resolved = resolve_active_server(request)
        # Fallback is earliest membership (joined_at, pk) — server_a in this setup.
        self.assertEqual(resolved.pk, self.server_a.pk)
        self.assertEqual(
            request.session[ACTIVE_SERVER_SESSION_KEY],
            self.server_a.pk,
        )

    def test_float_session_id_rejected(self):
        request = self._request()
        request.session[ACTIVE_SERVER_SESSION_KEY] = 2.9
        resolved = resolve_active_server(request)
        self.assertEqual(resolved.pk, self.server_a.pk)
        self.assertEqual(
            request.session[ACTIVE_SERVER_SESSION_KEY],
            self.server_a.pk,
        )

    def test_session_id_for_server_without_membership(self):
        outsider = create_server(name="Out", slug="ctx-out")
        request = self._request()
        request.session[ACTIVE_SERVER_SESSION_KEY] = outsider.pk
        resolved = resolve_active_server(request)
        self.assertEqual(resolved.pk, self.server_a.pk)
        self.assertEqual(
            request.session[ACTIVE_SERVER_SESSION_KEY],
            self.server_a.pk,
        )

    def test_left_membership_after_selection(self):
        request = self._request()
        request.session[ACTIVE_SERVER_SESSION_KEY] = self.server_a.pk
        self.membership_a.status = MembershipStatus.LEFT
        self.membership_a.save(update_fields=["status"])
        resolved = resolve_active_server(request)
        self.assertEqual(resolved.pk, self.server_b.pk)

    def test_removed_membership_after_selection(self):
        request = self._request()
        request.session[ACTIVE_SERVER_SESSION_KEY] = self.server_b.pk
        self.membership_b.status = MembershipStatus.REMOVED
        self.membership_b.save(update_fields=["status"])
        resolved = resolve_active_server(request)
        self.assertEqual(resolved.pk, self.server_a.pk)

    def test_inactive_server_after_selection(self):
        request = self._request()
        request.session[ACTIVE_SERVER_SESSION_KEY] = self.server_a.pk
        self.server_a.is_active = False
        self.server_a.save(update_fields=["is_active"])
        resolved = resolve_active_server(request)
        self.assertEqual(resolved.pk, self.server_b.pk)

    def test_no_memberships(self):
        Membership.objects.filter(user=self.user).delete()
        request = self._request()
        request.session[ACTIVE_SERVER_SESSION_KEY] = self.server_a.pk
        resolved = resolve_active_server(request)
        self.assertIsNone(resolved)
        self.assertNotIn(ACTIVE_SERVER_SESSION_KEY, request.session)

    def test_single_membership_auto_selection(self):
        self.membership_b.delete()
        request = self._request()
        request.session.pop(ACTIVE_SERVER_SESSION_KEY, None)
        resolved = resolve_active_server(request)
        self.assertEqual(resolved.pk, self.server_a.pk)

    def test_multiple_memberships_no_valid_selection_falls_back(self):
        request = self._request()
        request.session.pop(ACTIVE_SERVER_SESSION_KEY, None)
        resolved = resolve_active_server(request)
        self.assertIsNotNone(resolved)
        self.assertIn(resolved.pk, {self.server_a.pk, self.server_b.pk})


class SubjectAccessPolicyTests(TestCase):
    def setUp(self):
        self.user = create_verified_user()
        self.other = create_verified_user(email="other@example.com", full_name="Other")
        self.server = create_server()
        self.other_server = create_server(name="Other", slug="other")
        create_default_channels(self.server)
        create_default_channels(self.other_server)
        self.subject_cs = Channel.objects.create(
            server=self.server,
            name="Computer Science 101",
            slug="CS101",
            channel_type=ChannelType.SUBJECT,
        )
        self.subject_math = Channel.objects.create(
            server=self.server,
            name="MATH201",
            slug="MATH201",
            channel_type=ChannelType.SUBJECT,
        )
        self.other_subject = Channel.objects.create(
            server=self.other_server,
            name="CS101",
            slug="CS101",
            channel_type=ChannelType.SUBJECT,
        )
        self.membership = create_membership(self.user, self.server)
        MembershipSubject.objects.create(
            membership=self.membership,
            subject_code="CS101",
        )

    def test_student_sees_defaults_and_exact_slug_subjects_only(self):
        channels = list(get_accessible_channels_for_user(self.user, self.server))
        types_and_slugs = {(c.channel_type, c.slug) for c in channels}
        self.assertIn((ChannelType.ANNOUNCEMENTS, "announcements"), types_and_slugs)
        self.assertIn((ChannelType.CALENDAR, "calendar"), types_and_slugs)
        self.assertIn((ChannelType.RULES, "rules"), types_and_slugs)
        self.assertIn((ChannelType.SUBJECT, "CS101"), types_and_slugs)
        self.assertNotIn((ChannelType.SUBJECT, "MATH201"), types_and_slugs)

    def test_non_member_sees_nothing(self):
        self.assertEqual(list(get_accessible_channels_for_user(self.other, self.server)), [])

    def test_cross_server_subject_not_accessible(self):
        self.assertFalse(user_can_access_channel(self.user, self.other_subject))
        self.assertFalse(user_can_access_channel(self.user, self.subject_math))
        self.assertTrue(user_can_access_channel(self.user, self.subject_cs))

    def test_left_membership_loses_access(self):
        self.membership.status = MembershipStatus.LEFT
        self.membership.save(update_fields=["status"])
        self.assertFalse(user_can_access_channel(self.user, self.subject_cs))

    def test_case_variant_slug_denied(self):
        MembershipSubject.objects.filter(membership=self.membership).delete()
        MembershipSubject.objects.create(membership=self.membership, subject_code="cs101")
        # Channel slug is CS101 — exact match required; case variant denied.
        self.assertFalse(user_can_access_channel(self.user, self.subject_cs))

    def test_reversed_capitalization_denied(self):
        MembershipSubject.objects.filter(membership=self.membership).delete()
        MembershipSubject.objects.create(membership=self.membership, subject_code="Cs101")
        self.assertFalse(user_can_access_channel(self.user, self.subject_cs))

    def test_name_match_without_slug_match_denied(self):
        MembershipSubject.objects.filter(membership=self.membership).delete()
        MembershipSubject.objects.create(
            membership=self.membership,
            subject_code="Computer Science 101",
        )
        # Name equals subject_code but slug does not — must deny.
        self.assertFalse(user_can_access_channel(self.user, self.subject_cs))

    def test_spaced_code_without_exact_slug_denied(self):
        MembershipSubject.objects.filter(membership=self.membership).delete()
        MembershipSubject.objects.create(membership=self.membership, subject_code="CS 101")
        channel = Channel.objects.create(
            server=self.server,
            name="CS 101",
            slug="cs-101",
            channel_type=ChannelType.SUBJECT,
        )
        self.assertFalse(user_can_access_channel(self.user, channel))


class PresidentTransferServiceTests(TestCase):
    def setUp(self):
        self.president = create_verified_user(
            email="pres@example.com",
            full_name="President",
            password="StrongPass123",
        )
        self.member = create_verified_user(
            email="member@example.com",
            full_name="Member",
            password="StrongPass123",
        )
        self.outsider = create_verified_user(
            email="out@example.com",
            full_name="Outsider",
        )
        self.server = create_server()
        self.other_server = create_server(name="Other", slug="other-srv")
        self.pres_membership = create_membership(
            self.president, self.server, role=MembershipRole.PRESIDENT
        )
        self.member_membership = create_membership(self.member, self.server)
        create_membership(
            self.president, self.other_server, role=MembershipRole.STUDENT
        )
        create_membership(
            self.outsider, self.other_server, role=MembershipRole.PRESIDENT
        )

    def test_successful_transfer(self):
        transfer_presidency(
            server=self.server,
            acting_user=self.president,
            target_membership_id=self.member_membership.pk,
            password="StrongPass123",
        )
        self.pres_membership.refresh_from_db()
        self.member_membership.refresh_from_db()
        self.assertEqual(self.pres_membership.role, MembershipRole.STUDENT)
        self.assertEqual(self.member_membership.role, MembershipRole.PRESIDENT)
        self.assertEqual(
            Membership.objects.filter(
                server=self.server,
                role=MembershipRole.PRESIDENT,
                status=MembershipStatus.ACTIVE,
            ).count(),
            1,
        )
        other = Membership.objects.get(user=self.president, server=self.other_server)
        self.assertEqual(other.role, MembershipRole.STUDENT)
        self.assertEqual(other.status, MembershipStatus.ACTIVE)

    def test_wrong_password_rejected_unchanged_state(self):
        with self.assertRaises(ValidationError) as ctx:
            transfer_presidency(
                server=self.server,
                acting_user=self.president,
                target_membership_id=self.member_membership.pk,
                password="WrongPassword",
            )
        self.assertIn("password", ctx.exception.message_dict)
        self.pres_membership.refresh_from_db()
        self.member_membership.refresh_from_db()
        self.assertEqual(self.pres_membership.role, MembershipRole.PRESIDENT)
        self.assertEqual(self.member_membership.role, MembershipRole.STUDENT)

    def test_target_id_true_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            transfer_presidency(
                server=self.server,
                acting_user=self.president,
                target_membership_id=True,
                password="StrongPass123",
            )
        self.assertIn("target", ctx.exception.message_dict)

    def test_target_id_false_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            transfer_presidency(
                server=self.server,
                acting_user=self.president,
                target_membership_id=False,
                password="StrongPass123",
            )
        self.assertIn("target", ctx.exception.message_dict)

    def test_target_id_float_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            transfer_presidency(
                server=self.server,
                acting_user=self.president,
                target_membership_id=1.5,
                password="StrongPass123",
            )
        self.assertIn("target", ctx.exception.message_dict)

    def test_target_id_zero_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            transfer_presidency(
                server=self.server,
                acting_user=self.president,
                target_membership_id=0,
                password="StrongPass123",
            )
        self.assertIn("target", ctx.exception.message_dict)

    def test_target_id_negative_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            transfer_presidency(
                server=self.server,
                acting_user=self.president,
                target_membership_id=-1,
                password="StrongPass123",
            )
        self.assertIn("target", ctx.exception.message_dict)

    def test_target_id_malformed_string_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            transfer_presidency(
                server=self.server,
                acting_user=self.president,
                target_membership_id="not-an-id",
                password="StrongPass123",
            )
        self.assertIn("target", ctx.exception.message_dict)

    def test_target_id_none_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            transfer_presidency(
                server=self.server,
                acting_user=self.president,
                target_membership_id=None,
                password="StrongPass123",
            )
        self.assertIn("target", ctx.exception.message_dict)

    def test_missing_password_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            transfer_presidency(
                server=self.server,
                acting_user=self.president,
                target_membership_id=self.member_membership.pk,
                password="",
            )
        self.assertIn("password", ctx.exception.message_dict)
        self.pres_membership.refresh_from_db()
        self.assertEqual(self.pres_membership.role, MembershipRole.PRESIDENT)

    def test_inactive_acting_user_rejected(self):
        self.president.is_active = False
        self.president.save(update_fields=["is_active"])
        with self.assertRaises(ValidationError) as ctx:
            transfer_presidency(
                server=self.server,
                acting_user=self.president,
                target_membership_id=self.member_membership.pk,
                password="StrongPass123",
            )
        self.assertIn("acting_user", ctx.exception.message_dict)
        self.pres_membership.refresh_from_db()
        self.assertEqual(self.pres_membership.role, MembershipRole.PRESIDENT)

    def test_non_president_rejected(self):
        with self.assertRaises(ValidationError):
            transfer_presidency(
                server=self.server,
                acting_user=self.member,
                target_membership_id=self.pres_membership.pk,
                password="StrongPass123",
            )

    def test_self_transfer_rejected(self):
        with self.assertRaises(ValidationError):
            transfer_presidency(
                server=self.server,
                acting_user=self.president,
                target_membership_id=self.pres_membership.pk,
                password="StrongPass123",
            )

    def test_cross_server_target_rejected(self):
        outsider_membership = Membership.objects.get(
            user=self.outsider, server=self.other_server
        )
        with self.assertRaises(ValidationError):
            transfer_presidency(
                server=self.server,
                acting_user=self.president,
                target_membership_id=outsider_membership.pk,
                password="StrongPass123",
            )

    def test_left_target_rejected(self):
        self.member_membership.status = MembershipStatus.LEFT
        self.member_membership.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            transfer_presidency(
                server=self.server,
                acting_user=self.president,
                target_membership_id=self.member_membership.pk,
                password="StrongPass123",
            )

    def test_no_membership_created(self):
        count_before = Membership.objects.count()
        transfer_presidency(
            server=self.server,
            acting_user=self.president,
            target_membership_id=self.member_membership.pk,
            password="StrongPass123",
        )
        self.assertEqual(Membership.objects.count(), count_before)

    def test_subjects_and_timestamps_preserved(self):
        MembershipSubject.objects.create(
            membership=self.member_membership,
            subject_code="CS101",
        )
        joined = self.member_membership.joined_at
        last_act = self.member_membership.last_activated_at
        transfer_presidency(
            server=self.server,
            acting_user=self.president,
            target_membership_id=self.member_membership.pk,
            password="StrongPass123",
        )
        self.member_membership.refresh_from_db()
        self.assertEqual(self.member_membership.joined_at, joined)
        self.assertEqual(self.member_membership.last_activated_at, last_act)
        self.assertEqual(self.member_membership.status, MembershipStatus.ACTIVE)
        self.assertTrue(
            MembershipSubject.objects.filter(
                membership=self.member_membership,
                subject_code="CS101",
            ).exists()
        )

    def test_former_president_loses_authority(self):
        transfer_presidency(
            server=self.server,
            acting_user=self.president,
            target_membership_id=self.member_membership.pk,
            password="StrongPass123",
        )
        self.assertFalse(is_active_president_of_server(self.president, self.server))
        self.assertTrue(is_active_president_of_server(self.member, self.server))


class TransferTransactionRollbackTests(TestCase):
    def setUp(self):
        self.president = create_verified_user(
            email="rollpres@example.com",
            full_name="Roll Pres",
            password="StrongPass123",
        )
        self.member = create_verified_user(
            email="rollmem@example.com",
            full_name="Roll Mem",
            password="StrongPass123",
        )
        self.server = create_server(name="Rollback", slug="rollback")
        self.pres_membership = create_membership(
            self.president, self.server, role=MembershipRole.PRESIDENT
        )
        self.member_membership = create_membership(self.member, self.server)

    def test_rollback_when_target_promotion_fails(self):
        original_save = Membership.save
        call_count = {"n": 0}

        def flaky_save(self, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                raise RuntimeError("simulated promotion failure")
            return original_save(self, *args, **kwargs)

        with patch.object(Membership, "save", flaky_save):
            with self.assertRaises(RuntimeError):
                transfer_presidency(
                    server=self.server,
                    acting_user=self.president,
                    target_membership_id=self.member_membership.pk,
                    password="StrongPass123",
                )

        self.pres_membership.refresh_from_db()
        self.member_membership.refresh_from_db()
        self.assertEqual(self.pres_membership.role, MembershipRole.PRESIDENT)
        self.assertEqual(self.member_membership.role, MembershipRole.STUDENT)


class TransferValidationEdgeCaseTests(TestCase):
    def setUp(self):
        self.president = create_verified_user(
            email="valpres@example.com",
            full_name="Val Pres",
            password="StrongPass123",
        )
        self.member = create_verified_user(
            email="valmem@example.com",
            full_name="Val Mem",
            password="StrongPass123",
        )
        self.server = create_server(name="Val Server", slug="val-srv")
        self.other_server = create_server(name="Val Other", slug="val-other")
        self.pres_membership = create_membership(
            self.president, self.server, role=MembershipRole.PRESIDENT
        )
        self.member_membership = create_membership(self.member, self.server)
        self.other_membership = create_membership(
            self.president, self.other_server, role=MembershipRole.STUDENT
        )
        MembershipSubject.objects.create(
            membership=self.member_membership,
            subject_code="HIST101",
        )
        MembershipSubject.objects.create(
            membership=self.other_membership,
            subject_code="KEEPME",
        )

    def test_unverified_target_rejected(self):
        self.member.is_email_verified = False
        self.member.save(update_fields=["is_email_verified"])
        with self.assertRaises(ValidationError) as ctx:
            transfer_presidency(
                server=self.server,
                acting_user=self.president,
                target_membership_id=self.member_membership.pk,
                password="StrongPass123",
            )
        self.assertIn("target", ctx.exception.message_dict)
        self.pres_membership.refresh_from_db()
        self.assertEqual(self.pres_membership.role, MembershipRole.PRESIDENT)

    def test_inactive_target_account_rejected(self):
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        with self.assertRaises(ValidationError) as ctx:
            transfer_presidency(
                server=self.server,
                acting_user=self.president,
                target_membership_id=self.member_membership.pk,
                password="StrongPass123",
            )
        self.assertIn("target", ctx.exception.message_dict)

    def test_removed_target_membership_rejected(self):
        self.member_membership.status = MembershipStatus.REMOVED
        self.member_membership.save(update_fields=["status"])
        with self.assertRaises(ValidationError) as ctx:
            transfer_presidency(
                server=self.server,
                acting_user=self.president,
                target_membership_id=self.member_membership.pk,
                password="StrongPass123",
            )
        self.assertIn("target", ctx.exception.message_dict)

    def test_inactive_server_rejected(self):
        self.server.is_active = False
        self.server.save(update_fields=["is_active"])
        with self.assertRaises(ValidationError) as ctx:
            transfer_presidency(
                server=self.server,
                acting_user=self.president,
                target_membership_id=self.member_membership.pk,
                password="StrongPass123",
            )
        self.assertIn("server", ctx.exception.message_dict)

    def test_acting_president_no_longer_active_rejected(self):
        self.pres_membership.status = MembershipStatus.LEFT
        self.pres_membership.save(update_fields=["status"])
        with self.assertRaises(ValidationError) as ctx:
            transfer_presidency(
                server=self.server,
                acting_user=self.president,
                target_membership_id=self.member_membership.pk,
                password="StrongPass123",
            )
        self.assertIn("acting_user", ctx.exception.message_dict)

    def test_subjects_and_unrelated_membership_unchanged_on_success(self):
        transfer_presidency(
            server=self.server,
            acting_user=self.president,
            target_membership_id=self.member_membership.pk,
            password="StrongPass123",
        )
        self.member_membership.refresh_from_db()
        self.other_membership.refresh_from_db()
        self.assertEqual(self.member_membership.role, MembershipRole.PRESIDENT)
        self.assertTrue(
            MembershipSubject.objects.filter(
                membership=self.member_membership,
                subject_code="HIST101",
            ).exists()
        )
        self.assertEqual(self.other_membership.role, MembershipRole.STUDENT)
        self.assertEqual(self.other_membership.status, MembershipStatus.ACTIVE)
        self.assertTrue(
            MembershipSubject.objects.filter(
                membership=self.other_membership,
                subject_code="KEEPME",
            ).exists()
        )


class PresidentTransferViewTests(TestCase):
    def setUp(self):
        self.president = create_verified_user(
            email="pres2@example.com",
            full_name="President Two",
            password="StrongPass123",
        )
        self.member = create_verified_user(
            email="member2@example.com",
            full_name="Member Two",
            password="StrongPass123",
        )
        self.server = create_server(name="Transfer Server", slug="xfer")
        self.pres_membership = create_membership(
            self.president, self.server, role=MembershipRole.PRESIDENT
        )
        self.member_membership = create_membership(self.member, self.server)
        self.client = Client()
        self.client.force_login(self.president)

    def test_get_transfer_page_as_president(self):
        response = self.client.get(
            reverse("servers:transfer_presidency", args=[self.server.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Transfer President title")
        self.assertContains(response, self.member.full_name)

    def test_non_president_gets_404(self):
        self.client.force_login(self.member)
        response = self.client.get(
            reverse("servers:transfer_presidency", args=[self.server.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_anonymous_redirects(self):
        self.client.logout()
        response = self.client.get(
            reverse("servers:transfer_presidency", args=[self.server.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_post_successful_transfer(self):
        response = self.client.post(
            reverse("servers:transfer_presidency", args=[self.server.pk]),
            {
                "target_membership_id": self.member_membership.pk,
                "password": "StrongPass123",
                "confirm": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.pres_membership.refresh_from_db()
        self.member_membership.refresh_from_db()
        self.assertEqual(self.pres_membership.role, MembershipRole.STUDENT)
        self.assertEqual(self.member_membership.role, MembershipRole.PRESIDENT)

    def test_post_wrong_password(self):
        response = self.client.post(
            reverse("servers:transfer_presidency", args=[self.server.pk]),
            {
                "target_membership_id": self.member_membership.pk,
                "password": "bad",
                "confirm": "on",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.pres_membership.refresh_from_db()
        self.assertEqual(self.pres_membership.role, MembershipRole.PRESIDENT)

    def test_post_missing_password(self):
        response = self.client.post(
            reverse("servers:transfer_presidency", args=[self.server.pk]),
            {
                "target_membership_id": self.member_membership.pk,
                "confirm": "on",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.pres_membership.refresh_from_db()
        self.assertEqual(self.pres_membership.role, MembershipRole.PRESIDENT)

    def test_post_missing_confirmation(self):
        response = self.client.post(
            reverse("servers:transfer_presidency", args=[self.server.pk]),
            {
                "target_membership_id": self.member_membership.pk,
                "password": "StrongPass123",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.pres_membership.refresh_from_db()
        self.assertEqual(self.pres_membership.role, MembershipRole.PRESIDENT)

    def test_replay_after_successful_transfer_denied(self):
        self.client.post(
            reverse("servers:transfer_presidency", args=[self.server.pk]),
            {
                "target_membership_id": self.member_membership.pk,
                "password": "StrongPass123",
                "confirm": "on",
            },
        )
        # Former president tries again.
        response = self.client.get(
            reverse("servers:transfer_presidency", args=[self.server.pk])
        )
        self.assertEqual(response.status_code, 404)
        response = self.client.post(
            reverse("servers:transfer_presidency", args=[self.server.pk]),
            {
                "target_membership_id": self.pres_membership.pk,
                "password": "StrongPass123",
                "confirm": "on",
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_dashboard_shows_transfer_link_for_active_president(self):
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Transfer President title")


class TransferEligibleListFilterTests(TestCase):
    def setUp(self):
        self.president = create_verified_user(
            email="eligpres@example.com",
            full_name="Elig Pres",
            password="StrongPass123",
        )
        self.good = create_verified_user(
            email="eliggood@example.com",
            full_name="Elig Good",
        )
        self.unverified = create_verified_user(
            email="eligunv@example.com",
            full_name="Elig Unverified",
        )
        self.unverified.is_email_verified = False
        self.unverified.save(update_fields=["is_email_verified"])
        self.inactive = create_verified_user(
            email="eliginact@example.com",
            full_name="Elig Inactive",
        )
        self.inactive.is_active = False
        self.inactive.save(update_fields=["is_active"])
        self.server = create_server(name="Elig", slug="elig")
        create_membership(
            self.president, self.server, role=MembershipRole.PRESIDENT
        )
        create_membership(self.good, self.server)
        create_membership(self.unverified, self.server)
        create_membership(self.inactive, self.server)
        self.client = Client()
        self.client.force_login(self.president)

    def test_eligible_list_excludes_unverified_and_inactive(self):
        response = self.client.get(
            reverse("servers:transfer_presidency", args=[self.server.pk])
        )
        self.assertEqual(response.status_code, 200)
        eligible = list(response.context["eligible_members"])
        user_ids = {m.user_id for m in eligible}
        self.assertIn(self.good.pk, user_ids)
        self.assertNotIn(self.unverified.pk, user_ids)
        self.assertNotIn(self.inactive.pk, user_ids)
        self.assertNotIn(self.president.pk, user_ids)


class MultiServerPresidentIsolationTests(TestCase):
    def setUp(self):
        self.user = create_verified_user(
            email="multi@example.com",
            password="StrongPass123",
        )
        self.server_a = create_server(name="A", slug="iso-a")
        self.server_b = create_server(name="B", slug="iso-b")
        self.other = create_verified_user(
            email="recv@example.com",
            full_name="Receiver",
            password="StrongPass123",
        )
        self.pres_a = create_membership(
            self.user, self.server_a, role=MembershipRole.PRESIDENT
        )
        self.student_b = create_membership(
            self.user, self.server_b, role=MembershipRole.STUDENT
        )
        self.recv_a = create_membership(self.other, self.server_a)

    def test_president_only_in_server_a(self):
        self.assertTrue(is_active_president_of_server(self.user, self.server_a))
        self.assertFalse(is_active_president_of_server(self.user, self.server_b))

    def test_transfer_in_a_does_not_affect_b(self):
        transfer_presidency(
            server=self.server_a,
            acting_user=self.user,
            target_membership_id=self.recv_a.pk,
            password="StrongPass123",
        )
        self.student_b.refresh_from_db()
        self.assertEqual(self.student_b.role, MembershipRole.STUDENT)
        self.assertEqual(self.student_b.status, MembershipStatus.ACTIVE)
        self.assertFalse(is_active_president_of_server(self.user, self.server_a))
        self.assertFalse(is_active_president_of_server(self.user, self.server_b))

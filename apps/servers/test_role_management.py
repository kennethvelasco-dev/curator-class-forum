"""Acceptance tests for server-scoped President and Officer role management."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, connections
from django.test import (
    Client,
    TestCase,
    TransactionTestCase,
)
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.servers.models import (
    JoinRequest,
    Membership,
    MembershipRole,
    MembershipStatus,
    MembershipSubject,
    RequestStatus,
    Server,
)
from apps.servers.services.roles import change_member_role
from apps.servers.services.server_requests import decide_join_request
from apps.servers.services.transfer import transfer_presidency


User = get_user_model()


def create_user(email, **kwargs):
    return User.objects.create_user(
        email=email,
        password="StrongPass123",
        full_name=kwargs.pop("full_name", email),
        is_email_verified=kwargs.pop("is_email_verified", True),
        **kwargs,
    )


def create_membership(
    user,
    server,
    *,
    role=MembershipRole.STUDENT,
    status=MembershipStatus.ACTIVE,
):
    return Membership.objects.create(
        user=user,
        server=server,
        role=role,
        status=status,
    )


def member_list_url(server):
    return reverse("servers:server_member_list", args=[server.pk])


def role_change_url(server, membership):
    return reverse(
        "servers:change_member_role",
        args=[server.pk, membership.pk],
    )


class MemberRoleServiceTests(TestCase):
    def setUp(self):
        self.president = create_user("president@example.com")
        self.student = create_user("student@example.com")
        self.server = Server.objects.create(name="Class A", slug="class-a")
        self.president_membership = create_membership(
            self.president,
            self.server,
            role=MembershipRole.PRESIDENT,
        )
        self.student_membership = create_membership(self.student, self.server)
        self.subject = MembershipSubject.objects.create(
            membership=self.student_membership,
            subject_code="CS101",
            subject_name="Computer Science",
        )

    def change_role(
        self,
        *,
        target=None,
        role=MembershipRole.OFFICER,
        actor=None,
        server=None,
    ):
        return change_member_role(
            server=server or self.server,
            acting_user=actor or self.president,
            target_membership_id=(target or self.student_membership).pk,
            new_role=role,
        )

    def test_r01_president_promotes_student_and_updates_timestamp(self):
        previous_updated_at = self.student_membership.updated_at

        updated, changed = self.change_role()

        self.student_membership.refresh_from_db()
        self.assertTrue(changed)
        self.assertEqual(updated.pk, self.student_membership.pk)
        self.assertEqual(self.student_membership.role, MembershipRole.OFFICER)
        self.assertGreater(self.student_membership.updated_at, previous_updated_at)

    def test_r02_demoting_officer_preserves_subject_records(self):
        self.student_membership.role = MembershipRole.OFFICER
        self.student_membership.save(update_fields=["role"])
        original_subjects = list(
            MembershipSubject.objects.filter(
                membership=self.student_membership
            ).values_list("pk", "subject_code", "subject_name", "created_at")
        )

        _, changed = self.change_role(role=MembershipRole.STUDENT)

        self.assertTrue(changed)
        self.student_membership.refresh_from_db()
        self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)
        self.assertEqual(
            list(
                MembershipSubject.objects.filter(
                    membership=self.student_membership
                ).values_list("pk", "subject_code", "subject_name", "created_at")
            ),
            original_subjects,
        )

    def test_r03_same_role_is_a_noop_without_membership_update(self):
        with CaptureQueriesContext(connection) as queries:
            membership, changed = self.change_role(role=MembershipRole.STUDENT)

        membership_updates = [
            query["sql"]
            for query in queries
            if query["sql"].lstrip().upper().startswith("UPDATE")
            and "SERVERS_MEMBERSHIP" in query["sql"].upper()
        ]
        self.assertFalse(changed)
        self.assertEqual(membership.pk, self.student_membership.pk)
        self.assertEqual(membership_updates, [])

    def test_r04_president_target_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.change_role(
                target=self.president_membership,
                role=MembershipRole.STUDENT,
            )

        self.president_membership.refresh_from_db()
        self.assertEqual(
            self.president_membership.role,
            MembershipRole.PRESIDENT,
        )

    def test_r05_president_cannot_change_own_membership(self):
        with self.assertRaises(ValidationError):
            self.change_role(
                target=self.president_membership,
                role=MembershipRole.OFFICER,
            )

        self.president_membership.refresh_from_db()
        self.assertEqual(
            self.president_membership.role,
            MembershipRole.PRESIDENT,
        )

    def test_r06_left_and_removed_memberships_are_rejected(self):
        for status in (MembershipStatus.LEFT, MembershipStatus.REMOVED):
            with self.subTest(status=status):
                self.student_membership.status = status
                self.student_membership.save(update_fields=["status"])

                with self.assertRaises(ValidationError):
                    self.change_role()

                self.student_membership.refresh_from_db()
                self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)
                self.assertEqual(self.student_membership.status, status)
                self.student_membership.status = MembershipStatus.ACTIVE
                self.student_membership.save(update_fields=["status"])

    def test_r07_service_rejects_president_admin_empty_and_unknown_roles(self):
        for role in ("president", "admin", "", "unknown"):
            with self.subTest(role=role):
                with self.assertRaises(ValidationError):
                    self.change_role(role=role)

                self.student_membership.refresh_from_db()
                self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)

    def test_unicode_and_malformed_membership_ids_raise_validation_error(self):
        invalid_ids = (
            "²",
            "³",
            "\u0661\u0662",
            "¹²³",
            "½",
            "0",
            "-5",
            None,
            True,
            False,
            "abc",
            "",
            "   ",
        )
        for raw_id in invalid_ids:
            with self.subTest(raw_id=raw_id):
                with self.assertRaises(ValidationError) as ctx:
                    change_member_role(
                        server=self.server,
                        acting_user=self.president,
                        target_membership_id=raw_id,
                        new_role=MembershipRole.OFFICER,
                    )
                self.assertIn("target_membership_id", ctx.exception.message_dict)

    def test_stale_role_change_submission_rejected(self):
        # Stale promotion: form thought target was student, but target is already officer
        self.student_membership.role = MembershipRole.OFFICER
        self.student_membership.save(update_fields=["role"])

        with self.assertRaises(ValidationError) as ctx:
            change_member_role(
                server=self.server,
                acting_user=self.president,
                target_membership_id=self.student_membership.pk,
                new_role=MembershipRole.OFFICER,
                expected_role="student",
            )
        self.assertIn("expected_role", ctx.exception.message_dict)
        self.student_membership.refresh_from_db()
        self.assertEqual(self.student_membership.role, MembershipRole.OFFICER)

        # Stale demotion: form thought target was officer, but target is already student
        self.student_membership.role = MembershipRole.STUDENT
        self.student_membership.save(update_fields=["role"])

        with self.assertRaises(ValidationError) as ctx:
            change_member_role(
                server=self.server,
                acting_user=self.president,
                target_membership_id=self.student_membership.pk,
                new_role=MembershipRole.STUDENT,
                expected_role="officer",
            )
        self.assertIn("expected_role", ctx.exception.message_dict)
        self.student_membership.refresh_from_db()
        self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)

    def test_valid_expected_role_succeeds(self):
        updated, changed = change_member_role(
            server=self.server,
            acting_user=self.president,
            target_membership_id=self.student_membership.pk,
            new_role=MembershipRole.OFFICER,
            expected_role="student",
        )
        self.assertTrue(changed)
        self.student_membership.refresh_from_db()
        self.assertEqual(self.student_membership.role, MembershipRole.OFFICER)

    def test_target_must_be_active_and_verified(self):
        for field, value in (("is_active", False), ("is_email_verified", False)):
            with self.subTest(field=field):
                setattr(self.student, field, value)
                self.student.save(update_fields=[field])

                with self.assertRaises(ValidationError):
                    self.change_role()

                self.student_membership.refresh_from_db()
                self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)
                setattr(self.student, field, True)
                self.student.save(update_fields=[field])

    def test_actor_must_be_active_and_verified(self):
        for field, value in (("is_active", False), ("is_email_verified", False)):
            with self.subTest(field=field):
                setattr(self.president, field, value)
                self.president.save(update_fields=[field])

                with self.assertRaises(ValidationError):
                    self.change_role()

                self.student_membership.refresh_from_db()
                self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)
                setattr(self.president, field, True)
                self.president.save(update_fields=[field])

    def test_actor_must_be_active_president_of_requested_server(self):
        officer = create_user("officer@example.com")
        create_membership(
            officer,
            self.server,
            role=MembershipRole.OFFICER,
        )
        other_server = Server.objects.create(name="Class B", slug="class-b")
        other_president = create_user("other-president@example.com")
        create_membership(
            other_president,
            other_server,
            role=MembershipRole.PRESIDENT,
        )

        for actor in (officer, other_president):
            with self.subTest(actor=actor.email):
                with self.assertRaises(ValidationError):
                    self.change_role(actor=actor)
                self.student_membership.refresh_from_db()
                self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)

    def test_inactive_president_membership_cannot_manage_roles(self):
        self.president_membership.status = MembershipStatus.LEFT
        self.president_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.change_role()

        self.student_membership.refresh_from_db()
        self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)

    def test_inactive_server_is_rejected(self):
        self.server.is_active = False
        self.server.save(update_fields=["is_active"])

        with self.assertRaises(ValidationError):
            self.change_role()

        self.student_membership.refresh_from_db()
        self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)

    def test_cross_server_membership_id_is_rejected(self):
        other_server = Server.objects.create(name="Class B", slug="class-b")
        other_member = create_user("other-member@example.com")
        other_membership = create_membership(other_member, other_server)

        with self.assertRaises(ValidationError):
            self.change_role(target=other_membership)

        self.student_membership.refresh_from_db()
        other_membership.refresh_from_db()
        self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)
        self.assertEqual(other_membership.role, MembershipRole.STUDENT)

    def test_invalid_operation_preserves_all_membership_state(self):
        other_server = Server.objects.create(name="Class B", slug="class-b")
        other_member = create_user("other-member@example.com")
        other_membership = create_membership(other_member, other_server)
        tracked = (
            self.president_membership,
            self.student_membership,
            other_membership,
        )
        before = {
            membership.pk: (membership.role, membership.status, membership.updated_at)
            for membership in tracked
        }

        with self.assertRaises(ValidationError):
            self.change_role(target=other_membership)

        for membership in tracked:
            membership.refresh_from_db()
            self.assertEqual(
                (
                    membership.role,
                    membership.status,
                    membership.updated_at,
                ),
                before[membership.pk],
            )

    def test_role_change_preserves_status_subjects_and_other_server_membership(self):
        other_server = Server.objects.create(name="Class B", slug="class-b")
        other_membership = create_membership(self.student, other_server)
        original_timestamps = (
            self.student_membership.joined_at,
            self.student_membership.last_activated_at,
            self.student_membership.left_at,
            self.student_membership.created_at,
        )
        original_subject = (
            self.subject.pk,
            self.subject.subject_code,
            self.subject.subject_name,
            self.subject.created_at,
        )

        self.change_role()

        self.student_membership.refresh_from_db()
        other_membership.refresh_from_db()
        self.assertEqual(self.student_membership.status, MembershipStatus.ACTIVE)
        self.assertEqual(
            (
                self.student_membership.joined_at,
                self.student_membership.last_activated_at,
                self.student_membership.left_at,
                self.student_membership.created_at,
            ),
            original_timestamps,
        )
        subject = self.student_membership.subjects.get()
        self.assertEqual(
            (
                subject.pk,
                subject.subject_code,
                subject.subject_name,
                subject.created_at,
            ),
            original_subject,
        )
        self.assertEqual(other_membership.role, MembershipRole.STUDENT)
        self.assertEqual(other_membership.status, MembershipStatus.ACTIVE)


class MemberRoleViewTests(TestCase):
    def setUp(self):
        self.president = create_user("view-president@example.com")
        self.student = create_user("view-student@example.com")
        self.server = Server.objects.create(name="View Class", slug="view-class")
        self.president_membership = create_membership(
            self.president,
            self.server,
            role=MembershipRole.PRESIDENT,
        )
        self.student_membership = create_membership(self.student, self.server)
        self.client = Client()
        self.client.force_login(self.president)
        self.list_url = member_list_url(self.server)
        self.role_url = role_change_url(self.server, self.student_membership)

    def test_r01_promote_post_redirects_and_reports_success(self):
        previous_updated_at = self.student_membership.updated_at

        response = self.client.post(
            self.role_url,
            {"new_role": MembershipRole.OFFICER},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, self.list_url)
        self.assertIn(
            "The member's role was updated.",
            [str(message) for message in response.context["messages"]],
        )
        self.student_membership.refresh_from_db()
        self.assertEqual(self.student_membership.role, MembershipRole.OFFICER)
        self.assertGreater(self.student_membership.updated_at, previous_updated_at)

    def test_r02_demotion_preserves_subjects(self):
        self.student_membership.role = MembershipRole.OFFICER
        self.student_membership.save(update_fields=["role"])
        subject = MembershipSubject.objects.create(
            membership=self.student_membership,
            subject_code="MATH201",
        )

        response = self.client.post(
            self.role_url,
            {"new_role": MembershipRole.STUDENT},
        )

        self.assertEqual(response.status_code, 302)
        self.student_membership.refresh_from_db()
        self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)
        self.assertEqual(
            list(self.student_membership.subjects.values_list("pk", flat=True)),
            [subject.pk],
        )

    def test_r03_same_role_post_is_informational_and_does_not_update_membership(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.post(
                self.role_url,
                {"new_role": MembershipRole.STUDENT},
                follow=True,
            )

        membership_updates = [
            query["sql"]
            for query in queries
            if query["sql"].lstrip().upper().startswith("UPDATE")
            and "SERVERS_MEMBERSHIP" in query["sql"].upper()
        ]
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "The member already has that role.",
            [str(message) for message in response.context["messages"]],
        )
        self.assertEqual(membership_updates, [])

    def test_r04_and_r05_president_target_and_self_change_are_rejected(self):
        url = role_change_url(self.server, self.president_membership)
        for role in (MembershipRole.STUDENT, MembershipRole.OFFICER):
            with self.subTest(role=role):
                response = self.client.post(url, {"new_role": role})
                self.assertEqual(response.status_code, 400)
                self.president_membership.refresh_from_db()
                self.assertEqual(
                    self.president_membership.role,
                    MembershipRole.PRESIDENT,
                )

    def test_r06_left_or_removed_memberships_are_rejected(self):
        for status in (MembershipStatus.LEFT, MembershipStatus.REMOVED):
            with self.subTest(status=status):
                self.student_membership.status = status
                self.student_membership.save(update_fields=["status"])
                response = self.client.post(
                    self.role_url,
                    {"new_role": MembershipRole.OFFICER},
                )
                self.assertEqual(response.status_code, 400)
                self.student_membership.refresh_from_db()
                self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)
                self.assertEqual(self.student_membership.status, status)
                self.student_membership.status = MembershipStatus.ACTIVE
                self.student_membership.save(update_fields=["status"])

    def test_r07_form_rejects_president_admin_and_unknown_roles(self):
        for role in ("president", "admin", "", "unknown"):
            with self.subTest(role=role):
                response = self.client.post(self.role_url, {"new_role": role})
                self.assertEqual(response.status_code, 400)
                self.student_membership.refresh_from_db()
                self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)

    def test_r08_officer_cannot_post_role_change(self):
        officer = create_user("role-officer@example.com")
        create_membership(
            officer,
            self.server,
            role=MembershipRole.OFFICER,
        )
        self.client.force_login(officer)

        response = self.client.post(
            self.role_url,
            {"new_role": MembershipRole.OFFICER},
        )

        self.assertEqual(response.status_code, 404)
        self.student_membership.refresh_from_db()
        self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)

    def test_r09_student_cannot_post_role_change(self):
        other_student = create_user("another-student@example.com")
        create_membership(other_student, self.server)
        self.client.force_login(other_student)

        response = self.client.post(
            self.role_url,
            {"new_role": MembershipRole.OFFICER},
        )

        self.assertEqual(response.status_code, 404)
        self.student_membership.refresh_from_db()
        self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)

    def test_r10_anonymous_redirect_and_unverified_forbidden(self):
        self.client.logout()
        anonymous_response = self.client.post(
            self.role_url,
            {"new_role": MembershipRole.OFFICER},
        )
        self.assertEqual(anonymous_response.status_code, 302)
        self.assertIn("/accounts/login/", anonymous_response.url)

        unverified = create_user(
            "unverified@example.com",
            is_email_verified=False,
        )
        self.client.force_login(unverified)
        unverified_response = self.client.post(
            self.role_url,
            {"new_role": MembershipRole.OFFICER},
        )
        self.assertEqual(unverified_response.status_code, 403)
        self.assertTemplateUsed(
            unverified_response,
            "accounts/verification_required.html",
        )
        self.student_membership.refresh_from_db()
        self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)

    def test_r11_president_of_another_server_gets_404(self):
        other_server = Server.objects.create(name="Other", slug="other")
        other_president = create_user("other-president-view@example.com")
        create_membership(
            other_president,
            other_server,
            role=MembershipRole.PRESIDENT,
        )
        self.client.force_login(other_president)

        response = self.client.post(
            self.role_url,
            {"new_role": MembershipRole.OFFICER},
        )

        self.assertEqual(response.status_code, 404)
        self.student_membership.refresh_from_db()
        self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)

    def test_r12_cross_server_membership_id_is_rejected_without_disclosure(self):
        other_server = Server.objects.create(name="Other", slug="other")
        private_user = create_user(
            "private-other@example.com",
            full_name="Private Other Member",
        )
        other_membership = create_membership(private_user, other_server)

        response = self.client.post(
            role_change_url(self.server, other_membership),
            {"new_role": MembershipRole.OFFICER},
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotContains(
            response,
            private_user.full_name,
            status_code=400,
        )
        other_membership.refresh_from_db()
        self.assertEqual(other_membership.role, MembershipRole.STUDENT)

    def test_r13_nonmember_staff_cannot_view_member_list_or_change_roles(self):
        staff_user = create_user("staff@example.com", is_staff=True)
        self.client.force_login(staff_user)

        list_response = self.client.get(self.list_url)
        change_response = self.client.post(
            self.role_url,
            {"new_role": MembershipRole.OFFICER},
        )

        self.assertEqual(list_response.status_code, 404)
        self.assertEqual(change_response.status_code, 404)
        self.student_membership.refresh_from_db()
        self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)

    def test_r14_role_change_endpoint_rejects_get(self):
        response = self.client.get(self.role_url)

        self.assertEqual(response.status_code, 405)
        self.student_membership.refresh_from_db()
        self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)

    def test_r15_role_change_endpoint_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.president)

        response = csrf_client.post(
            self.role_url,
            {"new_role": MembershipRole.OFFICER},
        )

        self.assertEqual(response.status_code, 403)
        self.student_membership.refresh_from_db()
        self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)

    def test_r16_promoted_student_can_view_member_list_without_relogin(self):
        student_client = Client()
        student_client.force_login(self.student)
        president_client = Client()
        president_client.force_login(self.president)
        self.assertEqual(student_client.get(self.list_url).status_code, 404)

        president_client.post(
            self.role_url,
            {"new_role": MembershipRole.OFFICER},
        )

        response = student_client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.student.full_name)

    def test_r17_demoted_officer_loses_member_list_access_without_relogin(self):
        self.student_membership.role = MembershipRole.OFFICER
        self.student_membership.save(update_fields=["role"])
        officer_client = Client()
        officer_client.force_login(self.student)
        president_client = Client()
        president_client.force_login(self.president)
        self.assertEqual(officer_client.get(self.list_url).status_code, 200)

        president_client.post(
            self.role_url,
            {"new_role": MembershipRole.STUDENT},
        )

        response = officer_client.get(self.list_url)

        self.assertEqual(response.status_code, 404)

    def test_r18_user_model_has_no_global_membership_role_fields(self):
        field_names = {field.name for field in User._meta.get_fields()}

        self.assertNotIn("is_president", field_names)
        self.assertNotIn("is_officer", field_names)

    def test_r19_member_list_contains_only_active_members_of_requested_server(self):
        active_officer = create_user(
            "active-officer@example.com",
            full_name="Active Officer",
        )
        create_membership(
            active_officer,
            self.server,
            role=MembershipRole.OFFICER,
        )
        left_member = create_user(
            "left-member@example.com",
            full_name="Left Member",
        )
        create_membership(
            left_member,
            self.server,
            status=MembershipStatus.LEFT,
        )
        other_server = Server.objects.create(name="Other", slug="other")
        other_member = create_user(
            "other-member@example.com",
            full_name="Other Server Member",
        )
        create_membership(other_member, other_server)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.president.full_name)
        self.assertContains(response, self.student.full_name)
        self.assertContains(response, active_officer.full_name)
        self.assertContains(response, 'name="new_role"')
        self.assertNotContains(response, left_member.full_name)
        self.assertNotContains(response, other_member.full_name)

    def test_active_officer_can_view_member_list_without_role_controls(self):
        officer = create_user("list-officer@example.com")
        create_membership(
            officer,
            self.server,
            role=MembershipRole.OFFICER,
        )
        self.client.force_login(officer)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.student.full_name)
        self.assertNotContains(response, 'name="new_role"')

    def test_stale_promotion_post_rejected(self):
        # Target is already officer in database
        self.student_membership.role = MembershipRole.OFFICER
        self.student_membership.save(update_fields=["role"])

        response = self.client.post(
            self.role_url,
            {"expected_role": "student", "new_role": MembershipRole.OFFICER},
        )

        self.assertEqual(response.status_code, 400)
        self.student_membership.refresh_from_db()
        self.assertEqual(self.student_membership.role, MembershipRole.OFFICER)

    def test_stale_demotion_post_rejected(self):
        # Target is already student in database
        self.student_membership.role = MembershipRole.STUDENT
        self.student_membership.save(update_fields=["role"])

        response = self.client.post(
            self.role_url,
            {"expected_role": "officer", "new_role": MembershipRole.STUDENT},
        )

        self.assertEqual(response.status_code, 400)
        self.student_membership.refresh_from_db()
        self.assertEqual(self.student_membership.role, MembershipRole.STUDENT)

    def test_matching_expected_role_post_succeeds(self):
        response = self.client.post(
            self.role_url,
            {"expected_role": "student", "new_role": MembershipRole.OFFICER},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, self.list_url)
        self.student_membership.refresh_from_db()
        self.assertEqual(self.student_membership.role, MembershipRole.OFFICER)

    def test_member_list_renders_hidden_expected_role_input(self):
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="expected_role"')
        self.assertContains(response, 'value="student"')


class MemberRoleTransferConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.president = create_user("concurrent-president@example.com")
        self.target = create_user("concurrent-target@example.com")
        self.server = Server.objects.create(
            name="Concurrent Class",
            slug="concurrent-class",
        )
        create_membership(
            self.president,
            self.server,
            role=MembershipRole.PRESIDENT,
        )
        self.target_membership = create_membership(self.target, self.server)

    @skipUnless(
        connection.vendor == "postgresql",
        "PostgreSQL row-lock concurrency is not verified on this database.",
    )
    def test_r20_concurrent_role_change_and_transfer_keep_one_president(self):
        barrier = Barrier(2)

        def run_role_change():
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                return change_member_role(
                    server=self.server,
                    acting_user=self.president,
                    target_membership_id=self.target_membership.pk,
                    new_role=MembershipRole.OFFICER,
                )
            finally:
                connections.close_all()

        def run_transfer():
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                return transfer_presidency(
                    server=self.server,
                    acting_user=self.president,
                    target_membership_id=self.target_membership.pk,
                    password="StrongPass123",
                )
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            role_future = executor.submit(run_role_change)
            transfer_future = executor.submit(run_transfer)
            outcomes = []
            for future in (role_future, transfer_future):
                try:
                    outcomes.append(future.result(timeout=30))
                except ValidationError:
                    outcomes.append("revalidated-and-rejected")

        self.assertEqual(len(outcomes), 2)
        self.assertEqual(
            Membership.objects.filter(
                server=self.server,
                role=MembershipRole.PRESIDENT,
                status=MembershipStatus.ACTIVE,
            ).count(),
            1,
        )

    @skipUnless(
        connection.vendor == "postgresql",
        "PostgreSQL row-lock concurrency is not verified on this database.",
    )
    def test_concurrent_role_change_and_decide_join_request_no_deadlock(self):
        applicant = create_user("applicant@example.com")
        join_request = JoinRequest.objects.create(
            user=applicant,
            server=self.server,
            student_number="2024-00001",
            status=RequestStatus.PENDING,
        )
        barrier = Barrier(2)

        def run_role_change():
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                return change_member_role(
                    server=self.server,
                    acting_user=self.president,
                    target_membership_id=self.target_membership.pk,
                    new_role=MembershipRole.OFFICER,
                )
            finally:
                connections.close_all()

        def run_join_decision():
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                return decide_join_request(
                    request_id=join_request.pk,
                    reviewer=self.president,
                    decision=RequestStatus.APPROVED,
                    decision_reason="Approved applicant",
                    membership_role=MembershipRole.STUDENT,
                )
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            role_future = executor.submit(run_role_change)
            join_future = executor.submit(run_join_decision)
            outcomes = []
            for future in (role_future, join_future):
                try:
                    outcomes.append(future.result(timeout=30))
                except ValidationError:
                    outcomes.append("revalidated-and-rejected")

        self.assertEqual(len(outcomes), 2)
        # Both operations succeed without any PostgreSQL deadlock
        self.target_membership.refresh_from_db()
        join_request.refresh_from_db()
        self.assertEqual(self.target_membership.role, MembershipRole.OFFICER)
        self.assertEqual(join_request.status, RequestStatus.APPROVED)
        self.assertTrue(
            Membership.objects.filter(
                user=applicant,
                server=self.server,
                role=MembershipRole.STUDENT,
                status=MembershipStatus.ACTIVE,
            ).exists()
        )

    @skipUnless(
        connection.vendor == "postgresql",
        "PostgreSQL row-lock concurrency is not verified on this database.",
    )
    def test_concurrent_role_change_and_decide_join_request_same_target_no_deadlock(self):
        join_request = JoinRequest.objects.create(
            user=self.target,
            server=self.server,
            student_number="2024-00002",
            status=RequestStatus.PENDING,
        )
        barrier = Barrier(2)

        def run_role_change():
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                return change_member_role(
                    server=self.server,
                    acting_user=self.president,
                    target_membership_id=self.target_membership.pk,
                    new_role=MembershipRole.OFFICER,
                )
            finally:
                connections.close_all()

        def run_join_decision():
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                return decide_join_request(
                    request_id=join_request.pk,
                    reviewer=self.president,
                    decision=RequestStatus.APPROVED,
                    decision_reason="Approved duplicate target request",
                    membership_role=MembershipRole.STUDENT,
                )
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            role_future = executor.submit(run_role_change)
            join_future = executor.submit(run_join_decision)
            outcomes = []
            for future in (role_future, join_future):
                try:
                    outcomes.append(future.result(timeout=30))
                except ValidationError:
                    outcomes.append("revalidated-and-rejected")

        self.assertEqual(len(outcomes), 2)
        # Neither operation raised an unhandled database deadlock (OperationalError/DeadlockDetected)
        self.target_membership.refresh_from_db()
        self.assertEqual(self.target_membership.role, MembershipRole.OFFICER)

    def test_sequential_role_change_and_decide_join_request(self):
        join_request = JoinRequest.objects.create(
            user=self.target,
            server=self.server,
            student_number="2024-00001",
            status=RequestStatus.PENDING,
        )
        # Demote target to LEFT so decide_join_request for returning member can run
        self.target_membership.status = MembershipStatus.LEFT
        self.target_membership.save(update_fields=["status"])

        decide_join_request(
            request_id=join_request.pk,
            reviewer=self.president,
            decision=RequestStatus.APPROVED,
            decision_reason="Reactivated member",
            membership_role=MembershipRole.STUDENT,
        )
        self.target_membership.refresh_from_db()
        self.assertEqual(self.target_membership.status, MembershipStatus.ACTIVE)
        self.assertEqual(self.target_membership.role, MembershipRole.STUDENT)

        updated, changed = change_member_role(
            server=self.server,
            acting_user=self.president,
            target_membership_id=self.target_membership.pk,
            new_role=MembershipRole.OFFICER,
            expected_role="student",
        )
        self.assertTrue(changed)
        self.target_membership.refresh_from_db()
        self.assertEqual(self.target_membership.role, MembershipRole.OFFICER)

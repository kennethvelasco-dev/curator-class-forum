import io
from datetime import datetime, timezone as datetime_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase
from pypdf import PdfWriter

from apps.servers.models import (
    JoinRequest,
    JoinRequestSubject,
    Membership,
    MembershipRole,
    MembershipStatus,
    MembershipSubject,
    RequestStatus,
    Server,
)
from apps.servers.forms import JoinRequestForm
from apps.servers.services.server_requests import (
    create_join_request,
    decide_join_request,
)

User = get_user_model()


def make_pdf_upload():
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    output = io.BytesIO()
    writer.write(output)
    return SimpleUploadedFile(
        "registration.pdf",
        output.getvalue(),
        content_type="application/pdf",
    )


def create_user(email, **kwargs):
    return User.objects.create_user(
        email=email,
        password="StrongPassword1",
        full_name="Test User",
        is_email_verified=True,
        **kwargs,
    )


class JoinRequestServiceTests(TestCase):
    def setUp(self):
        self.server = Server.objects.create(
            name="Computer Science",
            slug="computer-science",
        )

    def test_create_join_request_persists_normalized_subjects(self):
        student = create_user("student@example.com")

        request = create_join_request(
            user=student,
            server=self.server,
            student_number="20240001",
            subjects=["CS 201 - 2-1", "MTH 101 - A"],
            cor_file="private/cor.pdf",
        )

        self.assertEqual(request.status, RequestStatus.PENDING)
        self.assertEqual(
            list(request.subjects.values_list("subject_code", flat=True)),
            ["CS 201 - 2-1", "MTH 101 - A"],
        )

    def test_create_join_request_rolls_back_if_subject_persistence_fails(self):
        student = create_user("student@example.com")
        with patch(
            "apps.servers.services.server_requests.JoinRequestSubject.objects.bulk_create",
            side_effect=IntegrityError("simulated subject persistence failure"),
        ):
            with self.assertRaises(IntegrityError):
                create_join_request(
                    user=student,
                    server=self.server,
                    student_number="20240001",
                    subjects=["CS 201 - 2-1"],
                    cor_file="private/cor.pdf",
                )

        self.assertFalse(JoinRequest.objects.exists())

    def test_create_join_request_rejects_duplicate_pending_requests(self):
        student = create_user("student@example.com")
        create_join_request(
            user=student,
            server=self.server,
            student_number="20240001",
            subjects=["CS 201 - 2-1"],
            cor_file="private/cor.pdf",
        )

        with self.assertRaises(ValidationError):
            create_join_request(
                user=student,
                server=self.server,
                student_number="20240002",
                subjects=["MTH 101 - A"],
                cor_file="private/another.pdf",
            )

    def test_create_join_request_rejects_inactive_server(self):
        student = create_user("student@example.com")
        self.server.is_active = False
        self.server.save(update_fields=("is_active",))

        with self.assertRaisesMessage(
            ValidationError,
            "This server is not accepting join requests.",
        ):
            create_join_request(
                user=student,
                server=self.server,
                student_number="20240001",
                subjects=["CS 201 - 2-1"],
                cor_file="private/cor.pdf",
            )

        self.assertFalse(JoinRequest.objects.exists())

    def test_create_join_request_rejects_active_membership(self):
        student = create_user("student@example.com")
        Membership.objects.create(user=student, server=self.server)

        with self.assertRaisesMessage(
            ValidationError,
            "You already belong to this server.",
        ):
            create_join_request(
                user=student,
                server=self.server,
                student_number="20240001",
                subjects=["CS 201 - 2-1"],
                cor_file="private/cor.pdf",
            )

        self.assertFalse(JoinRequest.objects.exists())

    def test_create_join_request_rejects_blank_subject_entries(self):
        student = create_user("student@example.com")
        for subjects in (["CS 201 - 2-1", ""], ["CS 201 - 2-1", "   "], []):
            with self.subTest(subjects=subjects):
                with self.assertRaises(ValidationError):
                    create_join_request(
                        user=student,
                        server=self.server,
                        student_number="20240001",
                        subjects=subjects,
                        cor_file="private/cor.pdf",
                    )

    def test_create_join_request_rejects_duplicate_subjects_after_normalization(self):
        student = create_user("student@example.com")

        with self.assertRaisesMessage(
            ValidationError,
            "Duplicate subject entries are not allowed.",
        ):
            create_join_request(
                user=student,
                server=self.server,
                student_number="20240001",
                subjects=["CS   201 - 2-1", "cs 201 - 2-1"],
                cor_file="private/cor.pdf",
            )

    def test_join_request_form_rejects_blank_entries_and_accepts_multiple_entries(self):
        invalid_inputs = (
            "CS 201 - 2-1\n",
            "CS 201 - 2-1\n   \nMTH 101 - A",
            "CS 201 - 2-1,,MTH 101 - A",
        )
        for value in invalid_inputs:
            with self.subTest(value=value):
                form = JoinRequestForm(
                    data={
                        "server": str(self.server.pk),
                        "registered_name": "Test User",
                        "student_number": "20240001",
                        "subject_entries": value,
                    },
                    files={"cor_file": make_pdf_upload()},
                )
                self.assertFalse(form.is_valid())
                self.assertIn("subject_entries", form.errors)

        form = JoinRequestForm(
            data={
                "server": str(self.server.pk),
                "registered_name": "Test User",
                "student_number": "20240001",
                "subject_entries": "CS 201 - 2-1\nMTH 101 - A",
            },
            files={"cor_file": make_pdf_upload()},
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["subject_entries"],
            ["CS 201 - 2-1", "MTH 101 - A"],
        )

    def test_join_request_form_rejects_normalized_duplicates_and_missing_values(self):
        duplicate_form = JoinRequestForm(
            data={
                "server": str(self.server.pk),
                "registered_name": "Test User",
                "student_number": "20240001",
                "subject_entries": "CS 201 - 2-1\n cs   201 - 2-1 ",
            },
            files={"cor_file": make_pdf_upload()},
        )
        self.assertFalse(duplicate_form.is_valid())
        self.assertIn("subject_entries", duplicate_form.errors)

        missing_form = JoinRequestForm(
            data={
                "server": str(self.server.pk),
                "registered_name": "Test User",
                "student_number": " ",
                "subject_entries": "   ",
            },
            files={"cor_file": make_pdf_upload()},
        )
        self.assertFalse(missing_form.is_valid())
        self.assertIn("student_number", missing_form.errors)
        self.assertIn("subject_entries", missing_form.errors)

    def test_decide_join_request_creates_first_time_membership(self):
        president = create_user("president@example.com")
        Membership.objects.create(
            user=president,
            server=self.server,
            role=MembershipRole.PRESIDENT,
            status=MembershipStatus.ACTIVE,
        )
        student = create_user("student@example.com")

        request = create_join_request(
            user=student,
            server=self.server,
            student_number="20240001",
            subjects=["CS 201 - 2-1", "MTH 101 - A"],
            cor_file="private/cor.pdf",
        )

        decided = decide_join_request(
            request_id=request.pk,
            reviewer=president,
            decision=RequestStatus.APPROVED,
            decision_reason="Welcome.",
        )

        self.assertEqual(decided.status, RequestStatus.APPROVED)
        membership = Membership.objects.get(user=student, server=self.server)
        self.assertEqual(membership.role, MembershipRole.STUDENT)
        self.assertEqual(membership.joined_at, membership.last_activated_at)
        self.assertEqual(membership.joined_at, decided.reviewed_at)
        self.assertEqual(
            list(membership.subjects.values_list("subject_code", flat=True)),
            ["CS 201 - 2-1", "MTH 101 - A"],
        )

    def test_decide_join_request_rejects_a_second_decision_without_changes(self):
        president = create_user("president@example.com")
        Membership.objects.create(
            user=president,
            server=self.server,
            role=MembershipRole.PRESIDENT,
            status=MembershipStatus.ACTIVE,
        )
        student = create_user("student@example.com")
        request = create_join_request(
            user=student,
            server=self.server,
            student_number="20240001",
            subjects=["CS 201 - 2-1"],
            cor_file="private/cor.pdf",
        )

        decide_join_request(
            request_id=request.pk,
            reviewer=president,
            decision=RequestStatus.APPROVED,
            decision_reason="Enrollment confirmed.",
        )

        request.refresh_from_db()
        membership = Membership.objects.get(user=student, server=self.server)
        request_decision = (
            request.status,
            request.decision_reason,
            request.reviewed_by_id,
            request.reviewed_at,
        )
        membership_state = (
            membership.pk,
            membership.role,
            membership.status,
            membership.joined_at,
            membership.last_activated_at,
            membership.left_at,
            list(membership.subjects.values_list("subject_code", flat=True)),
        )

        with self.assertRaisesMessage(
            ValidationError,
            "This request has already been decided.",
        ):
            decide_join_request(
                request_id=request.pk,
                reviewer=president,
                decision=RequestStatus.REJECTED,
                decision_reason="Attempted second decision.",
            )

        request.refresh_from_db()
        membership.refresh_from_db()
        self.assertEqual(
            (
                request.status,
                request.decision_reason,
                request.reviewed_by_id,
                request.reviewed_at,
            ),
            request_decision,
        )
        self.assertEqual(
            (
                membership.pk,
                membership.role,
                membership.status,
                membership.joined_at,
                membership.last_activated_at,
                membership.left_at,
                list(membership.subjects.values_list("subject_code", flat=True)),
            ),
            membership_state,
        )

    def test_decide_join_request_reactivates_existing_membership_with_role(self):
        president = create_user("president@example.com")
        Membership.objects.create(
            user=president,
            server=self.server,
            role=MembershipRole.PRESIDENT,
            status=MembershipStatus.ACTIVE,
        )
        student = create_user("student@example.com")
        membership = Membership.objects.create(
            user=student,
            server=self.server,
            role=MembershipRole.STUDENT,
            status=MembershipStatus.LEFT,
        )
        old_subject = MembershipSubject.objects.create(
            membership=membership,
            subject_code="OLD 100 - 1A",
        )

        request = create_join_request(
            user=student,
            server=self.server,
            student_number="20240001",
            subjects=["CS 201 - 2-1"],
            cor_file="private/cor.pdf",
        )

        approval_time = datetime(2026, 11, 7, 12, 0, tzinfo=datetime_timezone.utc)
        with patch(
            "apps.servers.services.server_requests.timezone.now",
            return_value=approval_time,
        ):
            decide_join_request(
                request_id=request.pk,
                reviewer=president,
                decision=RequestStatus.APPROVED,
                decision_reason="Welcome back.",
                membership_role=MembershipRole.OFFICER,
            )

        membership.refresh_from_db()
        self.assertEqual(membership.pk, request.user.memberships.get(server=self.server).pk)
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)
        self.assertEqual(membership.role, MembershipRole.OFFICER)
        self.assertIsNone(membership.left_at)
        self.assertEqual(membership.joined_at, approval_time)
        self.assertEqual(membership.last_activated_at, approval_time)
        self.assertFalse(MembershipSubject.objects.filter(pk=old_subject.pk).exists())
        self.assertEqual(
            list(membership.subjects.values_list("subject_code", flat=True)),
            ["CS 201 - 2-1"],
        )

    def test_decide_join_request_rejects_without_reason_and_does_not_create_membership(self):
        president = create_user("president@example.com")
        Membership.objects.create(
            user=president,
            server=self.server,
            role=MembershipRole.PRESIDENT,
            status=MembershipStatus.ACTIVE,
        )
        student = create_user("student@example.com")
        prior_membership = Membership.objects.create(
            user=student,
            server=self.server,
            role=MembershipRole.STUDENT,
            status=MembershipStatus.LEFT,
        )
        prior_subject = MembershipSubject.objects.create(
            membership=prior_membership,
            subject_code="OLD 100 - 1A",
        )
        request = JoinRequest.objects.create(
            user=student,
            server=self.server,
            student_number="20240001",
            cor_file=None,
        )
        JoinRequestSubject.objects.create(
            join_request=request,
            subject_code="CS 201 - 2-1",
        )

        with self.assertRaisesMessage(ValidationError, "A reason is required."):
            decide_join_request(
                request_id=request.pk,
                reviewer=president,
                decision=RequestStatus.REJECTED,
                decision_reason="  ",
            )

        decide_join_request(
            request_id=request.pk,
            reviewer=president,
            decision=RequestStatus.REJECTED,
            decision_reason="Not enrolled in this class.",
        )
        request.refresh_from_db()
        self.assertEqual(request.status, RequestStatus.REJECTED)
        self.assertEqual(request.decision_reason, "Not enrolled in this class.")
        prior_membership.refresh_from_db()
        self.assertEqual(prior_membership.status, MembershipStatus.LEFT)
        self.assertTrue(MembershipSubject.objects.filter(pk=prior_subject.pk).exists())

    def test_decision_is_committed_before_cleanup_and_cleanup_failure_does_not_revert(self):
        president = create_user("president@example.com")
        Membership.objects.create(
            user=president,
            server=self.server,
            role=MembershipRole.PRESIDENT,
            status=MembershipStatus.ACTIVE,
        )
        student = create_user("student@example.com")
        request = create_join_request(
            user=student,
            server=self.server,
            student_number="20240001",
            subjects=["CS 201 - 2-1"],
            cor_file="private/cor.pdf",
        )

        def verify_committed_and_fail(decided_request):
            persisted = JoinRequest.objects.get(pk=decided_request.pk)
            self.assertEqual(persisted.status, RequestStatus.APPROVED)
            raise RuntimeError("simulated cleanup failure")

        with patch(
            "apps.servers.services.server_requests.attempt_cor_cleanup",
            side_effect=verify_committed_and_fail,
        ) as cleanup:
            with self.captureOnCommitCallbacks(execute=True):
                decide_join_request(
                    request_id=request.pk,
                    reviewer=president,
                    decision=RequestStatus.APPROVED,
                    decision_reason="Enrolled.",
                )
        request.refresh_from_db()
        self.assertEqual(request.status, RequestStatus.APPROVED)
        cleanup.assert_called_once()

    def test_null_cor_reference_uses_existing_cleanup_without_storage(self):
        president = create_user("president@example.com")
        Membership.objects.create(
            user=president,
            server=self.server,
            role=MembershipRole.PRESIDENT,
            status=MembershipStatus.ACTIVE,
        )
        student = create_user("student@example.com")
        request = JoinRequest.objects.create(
            user=student,
            server=self.server,
            student_number="20240001",
            cor_file=None,
        )
        JoinRequestSubject.objects.create(
            join_request=request,
            subject_code="CS 201 - 2-1",
        )

        with patch(
            "apps.servers.services.server_requests.attempt_cor_cleanup",
        ) as cleanup:
            with self.captureOnCommitCallbacks(execute=True):
                decide_join_request(
                    request_id=request.pk,
                    reviewer=president,
                    decision=RequestStatus.REJECTED,
                    decision_reason="Not enrolled.",
                )

        request.refresh_from_db()
        self.assertEqual(request.cor_cleanup_status, "not_required")
        cleanup.assert_called_once()
        self.assertEqual(cleanup.call_args.args[0].pk, request.pk)

    def test_decide_join_request_rejects_president_role(self):
        president = create_user("president@example.com")
        Membership.objects.create(
            user=president,
            server=self.server,
            role=MembershipRole.PRESIDENT,
            status=MembershipStatus.ACTIVE,
        )
        student = create_user("student@example.com")
        existing_membership = Membership.objects.create(
            user=student,
            server=self.server,
            role=MembershipRole.STUDENT,
            status=MembershipStatus.LEFT,
        )
        request = create_join_request(
            user=student,
            server=self.server,
            student_number="20240001",
            subjects=["CS 201 - 2-1"],
            cor_file="private/cor.pdf",
        )

        with self.assertRaises(ValidationError):
            decide_join_request(
                request_id=request.pk,
                reviewer=president,
                decision=RequestStatus.APPROVED,
                decision_reason="Welcome.",
                membership_role=MembershipRole.PRESIDENT,
            )
        existing_membership.refresh_from_db()
        self.assertEqual(existing_membership.status, MembershipStatus.LEFT)

    def test_returning_member_can_be_reactivated_as_student(self):
        president = create_user("president@example.com")
        Membership.objects.create(
            user=president,
            server=self.server,
            role=MembershipRole.PRESIDENT,
            status=MembershipStatus.ACTIVE,
        )
        student = create_user("student@example.com")
        existing_membership = Membership.objects.create(
            user=student,
            server=self.server,
            role=MembershipRole.OFFICER,
            status=MembershipStatus.REMOVED,
        )
        request = create_join_request(
            user=student,
            server=self.server,
            student_number="20240001",
            subjects=["CS 201 - 2-1"],
            cor_file="private/cor.pdf",
        )

        decide_join_request(
            request_id=request.pk,
            reviewer=president,
            decision=RequestStatus.APPROVED,
            decision_reason="Welcome back.",
            membership_role=MembershipRole.STUDENT,
        )

        existing_membership.refresh_from_db()
        self.assertEqual(existing_membership.role, MembershipRole.STUDENT)
        self.assertEqual(existing_membership.status, MembershipStatus.ACTIVE)

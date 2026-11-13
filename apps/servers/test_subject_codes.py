"""Tests for the canonical subject-code contract and its integration points."""

import io

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from pypdf import PdfWriter

from apps.servers.forms import JoinRequestForm
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
from apps.servers.services.server_requests import (
    create_join_request,
    decide_join_request,
)
from apps.servers.subject_codes import (
    SUBJECT_CODE_MAX_LENGTH,
    SubjectCodeError,
    canonicalize_subject_code,
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


class CanonicalizeSubjectCodeTests(TestCase):
    """Pure unit tests for canonicalize_subject_code."""

    def test_strips_and_collapses_whitespace(self):
        self.assertEqual(
            canonicalize_subject_code("  CS   201  -  2-1  "),
            "CS 201 - 2-1",
        )

    def test_preserves_capitalization(self):
        self.assertEqual(canonicalize_subject_code("Cs 201"), "Cs 201")
        self.assertEqual(canonicalize_subject_code("CS 201"), "CS 201")
        self.assertEqual(canonicalize_subject_code("cs 201"), "cs 201")

    def test_accepts_exactly_max_length(self):
        value = "A" * SUBJECT_CODE_MAX_LENGTH
        self.assertEqual(canonicalize_subject_code(value), value)

    def test_rejects_longer_than_max_length(self):
        value = "A" * (SUBJECT_CODE_MAX_LENGTH + 1)
        with self.assertRaises(SubjectCodeError) as ctx:
            canonicalize_subject_code(value)
        self.assertIn(str(SUBJECT_CODE_MAX_LENGTH), str(ctx.exception))

    def test_rejects_empty_and_whitespace_only(self):
        for raw in ("", "   ", "\t\n", " \n "):
            with self.subTest(raw=repr(raw)):
                with self.assertRaises(SubjectCodeError):
                    canonicalize_subject_code(raw)

    def test_rejects_non_string(self):
        for raw in (None, 123, ["CS 201"], b"CS 201"):
            with self.subTest(raw=raw):
                with self.assertRaises(SubjectCodeError):
                    canonicalize_subject_code(raw)

    def test_rejects_non_printable(self):
        for raw in (
            "CS\x00101",
            "CS\n101",  # newline is non-printable; rejected before normalization
            "CS\t101",  # tab is non-printable; rejected before normalization
            "CS\r101",  # carriage return is non-printable; rejected before normalization
            "CS\x07101",  # control character is non-printable
            "CS\u200b101",  # zero-width space is not printable
        ):
            with self.subTest(raw=repr(raw)):
                with self.assertRaises(SubjectCodeError):
                    canonicalize_subject_code(raw)

    def test_subject_code_error_is_value_error(self):
        self.assertTrue(issubclass(SubjectCodeError, ValueError))


class JoinRequestFormSubjectCodeTests(TestCase):
    def setUp(self):
        self.server = Server.objects.create(
            name="Computer Science",
            slug="computer-science",
        )

    def _form(self, subject_entries, student_number="20240001"):
        return JoinRequestForm(
            data={
                "server": str(self.server.pk),
                "registered_name": "Test User",
                "student_number": student_number,
                "subject_entries": subject_entries,
            },
            files={"cor_file": make_pdf_upload()},
        )

    def test_form_normalizes_whitespace_and_preserves_case(self):
        form = self._form("  CS   201  \n  mth  101  ")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["subject_entries"],
            ["CS 201", "mth 101"],
        )

    def test_form_rejects_case_insensitive_duplicates(self):
        form = self._form("CS 201\ncs 201")
        self.assertFalse(form.is_valid())
        self.assertIn("subject_entries", form.errors)

    def test_form_rejects_empty_and_overlong(self):
        form = self._form("   ")
        self.assertFalse(form.is_valid())
        self.assertIn("subject_entries", form.errors)

        form = self._form("A" * (SUBJECT_CODE_MAX_LENGTH + 1))
        self.assertFalse(form.is_valid())
        self.assertIn("subject_entries", form.errors)

    def test_form_label_indicates_subject_codes_only(self):
        form = JoinRequestForm()
        self.assertEqual(form.fields["subject_entries"].label, "Subject codes")
        help_text = form.fields["subject_entries"].help_text or ""
        self.assertIn("subject codes", help_text.lower())


class JoinRequestServiceSubjectCodeTests(TestCase):
    def setUp(self):
        self.server = Server.objects.create(
            name="Computer Science",
            slug="computer-science",
        )

    def test_create_persists_canonical_codes(self):
        student = create_user("student@example.com")
        request = create_join_request(
            user=student,
            server=self.server,
            student_number="20240001",
            subjects=["  CS   201  ", "MTH 101"],
            cor_file="private/cor.pdf",
        )
        codes = list(request.subjects.values_list("subject_code", flat=True))
        self.assertEqual(codes, ["CS 201", "MTH 101"])

    def test_create_rejects_duplicate_after_canonicalization(self):
        student = create_user("student@example.com")
        with self.assertRaises(ValidationError) as ctx:
            create_join_request(
                user=student,
                server=self.server,
                student_number="20240001",
                subjects=["CS 201", "cs 201"],
                cor_file="private/cor.pdf",
            )
        self.assertIn("subjects", ctx.exception.message_dict)

    def test_create_rejects_non_string_and_empty(self):
        student = create_user("student@example.com")
        with self.assertRaises(ValidationError):
            create_join_request(
                user=student,
                server=self.server,
                student_number="20240001",
                subjects=[None],
                cor_file="private/cor.pdf",
            )
        with self.assertRaises(ValidationError):
            create_join_request(
                user=student,
                server=self.server,
                student_number="20240001",
                subjects=["  "],
                cor_file="private/cor.pdf",
            )

    def test_create_rejects_overlong(self):
        student = create_user("student@example.com")
        with self.assertRaises(ValidationError):
            create_join_request(
                user=student,
                server=self.server,
                student_number="20240001",
                subjects=["X" * (SUBJECT_CODE_MAX_LENGTH + 1)],
                cor_file="private/cor.pdf",
            )

    def test_approval_preserves_canonical_codes(self):
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
            subjects=["  CS 201  ", "mth 101"],
            cor_file="private/cor.pdf",
        )
        decide_join_request(
            request_id=request.pk,
            reviewer=president,
            decision=RequestStatus.APPROVED,
            decision_reason="Enrolled.",
        )
        membership = Membership.objects.get(user=student, server=self.server)
        codes = list(membership.subjects.values_list("subject_code", flat=True))
        self.assertEqual(codes, ["CS 201", "mth 101"])

    def test_approval_rejects_invalid_persisted_subject_code(self):
        """Approval must reject persisted codes that fail the canonical contract."""
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
            cor_file="private/cor.pdf",
        )
        # Persist an invalid code directly (bypassing create_join_request validation).
        JoinRequestSubject.objects.create(
            join_request=request,
            subject_code="",  # empty — fails canonicalize
        )

        with self.assertRaises(ValidationError) as ctx:
            decide_join_request(
                request_id=request.pk,
                reviewer=president,
                decision=RequestStatus.APPROVED,
                decision_reason="Should not approve.",
            )
        self.assertIn("subjects", ctx.exception.message_dict)

        request.refresh_from_db()
        self.assertEqual(request.status, RequestStatus.PENDING)
        self.assertFalse(
            Membership.objects.filter(user=student, server=self.server).exists()
        )

    def test_approval_rejects_case_insensitive_duplicate_persisted_subject_codes(self):
        """Approval must reject case-insensitive duplicates among persisted codes."""
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
            cor_file="private/cor.pdf",
        )
        # UniqueConstraint is case-sensitive; DB accepts both. Approval must not.
        JoinRequestSubject.objects.create(
            join_request=request,
            subject_code="CS 201",
        )
        JoinRequestSubject.objects.create(
            join_request=request,
            subject_code="cs 201",
        )

        with self.assertRaises(ValidationError) as ctx:
            decide_join_request(
                request_id=request.pk,
                reviewer=president,
                decision=RequestStatus.APPROVED,
                decision_reason="Should not approve.",
            )
        self.assertIn("subjects", ctx.exception.message_dict)
        self.assertIn(
            "Duplicate subject entries are not allowed.",
            str(ctx.exception.message_dict["subjects"]),
        )

        request.refresh_from_db()
        self.assertEqual(request.status, RequestStatus.PENDING)
        self.assertFalse(
            Membership.objects.filter(user=student, server=self.server).exists()
        )
        # JoinRequestSubject rows must remain unmodified.
        persisted = list(
            JoinRequestSubject.objects.filter(join_request=request)
            .order_by("pk")
            .values_list("subject_code", flat=True)
        )
        self.assertEqual(persisted, ["CS 201", "cs 201"])

    def test_failed_approval_validation_does_not_modify_existing_membership_subjects(self):
        """Failed approval validation must not change existing membership subjects."""
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
        existing_subject = MembershipSubject.objects.create(
            membership=membership,
            subject_code="OLD 100 - 1A",
        )

        request = JoinRequest.objects.create(
            user=student,
            server=self.server,
            student_number="20240001",
            cor_file="private/cor.pdf",
        )
        # Invalid but DB-storable code (zero-width space is non-printable and
        # fits VARCHAR(64) on PostgreSQL). Approval must reject it.
        JoinRequestSubject.objects.create(
            join_request=request,
            subject_code="CS\u200b101",
        )

        with self.assertRaises(ValidationError):
            decide_join_request(
                request_id=request.pk,
                reviewer=president,
                decision=RequestStatus.APPROVED,
                decision_reason="Should not approve.",
                membership_role=MembershipRole.STUDENT,
            )

        request.refresh_from_db()
        membership.refresh_from_db()
        self.assertEqual(request.status, RequestStatus.PENDING)
        self.assertEqual(membership.status, MembershipStatus.LEFT)
        self.assertTrue(
            MembershipSubject.objects.filter(pk=existing_subject.pk).exists()
        )
        self.assertEqual(
            list(membership.subjects.values_list("subject_code", flat=True)),
            ["OLD 100 - 1A"],
        )

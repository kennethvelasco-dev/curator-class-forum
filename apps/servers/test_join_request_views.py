import io
import tempfile
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from pypdf import PdfWriter

from apps.servers.models import (
    JoinRequest,
    JoinRequestSubject,
    Membership,
    MembershipRole,
    MembershipStatus,
    RequestStatus,
    Server,
)
from apps.servers.storage import delete_cor, get_cor_storage
from apps.servers.validators import MAX_COR_FILE_SIZE


User = get_user_model()


def make_pdf_bytes():
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


VALID_PDF = make_pdf_bytes()


def make_upload(name="registration.pdf", content=VALID_PDF):
    return SimpleUploadedFile(
        name,
        content,
        content_type="application/pdf",
    )


class JoinRequestViewTests(TestCase):
    def setUp(self):
        self.storage_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage_dir.cleanup)
        settings_override = override_settings(
            PRIVATE_COR_STORAGE_ROOT=self.storage_dir.name,
        )
        settings_override.enable()
        self.addCleanup(settings_override.disable)

        self.student = self.create_user("student@example.com", full_name="Test Student")
        self.server = self.create_server("Class A", "class-a")
        self.submit_url = reverse("servers:join_request")

    def create_user(self, email, **extra_fields):
        return User.objects.create_user(
            email=email,
            password="StrongPassword1",
            full_name=extra_fields.pop("full_name", "Test User"),
            is_email_verified=True,
            **extra_fields,
        )

    def create_server(self, name, slug):
        return Server.objects.create(name=name, slug=slug)

    def create_pending_request(self, user, server, *, cor_file=None):
        request = JoinRequest.objects.create(
            user=user,
            server=server,
            student_number="20240001",
            cor_file=cor_file,
        )
        JoinRequestSubject.objects.create(
            join_request=request,
            subject_code="CS 201 - 2-1",
        )
        return request

    def join_data(self, **overrides):
        data = {
            "server": str(self.server.pk),
            "registered_name": self.student.full_name,
            "student_number": "20240001",
            "subject_entries": "CS 201 - 2-1\nMTH 101 - A",
            "cor_file": make_upload(),
        }
        data.update(overrides)
        return data

    def test_anonymous_user_is_redirected_and_unverified_user_is_denied(self):
        response = self.client.post(self.submit_url, self.join_data())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            urlsplit(response.url).path,
            reverse("accounts:login"),
        )

        self.student.is_email_verified = False
        self.student.save(update_fields=("is_email_verified",))
        self.client.force_login(self.student)
        response = self.client.post(self.submit_url, self.join_data())
        self.assertEqual(response.status_code, 403)
        self.assertFalse(JoinRequest.objects.exists())

    def test_verified_student_submission_persists_subjects_and_shows_confirmation(self):
        self.client.force_login(self.student)

        response = self.client.post(
            self.submit_url,
            self.join_data(),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Your join request has been submitted successfully and is pending President review.",
        )
        self.assertContains(response, "Block out your contact number on your CoR")
        request = JoinRequest.objects.get()
        self.assertEqual(request.user, self.student)
        self.assertEqual(request.server, self.server)
        self.assertEqual(request.status, RequestStatus.PENDING)
        self.assertEqual(
            list(request.subjects.values_list("subject_code", flat=True)),
            ["CS 201 - 2-1", "MTH 101 - A"],
        )
        storage = get_cor_storage()
        self.assertTrue(storage.exists(request.cor_file))
        self.assertNotIn("://", request.cor_file)
        with self.assertRaisesMessage(
            ValueError,
            "Private CoR files do not have public URLs.",
        ):
            storage.url(request.cor_file)
        self.assertNotContains(response, request.cor_file)

    def test_inactive_server_and_invalid_subject_or_student_number_are_rejected(self):
        self.client.force_login(self.student)
        self.server.is_active = False
        self.server.save(update_fields=("is_active",))
        response = self.client.post(self.submit_url, self.join_data())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(JoinRequest.objects.exists())

        self.server.is_active = True
        self.server.save(update_fields=("is_active",))
        invalid_data = (
            {"student_number": " ", "subject_entries": "CS 201 - 2-1"},
            {"registered_name": "A different name"},
            {"subject_entries": "CS 201 - 2-1\n"},
            {"subject_entries": "CS 201 - 2-1\n   \nMTH 101 - A"},
            {"subject_entries": "CS 201 - 2-1\n cs   201 - 2-1 "},
            {"subject_entries": "   "},
        )
        for overrides in invalid_data:
            with self.subTest(overrides=overrides):
                response = self.client.post(
                    self.submit_url,
                    self.join_data(**overrides),
                )
                self.assertEqual(response.status_code, 200)
                self.assertFalse(JoinRequest.objects.exists())

    def test_invalid_or_oversized_pdf_is_rejected(self):
        self.client.force_login(self.student)
        response = self.client.post(
            self.submit_url,
            self.join_data(cor_file=make_upload("not-a-pdf.txt", b"not a pdf")),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(JoinRequest.objects.exists())

        oversized_pdf = VALID_PDF + b" " * (
            MAX_COR_FILE_SIZE + 1 - len(VALID_PDF)
        )
        response = self.client.post(
            self.submit_url,
            self.join_data(cor_file=make_upload(content=oversized_pdf)),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(JoinRequest.objects.exists())

    def test_pending_request_and_active_membership_are_rejected(self):
        self.client.force_login(self.student)
        existing_request = self.create_pending_request(self.student, self.server)
        response = self.client.post(self.submit_url, self.join_data())
        self.assertEqual(response.status_code, 200)
        existing_request.delete()

        Membership.objects.create(user=self.student, server=self.server)
        response = self.client.post(self.submit_url, self.join_data())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(JoinRequest.objects.exists())

    def test_database_failure_after_upload_compensates_by_deleting_cor(self):
        self.client.force_login(self.student)
        with (
            patch(
                "apps.servers.views.create_join_request",
                side_effect=IntegrityError("simulated persistence failure"),
            ),
            patch(
                "apps.servers.views.delete_cor",
                wraps=delete_cor,
            ) as delete,
        ):
            response = self.client.post(self.submit_url, self.join_data())

        self.assertEqual(response.status_code, 503)
        self.assertEqual(JoinRequest.objects.count(), 0)
        delete.assert_called_once()
        stored_key = delete.call_args.args[0]
        self.assertFalse(get_cor_storage().exists(stored_key))
        self.assertNotContains(response, stored_key, status_code=503)
        self.assertNotContains(
            response,
            "simulated persistence failure",
            status_code=503,
        )


class JoinRequestPresidentViewTests(TestCase):
    def setUp(self):
        self.storage_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage_dir.cleanup)
        settings_override = override_settings(
            PRIVATE_COR_STORAGE_ROOT=self.storage_dir.name,
        )
        settings_override.enable()
        self.addCleanup(settings_override.disable)

        self.server = Server.objects.create(name="Class A", slug="class-a")
        self.other_server = Server.objects.create(
            name="Class B",
            slug="class-b",
        )
        self.president = self.create_user("president@example.com")
        self.president_membership = self.create_membership(
            self.president,
            self.server,
            MembershipRole.PRESIDENT,
        )
        self.student = self.create_user("student@example.com")
        self.request = self.create_pending_request(self.student, self.server)
        self.queue_url = reverse("servers:join_request_queue")

    def create_user(self, email, **extra_fields):
        return User.objects.create_user(
            email=email,
            password="StrongPassword1",
            full_name=extra_fields.pop("full_name", "Test User"),
            is_email_verified=True,
            **extra_fields,
        )

    def create_membership(self, user, server, role, status=MembershipStatus.ACTIVE):
        return Membership.objects.create(
            user=user,
            server=server,
            role=role,
            status=status,
        )

    def create_pending_request(self, user, server, *, cor_file=None, status=RequestStatus.PENDING):
        request = JoinRequest.objects.create(
            user=user,
            server=server,
            student_number="20240001",
            cor_file=cor_file,
            status=status,
        )
        JoinRequestSubject.objects.create(
            join_request=request,
            subject_code="CS 201 - 2-1",
        )
        return request

    def test_only_active_president_can_view_own_queue(self):
        self.client.force_login(self.president)
        response = self.client.get(self.queue_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test User")
        self.assertContains(response, "20240001")

        other_user = self.create_user("other@example.com")
        self.client.force_login(other_user)
        response = self.client.get(self.queue_url)
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, "20240001", status_code=403)

        officer = self.create_user("officer@example.com")
        self.create_membership(officer, self.server, MembershipRole.OFFICER)
        self.client.force_login(officer)
        self.assertEqual(self.client.get(self.queue_url).status_code, 403)
        decision_url = reverse(
            "servers:decide_join_request",
            args=(self.request.pk,),
        )
        response = self.client.post(
            decision_url,
            {"decision": "approved", "decision_reason": "Accept."},
        )
        self.assertEqual(response.status_code, 302)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, RequestStatus.PENDING)

        inactive_president = self.create_user("inactive@example.com")
        inactive_membership = self.create_membership(
            inactive_president,
            self.server,
            MembershipRole.PRESIDENT,
            MembershipStatus.LEFT,
        )
        self.client.force_login(inactive_president)
        self.assertEqual(self.client.get(self.queue_url).status_code, 403)
        response = self.client.post(
            decision_url,
            {"decision": "approved", "decision_reason": "Accept."},
        )
        self.assertEqual(response.status_code, 302)
        self.request.refresh_from_db()
        inactive_membership.refresh_from_db()
        self.assertEqual(self.request.status, RequestStatus.PENDING)
        self.assertEqual(inactive_membership.status, MembershipStatus.LEFT)

    def test_president_queue_excludes_requests_from_other_servers(self):
        outsider = self.create_user("outsider@example.com")
        self.create_pending_request(outsider, self.other_server)

        self.client.force_login(self.president)
        response = self.client.get(self.queue_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "20240001")
        self.assertEqual(len(response.context["review_items"]), 1)
        self.assertEqual(response.context["review_items"][0].server, self.server)

    def test_non_president_and_other_server_president_cannot_decide_request(self):
        decision_url = reverse(
            "servers:decide_join_request",
            args=(self.request.pk,),
        )
        student = self.create_user("student-reviewer@example.com")
        self.client.force_login(student)
        response = self.client.post(
            decision_url,
            {"decision": "approved", "decision_reason": "Accept."},
        )
        self.assertEqual(response.status_code, 302)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, RequestStatus.PENDING)

        other_president = self.create_user("other-president@example.com")
        self.create_membership(
            other_president,
            self.other_server,
            MembershipRole.PRESIDENT,
        )
        self.client.force_login(other_president)
        response = self.client.post(
            decision_url,
            {"decision": "approved", "decision_reason": "Accept."},
        )
        self.assertEqual(response.status_code, 302)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, RequestStatus.PENDING)
        self.assertFalse(
            Membership.objects.filter(
                user=self.student,
                server=self.server,
            ).exists()
        )

    def test_decision_view_rejects_missing_reason_and_records_valid_rejection(self):
        self.client.force_login(self.president)
        decision_url = reverse(
            "servers:decide_join_request",
            args=(self.request.pk,),
        )
        response = self.client.post(
            decision_url,
            {"decision": "rejected", "decision_reason": "  "},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            "This field is required.",
            [str(message) for message in response.wsgi_request._messages],
        )
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, RequestStatus.PENDING)

        response = self.client.post(
            decision_url,
            {
                "decision": "rejected",
                "decision_reason": "Student is not enrolled.",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, RequestStatus.REJECTED)
        self.assertEqual(
            self.request.decision_reason,
            "Student is not enrolled.",
        )
        self.assertFalse(
            Membership.objects.filter(
                user=self.student,
                server=self.server,
            ).exists()
        )

    def test_authorized_president_can_access_pending_cor_only(self):
        storage = get_cor_storage()
        key = storage.save("registration.pdf", make_upload())
        self.request.cor_file = key
        self.request.save(update_fields=("cor_file",))
        cor_url = reverse(
            "servers:join_request_cor",
            args=(self.request.pk,),
        )

        self.client.force_login(self.president)
        response = self.client.get(cor_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(b"".join(response.streaming_content), VALID_PDF)
        self.assertNotIn(key, response["Content-Disposition"])

        other_president = self.create_user("other-president@example.com")
        self.create_membership(
            other_president,
            self.other_server,
            MembershipRole.PRESIDENT,
        )
        self.client.force_login(other_president)
        response = self.client.get(cor_url)
        self.assertEqual(response.status_code, 404)

        inactive_president = self.create_user("inactive-president@example.com")
        self.create_membership(
            inactive_president,
            self.server,
            MembershipRole.PRESIDENT,
            MembershipStatus.REMOVED,
        )
        self.client.force_login(inactive_president)
        self.assertEqual(self.client.get(cor_url).status_code, 404)

        self.client.force_login(self.student)
        self.assertEqual(self.client.get(cor_url).status_code, 404)

    def test_decided_request_cor_is_not_accessible(self):
        key = get_cor_storage().save("registration.pdf", make_upload())
        self.request.cor_file = key
        self.request.save(update_fields=("cor_file",))
        self.request.status = RequestStatus.REJECTED
        self.request.save(update_fields=("status",))
        self.client.force_login(self.president)

        response = self.client.get(
            reverse("servers:join_request_cor", args=(self.request.pk,)),
        )

        self.assertEqual(response.status_code, 404)

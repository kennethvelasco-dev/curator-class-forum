import io
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from pypdf import PdfWriter

from apps.servers.models import RequestStatus, ServerRequest
from apps.servers.storage import CorDeletionError, delete_cor, get_cor_storage
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


class ServerRequestViewTests(TestCase):
    def setUp(self):
        self.storage_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage_dir.cleanup)
        settings_override = override_settings(
            PRIVATE_COR_STORAGE_ROOT=self.storage_dir.name,
        )
        settings_override.enable()
        self.addCleanup(settings_override.disable)

        self.user = User.objects.create_user(
            email="student@example.com",
            password="StrongPass8",
            full_name="Test Student",
            is_email_verified=True,
        )
        self.url = reverse("servers:server_request")

    def post_valid_request(self, *, follow=False, **overrides):
        data = {
            "proposed_name": "Computer Science",
            "proposed_section": "3A",
            "cor_file": make_upload(),
        }
        data.update(overrides)
        return self.client.post(self.url, data, follow=follow)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.post_valid_request()

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={self.url}",
        )
        self.assertEqual(ServerRequest.objects.count(), 0)

    def test_unverified_user_cannot_submit(self):
        self.user.is_email_verified = False
        self.user.save(update_fields=["is_email_verified"])
        self.client.force_login(self.user)

        response = self.post_valid_request()

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "accounts/verification_required.html")
        self.assertEqual(ServerRequest.objects.count(), 0)

    def test_verified_student_can_submit_and_receives_pending_receipt(self):
        self.client.force_login(self.user)

        response = self.post_valid_request(follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Your server request was submitted and is pending Admin review.",
        )
        request_obj = ServerRequest.objects.get()
        self.assertEqual(request_obj.requester, self.user)
        self.assertEqual(request_obj.status, RequestStatus.PENDING)
        self.assertEqual(request_obj.proposed_name, "Computer Science")
        self.assertEqual(request_obj.proposed_section, "3A")

        storage = get_cor_storage()
        self.assertTrue(storage.exists(request_obj.cor_file))
        with self.assertRaisesMessage(
            ValueError,
            "Private CoR files do not have public URLs.",
        ):
            storage.url(request_obj.cor_file)
        self.assertNotIn("://", request_obj.cor_file)
        self.assertNotContains(response, request_obj.cor_file)
        self.assertNotContains(response, str(storage.location))
        self.assertContains(response, "mask or block out your personal contact number")

    def test_only_active_staff_can_retrieve_a_private_cor(self):
        stored_key = get_cor_storage().save(
            "registration.pdf",
            make_upload(),
        )
        request_obj = ServerRequest.objects.create(
            requester=self.user,
            proposed_name="Computer Science",
            cor_file=stored_key,
        )
        url = reverse(
            "servers:server_request_cor",
            args=[request_obj.pk],
        )
        self.client.force_login(self.user)

        denied_response = self.client.get(url)

        self.assertEqual(denied_response.status_code, 302)
        self.assertEqual(
            urlsplit(denied_response.url).path,
            reverse("admin:login"),
        )

        admin_user = User.objects.create_user(
            email="admin@example.com",
            password="StrongPass8",
            full_name="Platform Admin",
            is_staff=True,
        )
        self.client.force_login(admin_user)

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            b"".join(response.streaming_content),
            VALID_PDF,
        )
        self.assertEqual(
            response["Content-Disposition"],
            'inline; filename="server-request-cor.pdf"',
        )
        self.assertEqual(
            response["Cache-Control"],
            "private, no-store",
        )
        self.assertNotIn(stored_key, response["Content-Disposition"])
        self.assertNotIn(self.storage_dir.name, response["Content-Disposition"])

    def test_staff_can_retrieve_cor_for_pending_request(self):
        stored_key = get_cor_storage().save(
            "registration.pdf",
            make_upload(),
        )
        request_obj = ServerRequest.objects.create(
            requester=self.user,
            proposed_name="Computer Science",
            status=RequestStatus.PENDING,
            cor_file=stored_key,
        )
        admin_user = User.objects.create_user(
            email="admin@example.com",
            password="StrongPass8",
            full_name="Platform Admin",
            is_staff=True,
        )
        self.client.force_login(admin_user)

        response = self.client.get(
            reverse(
                "servers:server_request_cor",
                args=[request_obj.pk],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(b"".join(response.streaming_content), VALID_PDF)

    def test_staff_cannot_retrieve_cor_for_approved_request(self):
        self._assert_staff_cannot_retrieve_decided_request(
            RequestStatus.APPROVED,
        )

    def test_staff_cannot_retrieve_cor_for_rejected_request(self):
        self._assert_staff_cannot_retrieve_decided_request(
            RequestStatus.REJECTED,
        )

    def _assert_staff_cannot_retrieve_decided_request(self, status):
        storage = get_cor_storage()
        stored_key = storage.save("registration.pdf", make_upload())
        request_obj = ServerRequest.objects.create(
            requester=self.user,
            proposed_name="Computer Science",
            status=status,
            cor_file=stored_key,
        )
        admin_user = User.objects.create_user(
            email="admin@example.com",
            password="StrongPass8",
            full_name="Platform Admin",
            is_staff=True,
        )
        self.client.force_login(admin_user)

        response = self.client.get(
            reverse(
                "servers:server_request_cor",
                args=[request_obj.pk],
            )
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(storage.exists(stored_key))

    def test_anonymous_user_cannot_retrieve_private_cor(self):
        request_obj = ServerRequest.objects.create(
            requester=self.user,
            proposed_name="Computer Science",
            cor_file="private/private-key.pdf",
        )

        response = self.client.get(
            reverse(
                "servers:server_request_cor",
                args=[request_obj.pk],
            )
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            urlsplit(response.url).path,
            reverse("admin:login"),
        )

    def test_missing_private_cor_returns_not_found_to_admin(self):
        request_obj = ServerRequest.objects.create(
            requester=self.user,
            proposed_name="Computer Science",
            cor_file="private/missing.pdf",
        )
        admin_user = User.objects.create_user(
            email="admin@example.com",
            password="StrongPass8",
            full_name="Platform Admin",
            is_staff=True,
        )
        self.client.force_login(admin_user)

        response = self.client.get(
            reverse(
                "servers:server_request_cor",
                args=[request_obj.pk],
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_non_pdf_upload_is_rejected(self):
        self.client.force_login(self.user)

        response = self.post_valid_request(cor_file=make_upload("notes.txt"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Upload a PDF file.")
        self.assertEqual(ServerRequest.objects.count(), 0)
        self.assertEqual(list(Path(self.storage_dir.name).iterdir()), [])

    def test_invalid_pdf_content_is_rejected(self):
        self.client.force_login(self.user)

        response = self.post_valid_request(
            cor_file=make_upload(content=b"not a valid PDF"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not a valid PDF")
        self.assertEqual(ServerRequest.objects.count(), 0)

    def test_upload_over_6_mib_is_rejected(self):
        self.client.force_login(self.user)
        content = VALID_PDF + b" " * (
            MAX_COR_FILE_SIZE + 1 - len(VALID_PDF)
        )

        response = self.post_valid_request(
            cor_file=make_upload(content=content),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "no larger than 6 MB")
        self.assertEqual(ServerRequest.objects.count(), 0)

    def test_duplicate_pending_request_is_rejected_and_upload_removed(self):
        ServerRequest.objects.create(
            requester=self.user,
            proposed_name="Existing Class",
        )
        self.client.force_login(self.user)

        with patch("apps.servers.views.get_cor_storage") as storage_factory:
            response = self.post_valid_request()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already have a pending server request")
        self.assertEqual(ServerRequest.objects.count(), 1)
        self.assertEqual(list(Path(self.storage_dir.name).iterdir()), [])
        storage_factory.assert_not_called()

    def test_private_storage_failure_returns_safe_error(self):
        self.client.force_login(self.user)
        sensitive_detail = str(Path(self.storage_dir.name) / "private-path")
        storage = type(
            "FailingStorage",
            (),
            {
                "save": lambda self, name, uploaded_file: (
                    _raise_storage_error(sensitive_detail)
                )
            },
        )()

        with self.assertLogs("apps.servers.views", level="ERROR") as captured:
            with patch(
                "apps.servers.views.get_cor_storage",
                return_value=storage,
            ):
                response = self.post_valid_request()

        self.assertEqual(response.status_code, 503)
        self.assertContains(
            response,
            "We could not securely store your document.",
            status_code=503,
        )
        self.assertNotContains(response, sensitive_detail, status_code=503)
        self.assertNotIn(sensitive_detail, "\n".join(captured.output))
        self.assertNotIn(self.user.email, "\n".join(captured.output))
        self.assertEqual(ServerRequest.objects.count(), 0)

    def test_database_failure_after_storage_compensates_by_deleting_upload(self):
        self.client.force_login(self.user)
        with self.assertLogs("apps.servers.views", level="ERROR") as captured:
            with patch(
                "apps.servers.views.create_server_request",
                side_effect=IntegrityError("private database detail"),
            ), patch(
                "apps.servers.views.delete_cor",
                wraps=delete_cor,
            ) as delete_mock:
                response = self.post_valid_request()

        self.assertEqual(response.status_code, 503)
        self.assertContains(
            response,
            "We could not submit your request.",
            status_code=503,
        )
        deleted_key = delete_mock.call_args.args[0]
        self.assertEqual(delete_mock.call_count, 1)
        self.assertEqual(list(Path(self.storage_dir.name).iterdir()), [])
        self.assertNotContains(response, deleted_key, status_code=503)
        self.assertNotContains(
            response,
            str(Path(self.storage_dir.name)),
            status_code=503,
        )
        self.assertNotIn(deleted_key, "\n".join(captured.output))
        self.assertNotIn(self.user.email, "\n".join(captured.output))

    def test_failed_compensating_delete_logs_no_sensitive_details(self):
        self.client.force_login(self.user)
        with self.assertLogs("apps.servers.views", level="ERROR") as captured:
            with patch(
                "apps.servers.views.create_server_request",
                side_effect=IntegrityError("private database detail"),
            ), patch(
                "apps.servers.views.delete_cor",
                side_effect=CorDeletionError("private storage detail"),
            ) as delete_mock:
                response = self.post_valid_request()

        deleted_key = delete_mock.call_args.args[0]
        log_output = "\n".join(captured.output)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(deleted_key, log_output)
        self.assertNotIn(self.user.email, log_output)
        self.assertNotIn(self.storage_dir.name, log_output)
        self.assertNotIn("private database detail", log_output)
        self.assertNotIn("private storage detail", log_output)
        self.assertEqual(delete_mock.call_count, 2)

    def test_failed_compensating_delete_is_retried_for_same_file(self):
        self.client.force_login(self.user)
        delete_attempts = 0

        def fail_once_then_delete(file_name, *, storage):
            nonlocal delete_attempts
            delete_attempts += 1
            if delete_attempts == 1:
                raise CorDeletionError("transient storage failure")
            return delete_cor(file_name, storage=storage)

        with patch(
            "apps.servers.views.create_server_request",
            side_effect=IntegrityError("private database detail"),
        ), patch(
            "apps.servers.views.delete_cor",
            side_effect=fail_once_then_delete,
        ) as delete_mock:
            response = self.post_valid_request()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(delete_mock.call_count, 2)
        self.assertEqual(
            delete_mock.call_args_list[0].args[0],
            delete_mock.call_args_list[1].args[0],
        )
        self.assertEqual(list(Path(self.storage_dir.name).iterdir()), [])


def _raise_storage_error(detail):
    raise OSError(detail)

import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from apps.channels.models import Channel, ChannelType
from apps.servers.models import (
    CorCleanupStatus,
    Membership,
    MembershipRole,
    MembershipStatus,
    RequestStatus,
    Server,
    ServerRequest,
)
from apps.servers.storage import CorDeletionResult, get_cor_storage

User = get_user_model()


class AdminProvisioningIntegrationTests(TestCase):
    def setUp(self):
        self.storage_tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage_tempdir.cleanup)

        storage_settings = override_settings(
            PRIVATE_COR_STORAGE_ROOT=self.storage_tempdir.name,
        )
        storage_settings.enable()
        self.addCleanup(storage_settings.disable)

        self.requester = User.objects.create_user(
            email="student@example.com",
            password="TestPassword123",
            full_name="Test Student",
            is_email_verified=True,
        )
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="TestPassword123",
            full_name="Platform Admin",
            is_staff=True,
            is_email_verified=True,
        )
        self.officer_user = User.objects.create_user(
            email="officer@example.com",
            password="TestPassword123",
            full_name="Test Officer",
            is_email_verified=True,
        )
        self.president_user = User.objects.create_user(
            email="president@example.com",
            password="TestPassword123",
            full_name="Test President",
            is_email_verified=True,
        )

        self.storage = get_cor_storage()
        self.stored_cor = self.storage.save(
            "registration.pdf",
            ContentFile(b"%PDF private CoR content"),
        )

        self.request_obj = ServerRequest.objects.create(
            requester=self.requester,
            proposed_name="Computer Science",
            proposed_section="3A",
            cor_file=self.stored_cor,
        )

        self.queue_url = reverse("servers:admin_server_request_queue")
        self.decision_url = reverse(
            "servers:decide_server_request", args=[self.request_obj.pk]
        )

    def post_decision(self, decision, reason="Reviewed after checking the CoR"):
        return self.client.post(
            self.decision_url,
            {
                f"request-{self.request_obj.pk}-decision": decision,
                f"request-{self.request_obj.pk}-decision_reason": reason,
            },
        )

    def test_approval_creates_server_president_membership_and_channels(self):
        self.client.force_login(self.admin)

        response = self.post_decision(RequestStatus.APPROVED)

        self.assertRedirects(response, self.queue_url)
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, RequestStatus.APPROVED)
        self.assertEqual(self.request_obj.decision_reason, "Reviewed after checking the CoR")
        self.assertEqual(self.request_obj.reviewed_by, self.admin)
        self.assertIsNotNone(self.request_obj.reviewed_at)
        self.assertIsNotNone(self.request_obj.created_server_id)

        self.assertEqual(Server.objects.count(), 1)
        server = Server.objects.get()
        self.assertEqual(server.name, "Computer Science")
        self.assertEqual(server.section, "3A")
        self.assertEqual(server.created_by, self.requester)

        self.assertEqual(Membership.objects.count(), 1)
        membership = Membership.objects.get()
        self.assertEqual(membership.server, server)
        self.assertEqual(membership.user, self.requester)
        self.assertEqual(membership.role, MembershipRole.PRESIDENT)
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)

        self.assertEqual(Channel.objects.filter(server=server).count(), 3)
        channel_names = set(
            Channel.objects.filter(server=server).values_list("name", flat=True)
        )
        self.assertSetEqual(channel_names, {"Announcements", "Calendar", "Rules"})

        self.assertFalse(
            Membership.objects.filter(user=self.admin).exists()
        )

    def test_rejection_creates_no_resources(self):
        self.client.force_login(self.admin)

        response = self.post_decision(RequestStatus.REJECTED)

        self.assertRedirects(response, self.queue_url)
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, RequestStatus.REJECTED)
        self.assertEqual(self.request_obj.reviewed_by, self.admin)
        self.assertIsNotNone(self.request_obj.reviewed_at)
        self.assertIsNone(self.request_obj.created_server_id)

        self.assertEqual(Server.objects.count(), 0)
        self.assertEqual(Membership.objects.count(), 0)
        self.assertEqual(Channel.objects.count(), 0)

    def test_officer_cannot_access_admin_queue(self):
        server = Server.objects.create(
            name="Computer Science", section="3A", slug="computer-science",
            created_by=self.requester,
        )
        Membership.objects.create(
            user=self.officer_user, server=server,
            role=MembershipRole.OFFICER, status=MembershipStatus.ACTIVE,
        )
        self.client.force_login(self.officer_user)
        response = self.client.get(self.queue_url)
        self.assertEqual(response.status_code, 403)

    def test_president_cannot_access_admin_queue(self):
        server = Server.objects.create(
            name="Computer Science", section="3A", slug="computer-science",
            created_by=self.requester,
        )
        Membership.objects.create(
            user=self.president_user, server=server,
            role=MembershipRole.PRESIDENT, status=MembershipStatus.ACTIVE,
        )
        self.client.force_login(self.president_user)
        response = self.client.get(self.queue_url)
        self.assertEqual(response.status_code, 403)

    def test_officer_cannot_access_decision_endpoint(self):
        server = Server.objects.create(
            name="Computer Science", section="3A", slug="computer-science",
            created_by=self.requester,
        )
        Membership.objects.create(
            user=self.officer_user, server=server,
            role=MembershipRole.OFFICER, status=MembershipStatus.ACTIVE,
        )
        self.client.force_login(self.officer_user)
        response = self.post_decision(RequestStatus.APPROVED)
        self.assertEqual(response.status_code, 403)
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, RequestStatus.PENDING)

    def test_president_cannot_access_decision_endpoint(self):
        server = Server.objects.create(
            name="Computer Science", section="3A", slug="computer-science",
            created_by=self.requester,
        )
        Membership.objects.create(
            user=self.president_user, server=server,
            role=MembershipRole.PRESIDENT, status=MembershipStatus.ACTIVE,
        )
        self.client.force_login(self.president_user)
        response = self.post_decision(RequestStatus.REJECTED)
        self.assertEqual(response.status_code, 403)
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, RequestStatus.PENDING)


class AdminProvisioningCleanupIntegrationTests(TransactionTestCase):
    def setUp(self):
        self.storage_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage_dir.cleanup)

        settings_override = override_settings(
            PRIVATE_COR_STORAGE_ROOT=self.storage_dir.name,
        )
        settings_override.enable()
        self.addCleanup(settings_override.disable)

        self.requester = User.objects.create_user(
            email="student@example.com",
            password="TestPassword123",
            full_name="Test Student",
            is_email_verified=True,
        )
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="TestPassword123",
            full_name="Platform Admin",
            is_staff=True,
            is_email_verified=True,
        )
        self.stored_cor = get_cor_storage().save(
            "registration.pdf",
            ContentFile(b"%PDF private CoR content"),
        )
        self.request_obj = ServerRequest.objects.create(
            requester=self.requester,
            proposed_name="Computer Science",
            proposed_section="3A",
            cor_file=self.stored_cor,
        )
        self.client.force_login(self.admin)

    def post_decision(self, decision):
        return self.client.post(
            reverse(
                "servers:decide_server_request",
                args=[self.request_obj.pk],
            ),
            {
                f"request-{self.request_obj.pk}-decision": decision,
                f"request-{self.request_obj.pk}-decision_reason": (
                    "Reviewed after checking the CoR"
                ),
            },
        )

    def test_approval_cleanup_runs_after_commit(self):
        def verify_committed_request(file_name, *, storage=None):
            self.assertFalse(connection.in_atomic_block)
            saved_request = ServerRequest.objects.get(pk=self.request_obj.pk)
            self.assertEqual(saved_request.status, RequestStatus.APPROVED)
            self.assertEqual(saved_request.cor_file, file_name)
            return CorDeletionResult.DELETED

        with patch(
            "apps.servers.services.cor_cleanup.delete_cor",
            side_effect=verify_committed_request,
        ) as delete:
            response = self.post_decision(RequestStatus.APPROVED)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(delete.call_count, 1)
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, RequestStatus.APPROVED)
        self.assertEqual(
            self.request_obj.cor_cleanup_status, CorCleanupStatus.COMPLETE
        )
        self.assertIsNone(self.request_obj.cor_file)

    def test_rejection_cleanup_runs_after_commit(self):
        def verify_committed_request(file_name, *, storage=None):
            self.assertFalse(connection.in_atomic_block)
            saved_request = ServerRequest.objects.get(pk=self.request_obj.pk)
            self.assertEqual(saved_request.status, RequestStatus.REJECTED)
            return CorDeletionResult.DELETED

        with patch(
            "apps.servers.services.cor_cleanup.delete_cor",
            side_effect=verify_committed_request,
        ) as delete:
            response = self.post_decision(RequestStatus.REJECTED)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(delete.call_count, 1)
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, RequestStatus.REJECTED)
        self.assertEqual(
            self.request_obj.cor_cleanup_status, CorCleanupStatus.COMPLETE
        )
        self.assertIsNone(self.request_obj.cor_file)
        self.assertEqual(Server.objects.count(), 0)
        self.assertEqual(Membership.objects.count(), 0)
        self.assertEqual(Channel.objects.count(), 0)
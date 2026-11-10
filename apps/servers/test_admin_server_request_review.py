import threading
from concurrent.futures import ThreadPoolExecutor
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection
from django.test import (
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)
from django.urls import reverse

from apps.channels.models import Channel, ChannelType
from apps.servers.models import (
    CorCleanupStatus,
    Membership,
    MembershipRole,
    RequestStatus,
    Server,
    ServerRequest,
)
from apps.servers.services.server_requests import (
    _SERVER_SLUG_UNIQUE_CONSTRAINT,
    decide_server_request,
)
from apps.servers.storage import (
    CorDeletionError,
    CorDeletionResult,
    get_cor_storage,
)


User = get_user_model()


class DatabaseErrorWithDiagnostics(Exception):
    def __init__(self, constraint_name):
        self.diag = SimpleNamespace(constraint_name=constraint_name)


class AdminServerRequestReviewTests(TestCase):
    def setUp(self):
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
        )
        self.url = reverse("servers:admin_server_request_queue")

        self.storage_tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage_tempdir.cleanup)

        storage_settings = override_settings(
            PRIVATE_COR_STORAGE_ROOT=self.storage_tempdir.name,
        )
        storage_settings.enable()
        self.addCleanup(storage_settings.disable)

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

        self.client.force_login(self.admin)

    def create_request(self, **kwargs):
        defaults = {
            "proposed_name": "Computer Science",
            "proposed_section": "3A",
            "cor_file": "private/example.pdf",
        }
        defaults.update(kwargs)
        if "requester" not in defaults:
            self._requester_counter = getattr(self, "_requester_counter", 0) + 1
            defaults["requester"] = User.objects.create_user(
                email=f"student{self._requester_counter}@example.com",
                password="TestPassword123",
                full_name="Test Student",
                is_email_verified=True,
            )
        return ServerRequest.objects.create(**defaults)

    def post_decision(self, request_obj, decision, reason="Reviewed"):
        return self.client.post(
            reverse("servers:decide_server_request", args=[request_obj.pk]),
            {
                f"request-{request_obj.pk}-decision": decision,
                f"request-{request_obj.pk}-decision_reason": reason,
            },
        )

    def test_non_admin_cannot_access_queue_or_decision_endpoint(self):
        requester = User.objects.create_user(
            email="nonadmin-requester@example.com",
            password="TestPassword123",
            full_name="Non Admin Requester",
            is_email_verified=True,
        )
        request_obj = self.create_request(requester=requester)
        self.client.force_login(requester)

        queue_response = self.client.get(self.url)
        decision_response = self.post_decision(
            request_obj,
            RequestStatus.APPROVED,
        )

        self.assertEqual(queue_response.status_code, 302)
        self.assertEqual(
            urlsplit(queue_response.url).path,
            reverse("admin:login"),
        )
        self.assertEqual(decision_response.status_code, 302)
        self.assertEqual(
            urlsplit(decision_response.url).path,
            reverse("admin:login"),
        )
        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, RequestStatus.PENDING)
        self.assertEqual(Server.objects.count(), 0)

    def test_pending_queue_only_shows_pending_requests(self):
        pending = self.create_request()
        decided = self.create_request(
            requester=User.objects.create_user(
                email="another@example.com",
                password="TestPassword123",
                full_name="Another Student",
                is_email_verified=True,
            ),
            proposed_name="Another Class",
            status=RequestStatus.REJECTED,
        )
        self.client.force_login(self.admin)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertContains(response, pending.proposed_name)
        self.assertContains(response, pending.requester.email)
        self.assertContains(response, "Review Certificate of Registration")
        self.assertNotContains(response, pending.cor_file)
        self.assertNotContains(response, decided.proposed_name)

    def test_approval_creates_server_president_and_exact_default_channels(self):
        request_obj = self.create_request()
        self.client.force_login(self.admin)

        response = self.post_decision(
            request_obj,
            RequestStatus.APPROVED,
            "  Verified class details  ",
        )

        self.assertRedirects(response, self.url)
        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, RequestStatus.APPROVED)
        self.assertEqual(request_obj.decision_reason, "Verified class details")
        self.assertEqual(request_obj.reviewed_by, self.admin)
        self.assertIsNotNone(request_obj.reviewed_at)
        self.assertIsNotNone(request_obj.created_server_id)

        server = request_obj.created_server
        self.assertEqual(Server.objects.count(), 1)
        self.assertEqual(server.name, request_obj.proposed_name)
        self.assertEqual(server.section, request_obj.proposed_section)
        self.assertEqual(server.created_by, request_obj.requester)

        membership = Membership.objects.get(server=server)
        self.assertEqual(membership.user, request_obj.requester)
        self.assertEqual(membership.role, MembershipRole.PRESIDENT)
        self.assertEqual(Channel.objects.filter(server=server).count(), 3)
        self.assertSetEqual(
            set(
                Channel.objects.filter(server=server).values_list(
                    "channel_type",
                    flat=True,
                )
            ),
            {
                ChannelType.ANNOUNCEMENTS,
                ChannelType.CALENDAR,
                ChannelType.RULES,
            },
        )
        self.assertSetEqual(
            set(
                Channel.objects.filter(server=server).values_list(
                    "name",
                    flat=True,
                )
            ),
            {"Announcements", "Calendar", "Rules"},
        )

    def test_whitespace_only_decision_reason_is_rejected(self):
        request_obj = self.create_request()
        self.client.force_login(self.admin)

        response = self.post_decision(
            request_obj,
            RequestStatus.APPROVED,
            "   ",
        )

        self.assertEqual(response.status_code, 400)
        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, RequestStatus.PENDING)
        self.assertEqual(Server.objects.count(), 0)

    def test_rejection_requires_reason_and_creates_no_server_resources(self):
        request_obj = self.create_request()
        self.client.force_login(self.admin)

        invalid_response = self.post_decision(
            request_obj,
            RequestStatus.REJECTED,
            "   ",
        )

        self.assertEqual(invalid_response.status_code, 400)
        self.assertEqual(Server.objects.count(), 0)

        response = self.post_decision(
            request_obj,
            RequestStatus.REJECTED,
            "The submitted CoR is unreadable",
        )

        self.assertRedirects(response, self.url)
        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, RequestStatus.REJECTED)
        self.assertEqual(
            request_obj.decision_reason,
            "The submitted CoR is unreadable",
        )
        self.assertEqual(request_obj.reviewed_by, self.admin)
        self.assertIsNotNone(request_obj.reviewed_at)
        self.assertIsNone(request_obj.created_server_id)
        self.assertEqual(Server.objects.count(), 0)
        self.assertEqual(Membership.objects.count(), 0)
        self.assertEqual(Channel.objects.count(), 0)

    def test_failed_channel_creation_rolls_back_approval_resources(self):
        request_obj = self.create_request()
        self.client.force_login(self.admin)

        original_save = Channel.save

        def fail_on_rules_channel(channel, *args, **kwargs):
            if channel.channel_type == ChannelType.RULES:
                raise IntegrityError("simulated channel failure")
            return original_save(channel, *args, **kwargs)

        with patch(
            "apps.channels.models.Channel.save",
            new=fail_on_rules_channel,
        ):
            response = self.post_decision(
                request_obj,
                RequestStatus.APPROVED,
                "Verified class details",
            )

        self.assertRedirects(response, self.url)
        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, RequestStatus.PENDING)
        self.assertEqual(
            request_obj.cor_cleanup_status,
            CorCleanupStatus.NOT_REQUIRED,
        )
        self.assertEqual(request_obj.cor_cleanup_attempts, 0)
        self.assertEqual(request_obj.cor_file, "private/example.pdf")
        self.assertIsNone(request_obj.created_server_id)
        self.assertIsNone(request_obj.reviewed_by_id)
        self.assertIsNone(request_obj.reviewed_at)
        self.assertEqual(request_obj.decision_reason, "")
        self.assertEqual(Server.objects.count(), 0)
        self.assertEqual(Membership.objects.count(), 0)
        self.assertEqual(Channel.objects.count(), 0)

    def test_server_slug_unique_constraint_collision_is_retried(self):
        request_obj = self.create_request()
        self.client.force_login(self.admin)
        original_save = Server.save
        save_attempts = 0

        def fail_first_server_save(server, *args, **kwargs):
            nonlocal save_attempts
            save_attempts += 1
            if save_attempts == 1:
                error = IntegrityError("duplicate server slug")
                error.__cause__ = DatabaseErrorWithDiagnostics(
                    _SERVER_SLUG_UNIQUE_CONSTRAINT,
                )
                raise error
            return original_save(server, *args, **kwargs)

        with patch.object(Server, "save", new=fail_first_server_save):
            response = self.post_decision(
                request_obj,
                RequestStatus.APPROVED,
            )

        self.assertRedirects(response, self.url)
        request_obj.refresh_from_db()
        self.assertEqual(save_attempts, 2)
        self.assertTrue(request_obj.created_server.slug.endswith(
            f"-{request_obj.pk}-2"
        ))
        self.assertEqual(Server.objects.count(), 1)
        self.assertEqual(Membership.objects.count(), 1)
        self.assertEqual(Channel.objects.count(), 3)

    def test_unrelated_server_integrity_error_is_not_retried_or_concealed(self):
        request_obj = self.create_request()
        self.client.force_login(self.admin)

        with patch.object(
            Server,
            "save",
            side_effect=IntegrityError("unrelated server constraint"),
        ) as save:
            response = self.post_decision(
                request_obj,
                RequestStatus.APPROVED,
            )

        self.assertRedirects(response, self.url)
        self.assertEqual(save.call_count, 1)
        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, RequestStatus.PENDING)
        self.assertIsNone(request_obj.created_server_id)
        self.assertEqual(Server.objects.count(), 0)
        self.assertEqual(Membership.objects.count(), 0)
        self.assertEqual(Channel.objects.count(), 0)

    def test_repeated_decision_does_not_duplicate_or_overwrite_resources(self):
        request_obj = self.create_request()
        self.client.force_login(self.admin)

        first_response = self.post_decision(
            request_obj,
            RequestStatus.APPROVED,
            "Original decision",
        )
        request_obj.refresh_from_db()
        original_server_id = request_obj.created_server_id

        second_response = self.post_decision(
            request_obj,
            RequestStatus.REJECTED,
            "A later decision",
        )

        self.assertRedirects(first_response, self.url)
        self.assertRedirects(second_response, self.url)
        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, RequestStatus.APPROVED)
        self.assertEqual(request_obj.decision_reason, "Original decision")
        self.assertEqual(request_obj.created_server_id, original_server_id)
        self.assertEqual(Server.objects.count(), 1)
        self.assertEqual(Membership.objects.count(), 1)
        self.assertEqual(Channel.objects.count(), 3)

class AdminServerRequestCleanupTests(TransactionTestCase):
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

        self.assertRedirects(
            response,
            reverse("servers:admin_server_request_queue"),
        )
        self.assertEqual(delete.call_count, 1)
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, RequestStatus.APPROVED)
        self.assertEqual(
            self.request_obj.cor_cleanup_status,
            CorCleanupStatus.COMPLETE,
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

        self.assertRedirects(
            response,
            reverse("servers:admin_server_request_queue"),
        )
        self.assertEqual(delete.call_count, 1)
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, RequestStatus.REJECTED)
        self.assertEqual(
            self.request_obj.cor_cleanup_status,
            CorCleanupStatus.COMPLETE,
        )
        self.assertIsNone(self.request_obj.cor_file)
        self.assertEqual(Server.objects.count(), 0)
        self.assertEqual(Membership.objects.count(), 0)
        self.assertEqual(Channel.objects.count(), 0)

    def test_cleanup_failure_keeps_decision_and_retryable_status(self):
        with patch(
            "apps.servers.services.cor_cleanup.delete_cor",
            side_effect=CorDeletionError("simulated private storage failure"),
        ):
            response = self.post_decision(RequestStatus.APPROVED)

        self.assertRedirects(
            response,
            reverse("servers:admin_server_request_queue"),
        )
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, RequestStatus.APPROVED)
        self.assertEqual(
            self.request_obj.cor_cleanup_status,
            CorCleanupStatus.PENDING,
        )
        self.assertEqual(self.request_obj.cor_cleanup_attempts, 1)
        self.assertEqual(self.request_obj.cor_file, self.stored_cor)
        self.assertEqual(
            self.request_obj.decision_reason,
            "Reviewed after checking the CoR",
        )
        self.assertEqual(self.request_obj.reviewed_by, self.admin)
        self.assertIsNotNone(self.request_obj.reviewed_at)
        self.assertEqual(Server.objects.count(), 1)
        self.assertEqual(Membership.objects.count(), 1)
        self.assertEqual(Channel.objects.count(), 3)

    def test_rejection_cleanup_failure_keeps_decision_retryable_without_resources(
        self,
    ):
        with patch(
            "apps.servers.services.cor_cleanup.delete_cor",
            side_effect=CorDeletionError("simulated private storage failure"),
        ):
            response = self.post_decision(RequestStatus.REJECTED)

        self.assertRedirects(
            response,
            reverse("servers:admin_server_request_queue"),
        )
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, RequestStatus.REJECTED)
        self.assertEqual(
            self.request_obj.decision_reason,
            "Reviewed after checking the CoR",
        )
        self.assertEqual(self.request_obj.reviewed_by, self.admin)
        self.assertIsNotNone(self.request_obj.reviewed_at)
        self.assertEqual(
            self.request_obj.cor_cleanup_status,
            CorCleanupStatus.PENDING,
        )
        self.assertEqual(self.request_obj.cor_cleanup_attempts, 1)
        self.assertEqual(self.request_obj.cor_file, self.stored_cor)
        self.assertIsNone(self.request_obj.created_server_id)
        self.assertEqual(Server.objects.count(), 0)
        self.assertEqual(Membership.objects.count(), 0)
        self.assertEqual(Channel.objects.count(), 0)


class AdminServerRequestPhysicalDeletionTests(TransactionTestCase):
    def setUp(self):
        self.storage_tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage_tempdir.cleanup)

        storage_settings = override_settings(
            PRIVATE_COR_STORAGE_ROOT=self.storage_tempdir.name,
        )
        storage_settings.enable()
        self.addCleanup(storage_settings.disable)

        self.storage = get_cor_storage()
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
        )
        self.client.force_login(self.admin)

    def create_request(self, cor_file, **kwargs):
        defaults = {
            "requester": self.requester,
            "proposed_name": "Computer Science",
            "proposed_section": "3A",
            "cor_file": cor_file,
        }
        defaults.update(kwargs)
        return ServerRequest.objects.create(**defaults)

    def post_decision(self, request_obj, decision, reason="Reviewed"):
        return self.client.post(
            reverse("servers:decide_server_request", args=[request_obj.pk]),
            {
                f"request-{request_obj.pk}-decision": decision,
                f"request-{request_obj.pk}-decision_reason": reason,
            },
        )

    def test_approval_physically_deletes_cor_file(self):
        cor_name = self.storage.save(
            "registration.pdf",
            ContentFile(b"%PDF-1.4 CoR content for approval"),
        )
        self.assertTrue(self.storage.exists(cor_name))

        request_obj = self.create_request(cor_file=cor_name)

        response = self.post_decision(
            request_obj,
            RequestStatus.APPROVED,
            "CoR verified and approved",
        )

        self.assertRedirects(
            response,
            reverse("servers:admin_server_request_queue"),
        )

        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, RequestStatus.APPROVED)
        self.assertIsNone(request_obj.cor_file)
        self.assertEqual(
            request_obj.cor_cleanup_status,
            CorCleanupStatus.COMPLETE,
        )
        self.assertFalse(self.storage.exists(cor_name))

        self.assertEqual(Server.objects.count(), 1)
        self.assertEqual(Membership.objects.count(), 1)
        self.assertEqual(Channel.objects.count(), 3)

    def test_rejection_physically_deletes_cor_file(self):
        cor_name = self.storage.save(
            "registration.pdf",
            ContentFile(b"%PDF-1.4 CoR content for rejection"),
        )
        self.assertTrue(self.storage.exists(cor_name))

        request_obj = self.create_request(cor_file=cor_name)

        response = self.post_decision(
            request_obj,
            RequestStatus.REJECTED,
            "The submitted CoR is unreadable",
        )

        self.assertRedirects(
            response,
            reverse("servers:admin_server_request_queue"),
        )

        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, RequestStatus.REJECTED)
        self.assertIsNone(request_obj.cor_file)
        self.assertEqual(
            request_obj.cor_cleanup_status,
            CorCleanupStatus.COMPLETE,
        )
        self.assertFalse(self.storage.exists(cor_name))

        self.assertEqual(Server.objects.count(), 0)
        self.assertEqual(Membership.objects.count(), 0)
        self.assertEqual(Channel.objects.count(), 0)


class AdminServerRequestConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.requester = User.objects.create_user(
            email="student@example.com",
            password="TestPassword123",
            full_name="Test Student",
            is_email_verified=True,
        )
        self.reviewers = (
            User.objects.create_user(
                email="admin-one@example.com",
                password="TestPassword123",
                full_name="Admin One",
                is_staff=True,
            ),
            User.objects.create_user(
                email="admin-two@example.com",
                password="TestPassword123",
                full_name="Admin Two",
                is_staff=True,
            ),
        )
        self.request_obj = ServerRequest.objects.create(
            requester=self.requester,
            proposed_name="Computer Science",
            proposed_section="3A",
        )

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_decisions_commit_only_one_choice(self):
        barrier = threading.Barrier(2)

        def decide(decision, reviewer):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    result = decide_server_request(
                        request_id=self.request_obj.pk,
                        reviewer=reviewer,
                        decision=decision,
                        decision_reason=f"Reviewed by {reviewer.full_name}",
                    )
                except ValidationError:
                    return "stale", decision, reviewer.pk
                return "decided", result.status, reviewer.pk
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(
                    decide,
                    RequestStatus.APPROVED,
                    self.reviewers[0],
                ),
                executor.submit(
                    decide,
                    RequestStatus.REJECTED,
                    self.reviewers[1],
                ),
            )
            outcomes = [future.result(timeout=30) for future in futures]

        winners = [outcome for outcome in outcomes if outcome[0] == "decided"]
        stale = [outcome for outcome in outcomes if outcome[0] == "stale"]
        self.assertEqual(len(winners), 1)
        self.assertEqual(len(stale), 1)

        winner = winners[0]
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, winner[1])
        self.assertEqual(self.request_obj.reviewed_by_id, winner[2])
        self.assertEqual(
            self.request_obj.decision_reason,
            f"Reviewed by {self.request_obj.reviewed_by.full_name}",
        )
        if winner[1] == RequestStatus.APPROVED:
            self.assertEqual(Server.objects.count(), 1)
            self.assertEqual(Membership.objects.count(), 1)
            self.assertEqual(Channel.objects.count(), 3)
        else:
            self.assertEqual(Server.objects.count(), 0)
            self.assertEqual(Membership.objects.count(), 0)
            self.assertEqual(Channel.objects.count(), 0)

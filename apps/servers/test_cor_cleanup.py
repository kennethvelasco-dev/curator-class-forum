import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.test import TransactionTestCase
from django.utils import timezone

from apps.servers.management.commands import cleanup_pending_cor_files
from apps.servers.services import cor_cleanup
from apps.servers.models import (
    CorCleanupStatus,
    JoinRequest,
    RequestStatus,
    Server,
    ServerRequest,
)
from apps.servers.services.cor_cleanup import (
    CorCleanupOutcome,
    attempt_cor_cleanup,
)
from apps.servers.storage import CorDeletionError, CorDeletionResult


User = get_user_model()
REQUEST_MODELS = (ServerRequest, JoinRequest)


def create_user():
    return User.objects.create_user(
        email=f"{uuid.uuid4().hex}@example.test",
        password="Test-password-123",
        full_name="Test Student",
    )


def create_request(
    model,
    *,
    status=RequestStatus.APPROVED,
    cor_file="private-cor.pdf",
    cleanup_status=CorCleanupStatus.PENDING,
    server=None,
):
    user = create_user()
    if model is ServerRequest:
        return ServerRequest.objects.create(
            requester=user,
            proposed_name="Test Class",
            status=status,
            cor_file=cor_file,
            cor_cleanup_status=cleanup_status,
        )

    if server is None:
        server = Server.objects.create(
            name="Test Class",
            slug=uuid.uuid4().hex,
        )
    return JoinRequest.objects.create(
        user=user,
        server=server,
        student_number="private-student-number",
        status=status,
        cor_file=cor_file,
        cor_cleanup_status=cleanup_status,
    )


class CorFileImmutabilityTests(TransactionTestCase):
    def test_full_save_preserves_cleanup_values_reserved_after_instance_load(self):
        for model in REQUEST_MODELS:
            with self.subTest(model=model.__name__):
                request = create_request(model)
                stale_request = model.objects.get(pk=request.pk)
                reserved_at = timezone.now()

                model.objects.filter(pk=request.pk).update(
                    cor_cleanup_status=CorCleanupStatus.PROCESSING,
                    cor_cleanup_attempts=1,
                    cor_cleanup_last_attempt_at=reserved_at,
                )

                stale_request.decision_reason = "Reviewed"
                stale_request.save()

                request.refresh_from_db()
                self.assertEqual(request.decision_reason, "Reviewed")
                self.assertEqual(
                    request.cor_cleanup_status,
                    CorCleanupStatus.PROCESSING,
                )
                self.assertEqual(request.cor_cleanup_attempts, 1)
                self.assertEqual(
                    request.cor_cleanup_last_attempt_at,
                    reserved_at,
                )

    def test_explicit_update_fields_are_not_modified(self):
        request = create_request(ServerRequest)
        stale_request = ServerRequest.objects.get(pk=request.pk)
        ServerRequest.objects.filter(pk=request.pk).update(
            cor_cleanup_status=CorCleanupStatus.PROCESSING,
            cor_cleanup_attempts=1,
        )

        stale_request.cor_cleanup_status = CorCleanupStatus.PENDING
        stale_request.save(update_fields=("cor_cleanup_status",))

        request.refresh_from_db()
        self.assertEqual(request.cor_cleanup_status, CorCleanupStatus.PENDING)
        self.assertEqual(request.cor_cleanup_attempts, 1)

    def test_pending_requests_can_receive_initial_cor_keys(self):
        for model in REQUEST_MODELS:
            with self.subTest(model=model.__name__):
                request = create_request(
                    model,
                    status=RequestStatus.PENDING,
                    cor_file=None,
                    cleanup_status=CorCleanupStatus.NOT_REQUIRED,
                )
                request.cor_file = "initial-cor-key.pdf"
                request.save(update_fields=("cor_file",))

                request.refresh_from_db()
                self.assertEqual(request.cor_file, "initial-cor-key.pdf")

    def test_decided_requests_reject_replacement_and_clearing(self):
        for model in REQUEST_MODELS:
            for status in (RequestStatus.APPROVED, RequestStatus.REJECTED):
                with self.subTest(model=model.__name__, status=status):
                    request = create_request(
                        model,
                        status=status,
                        cor_file="original-cor-key.pdf",
                    )
                    request.cor_file = "replacement-cor-key.pdf"
                    with self.assertRaises(ValidationError):
                        request.save(update_fields=("cor_file",))

                    request.refresh_from_db()
                    self.assertEqual(request.cor_file, "original-cor-key.pdf")

                    request.cor_file = None
                    with self.assertRaises(ValidationError):
                        request.save(update_fields=("cor_file",))

                    request.refresh_from_db()
                    self.assertEqual(request.cor_file, "original-cor-key.pdf")

    def test_decision_transition_cannot_change_existing_cor_key(self):
        for model in REQUEST_MODELS:
            with self.subTest(model=model.__name__):
                request = create_request(
                    model,
                    status=RequestStatus.APPROVED,
                    cor_file="original-cor-key.pdf",
                )
                request.status = RequestStatus.PENDING
                with self.assertRaises(ValidationError):
                    request.save(update_fields=("status",))
                request.refresh_from_db()
                self.assertEqual(request.status, RequestStatus.APPROVED)

                request.cor_file = "replacement-cor-key.pdf"
                with self.assertRaises(ValidationError):
                    request.save()


class CorCleanupServiceTests(TransactionTestCase):
    def test_cleanup_fields_use_their_model_defaults(self):
        for model in REQUEST_MODELS:
            with self.subTest(model=model.__name__):
                request = create_request(
                    model,
                    status=RequestStatus.PENDING,
                    cleanup_status=CorCleanupStatus.NOT_REQUIRED,
                )

                self.assertEqual(
                    request.cor_cleanup_status,
                    CorCleanupStatus.NOT_REQUIRED,
                )
                self.assertEqual(request.cor_cleanup_attempts, 0)
                self.assertIsNone(request.cor_cleanup_last_attempt_at)

    def test_successful_deletion_clears_the_key_for_both_models(self):
        for model in REQUEST_MODELS:
            with self.subTest(model=model.__name__):
                request = create_request(model)
                with patch(
                    "apps.servers.services.cor_cleanup.delete_cor",
                    return_value=CorDeletionResult.DELETED,
                ) as delete:
                    outcome = attempt_cor_cleanup(request, storage="test-storage")

                request.refresh_from_db()
                self.assertEqual(outcome, CorCleanupOutcome.DELETED)
                self.assertIsNone(request.cor_file)
                self.assertEqual(
                    request.cor_cleanup_status,
                    CorCleanupStatus.COMPLETE,
                )
                self.assertEqual(request.cor_cleanup_attempts, 1)
                self.assertIsNotNone(request.cor_cleanup_last_attempt_at)
                delete.assert_called_once_with(
                    "private-cor.pdf",
                    storage="test-storage",
                )

    def test_attempt_is_reserved_before_storage_for_both_models(self):
        for model in REQUEST_MODELS:
            with self.subTest(model=model.__name__):
                request = create_request(model)

                def verify_reservation(file_key, *, storage=None):
                    request.refresh_from_db()
                    self.assertEqual(request.cor_cleanup_attempts, 1)
                    self.assertIsNotNone(request.cor_cleanup_last_attempt_at)
                    self.assertEqual(
                        request.cor_cleanup_status,
                        CorCleanupStatus.PROCESSING,
                    )
                    return CorDeletionResult.DELETED

                with patch(
                    "apps.servers.services.cor_cleanup.delete_cor",
                    side_effect=verify_reservation,
                ) as delete:
                    outcome = attempt_cor_cleanup(request)

                self.assertEqual(outcome, CorCleanupOutcome.DELETED)
                delete.assert_called_once()

    def test_active_claim_is_not_reclaimed(self):
        for model in REQUEST_MODELS:
            with self.subTest(model=model.__name__):
                request = create_request(model)
                request.cor_cleanup_status = CorCleanupStatus.PROCESSING
                request.cor_cleanup_attempts = 1
                request.cor_cleanup_last_attempt_at = timezone.now()
                request.save(
                    update_fields=(
                        "cor_cleanup_status",
                        "cor_cleanup_attempts",
                        "cor_cleanup_last_attempt_at",
                    )
                )
                with patch(
                    "apps.servers.services.cor_cleanup.delete_cor"
                ) as delete:
                    outcome = attempt_cor_cleanup(request)

                self.assertEqual(
                    outcome,
                    CorCleanupOutcome.CLAIM_IN_PROGRESS,
                )
                delete.assert_not_called()
                request.refresh_from_db()
                self.assertEqual(request.cor_cleanup_attempts, 1)

    def test_abandoned_claim_is_recovered_and_reserved_again(self):
        request = create_request(JoinRequest)
        old_attempt_at = (
            timezone.now()
            - cor_cleanup.COR_CLEANUP_CLAIM_TIMEOUT
            - timedelta(seconds=1)
        )
        JoinRequest.objects.filter(pk=request.pk).update(
            cor_cleanup_status=CorCleanupStatus.PROCESSING,
            cor_cleanup_attempts=1,
            cor_cleanup_last_attempt_at=old_attempt_at,
        )

        def verify_recovery(file_key, *, storage=None):
            request.refresh_from_db()
            self.assertEqual(request.cor_cleanup_attempts, 2)
            self.assertGreater(
                request.cor_cleanup_last_attempt_at,
                old_attempt_at,
            )
            self.assertEqual(
                request.cor_cleanup_status,
                CorCleanupStatus.PROCESSING,
            )
            return CorDeletionResult.DELETED

        with patch(
            "apps.servers.services.cor_cleanup.delete_cor",
            side_effect=verify_recovery,
        ) as delete:
            outcome = attempt_cor_cleanup(request)

        self.assertEqual(outcome, CorCleanupOutcome.DELETED)
        delete.assert_called_once()
        request.refresh_from_db()
        self.assertEqual(request.cor_cleanup_attempts, 2)
        self.assertEqual(request.cor_cleanup_status, CorCleanupStatus.COMPLETE)

    def test_reservation_failure_prevents_storage_access(self):
        request = create_request(ServerRequest)
        with (
            patch(
                "apps.servers.services.cor_cleanup._reserve_claim",
                return_value=CorCleanupOutcome.ATTEMPT_RESERVATION_FAILED,
            ),
            patch(
                "apps.servers.services.cor_cleanup.delete_cor"
            ) as delete,
        ):
            outcome = attempt_cor_cleanup(request)

        request.refresh_from_db()
        self.assertEqual(
            outcome,
            CorCleanupOutcome.ATTEMPT_RESERVATION_FAILED,
        )
        self.assertEqual(request.cor_cleanup_attempts, 0)
        delete.assert_not_called()

    def test_database_transaction_defers_storage_until_after_commit(self):
        request = create_request(ServerRequest)
        with patch(
            "apps.servers.services.cor_cleanup.delete_cor"
        ) as delete:
            with transaction.atomic():
                outcome = attempt_cor_cleanup(request)
                delete.assert_not_called()

        self.assertEqual(
            outcome,
            CorCleanupOutcome.REQUIRES_COMMITTED_TRANSACTION,
        )
        delete.assert_not_called()

    def test_request_retrieval_failure_is_not_a_storage_attempt(self):
        request = create_request(JoinRequest)
        with (
            patch(
                "apps.servers.services.cor_cleanup._read_current",
                side_effect=DatabaseError("database detail"),
            ),
            patch(
                "apps.servers.services.cor_cleanup.delete_cor"
            ) as delete,
        ):
            outcome = attempt_cor_cleanup(request)

        request.refresh_from_db()
        self.assertEqual(
            outcome,
            CorCleanupOutcome.REQUEST_RETRIEVAL_FAILED,
        )
        self.assertEqual(request.cor_cleanup_attempts, 0)
        self.assertIsNone(request.cor_cleanup_last_attempt_at)
        delete.assert_not_called()

    def test_already_absent_counts_as_a_successful_storage_attempt(self):
        for model in REQUEST_MODELS:
            with self.subTest(model=model.__name__):
                request = create_request(model)
                with patch(
                    "apps.servers.services.cor_cleanup.delete_cor",
                    return_value=CorDeletionResult.ALREADY_ABSENT,
                ):
                    outcome = attempt_cor_cleanup(request)

                request.refresh_from_db()
                self.assertEqual(outcome, CorCleanupOutcome.ALREADY_ABSENT)
                self.assertIsNone(request.cor_file)
                self.assertEqual(request.cor_cleanup_attempts, 1)
                self.assertIsNotNone(request.cor_cleanup_last_attempt_at)

    def test_real_private_storage_file_is_removed_for_both_models(self):
        for model in REQUEST_MODELS:
            with self.subTest(model=model.__name__), TemporaryDirectory() as root:
                storage = FileSystemStorage(location=root)
                file_key = storage.save("registration.pdf", ContentFile(b"%PDF"))
                request = create_request(model, cor_file=file_key)

                outcome = attempt_cor_cleanup(request, storage=storage)

                request.refresh_from_db()
                self.assertEqual(outcome, CorCleanupOutcome.DELETED)
                self.assertFalse(storage.exists(file_key))
                self.assertIsNone(request.cor_file)
                self.assertEqual(
                    request.cor_cleanup_status,
                    CorCleanupStatus.COMPLETE,
                )

    def test_final_requests_without_references_finalize_without_attempts(self):
        for model in REQUEST_MODELS:
            for file_key in (None, ""):
                with self.subTest(model=model.__name__, file_key=file_key):
                    request = create_request(model, cor_file=file_key)
                    with patch(
                        "apps.servers.services.cor_cleanup.delete_cor"
                    ) as delete:
                        outcome = attempt_cor_cleanup(request)

                    request.refresh_from_db()
                    self.assertEqual(
                        outcome,
                        CorCleanupOutcome.FINALIZED_NO_REFERENCE,
                    )
                    self.assertEqual(
                        request.cor_cleanup_status,
                        CorCleanupStatus.COMPLETE,
                    )
                    self.assertEqual(request.cor_cleanup_attempts, 0)
                    self.assertIsNone(request.cor_cleanup_last_attempt_at)
                    delete.assert_not_called()

    def test_pending_business_requests_never_call_storage(self):
        for model in REQUEST_MODELS:
            with self.subTest(model=model.__name__):
                request = create_request(model, status=RequestStatus.PENDING)
                with patch(
                    "apps.servers.services.cor_cleanup.delete_cor"
                ) as delete:
                    outcome = attempt_cor_cleanup(request)

                self.assertEqual(outcome, CorCleanupOutcome.SKIPPED_PENDING)
                delete.assert_not_called()
                request.refresh_from_db()
                self.assertEqual(request.cor_cleanup_attempts, 0)

    def test_already_complete_requests_never_call_storage(self):
        for model in REQUEST_MODELS:
            with self.subTest(model=model.__name__):
                request = create_request(
                    model,
                    cleanup_status=CorCleanupStatus.COMPLETE,
                )
                with patch(
                    "apps.servers.services.cor_cleanup.delete_cor"
                ) as delete:
                    outcome = attempt_cor_cleanup(request)

                self.assertEqual(outcome, CorCleanupOutcome.ALREADY_COMPLETE)
                delete.assert_not_called()

    def test_deletion_failure_is_retryable_and_later_retry_succeeds(self):
        for model in REQUEST_MODELS:
            with self.subTest(model=model.__name__):
                request = create_request(model)
                with patch(
                    "apps.servers.services.cor_cleanup.delete_cor",
                    side_effect=[
                        CorDeletionError("private key and error details"),
                        CorDeletionResult.DELETED,
                    ],
                ) as delete:
                    first_outcome = attempt_cor_cleanup(request)
                    request.refresh_from_db()
                    first_attempt_at = request.cor_cleanup_last_attempt_at
                    second_outcome = attempt_cor_cleanup(request)

                request.refresh_from_db()
                self.assertEqual(
                    first_outcome,
                    CorCleanupOutcome.STORAGE_FAILED_RETRYABLE,
                )
                self.assertEqual(second_outcome, CorCleanupOutcome.DELETED)
                self.assertIsNone(request.cor_file)
                self.assertEqual(
                    request.cor_cleanup_status,
                    CorCleanupStatus.COMPLETE,
                )
                self.assertEqual(request.cor_cleanup_attempts, 2)
                self.assertGreaterEqual(
                    request.cor_cleanup_last_attempt_at,
                    first_attempt_at,
                )
                self.assertEqual(delete.call_count, 2)

    def test_unexpected_exceptions_are_tracked_without_sensitive_logging(self):
        request = create_request(JoinRequest)
        with patch(
            "apps.servers.services.cor_cleanup.delete_cor",
            side_effect=RuntimeError("private-student-number private-cor.pdf"),
        ):
            with self.assertLogs(
                "apps.servers.services.cor_cleanup",
                level="WARNING",
            ) as captured:
                outcome = attempt_cor_cleanup(request)

        request.refresh_from_db()
        self.assertEqual(
            outcome,
            CorCleanupOutcome.STORAGE_FAILED_RETRYABLE,
        )
        self.assertEqual(request.cor_file, "private-cor.pdf")
        self.assertEqual(request.cor_cleanup_status, CorCleanupStatus.PENDING)
        self.assertEqual(request.cor_cleanup_attempts, 1)
        self.assertIsNotNone(request.cor_cleanup_last_attempt_at)
        self.assertNotIn("private-cor.pdf", "\n".join(captured.output))
        self.assertNotIn("private-student-number", "\n".join(captured.output))

    def test_repeated_invocation_is_idempotent(self):
        request = create_request(ServerRequest)
        with patch(
            "apps.servers.services.cor_cleanup.delete_cor",
            return_value=CorDeletionResult.DELETED,
        ) as delete:
            first = attempt_cor_cleanup(request)
            second = attempt_cor_cleanup(request)

        self.assertEqual(first, CorCleanupOutcome.DELETED)
        self.assertEqual(second, CorCleanupOutcome.ALREADY_COMPLETE)
        delete.assert_called_once()

    def test_unsupported_models_are_rejected(self):
        with self.assertRaises(TypeError):
            attempt_cor_cleanup(create_user())

    def test_changed_file_key_is_not_cleared_by_a_stale_operation(self):
        request = create_request(JoinRequest)

        def change_key_then_delete(*args, **kwargs):
            JoinRequest.objects.filter(pk=request.pk).update(
                cor_file="replacement-key.pdf"
            )
            return CorDeletionResult.DELETED

        with patch(
            "apps.servers.services.cor_cleanup.delete_cor",
            side_effect=change_key_then_delete,
        ):
            outcome = attempt_cor_cleanup(request)

        request.refresh_from_db()
        self.assertEqual(outcome, CorCleanupOutcome.CLAIM_IN_PROGRESS)
        self.assertEqual(request.cor_file, "replacement-key.pdf")
        self.assertEqual(request.cor_cleanup_status, CorCleanupStatus.PROCESSING)
        self.assertEqual(request.cor_cleanup_attempts, 1)

    def test_completed_concurrent_operation_is_not_overwritten(self):
        request = create_request(ServerRequest)

        def complete_during_delete(*args, **kwargs):
            ServerRequest.objects.filter(pk=request.pk).update(
                cor_file=None,
                cor_cleanup_status=CorCleanupStatus.COMPLETE,
                cor_cleanup_attempts=2,
                cor_cleanup_last_attempt_at=timezone.now(),
            )
            return CorDeletionResult.DELETED

        with patch(
            "apps.servers.services.cor_cleanup.delete_cor",
            side_effect=complete_during_delete,
        ):
            outcome = attempt_cor_cleanup(request)

        request.refresh_from_db()
        self.assertEqual(outcome, CorCleanupOutcome.ALREADY_COMPLETE)
        self.assertIsNone(request.cor_file)
        self.assertEqual(request.cor_cleanup_status, CorCleanupStatus.COMPLETE)
        self.assertEqual(request.cor_cleanup_attempts, 2)

    def test_storage_failure_with_failed_state_persistence_is_distinct(self):
        request = create_request(ServerRequest)
        original_conditional_update = cor_cleanup._conditional_update
        update_calls = 0

        class FailedUpdate:
            def update(self, **kwargs):
                raise DatabaseError("database detail")

        def fail_failure_recording(*args, **kwargs):
            nonlocal update_calls
            update_calls += 1
            if update_calls == 1:
                return FailedUpdate()
            return original_conditional_update(*args, **kwargs)

        with (
            patch(
                "apps.servers.services.cor_cleanup.delete_cor",
                side_effect=CorDeletionError("storage detail"),
            ),
            patch(
                "apps.servers.services.cor_cleanup._conditional_update",
                side_effect=fail_failure_recording,
            ),
        ):
            outcome = attempt_cor_cleanup(request)

        request.refresh_from_db()
        self.assertEqual(
            outcome,
            CorCleanupOutcome.STORAGE_FAILURE_RECORDING_FAILED,
        )
        self.assertEqual(request.cor_cleanup_attempts, 1)
        self.assertEqual(request.cor_cleanup_status, CorCleanupStatus.PROCESSING)
        self.assertEqual(request.cor_file, "private-cor.pdf")

    def test_storage_success_with_failed_completion_is_retried_as_absent(self):
        request = create_request(JoinRequest)
        original_conditional_update = cor_cleanup._conditional_update
        update_calls = 0

        class FailedUpdate:
            def update(self, **kwargs):
                raise DatabaseError("database detail")

        def fail_completion(*args, **kwargs):
            nonlocal update_calls
            update_calls += 1
            if update_calls == 1:
                return FailedUpdate()
            return original_conditional_update(*args, **kwargs)

        with (
            patch(
                "apps.servers.services.cor_cleanup.delete_cor",
                side_effect=[
                    CorDeletionResult.DELETED,
                    CorDeletionResult.ALREADY_ABSENT,
                ],
            ) as delete,
            patch(
                "apps.servers.services.cor_cleanup._conditional_update",
                side_effect=fail_completion,
            ),
        ):
            first = attempt_cor_cleanup(request)
            request.refresh_from_db()
            JoinRequest.objects.filter(pk=request.pk).update(
                cor_cleanup_last_attempt_at=(
                    timezone.now()
                    - cor_cleanup.COR_CLEANUP_CLAIM_TIMEOUT
                    - timedelta(seconds=1)
                ),
            )
            second = attempt_cor_cleanup(request)

        request.refresh_from_db()
        self.assertEqual(
            first,
            CorCleanupOutcome.COMPLETION_RECORDING_FAILED,
        )
        self.assertEqual(second, CorCleanupOutcome.ALREADY_ABSENT)
        self.assertEqual(request.cor_cleanup_attempts, 2)
        self.assertEqual(request.cor_cleanup_status, CorCleanupStatus.COMPLETE)
        self.assertIsNone(request.cor_file)
        self.assertEqual(delete.call_count, 2)

    def test_cleanup_does_not_reverse_the_final_business_decision(self):
        request = create_request(JoinRequest, status=RequestStatus.REJECTED)
        with patch(
            "apps.servers.services.cor_cleanup.delete_cor",
            return_value=CorDeletionResult.DELETED,
        ):
            attempt_cor_cleanup(request)

        request.refresh_from_db()
        self.assertEqual(request.status, RequestStatus.REJECTED)


class CorCleanupCommandTests(TransactionTestCase):
    def setUp(self):
        self.server = Server.objects.create(
            name="Test Class",
            slug=uuid.uuid4().hex,
        )

    def run_command(self, *args, **kwargs):
        output = kwargs.pop("stdout", None)
        if output is None:
            output = StringIO()
        call_command(
            "cleanup_pending_cor_files",
            *args,
            stdout=output,
            stderr=output,
            **kwargs,
        )
        return output.getvalue()

    def test_selects_both_request_models_and_excludes_ineligible_rows(self):
        selected = [
            create_request(ServerRequest),
            create_request(JoinRequest, server=self.server),
        ]
        create_request(ServerRequest, status=RequestStatus.PENDING)
        create_request(
            JoinRequest,
            server=self.server,
            cleanup_status=CorCleanupStatus.COMPLETE,
        )
        seen_models = []

        with patch(
            "apps.servers.management.commands.cleanup_pending_cor_files."
            "attempt_cor_cleanup",
            side_effect=lambda request: (
                seen_models.append(type(request)),
                CorCleanupOutcome.DELETED,
            )[1],
        ):
            output = self.run_command()

        self.assertCountEqual(seen_models, [type(row) for row in selected])
        self.assertIn("selected=2", output)

    def test_dry_run_does_not_mutate_or_call_storage(self):
        server_request = create_request(ServerRequest)
        join_request = create_request(JoinRequest, server=self.server)
        with patch(
            "apps.servers.management.commands.cleanup_pending_cor_files."
            "attempt_cor_cleanup"
        ) as cleanup:
            output = self.run_command("--dry-run")

        server_request.refresh_from_db()
        join_request.refresh_from_db()
        cleanup.assert_not_called()
        self.assertIn("eligible=2", output)
        self.assertIn("server_requests=1", output)
        self.assertIn("join_requests=1", output)
        self.assertIn("files_checked=0", output)
        self.assertIn("does not verify individual file existence", output)
        self.assertEqual(server_request.cor_cleanup_attempts, 0)
        self.assertEqual(join_request.cor_cleanup_attempts, 0)

    def test_request_retrieval_failure_is_not_counted_as_storage_failure(self):
        create_request(ServerRequest)
        create_request(JoinRequest, server=self.server)
        real_retrieve_request = cleanup_pending_cor_files._retrieve_request

        def retrieve(model, request_pk):
            if model is ServerRequest:
                raise DatabaseError("private database detail")
            return real_retrieve_request(model, request_pk)

        output = StringIO()
        with (
            patch.object(
                cleanup_pending_cor_files,
                "_retrieve_request",
                side_effect=retrieve,
            ),
            patch(
                "apps.servers.management.commands.cleanup_pending_cor_files."
                "attempt_cor_cleanup",
                return_value=CorCleanupOutcome.DELETED,
            ) as cleanup,
        ):
            with self.assertRaises(CommandError):
                self.run_command(stdout=output)

        cleanup.assert_called_once()
        self.assertIn("request_retrieval_failed=1", output.getvalue())
        self.assertIn("deleted=1", output.getvalue())
        self.assertIn("unresolved_failures=1", output.getvalue())
        self.assertNotIn("storage_failed_retryable=1", output.getvalue())
        self.assertNotIn("private database detail", output.getvalue())

    def test_command_reports_distinct_reservation_and_completion_failures(self):
        create_request(ServerRequest)
        create_request(JoinRequest, server=self.server)
        output = StringIO()
        with patch(
            "apps.servers.management.commands.cleanup_pending_cor_files."
            "attempt_cor_cleanup",
            side_effect=[
                CorCleanupOutcome.ATTEMPT_RESERVATION_FAILED,
                CorCleanupOutcome.COMPLETION_RECORDING_FAILED,
            ],
        ):
            with self.assertRaises(CommandError):
                self.run_command(stdout=output)

        rendered = output.getvalue()
        self.assertIn("attempt_reservation_failed=1", rendered)
        self.assertIn("completion_recording_failed=1", rendered)
        self.assertIn("unresolved_failures=2", rendered)

    def test_limit_is_global_and_round_robin_selection_is_deterministic(self):
        requests = [
            create_request(ServerRequest),
            create_request(ServerRequest),
            create_request(JoinRequest, server=self.server),
            create_request(JoinRequest, server=self.server),
        ]
        selected = []
        with patch(
            "apps.servers.management.commands.cleanup_pending_cor_files."
            "attempt_cor_cleanup",
            side_effect=lambda request: (
                selected.append(type(request)),
                CorCleanupOutcome.DELETED,
            )[1],
        ):
            output = self.run_command("--limit", "3")

        self.assertEqual(len(selected), 3)
        self.assertEqual(selected, [ServerRequest, JoinRequest, ServerRequest])
        self.assertIn("selected=3", output)
        self.assertEqual(len(requests), 4)

    def test_repeated_limited_runs_alternate_after_a_failed_attempt(self):
        server_request = create_request(ServerRequest)
        join_request = create_request(JoinRequest, server=self.server)
        with patch(
            "apps.servers.services.cor_cleanup.delete_cor",
            side_effect=CorDeletionError("hidden file detail"),
        ) as delete:
            with self.assertRaises(CommandError):
                self.run_command("--limit", "1")
            with self.assertRaises(CommandError):
                self.run_command("--limit", "1")

        self.assertEqual(
            [call.args[0] for call in delete.call_args_list],
            [server_request.cor_file, join_request.cor_file],
        )

    def test_repeated_limited_runs_prioritize_never_attempted_requests(self):
        requests = [
            create_request(
                ServerRequest,
                cor_file=f"server-cor-{index}.pdf",
            )
            for index in range(3)
        ]

        with patch(
            "apps.servers.services.cor_cleanup.delete_cor",
            side_effect=CorDeletionError("hidden file detail"),
        ) as delete:
            for _ in requests:
                with self.assertRaises(CommandError):
                    self.run_command("--limit", "1")

        self.assertEqual(
            [call.args[0] for call in delete.call_args_list],
            [request.cor_file for request in requests],
        )

    def test_failure_does_not_stop_processing_and_output_is_aggregate_only(self):
        request = create_request(ServerRequest, cor_file="private-secret-key.pdf")
        join_request = create_request(
            JoinRequest,
            server=self.server,
            cor_file="another-private-key.pdf",
        )
        output = StringIO()
        with patch(
            "apps.servers.management.commands.cleanup_pending_cor_files."
            "attempt_cor_cleanup",
            side_effect=[
                CorCleanupOutcome.STORAGE_FAILED_RETRYABLE,
                CorCleanupOutcome.DELETED,
            ],
        ) as cleanup:
            with self.assertRaisesMessage(
                CommandError,
                "1 CoR cleanup failure(s) require attention.",
            ):
                self.run_command(stdout=output)

        self.assertEqual(cleanup.call_count, 2)
        rendered = output.getvalue()
        self.assertIn("selected=2", rendered)
        self.assertIn("storage_failed_retryable=1", rendered)
        self.assertIn("unresolved_failures=1", rendered)
        for private_value in (
            request.cor_file,
            join_request.cor_file,
            "private-student-number",
        ):
            self.assertNotIn(private_value, rendered)

    def test_retry_succeeds_on_later_command_run(self):
        request = create_request(JoinRequest, server=self.server)
        with patch(
            "apps.servers.services.cor_cleanup.delete_cor",
            side_effect=[
                CorDeletionError("hidden detail"),
                CorDeletionResult.DELETED,
            ],
        ):
            with self.assertRaises(CommandError):
                self.run_command()
            output = self.run_command()

        request.refresh_from_db()
        self.assertEqual(request.cor_cleanup_status, CorCleanupStatus.COMPLETE)
        self.assertIsNone(request.cor_file)
        self.assertIn("unresolved_failures=0", output)

    def test_zero_and_negative_limits_are_rejected(self):
        for limit in ("0", "-2"):
            with self.subTest(limit=limit):
                with self.assertRaisesMessage(
                    CommandError,
                    "--limit must be a positive integer.",
                ):
                    self.run_command("--limit", limit)


class CorCleanupDecisionIntegrationTests(TransactionTestCase):
    def setUp(self):
        self.request = create_request(
            ServerRequest,
            status=RequestStatus.PENDING,
            cleanup_status=CorCleanupStatus.NOT_REQUIRED,
        )

    def test_simulated_post_commit_pattern_failure_does_not_undo_decision(self):
        with patch(
            "apps.servers.services.cor_cleanup.delete_cor",
            side_effect=CorDeletionError("private storage detail"),
        ):
            with transaction.atomic():
                ServerRequest.objects.filter(pk=self.request.pk).update(
                    status=RequestStatus.APPROVED,
                    cor_cleanup_status=CorCleanupStatus.PENDING,
                )
                transaction.on_commit(
                    lambda: attempt_cor_cleanup(self.request)
                )
                request = ServerRequest.objects.get(pk=self.request.pk)
                self.assertEqual(request.status, RequestStatus.APPROVED)
                self.assertEqual(
                    request.cor_cleanup_status,
                    CorCleanupStatus.PENDING,
                )

        self.request.refresh_from_db()
        self.assertEqual(self.request.status, RequestStatus.APPROVED)
        self.assertEqual(
            self.request.cor_cleanup_status,
            CorCleanupStatus.PENDING,
        )
        self.assertEqual(self.request.cor_cleanup_attempts, 1)
        self.assertEqual(self.request.cor_file, "private-cor.pdf")


class CorCleanupThreadedConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.request = create_request(ServerRequest)

    def test_concurrent_idempotent_deletions_use_compare_and_set(self):
        barrier = threading.Barrier(2)
        read_lock = threading.Lock()
        synchronized_read_count = 0
        original_read = cor_cleanup._read_current

        def synchronize_reads(model, request_pk, using):
            nonlocal synchronized_read_count
            request = original_read(model, request_pk, using)
            with read_lock:
                synchronized_read_count += 1
                should_synchronize = synchronized_read_count <= 2
            if should_synchronize:
                barrier.wait(timeout=10)
            return request

        def attempt_in_thread():
            close_old_connections()
            try:
                request = ServerRequest.objects.get(pk=self.request.pk)
                return attempt_cor_cleanup(request)
            finally:
                connections.close_all()

        with (
            patch(
                "apps.servers.services.cor_cleanup.delete_cor",
                return_value=CorDeletionResult.DELETED,
            ) as delete,
            patch(
                "apps.servers.services.cor_cleanup._read_current",
                side_effect=synchronize_reads,
            ),
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(attempt_in_thread),
                    executor.submit(attempt_in_thread),
                ]
                outcomes = [future.result(timeout=20) for future in futures]

        self.request.refresh_from_db()
        self.assertEqual(delete.call_count, 1)
        self.assertEqual(outcomes.count(CorCleanupOutcome.DELETED), 1)
        self.assertEqual(self.request.cor_cleanup_attempts, 1)
        self.assertEqual(len(outcomes), 2)
        losing_outcome = next(
            outcome
            for outcome in outcomes
            if outcome != CorCleanupOutcome.DELETED
        )
        self.assertIn(
            losing_outcome,
            (
                CorCleanupOutcome.CLAIM_IN_PROGRESS,
                CorCleanupOutcome.ATTEMPT_RESERVATION_FAILED,
                CorCleanupOutcome.ALREADY_COMPLETE,
            ),
        )
        self.assertIsNone(self.request.cor_file)
        self.assertEqual(
            self.request.cor_cleanup_status,
            CorCleanupStatus.COMPLETE,
        )
        self.assertEqual(self.request.cor_cleanup_attempts, 1)


class CorCleanupMigrationTests(TransactionTestCase):
    reset_sequences = True

    def test_legacy_rows_are_backfilled_without_changing_decision_or_key(self):
        from django.db.migrations.executor import MigrationExecutor

        migrate_from = ("servers", "0001_initial")
        migrate_to = ("servers", "0002_cor_cleanup_lifecycle")
        executor = MigrationExecutor(connection)
        current_targets = executor.loader.graph.leaf_nodes()
        migrate_from_targets = [
            target for target in current_targets if target[0] != "servers"
        ]
        migrate_from_targets.append(migrate_from)
        executor.migrate(migrate_from_targets)

        try:
            legacy_apps = executor.loader.project_state(
                migrate_from_targets
            ).apps
            LegacyServer = legacy_apps.get_model("servers", "Server")
            LegacyServerRequest = legacy_apps.get_model(
                "servers",
                "ServerRequest",
            )
            LegacyJoinRequest = legacy_apps.get_model("servers", "JoinRequest")
            legacy_server = LegacyServer.objects.create(
                name="Legacy Class",
                slug=uuid.uuid4().hex,
            )

            cases = []
            for model in (LegacyServerRequest, LegacyJoinRequest):
                for status, file_key in (
                    ("approved", "legacy-approved.pdf"),
                    ("rejected", None),
                    ("rejected", ""),
                    ("pending", "legacy-pending.pdf"),
                ):
                    user = create_user()
                    fields = {
                        "status": status,
                        "cor_file": file_key,
                    }
                    if model is LegacyServerRequest:
                        fields.update(
                            requester_id=user.pk,
                            proposed_name="Legacy Class",
                        )
                    else:
                        fields.update(
                            user_id=user.pk,
                            server_id=legacy_server.pk,
                            student_number="legacy-student-number",
                        )
                    row = model.objects.create(**fields)
                    cases.append((model.__name__, row.pk, status, file_key))

            migrate_to_targets = [
                target for target in current_targets if target[0] != "servers"
            ]
            migrate_to_targets.append(migrate_to)
            MigrationExecutor(connection).migrate(migrate_to_targets)
            migrated_apps = MigrationExecutor(connection).loader.project_state(
                migrate_to_targets
            ).apps
            for model_name, request_pk, status, file_key in cases:
                migrated_model = migrated_apps.get_model(
                    "servers",
                    model_name,
                )
                migrated = migrated_model.objects.get(pk=request_pk)
                self.assertEqual(migrated.status, status)
                self.assertEqual(migrated.cor_file, file_key)
                if status == "pending":
                    expected_cleanup = "not_required"
                elif file_key:
                    expected_cleanup = "pending"
                else:
                    expected_cleanup = "complete"
                self.assertEqual(
                    migrated.cor_cleanup_status,
                    expected_cleanup,
                )
                self.assertEqual(migrated.cor_cleanup_attempts, 0)
                self.assertIsNone(migrated.cor_cleanup_last_attempt_at)
        finally:
            MigrationExecutor(connection).migrate(current_targets)

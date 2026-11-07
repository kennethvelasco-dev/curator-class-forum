import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from apps.servers.models import (
    RequestStatus,
    SERVER_REQUEST_PENDING_CONSTRAINT,
    SERVER_REQUEST_PENDING_MESSAGE,
    ServerRequest,
)
from apps.servers.services.server_requests import (
    _is_pending_request_conflict,
    create_server_request,
)


User = get_user_model()


class DatabaseErrorWithDiagnostics(Exception):
    def __init__(self, constraint_name):
        self.diag = SimpleNamespace(constraint_name=constraint_name)


class PendingRequestConflictDetectionTests(TestCase):
    def make_wrapped_integrity_error(self, database_error):
        error = IntegrityError("database constraint violation")
        error.__cause__ = database_error
        return error

    def test_sqlite_requester_unique_error_matches(self):
        database_error = sqlite3.IntegrityError(
            'UNIQUE constraint failed: "servers_serverrequest"."requester_id"'
        )
        database_error.sqlite_errorname = "SQLITE_CONSTRAINT_UNIQUE"

        self.assertTrue(
            _is_pending_request_conflict(
                self.make_wrapped_integrity_error(database_error)
            )
        )

    def test_sqlite_unique_error_on_another_column_does_not_match(self):
        database_error = sqlite3.IntegrityError(
            "UNIQUE constraint failed: servers_serverrequest.proposed_name"
        )
        database_error.sqlite_errorname = "SQLITE_CONSTRAINT_UNIQUE"

        self.assertFalse(
            _is_pending_request_conflict(
                self.make_wrapped_integrity_error(database_error)
            )
        )

    def test_postgresql_expected_constraint_matches(self):
        database_error = DatabaseErrorWithDiagnostics(
            SERVER_REQUEST_PENDING_CONSTRAINT,
        )

        self.assertTrue(
            _is_pending_request_conflict(
                self.make_wrapped_integrity_error(database_error)
            )
        )

    def test_postgresql_other_constraint_does_not_match(self):
        database_error = DatabaseErrorWithDiagnostics(
            "another_unique_constraint",
        )

        self.assertFalse(
            _is_pending_request_conflict(
                self.make_wrapped_integrity_error(database_error)
            )
        )


class ServerRequestCreationTests(TestCase):
    def setUp(self):
        self.requester = User.objects.create_user(
            email="student@example.com",
            password="StrongPass8",
            full_name="Test Student",
            is_email_verified=True,
        )

    def test_duplicate_pending_request_has_friendly_validation_error(self):
        create_server_request(
            requester=self.requester,
            proposed_name="Class A",
        )

        with self.assertRaisesMessage(
            ValidationError,
            SERVER_REQUEST_PENDING_MESSAGE,
        ):
            create_server_request(
                requester=self.requester,
                proposed_name="Class B",
            )

    def test_requester_can_submit_after_previous_request_is_decided(self):
        previous = create_server_request(
            requester=self.requester,
            proposed_name="Class A",
        )
        previous.status = RequestStatus.REJECTED
        previous.save(update_fields=["status"])

        next_request = create_server_request(
            requester=self.requester,
            proposed_name="Class B",
        )

        self.assertEqual(next_request.status, RequestStatus.PENDING)

    def test_concurrent_unique_violation_has_friendly_validation_error(self):
        original_save = ServerRequest.save

        def insert_competing_request(instance, *args, **kwargs):
            ServerRequest.objects.bulk_create(
                [
                    ServerRequest(
                        requester=instance.requester,
                        proposed_name="Concurrent request",
                    )
                ]
            )
            return original_save(instance, *args, **kwargs)

        with patch.object(
            ServerRequest,
            "save",
            new=insert_competing_request,
        ):
            with self.assertRaisesMessage(
                ValidationError,
                SERVER_REQUEST_PENDING_MESSAGE,
            ):
                create_server_request(
                    requester=self.requester,
                    proposed_name="Class A",
                )

    def test_unrelated_integrity_error_is_not_concealed(self):
        with patch.object(
            ServerRequest,
            "save",
            side_effect=IntegrityError("unrelated integrity failure"),
        ):
            with self.assertRaisesMessage(
                IntegrityError,
                "unrelated integrity failure",
            ):
                create_server_request(
                    requester=self.requester,
                    proposed_name="Class A",
                )

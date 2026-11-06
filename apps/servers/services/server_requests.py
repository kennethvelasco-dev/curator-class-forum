"""Creation services for server requests."""

import sqlite3

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.servers.models import (
    RequestStatus,
    SERVER_REQUEST_PENDING_CONSTRAINT,
    SERVER_REQUEST_PENDING_MESSAGE,
    ServerRequest,
)


def _is_pending_request_conflict(error):
    """Return whether a database error names the pending-request constraint."""
    database_error = error.__cause__
    if database_error is None:
        return False

    diagnostics = getattr(database_error, "diag", None)
    if diagnostics is not None:
        return (
            getattr(diagnostics, "constraint_name", None)
            == SERVER_REQUEST_PENDING_CONSTRAINT
        )

    if isinstance(database_error, sqlite3.IntegrityError):
        error_name = getattr(database_error, "sqlite_errorname", None)
        if error_name not in (None, "SQLITE_CONSTRAINT_UNIQUE"):
            return False

        prefix, separator, columns = str(database_error).partition(":")
        if not separator or prefix.strip().casefold() != "unique constraint failed":
            return False

        expected_column = (
            ServerRequest._meta.db_table,
            "requester_id",
        )
        for column in columns.split(","):
            identifiers = tuple(
                identifier.strip().strip('"`[]').strip()
                for identifier in column.strip().split(".")
            )
            if identifiers == expected_column:
                return True

    return False


def create_server_request(
    *,
    requester,
    proposed_name,
    proposed_section="",
    cor_file=None,
):
    """Validate and persist a server request, translating duplicate races."""
    if ServerRequest.objects.filter(
        requester=requester,
        status=RequestStatus.PENDING,
    ).exists():
        raise ValidationError(
            {"requester": SERVER_REQUEST_PENDING_MESSAGE}
        )

    request_obj = ServerRequest(
        requester=requester,
        proposed_name=proposed_name,
        proposed_section=proposed_section,
        cor_file=cor_file,
    )
    try:
        with transaction.atomic():
            request_obj.full_clean(
                exclude=("reviewed_by", "created_server"),
            )
            request_obj.save()
    except IntegrityError as error:
        if _is_pending_request_conflict(error):
            raise ValidationError(
                {"requester": SERVER_REQUEST_PENDING_MESSAGE}
            ) from None
        raise

    return request_obj

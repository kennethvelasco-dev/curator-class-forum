"""Creation and decision services for server requests."""

import sqlite3

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.channels.models import Channel, ChannelType
from apps.servers.models import (
    CorCleanupStatus,
    Membership,
    MembershipRole,
    MembershipStatus,
    RequestStatus,
    SERVER_REQUEST_PENDING_CONSTRAINT,
    SERVER_REQUEST_PENDING_MESSAGE,
    Server,
    ServerRequest,
)
from apps.servers.services.cor_cleanup import attempt_cor_cleanup


_DEFAULT_CHANNELS = (
    (ChannelType.ANNOUNCEMENTS, "Announcements"),
    (ChannelType.CALENDAR, "Calendar"),
    (ChannelType.RULES, "Rules"),
)
_SERVER_SLUG_UNIQUE_CONSTRAINT = "servers_server_slug_key"
_SERVER_SLUG_SAVE_ATTEMPTS = 5


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


def _server_slug_for_request(request_obj, collision_number=0):
    base_slug = slugify(
        f"{request_obj.proposed_name} {request_obj.proposed_section}"
    ) or "class-server"
    base_slug = base_slug[:80].rstrip("-") or "class-server"
    suffix_number = collision_number + 1
    candidate = _server_slug_candidate(
        base_slug,
        request_obj.pk,
        suffix_number,
    )
    while Server.objects.filter(slug=candidate).exists():
        suffix_number += 1
        candidate = _server_slug_candidate(
            base_slug,
            request_obj.pk,
            suffix_number,
        )

    return candidate


def _server_slug_candidate(base_slug, request_id, suffix_number):
    suffix = f"-{request_id}"
    if suffix_number > 1:
        suffix += f"-{suffix_number}"
    return f"{base_slug[:100 - len(suffix)]}{suffix}"


def _is_server_slug_conflict(error):
    database_error = error.__cause__
    if database_error is None:
        return False

    diagnostics = getattr(database_error, "diag", None)
    if diagnostics is not None:
        return (
            getattr(diagnostics, "constraint_name", None)
            == _SERVER_SLUG_UNIQUE_CONSTRAINT
        )

    if isinstance(database_error, sqlite3.IntegrityError):
        error_name = getattr(database_error, "sqlite_errorname", None)
        if error_name not in (None, "SQLITE_CONSTRAINT_UNIQUE"):
            return False

        prefix, separator, columns = str(database_error).partition(":")
        if not separator or prefix.strip().casefold() != "unique constraint failed":
            return False

        expected_column = (Server._meta.db_table, "slug")
        for column in columns.split(","):
            identifiers = tuple(
                identifier.strip().strip('"`[]').strip()
                for identifier in column.strip().split(".")
            )
            if identifiers == expected_column:
                return True

    return False


def _is_server_slug_validation_conflict(error):
    if not hasattr(error, "error_dict"):
        return False
    return any(
        validation_error.code == "unique"
        for validation_error in error.error_dict.get("slug", ())
    )


def decide_server_request(
    *,
    request_id,
    reviewer,
    decision,
    decision_reason,
):
    """Commit a server-request decision and its resources atomically."""
    if decision not in (RequestStatus.APPROVED, RequestStatus.REJECTED):
        raise ValidationError({"decision": "Choose approve or reject."})

    reason = (decision_reason or "").strip()
    if not reason:
        raise ValidationError({"decision_reason": "A reason is required."})

    with transaction.atomic():
        request_obj = (
            ServerRequest.objects.select_for_update()
            .get(pk=request_id)
        )
        if request_obj.status != RequestStatus.PENDING:
            raise ValidationError(
                {"status": "This request has already been decided."}
            )

        if decision == RequestStatus.APPROVED:
            server = Server(
                name=request_obj.proposed_name,
                section=request_obj.proposed_section,
                created_by=request_obj.requester,
            )
            for attempt in range(_SERVER_SLUG_SAVE_ATTEMPTS):
                server.slug = _server_slug_for_request(
                    request_obj,
                    collision_number=attempt,
                )
                try:
                    with transaction.atomic():
                        server.full_clean()
                        server.save(force_insert=True)
                except ValidationError as error:
                    if (
                        _is_server_slug_validation_conflict(error)
                        and attempt < _SERVER_SLUG_SAVE_ATTEMPTS - 1
                    ):
                        continue
                    raise
                except IntegrityError as error:
                    if (
                        _is_server_slug_conflict(error)
                        and attempt < _SERVER_SLUG_SAVE_ATTEMPTS - 1
                    ):
                        continue
                    raise
                break

            membership = Membership(
                user=request_obj.requester,
                server=server,
                role=MembershipRole.PRESIDENT,
                status=MembershipStatus.ACTIVE,
            )
            membership.full_clean()
            membership.save(force_insert=True)

            for channel_type, channel_name in _DEFAULT_CHANNELS:
                channel = Channel(
                    server=server,
                    name=channel_name,
                    slug=channel_type,
                    channel_type=channel_type,
                )
                channel.full_clean()
                channel.save(force_insert=True)

            request_obj.created_server = server

        request_obj.status = decision
        request_obj.decision_reason = reason
        request_obj.reviewed_by = reviewer
        request_obj.reviewed_at = timezone.now()
        request_obj.cor_cleanup_status = CorCleanupStatus.PENDING
        request_obj.full_clean(
            exclude=("created_server",)
            if decision == RequestStatus.REJECTED
            else (),
        )
        request_obj.save(
            update_fields=(
                "status",
                "decision_reason",
                "reviewed_by",
                "reviewed_at",
                "created_server",
                "cor_cleanup_status",
                "updated_at",
            )
        )
        transaction.on_commit(
            lambda decided_request=request_obj: attempt_cor_cleanup(
                decided_request
            ),
            robust=True,
        )

    return request_obj

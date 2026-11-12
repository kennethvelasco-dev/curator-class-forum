"""Creation and decision services for server and join requests."""

import re
import sqlite3

from django.core.exceptions import ValidationError
from django.db import connection, IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.channels.models import Channel, ChannelType
from apps.servers.models import (
    CorCleanupStatus,
    JoinRequest,
    JoinRequestSubject,
    Membership,
    MembershipRole,
    MembershipStatus,
    MembershipSubject,
    RequestStatus,
    SERVER_REQUEST_PENDING_CONSTRAINT,
    SERVER_REQUEST_PENDING_MESSAGE,
    Server,
    ServerRequest,
)
from apps.servers.permissions import is_active_president_of_server
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


def _normalize_subject_entry(value):
    if not isinstance(value, str):
        raise ValidationError({"subjects": "Subject entries must be text."})
    text = (value or "").strip()
    if not text:
        raise ValidationError({"subjects": "A subject entry is required."})
    normalized = re.sub(r"\s+", " ", text)
    if len(normalized) > 64:
        raise ValidationError(
            {"subjects": "Each subject entry must be 64 characters or fewer."}
        )
    return normalized


def _normalize_subject_entries(subjects):
    def split_entries(text):
        normalized_newlines = text.replace("\r\n", "\n").replace("\r", "\n")
        return [
            part
            for line in normalized_newlines.split("\n")
            for part in line.split(",")
        ]

    raw_items = []
    if isinstance(subjects, str):
        raw_items.extend(split_entries(subjects))
    else:
        for item in subjects or ():
            if isinstance(item, str):
                raw_items.extend(split_entries(item))
            else:
                raw_items.append(item)

    normalized = []
    seen = set()
    for entry in raw_items:
        value = _normalize_subject_entry(entry)
        key = value.casefold()
        if key in seen:
            raise ValidationError(
                {"subjects": "Duplicate subject entries are not allowed."}
            )
        seen.add(key)
        normalized.append(value)
    if not normalized:
        raise ValidationError(
            {"subjects": "At least one subject or section entry is required."}
        )
    return normalized


def create_join_request(*, user, server, student_number, subjects, cor_file):
    """Validate and persist a join request and its approved subject entries."""
    if user is None or not getattr(user, "is_authenticated", False):
        raise ValidationError({"user": "Authentication is required."})
    if not getattr(user, "is_email_verified", False):
        raise ValidationError({"user": "Only verified students can submit a join request."})
    if server is None:
        raise ValidationError({"server": "Select a valid server."})

    student_number_value = (student_number or "").strip()
    if not student_number_value:
        raise ValidationError({"student_number": "Student number is required."})

    normalized_subjects = _normalize_subject_entries(subjects)
    if not cor_file:
        raise ValidationError({"cor_file": "A CoR file is required."})

    request_obj = JoinRequest(
        user=user,
        student_number=student_number_value,
        cor_file=cor_file,
    )
    try:
        with transaction.atomic():
            server_id = getattr(server, "pk", server)
            try:
                current_server = Server.objects.select_for_update().get(
                    pk=server_id,
                )
            except Server.DoesNotExist:
                raise ValidationError(
                    {"server": "Select a valid server."}
                ) from None
            if not current_server.is_active:
                raise ValidationError(
                    {"server": "This server is not accepting join requests."}
                )
            request_obj.server = current_server

            if Membership.objects.filter(
                user=user,
                server=current_server,
                status=MembershipStatus.ACTIVE,
            ).exists():
                raise ValidationError(
                    {"server": "You already belong to this server."}
                )
            if JoinRequest.objects.filter(
                user=user,
                server=current_server,
                status=RequestStatus.PENDING,
            ).exists():
                raise ValidationError(
                    {
                        "server": (
                            "You already have a pending join request for this server."
                        )
                    }
                )

            request_obj.full_clean(exclude=("reviewed_by",))
            request_obj.save()
            JoinRequestSubject.objects.bulk_create(
                [
                    JoinRequestSubject(
                        join_request=request_obj,
                        subject_code=subject_code,
                    )
                    for subject_code in normalized_subjects
                ]
            )
    except IntegrityError as error:
        if _is_join_request_pending_conflict(error):
            raise ValidationError(
                {"server": "You already have a pending join request for this server."}
            ) from None
        raise
    return request_obj


def decide_join_request(
    *,
    request_id,
    reviewer,
    decision,
    decision_reason,
    membership_role=None,
):
    """Approve or reject a pending join request for the actual server."""
    if decision not in (RequestStatus.APPROVED, RequestStatus.REJECTED):
        raise ValidationError({"decision": "Choose approve or reject."})

    reason = (decision_reason or "").strip()
    if not reason:
        raise ValidationError({"decision_reason": "A reason is required."})

    with transaction.atomic():
        if getattr(connection.features, "has_select_for_update_of", False):
            request_obj = (
                JoinRequest.objects.select_for_update(of=("self",))
                .select_related("server", "user")
                .get(pk=request_id)
            )
        else:
            request_obj = (
                JoinRequest.objects.select_for_update()
                .select_related("server", "user")
                .get(pk=request_id)
            )
        if request_obj.status != RequestStatus.PENDING:
            raise ValidationError({"status": "This request has already been decided."})
        if not is_active_president_of_server(reviewer, request_obj.server):
            raise ValidationError(
                {"reviewer": "Only the active President of this server may review requests."}
            )

        decision_at = timezone.now()
        request_obj.decision_reason = reason
        request_obj.reviewed_by = reviewer
        request_obj.reviewed_at = decision_at
        request_obj.cor_cleanup_status = (
            CorCleanupStatus.PENDING if request_obj.cor_file else CorCleanupStatus.NOT_REQUIRED
        )

        if decision == RequestStatus.APPROVED:
            existing_membership = Membership.objects.select_for_update().filter(
                user=request_obj.user,
                server=request_obj.server,
            ).first()
            if existing_membership is None:
                chosen_role = (membership_role or "").strip().lower()
                if chosen_role and chosen_role not in (MembershipRole.STUDENT,):
                    raise ValidationError(
                        {"membership_role": "First-time join requests default to Student."}
                    )
                target_membership = Membership(
                    user=request_obj.user,
                    server=request_obj.server,
                    role=MembershipRole.STUDENT,
                    status=MembershipStatus.ACTIVE,
                    joined_at=decision_at,
                    last_activated_at=decision_at,
                )
                target_membership.full_clean()
                target_membership.save(force_insert=True)
            else:
                if existing_membership.status == MembershipStatus.ACTIVE:
                    raise ValidationError(
                        {"server": "This student already has an active membership in this server."}
                    )
                if existing_membership.status not in (MembershipStatus.LEFT, MembershipStatus.REMOVED):
                    raise ValidationError(
                        {"server": "This membership could not be reactivated."}
                    )
                chosen_role = (membership_role or "").strip().lower()
                if chosen_role not in (MembershipRole.STUDENT, MembershipRole.OFFICER):
                    raise ValidationError(
                        {"membership_role": "Choose Student or Officer for a returning member."}
                    )
                if chosen_role == MembershipRole.PRESIDENT:
                    raise ValidationError(
                        {"membership_role": "President is not a valid returning-member role."}
                    )
                target_membership = existing_membership
                target_membership.role = chosen_role
                target_membership.status = MembershipStatus.ACTIVE
                target_membership.left_at = None
                target_membership.last_activated_at = decision_at
                target_membership.joined_at = decision_at
                target_membership.full_clean()
                target_membership.save(
                    update_fields=(
                        "role",
                        "status",
                        "joined_at",
                        "last_activated_at",
                        "left_at",
                        "updated_at",
                    )
                )

            approved_subjects = list(
                JoinRequestSubject.objects.filter(join_request=request_obj).values_list(
                    "subject_code",
                    flat=True,
                )
            )
            MembershipSubject.objects.filter(membership=target_membership).delete()
            if approved_subjects:
                MembershipSubject.objects.bulk_create(
                    [
                        MembershipSubject(
                            membership=target_membership,
                            subject_code=subject_code,
                        )
                        for subject_code in approved_subjects
                    ]
                )

        request_obj.status = decision
        request_obj.save(
            update_fields=(
                "status",
                "decision_reason",
                "reviewed_by",
                "reviewed_at",
                "cor_cleanup_status",
                "updated_at",
            )
        )
        transaction.on_commit(
            lambda decided_request=request_obj: attempt_cor_cleanup(decided_request),
            robust=True,
        )

    return request_obj


def _is_join_request_pending_conflict(error):
    """Return whether a database error names the pending-join-request constraint."""
    database_error = error.__cause__
    if database_error is None:
        return False

    diagnostics = getattr(database_error, "diag", None)
    if diagnostics is not None:
        return (
            getattr(diagnostics, "constraint_name", None)
            == "servers_joinrequest_one_pending_per_user_server"
        )

    if isinstance(database_error, sqlite3.IntegrityError):
        error_name = getattr(database_error, "sqlite_errorname", None)
        if error_name not in (None, "SQLITE_CONSTRAINT_UNIQUE"):
            return False

        prefix, separator, columns = str(database_error).partition(":")
        if not separator or prefix.strip().casefold() != "unique constraint failed":
            return False

        expected_column = (JoinRequest._meta.db_table, "user_id", "server_id")
        for column in columns.split(","):
            identifiers = tuple(
                identifier.strip().strip('"`[]').strip()
                for identifier in column.strip().split(".")
            )
            if identifiers[:2] == expected_column[:2]:
                return True

    return False

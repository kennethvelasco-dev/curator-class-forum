"""Atomic President title transfer service."""

from django.core.exceptions import ValidationError
from django.db import connection, transaction

from apps.servers.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Server,
)


def _parse_positive_id(raw, *, field="target"):
    """
    Accept only a positive int or a digit-only string representing one.

    Rejects bool, float, zero, negatives, None, malformed strings, and
    other object types. No generic int(raw) fallback.
    """
    if isinstance(raw, bool) or raw is None:
        raise ValidationError({field: "Select a valid member."})
    if isinstance(raw, int):
        if raw <= 0:
            raise ValidationError({field: "Select a valid member."})
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text or not text.isdigit():
            raise ValidationError({field: "Select a valid member."})
        value = int(text)
        if value <= 0:
            raise ValidationError({field: "Select a valid member."})
        return value
    raise ValidationError({field: "Select a valid member."})


def _membership_locked_qs():
    """
    Membership queryset with select_for_update.

    Uses of=("self",) only when the backend advertises support
    (PostgreSQL). Avoids try/except around query execution so unrelated
    TypeErrors are not masked.
    """
    if getattr(connection.features, "has_select_for_update_of", False):
        return Membership.objects.select_for_update(of=("self",))
    return Membership.objects.select_for_update()


def transfer_presidency(*, server, acting_user, target_membership_id, password):
    """
    Transfer the active President role from acting_user to an existing
    active member of the same server.

    Application guarantees (logic/constraints verified under SQLite):
    - Entire operation runs inside transaction.atomic().
    - Server row is locked first with select_for_update (same ordering as
      join-request approval).
    - Membership rows are locked next via backend-aware select_for_update.
    - Eligibility is revalidated under those locks.
    - Password is verified only after locks and eligibility checks, and
      immediately before role changes.
    - Self-transfer is rejected; no Membership is created or reactivated.
    - Outgoing President becomes student; target becomes president.
    - Unrelated history (subjects, timestamps, other memberships) is
      left unchanged.
    - Server has no president/owner FK; authority lives only on Membership.

    Note: SQLite does not provide the same row-level locking semantics as
    PostgreSQL. These tests confirm application logic and constraint
    enforcement only. PostgreSQL concurrency remains a staging verification
    item and is not claimed here.
    """
    if server is None:
        raise ValidationError({"server": "A server is required."})
    if acting_user is None or not getattr(acting_user, "is_authenticated", False):
        raise ValidationError({"acting_user": "Authentication is required."})
    if not getattr(acting_user, "is_active", True):
        raise ValidationError({"acting_user": "Authentication is required."})
    if password is None or password == "":
        raise ValidationError({"password": "Password confirmation is required."})

    target_membership_id = _parse_positive_id(target_membership_id, field="target")

    with transaction.atomic():
        # Lock Server first (consistent with join-request approval ordering).
        locked_server = (
            Server.objects.select_for_update()
            .filter(pk=server.pk)
            .first()
        )
        if locked_server is None:
            raise ValidationError({"server": "Server not found."})
        if not locked_server.is_active:
            raise ValidationError({"server": "This server is not active."})

        acting_membership = (
            _membership_locked_qs()
            .filter(
                user=acting_user,
                server=locked_server,
                role=MembershipRole.PRESIDENT,
                status=MembershipStatus.ACTIVE,
            )
            .first()
        )
        if acting_membership is None:
            raise ValidationError(
                {
                    "acting_user": (
                        "Only the current active President of this server "
                        "may transfer the title."
                    )
                }
            )

        target_membership = (
            _membership_locked_qs()
            .filter(
                pk=target_membership_id,
                server=locked_server,
            )
            .select_related("user")
            .first()
        )
        if target_membership is None:
            raise ValidationError(
                {"target": "The selected member was not found in this server."}
            )
        if target_membership.status != MembershipStatus.ACTIVE:
            raise ValidationError(
                {"target": "The selected member is not an active member of this server."}
            )
        if target_membership.user_id == acting_user.pk:
            raise ValidationError(
                {"target": "You cannot transfer the President title to yourself."}
            )
        target_user = target_membership.user
        if not getattr(target_user, "is_email_verified", False):
            raise ValidationError(
                {"target": "The selected member must have a verified account."}
            )
        if not getattr(target_user, "is_active", True):
            raise ValidationError(
                {"target": "The selected member's account is not active."}
            )

        # Password check after locks and eligibility, before role changes.
        if not acting_user.check_password(password):
            raise ValidationError({"password": "Incorrect password."})

        # Demote outgoing President first so the partial unique constraint
        # is never violated when promoting the target.
        acting_membership.role = MembershipRole.STUDENT
        acting_membership.full_clean()
        acting_membership.save(update_fields=["role", "updated_at"])

        target_membership.role = MembershipRole.PRESIDENT
        target_membership.full_clean()
        target_membership.save(update_fields=["role", "updated_at"])

        president_count = Membership.objects.filter(
            server=locked_server,
            role=MembershipRole.PRESIDENT,
            status=MembershipStatus.ACTIVE,
        ).count()
        if president_count != 1:
            raise ValidationError(
                {
                    "server": (
                        "Transfer failed: the server must have exactly one "
                        "active President."
                    )
                }
            )

    return {
        "server": locked_server,
        "former_president": acting_membership,
        "new_president": target_membership,
    }

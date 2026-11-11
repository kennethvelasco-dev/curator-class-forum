"""Server-scoped Student and Officer role changes."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, transaction

from apps.servers.models import Membership, MembershipRole, MembershipStatus, Server


def _parse_membership_id(raw):
    """Accept only a positive integer or a digit-only string."""
    if isinstance(raw, bool) or raw is None:
        raise ValidationError({"target_membership_id": "Select a valid member."})
    if isinstance(raw, int):
        if raw > 0:
            return raw
    elif isinstance(raw, str):
        value = raw.strip()
        if value.isdigit() and int(value) > 0:
            return int(value)
    raise ValidationError({"target_membership_id": "Select a valid member."})


def _locked_memberships():
    queryset = Membership.objects
    if getattr(connection.features, "has_select_for_update_of", False):
        return queryset.select_for_update(of=("self",))
    return queryset.select_for_update()


def change_member_role(
    *,
    server,
    acting_user,
    target_membership_id,
    new_role,
):
    """
    Promote a Student to Officer or demote an Officer to Student.

    All authority and eligibility checks are repeated under locks. Only the
    target membership's role is persisted, preserving its other fields.
    Self-changes are rejected so a server retains an active President.

    Return ``(membership, changed)``; assigning the current Student or
    Officer role is a successful no-op and performs no Membership update.
    """
    if server is None or getattr(server, "pk", None) is None:
        raise ValidationError({"server": "A valid server is required."})
    if (
        acting_user is None
        or not getattr(acting_user, "is_authenticated", False)
        or not getattr(acting_user, "is_active", False)
    ):
        raise ValidationError({"acting_user": "An active account is required."})
    if not getattr(acting_user, "is_email_verified", False):
        raise ValidationError(
            {"acting_user": "A verified account is required."}
        )
    if new_role not in (MembershipRole.STUDENT, MembershipRole.OFFICER):
        raise ValidationError(
            {"new_role": "Members can only be assigned Student or Officer."}
        )

    target_membership_id = _parse_membership_id(target_membership_id)

    with transaction.atomic():
        locked_server = (
            Server.objects.select_for_update()
            .filter(pk=server.pk)
            .first()
        )
        if locked_server is None:
            raise ValidationError({"server": "Server not found."})
        if not locked_server.is_active:
            raise ValidationError({"server": "This server is not active."})

        memberships = _locked_memberships()
        president_membership = memberships.filter(
            user_id=acting_user.pk,
            server=locked_server,
            role=MembershipRole.PRESIDENT,
            status=MembershipStatus.ACTIVE,
        ).first()
        if president_membership is None:
            raise ValidationError(
                {
                    "acting_user": (
                        "Only this server's active President can manage member roles."
                    )
                }
            )

        target_membership = (
            memberships.filter(
                pk=target_membership_id,
                server=locked_server,
            )
            .first()
        )
        if target_membership is None:
            raise ValidationError(
                {
                    "target_membership_id": (
                        "The selected member was not found in this server."
                    )
                }
            )
        if target_membership.status != MembershipStatus.ACTIVE:
            raise ValidationError(
                {
                    "target_membership_id": (
                        "The selected member is not active in this server."
                    )
                }
            )
        if target_membership.role == MembershipRole.PRESIDENT:
            raise ValidationError(
                {
                    "target_membership_id": (
                        "The President role can only be changed through "
                        "Presidency transfer."
                    )
                }
            )
        if target_membership.user_id == acting_user.pk:
            raise ValidationError(
                {
                    "target_membership_id": (
                        "You cannot change your own role through member management."
                    )
                }
            )
        if target_membership.role not in (
            MembershipRole.STUDENT,
            MembershipRole.OFFICER,
        ):
            raise ValidationError(
                {"target_membership_id": "The member has an invalid role."}
            )

        user_model = get_user_model()
        locked_users = {
            user.pk: user
            for user in (
                user_model._default_manager.select_for_update()
                .filter(pk__in=(acting_user.pk, target_membership.user_id))
                .order_by("pk")
            )
        }
        locked_actor = locked_users.get(acting_user.pk)
        target_user = locked_users.get(target_membership.user_id)
        if (
            locked_actor is None
            or not locked_actor.is_active
            or not locked_actor.is_email_verified
        ):
            raise ValidationError(
                {"acting_user": "The President account is not eligible."}
            )
        if target_user is None or not target_user.is_active:
            raise ValidationError(
                {"target_membership_id": "The selected account is not active."}
            )
        if not target_user.is_email_verified:
            raise ValidationError(
                {
                    "target_membership_id": (
                        "The selected account must be verified."
                    )
                }
            )

        if target_membership.role == new_role:
            return target_membership, False

        valid_transition = (
            target_membership.role == MembershipRole.STUDENT
            and new_role == MembershipRole.OFFICER
        ) or (
            target_membership.role == MembershipRole.OFFICER
            and new_role == MembershipRole.STUDENT
        )
        if not valid_transition:
            raise ValidationError(
                {
                    "new_role": (
                        "Choose Officer for a Student or Student for an Officer."
                    )
                }
            )

        target_membership.role = new_role
        target_membership.save(update_fields=["role", "updated_at"])

    return target_membership, True

"""Server-scoped channel access policy (minimum FR-010 enforcement)."""

from django.db.models import Q

from apps.channels.models import Channel, ChannelType
from apps.servers.models import (
    Membership,
    MembershipStatus,
    MembershipSubject,
)


DEFAULT_CHANNEL_TYPES = (
    ChannelType.ANNOUNCEMENTS,
    ChannelType.CALENDAR,
    ChannelType.RULES,
)


def get_accessible_channels_for_user(user, server):
    """
    Return channels the user may access inside the given server.

    - Default channels (Announcements, Calendar, Rules) are visible to any
      active member of the server.
    - Subject channels are granted only when Channel.slug equals an approved
      MembershipSubject.subject_code for this membership exactly (case-
      sensitive, slug only — never Channel.name).
    - Matching is unambiguous within a server because Channel enforces
      UniqueConstraint(server, slug).
    - Non-members receive an empty queryset.
    - No Channel.subject_code field or MembershipSubject→Channel FK exists.
      Approximate matching (name, casefold, slugify) is intentionally not
      used; Sprint 3 subject-channel creation should set Channel.slug to the
      canonical subject_code for this policy to take effect.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return Channel.objects.none()
    if server is None:
        return Channel.objects.none()

    membership = (
        Membership.objects.filter(
            user=user,
            server=server,
            status=MembershipStatus.ACTIVE,
            server__is_active=True,
        )
        .first()
    )
    if membership is None:
        return Channel.objects.none()

    approved_codes = list(
        MembershipSubject.objects.filter(membership=membership).values_list(
            "subject_code",
            flat=True,
        )
    )
    # Exact slug equality only — no name matching, no case folding.
    approved_codes = [code for code in approved_codes if code]

    default_q = Q(channel_type__in=DEFAULT_CHANNEL_TYPES)
    if approved_codes:
        subject_q = Q(channel_type=ChannelType.SUBJECT, slug__in=approved_codes)
        channel_filter = default_q | subject_q
    else:
        channel_filter = default_q

    return (
        Channel.objects.filter(server=server)
        .filter(channel_filter)
        .order_by("channel_type", "name", "pk")
    )


def user_can_access_channel(user, channel):
    """
    Return whether the user is authorized to access the given channel.

    Enforces server-scoped membership and exact subject-slug isolation.
    """
    if channel is None:
        return False
    accessible = get_accessible_channels_for_user(user, channel.server)
    return accessible.filter(pk=channel.pk).exists()

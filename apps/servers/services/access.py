"""Server-scoped channel access policy (FR-016, US-05, BR-01).

Shows a member only the channels the member may access, scoped to a single
server. Subject-channel access is driven by the user's current approved
MembershipSubject records matched against Channel.subject_code (case-
insensitive). Officer and President roles unlock every channel in their own
active server. No permission results are cached; subject enrollment changes
take effect on the next request.
"""

from django.db.models import Q

from apps.channels.models import Channel, ChannelType
from apps.servers.models import (
    Membership,
    MembershipRole,
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
    Return the queryset of channels the user may access inside the given server.

    Policy:
    - Anonymous / None user, None server: no channels.
    - No active membership in an active server: no channels.
    - LEFT / REMOVED membership: no channels.
    - Membership in another server: no access to this server's channels.
    - Active Officer / President in an active server: all channels in that server.
    - Active Student: default channels (Announcements, Calendar, Rules) plus
      subject channels whose subject_code matches one of the student's current
      approved MembershipSubject.subject_code values (case-insensitive).
      A student with no approved subjects sees only default channels.
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
        .select_related("server")
        .first()
    )
    if membership is None:
        return Channel.objects.none()

    base_qs = Channel.objects.filter(server=server)
    default_q = Q(channel_type__in=DEFAULT_CHANNEL_TYPES)

    # Officers and Presidents see every channel in their own active server.
    if membership.role in (
        MembershipRole.OFFICER,
        MembershipRole.PRESIDENT,
    ):
        return base_qs.order_by("channel_type", "name", "pk")

    # Students: default channels plus assigned subject channels.
    approved_codes = [
        code
        for code in MembershipSubject.objects.filter(membership=membership).values_list(
            "subject_code", flat=True
        )
        if code
    ]

    if not approved_codes:
        # Empty-subject safeguard: only default channels. Never fall through to
        # an unrestricted subject filter that would expose every subject channel.
        return base_qs.filter(default_q).order_by("channel_type", "name", "pk")

    # Case-insensitive match of Channel.subject_code against each approved
    # subject code. __iexact is portable across SQLite and PostgreSQL and only
    # matches non-null subject_codes, so no separate isnull term is needed.
    subject_q = Q()
    for code in approved_codes:
        subject_q |= Q(
            channel_type=ChannelType.SUBJECT,
            subject_code__iexact=code,
        )

    return (
        base_qs.filter(default_q | subject_q)
        .order_by("channel_type", "name", "pk")
    )


def user_can_access_channel(user, channel):
    """
    Return whether the user is authorized to access the given channel.

    Delegates to get_accessible_channels_for_user so a single, centralized
    policy is enforced rather than a separate permission system.
    """
    if channel is None:
        return False
    accessible = get_accessible_channels_for_user(user, channel.server)
    return accessible.filter(pk=channel.pk).exists()

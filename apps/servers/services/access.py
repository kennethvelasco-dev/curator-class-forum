"""Server-scoped channel access policy (FR-016, US-05, BR-01).

Shows a member only the channels the member may access, scoped to a single
server. Subject-channel access is driven by the user's current approved
MembershipSubject records matched against Channel.subject_code_normalized
(canonicalized + Unicode case-folded). Officer and President roles unlock every
channel in their own active server. No permission results are cached; subject
enrollment changes take effect on the next request.
"""

from django.db.models import Q, Exists, OuterRef

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
      subject channels whose subject_code_normalized matches one of the
      student's current approved MembershipSubject records (canonicalized and
      Unicode case-folded). A student with no approved subjects sees only
      default channels.

    All authorization predicates (active membership, active server, role, and
    subject matching) are expressed as correlated database subqueries evaluated
    when the queryset is consumed, preserving laziness and preventing stale
    permissions if membership status or subject enrollments change after
    queryset construction.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return Channel.objects.none()
    if server is None:
        return Channel.objects.none()

    base_qs = Channel.objects.filter(server=server)

    # 1 & 2 & 3: Active membership in an active server checked at evaluation time
    # through a correlated Exists predicate across all channels (including defaults).
    active_membership = Membership.objects.filter(
        user=user,
        server=OuterRef("server_id"),
        status=MembershipStatus.ACTIVE,
        server__is_active=True,
    )

    # 4: Elevated Officer/President access within their active server, evaluated at query time.
    is_officer_or_president = Membership.objects.filter(
        user=user,
        server=OuterRef("server_id"),
        role__in=(MembershipRole.OFFICER, MembershipRole.PRESIDENT),
        status=MembershipStatus.ACTIVE,
        server__is_active=True,
    )

    # 5: Correlated Exists matching between Channel.subject_code_normalized
    # and MembershipSubject.subject_code_normalized for current approved subjects.
    # Legacy channels (where Channel.subject_code_normalized is None) will not match.
    has_approved_subject = MembershipSubject.objects.filter(
        membership__user=user,
        membership__server=OuterRef("server_id"),
        membership__status=MembershipStatus.ACTIVE,
        membership__server__is_active=True,
        subject_code_normalized=OuterRef("subject_code_normalized"),
    ).exclude(subject_code_normalized__isnull=True)

    default_channels_q = Q(channel_type__in=DEFAULT_CHANNEL_TYPES)
    officer_president_q = Q(Exists(is_officer_or_president))
    student_subject_q = Q(
        channel_type=ChannelType.SUBJECT,
    ) & Q(Exists(has_approved_subject))

    membership_gate = Q(Exists(active_membership))
    channel_visibility = default_channels_q | officer_president_q | student_subject_q

    return base_qs.filter(membership_gate & channel_visibility).order_by(
        "channel_type", "name", "pk"
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

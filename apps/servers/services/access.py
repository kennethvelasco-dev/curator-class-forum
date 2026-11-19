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
from apps.servers.subject_codes import canonicalize_subject_code, SubjectCodeError


DEFAULT_CHANNEL_TYPES = (
    ChannelType.ANNOUNCEMENTS,
    ChannelType.CALENDAR,
    ChannelType.RULES,
)


def _normalize_approved_codes(codes):
    """Return a list of case-folded, canonicalized subject-code comparison keys.

    Invalid codes are skipped defensively so they never grant access.
    """
    normalized = []
    for code in codes:
        if not code:
            continue
        try:
            normalized.append(canonicalize_subject_code(code).casefold())
        except SubjectCodeError:
            continue
    return normalized


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

    All filtering is expressed in the database query so that role authorization
    and subject matching are evaluated when the queryset is consumed, not at
    construction time. No permission results are cached.
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

    # Normalize approved subject codes once; invalid codes are skipped so they
    # never grant access.
    approved_codes = MembershipSubject.objects.filter(
        membership=membership
    ).values_list("subject_code", flat=True)
    normalized_codes = _normalize_approved_codes(approved_codes)

    # Role check pushed into the database via a correlated EXISTS subquery so
    # it is evaluated when the queryset is consumed, not at construction time.
    # This prevents a concurrent role demotion from leaving a previously
    # authorized unrestricted queryset available after evaluation.
    is_officer_or_president = Membership.objects.filter(
        user=user,
        server=OuterRef("server_id"),
        role__in=(MembershipRole.OFFICER, MembershipRole.PRESIDENT),
        status=MembershipStatus.ACTIVE,
    ).filter(server__is_active=True)

    subject_access_q = Q(
        channel_type=ChannelType.SUBJECT,
    ) & (
        Q(subject_code_normalized__in=normalized_codes)
        | Q(Exists(is_officer_or_president))
    )

    return (
        base_qs.filter(default_q | subject_access_q)
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

"""Server-scoped authorization helpers for membership workflows."""

from apps.servers.models import Membership, MembershipRole, MembershipStatus


def is_active_president_of_server(user, server):
    """Return whether the user is an active President in the given server."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if server is None:
        return False
    return Membership.objects.filter(
        user=user,
        server=server,
        role=MembershipRole.PRESIDENT,
        status=MembershipStatus.ACTIVE,
    ).exists()


def can_view_server_member_list(user, server):
    """Return whether the user is an active President or Officer in a server."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if server is None:
        return False
    return Membership.objects.filter(
        user=user,
        server=server,
        role__in=(MembershipRole.PRESIDENT, MembershipRole.OFFICER),
        status=MembershipStatus.ACTIVE,
        server__is_active=True,
    ).exists()

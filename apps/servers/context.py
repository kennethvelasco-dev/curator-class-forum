"""Validated server context helpers for multi-server memberships."""

from apps.servers.models import Membership, MembershipStatus

ACTIVE_SERVER_SESSION_KEY = "servers.active_server_id"


def get_active_memberships(user):
    """Return the user's active memberships in active servers."""
    if user is None or not getattr(user, "is_authenticated", False):
        return Membership.objects.none()
    return (
        Membership.objects.filter(
            user=user,
            status=MembershipStatus.ACTIVE,
            server__is_active=True,
        )
        .select_related("server")
        .order_by("joined_at", "pk")
    )


def get_active_membership_for_server(user, server):
    """Return the user's active membership for a specific server, or None."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    if server is None:
        return None
    return (
        Membership.objects.filter(
            user=user,
            server=server,
            status=MembershipStatus.ACTIVE,
            server__is_active=True,
        )
        .select_related("server")
        .first()
    )


def _parse_server_id(raw):
    """
    Parse a session or form value into a positive integer server PK.

    Accepts only:
    - positive int (not bool; bool is rejected explicitly)
    - digit-only strings representing a positive integer

    Rejects: None, bool, float, zero, negatives, signed/decimal strings,
    empty strings, and any other object type. No generic int(raw) fallback.
    """
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, str):
        text = raw.strip()
        if not text or not text.isdigit():
            return None
        value = int(text)
        return value if value > 0 else None
    return None


def resolve_active_server(request):
    """
    Resolve the current server context from the session.

    Always re-validates against the user's active Membership and the
    server's active state. Session state never replaces authorization.
    """
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return None

    memberships = list(get_active_memberships(request.user))
    if not memberships:
        _clear_active_server(request)
        return None

    if len(memberships) == 1:
        only = memberships[0]
        _set_session_server_id(request, only.server_id)
        return only.server

    raw_id = request.session.get(ACTIVE_SERVER_SESSION_KEY)
    server_id = _parse_server_id(raw_id)
    if server_id is not None:
        for membership in memberships:
            if membership.server_id == server_id:
                return membership.server
        _clear_active_server(request)
    elif raw_id is not None:
        _clear_active_server(request)

    # Fall back to the earliest membership when no valid selection exists.
    fallback = memberships[0]
    _set_session_server_id(request, fallback.server_id)
    return fallback.server


def set_active_server(request, server_id):
    """
    Attempt to set the active server context.

    Returns True only when the user has an active membership in an active
    server with the given primary key.
    """
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return False

    parsed = _parse_server_id(server_id)
    if parsed is None:
        return False

    membership = (
        Membership.objects.filter(
            user=request.user,
            server_id=parsed,
            status=MembershipStatus.ACTIVE,
            server__is_active=True,
        )
        .select_related("server")
        .first()
    )
    if membership is None:
        return False

    _set_session_server_id(request, membership.server_id)
    return True


def _set_session_server_id(request, server_id):
    request.session[ACTIVE_SERVER_SESSION_KEY] = int(server_id)


def _clear_active_server(request):
    request.session.pop(ACTIVE_SERVER_SESSION_KEY, None)

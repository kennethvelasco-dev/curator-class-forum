"""Test factories for the anonymity tests, written against the merged models.

``Thread.save`` and ``Reply.save`` (Issue #31) reject authors without channel
access, so ``make_channel`` creates active student memberships for the users
that will post. A default (Announcements) channel is used because every active
member may access it.
"""

import itertools

from django.contrib.auth import get_user_model

from apps.channels.models import Channel, ChannelType
from apps.discussions.models import Reply, Thread
from apps.servers.models import Membership, MembershipRole, MembershipStatus, Server

_counter = itertools.count(1)


def make_user(pk=None, name="Zed Quillfeather", email=None):
    """Create a verified user, optionally with an explicit distinctive pk."""
    unique = next(_counter)
    extra = {"id": pk} if pk is not None else {}
    return get_user_model().objects.create_user(
        email=email or f"user{unique}@example.edu",
        password=None,  # unusable password: avoids slow hashing in tests
        full_name=name,
        is_email_verified=True,
        **extra,
    )


def make_channel(members=()):
    """Create a server with an Announcements channel and active student members."""
    unique = next(_counter)
    members = list(members)
    creator = members[0] if members else make_user()
    server = Server.objects.create(
        name=f"Server {unique}", slug=f"server-{unique}", created_by=creator
    )
    for user in members:
        Membership.objects.create(
            user=user,
            server=server,
            role=MembershipRole.STUDENT,
            status=MembershipStatus.ACTIVE,
        )
    return Channel.objects.create(
        server=server,
        name="Announcements",
        slug="announcements",
        channel_type=ChannelType.ANNOUNCEMENTS,
    )


def make_thread(author, *, channel=None, anonymous=False, title="Question", body="Body"):
    return Thread.objects.create(
        channel=channel or make_channel(members=[author]),
        author=author,
        title=title,
        body=body,
        is_anonymous=anonymous,
    )


def make_reply(thread, author, *, anonymous=False, body="Reply"):
    return Reply.objects.create(
        thread=thread, author=author, body=body, is_anonymous=anonymous
    )

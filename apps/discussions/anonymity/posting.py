"""Single save path for posts that may be anonymous (Issue #36).

Thread and reply views call ``publish_post`` so the contract is the same in
both workflows: set the author from the request, take the anonymity choice from
the validated form, save, and allocate the alias, all in one transaction. If
the save or the allocation fails nothing is kept, so no orphaned alias remains.
"""

from django.db import transaction

from apps.discussions.anonymity.service import ensure_alias_for_post


def publish_post(post, *, author, is_anonymous):
    """Save a Thread or Reply authored by ``author`` and return it.

    ``author`` must be the authenticated request user and ``is_anonymous`` the
    validated checkbox value; neither may come from client-supplied identity
    data.
    """
    with transaction.atomic():
        post.author = author
        post.is_anonymous = bool(is_anonymous)
        post.save()
        ensure_alias_for_post(post)
    return post

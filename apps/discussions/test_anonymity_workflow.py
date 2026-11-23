"""Issue #36 integration tests through the real discussion workflows.

Thread creation and the channel thread list are exercised over HTTP. There is
no reply route on this revision (Issue #34), so replies are exercised through
``publish_post``, the single save path that the reply view must call.
"""

import re
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.channels.models import Channel, ChannelType
from apps.discussions.anonymity.leak_assertions import assert_no_identity_leak
from apps.discussions.anonymity.models import ThreadAlias
from apps.discussions.anonymity.posting import publish_post
from apps.discussions.anonymity.service import (
    AliasAllocationError,
    ensure_alias_for_post,
    resolve_identities,
)
from apps.discussions.models import Reply, Thread
from apps.servers.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    MembershipSubject,
    Server,
)

User = get_user_model()
TEMPLATES = Path(__file__).resolve().parents[2] / "templates"


def make_member(server, pk, name, email):
    user = User.objects.create_user(
        email=email, password=None, full_name=name, is_email_verified=True, id=pk
    )
    membership = Membership.objects.create(
        user=user, server=server, role=MembershipRole.STUDENT,
        status=MembershipStatus.ACTIVE,
    )
    MembershipSubject.objects.create(membership=membership, subject_code="general")
    return user


class WorkflowBase(TestCase):
    def setUp(self):
        creator = User.objects.create_user(
            email="creator@example.edu", password=None, full_name="Creator",
            is_email_verified=True,
        )
        self.server = Server.objects.create(
            name="Workflow Server", slug="workflow-server", created_by=creator
        )
        self.channel = Channel.objects.create(
            server=self.server, name="General", slug="general",
            subject_code="general", channel_type=ChannelType.SUBJECT,
        )
        self.starter = make_member(self.server, 48271, "Zed Quillfeather", "zed.quillfeather@example.edu")
        self.other = make_member(self.server, 53917, "Mina Harrowgate", "mina.harrowgate@example.edu")
        self.create_url = reverse(
            "channels:create_thread", args=[self.server.pk, self.channel.pk]
        )
        self.subject_url = reverse(
            "channels:subject", args=[self.server.pk, self.channel.pk]
        )

    def post_thread(self, user, anonymous, title="A question", body="Some details."):
        self.client.force_login(user)
        data = {"title": title, "body": body}
        if anonymous:
            data["is_anonymous"] = "on"
        return self.client.post(self.create_url, data)


class ThreadFormTests(WorkflowBase):
    def test_form_has_checkbox_notice_and_script(self):
        self.client.force_login(self.starter)
        response = self.client.get(self.create_url)
        html = response.content.decode()
        self.assertContains(response, 'name="is_anonymous"')
        self.assertContains(response, "Post Anonymously")
        self.assertContains(response, "data-anonymity-notice")
        for phrase in ("President", "Admin", "reason", "audit log", "notified"):
            self.assertIn(phrase, html)
        self.assertContains(response, "js/anonymity.js")
        notice_tag = re.search(r"<div[^>]*data-anonymity-notice[^>]*>", html).group(0)
        self.assertNotIn("hidden", notice_tag)
        self.assertEqual(html.count('name="is_anonymous"'), 1)

    def test_notice_does_not_claim_the_reveal_workflow_exists_here(self):
        self.client.force_login(self.starter)
        html = self.client.get(self.create_url).content.decode().lower()
        self.assertNotIn("you can request", html)


class ThreadCreationTests(WorkflowBase):
    def test_anonymous_thread_persists_flag_author_and_alias(self):
        response = self.post_thread(self.starter, anonymous=True)
        self.assertRedirects(response, self.subject_url)
        thread = Thread.objects.get()
        self.assertTrue(thread.is_anonymous)
        self.assertEqual(thread.author, self.starter)
        alias = ThreadAlias.objects.get(thread=thread)
        self.assertEqual(alias.user, self.starter)
        self.assertRegex(alias.label, r"^CSS-\d{5}$")

    def test_named_thread_persists_flag_and_creates_no_alias(self):
        self.post_thread(self.starter, anonymous=False)
        thread = Thread.objects.get()
        self.assertFalse(thread.is_anonymous)
        self.assertEqual(thread.author, self.starter)
        self.assertEqual(ThreadAlias.objects.count(), 0)

    def test_forged_identity_fields_are_ignored(self):
        self.client.force_login(self.starter)
        self.client.post(
            self.create_url,
            {
                "title": "t", "body": "b", "is_anonymous": "on",
                "author": str(self.other.pk), "author_id": str(self.other.pk),
                "label": "CSS-ABCDE", "alias": "CSS-ABCDE", "anon_label": "CSS-ABCDE",
            },
        )
        thread = Thread.objects.get()
        self.assertEqual(thread.author, self.starter)
        alias = ThreadAlias.objects.get(thread=thread)
        self.assertEqual(alias.user, self.starter)
        self.assertNotEqual(alias.label, "CSS-ABCDE")
        self.assertRegex(alias.label, r"^CSS-\d{5}$")

    def test_invalid_submission_creates_nothing_and_keeps_the_notice(self):
        self.client.force_login(self.starter)
        response = self.client.post(
            self.create_url, {"title": "  ", "body": "b", "is_anonymous": "on"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Thread.objects.count(), 0)
        self.assertEqual(ThreadAlias.objects.count(), 0)
        self.assertContains(response, "data-anonymity-notice")

    def test_non_member_cannot_post_and_leaves_no_alias(self):
        outsider = User.objects.create_user(
            email="out@example.edu", password=None, full_name="Outside",
            is_email_verified=True,
        )
        response = self.post_thread(outsider, anonymous=True)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Thread.objects.count(), 0)
        self.assertEqual(ThreadAlias.objects.count(), 0)


class ThreadListRenderingTests(WorkflowBase):
    def test_other_member_sees_alias_and_author_badge_without_identity(self):
        self.post_thread(self.starter, anonymous=True, title="Anon question")
        alias = ThreadAlias.objects.get().label
        self.client.force_login(self.other)
        response = self.client.get(self.subject_url)
        self.assertContains(response, alias)
        self.assertContains(response, "author-badge")
        assert_no_identity_leak(self, response, self.starter)

    def test_the_starters_own_view_is_also_pseudonymous(self):
        self.post_thread(self.starter, anonymous=True)
        response = self.client.get(self.subject_url)
        self.assertContains(response, ThreadAlias.objects.get().label)
        assert_no_identity_leak(self, response, self.starter)

    def test_named_thread_shows_the_real_name_and_badge(self):
        self.post_thread(self.starter, anonymous=False)
        self.client.force_login(self.other)
        response = self.client.get(self.subject_url)
        self.assertContains(response, "Zed Quillfeather")
        self.assertContains(response, "author-badge")

    def test_alias_is_stable_across_reloads(self):
        self.post_thread(self.starter, anonymous=True)
        first = self.client.get(self.subject_url).content
        second = self.client.get(self.subject_url).content
        self.assertEqual(first, second)
        self.assertEqual(ThreadAlias.objects.count(), 1)

    def test_template_context_carries_no_author_or_user_object(self):
        self.post_thread(self.starter, anonymous=True)
        self.client.force_login(self.other)
        response = self.client.get(self.subject_url)
        self.assertNotIn("threads", response.context)
        (item,) = response.context["thread_items"]
        self.assertEqual(
            set(item), {"id", "title", "body", "created_at", "identity"}
        )
        values = [v for ctx in response.context for v in ctx.flatten().values()]
        self.assertFalse(
            any(isinstance(v, User) and v.pk == self.starter.pk for v in values),
            "the anonymous author must not appear in the template context",
        )

    def test_list_query_count_does_not_grow_with_thread_count(self):
        self.post_thread(self.starter, True, title="one")
        self.post_thread(self.starter, False, title="two")
        self.client.force_login(self.other)
        with CaptureQueriesContext(connection) as one:
            self.client.get(self.subject_url)
        for n in range(5):
            self.post_thread(self.starter, n % 2 == 0, title=f"more {n}")
        self.client.force_login(self.other)
        with CaptureQueriesContext(connection) as many:
            self.client.get(self.subject_url)
        self.assertEqual(len(one), len(many))

    def test_failed_alias_allocation_rolls_the_thread_back(self):
        self.client.raise_request_exception = False
        with mock.patch(
            "apps.discussions.anonymity.posting.ensure_alias_for_post",
            side_effect=AliasAllocationError("no label"),
        ):
            response = self.post_thread(self.starter, anonymous=True)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(Thread.objects.count(), 0)
        self.assertEqual(ThreadAlias.objects.count(), 0)

    def test_same_author_gets_independent_aliases_in_separate_threads(self):
        self.post_thread(self.starter, True, title="first")
        self.post_thread(self.starter, True, title="second")
        first, second = Thread.objects.order_by("pk")
        a = ThreadAlias.objects.get(thread=first, user=self.starter)
        b = ThreadAlias.objects.get(thread=second, user=self.starter)
        self.assertNotEqual(a.pk, b.pk)
        self.assertEqual(ThreadAlias.objects.count(), 2)


class ReplyPublishingTests(WorkflowBase):
    """Replies through ``publish_post`` (the reply route itself is Issue #34)."""

    def setUp(self):
        super().setUp()
        self.post_thread(self.starter, anonymous=True)
        self.thread = Thread.objects.get()

    def reply(self, user, anonymous, body="reply"):
        return publish_post(
            Reply(thread=self.thread, body=body), author=user, is_anonymous=anonymous
        )

    def identities(self, *replies):
        return resolve_identities(self.thread, [self.thread, *replies])

    def test_reply_flags_and_alias_creation(self):
        named = self.reply(self.other, False)
        anon = self.reply(self.other, True)
        self.assertFalse(Reply.objects.get(pk=named.pk).is_anonymous)
        self.assertTrue(Reply.objects.get(pk=anon.pk).is_anonymous)
        self.assertEqual(ThreadAlias.objects.filter(user=self.other).count(), 1)

    def test_starters_replies_reuse_the_thread_alias_and_get_the_badge(self):
        r1 = self.reply(self.starter, True)
        r2 = self.reply(self.starter, True)
        thread_identity, i1, i2 = self.identities(r1, r2)
        self.assertEqual(thread_identity.display_name, i1.display_name)
        self.assertEqual(i1.display_name, i2.display_name)
        self.assertTrue(thread_identity.show_author_badge)
        self.assertTrue(i1.show_author_badge and i2.show_author_badge)
        self.assertEqual(ThreadAlias.objects.filter(user=self.starter).count(), 1)

    def test_other_participants_get_their_own_alias_and_no_badge(self):
        starter_reply = self.reply(self.starter, True)
        other_anon = self.reply(self.other, True)
        other_named = self.reply(self.other, False)
        t, s, a, n = self.identities(starter_reply, other_anon, other_named)
        self.assertNotEqual(a.display_name, s.display_name)
        self.assertFalse(a.show_author_badge)
        self.assertEqual(n.display_name, "Mina Harrowgate")
        self.assertFalse(n.show_author_badge)

    def test_reply_alias_is_resolved_through_the_parent_thread(self):
        reply = self.reply(self.other, True)
        alias = ThreadAlias.objects.get(user=self.other)
        self.assertEqual(alias.thread_id, reply.thread_id)

    def test_failed_reply_leaves_no_alias(self):
        before = ThreadAlias.objects.count()
        with mock.patch(
            "apps.discussions.anonymity.posting.ensure_alias_for_post",
            side_effect=AliasAllocationError("no label"),
        ):
            with self.assertRaises(AliasAllocationError):
                self.reply(self.other, True)
        self.assertEqual(Reply.objects.count(), 0)
        self.assertEqual(ThreadAlias.objects.count(), before)


class AuthorBadgeWorkflowTests(WorkflowBase):
    """Author-badge policy through publish_post.

    Threads are created over HTTP (the reply route itself is Issue #34 and does
    not exist yet), replies are created through publish_post, and badges are
    checked through resolve_identities.
    """

    def make_named_thread(self):
        self.post_thread(self.starter, anonymous=False, title="Named thread")
        thread = Thread.objects.get(title="Named thread")
        ensure_alias_for_post(thread)
        return thread

    def make_anon_thread(self):
        self.post_thread(self.starter, anonymous=True, title="Anon thread")
        thread = Thread.objects.get(title="Anon thread")
        ensure_alias_for_post(thread)
        return thread

    def reply(self, thread, user, anonymous, body="reply"):
        return publish_post(
            Reply(thread=thread, body=body), author=user, is_anonymous=anonymous
        )

    def identities(self, thread, *replies):
        return resolve_identities(thread, [thread, *replies])

    def test_named_thread_named_reply_badge(self):
        thread = self.make_named_thread()
        reply = self.reply(thread, self.starter, anonymous=False)
        t, r = self.identities(thread, reply)
        self.assertTrue(t.show_author_badge)
        self.assertTrue(r.show_author_badge)

    def test_anonymous_thread_anonymous_reply_badge(self):
        thread = self.make_anon_thread()
        reply = self.reply(thread, self.starter, anonymous=True)
        t, r = self.identities(thread, reply)
        self.assertTrue(t.show_author_badge)
        self.assertTrue(r.show_author_badge)
        self.assertEqual(r.display_name, t.display_name)  # same alias as thread

    def test_named_thread_anonymous_reply_no_badge(self):
        thread = self.make_named_thread()
        reply = self.reply(thread, self.starter, anonymous=True)
        t, r = self.identities(thread, reply)
        self.assertTrue(t.show_author_badge)
        self.assertFalse(r.show_author_badge)

    def test_anonymous_thread_named_reply_no_badge(self):
        thread = self.make_anon_thread()
        reply = self.reply(thread, self.starter, anonymous=False)
        t, r = self.identities(thread, reply)
        self.assertTrue(t.show_author_badge)
        self.assertFalse(r.show_author_badge)

    def test_other_users_replies_never_badged(self):
        thread = self.make_named_thread()
        reply = self.reply(thread, self.other, anonymous=False)
        t, r = self.identities(thread, reply)
        self.assertTrue(t.show_author_badge)
        self.assertFalse(r.show_author_badge)

        thread2 = self.make_anon_thread()
        reply2 = self.reply(thread2, self.other, anonymous=True)
        t2, r2 = self.identities(thread2, reply2)
        self.assertTrue(t2.show_author_badge)
        self.assertFalse(r2.show_author_badge)


class RenderedTemplateScanTests(TestCase):
    FORBIDDEN = (
        r"thread\.author", r"\.author\b", r"author_id", r"author\.", r"\.email\b",
        r"full_name", r"data-author", r"data-user",
    )

    def test_integrated_templates_never_reference_author_data(self):
        for name in ("channels/subject.html", "discussions/create_thread.html"):
            text = (TEMPLATES / name).read_text()
            for pattern in self.FORBIDDEN:
                with self.subTest(template=name, pattern=pattern):
                    self.assertIsNone(re.search(pattern, text), name)
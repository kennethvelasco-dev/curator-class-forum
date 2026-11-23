"""Display, posting-flow and leakage tests for Issue #36.

The scratch view below stands in for the thread-detail view that Issues #33/#34
will provide. Replace it with the real URL once those merge (see report).
"""

import dataclasses

from django import forms
from django.contrib import admin
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.template import engines
from django.test import TestCase, override_settings
from django.urls import path

from apps.discussions.anonymity.factories import (
    make_channel,
    make_reply,
    make_thread,
    make_user,
)
from apps.discussions.anonymity.forms import AnonymityFormMixin
from apps.discussions.anonymity.leak_assertions import assert_no_identity_leak
from apps.discussions.anonymity.models import ThreadAlias
from apps.discussions.anonymity.service import (
    ensure_alias_for_post,
    resolve_identities,
)
from apps.discussions.models import Reply, Thread

PAGE = engines["django"].from_string(
    """
<h1>{{ thread.title }}</h1>
<div id="thread">{% include "discussions/_identity.html" with identity=thread_identity %}</div>
{% for item in replies %}
<div class="reply">{% include "discussions/_identity.html" with identity=item.identity %}
<p>{{ item.reply.body }}</p></div>
{% endfor %}
"""
)


def thread_page(request, thread_id):
    thread = Thread.objects.get(pk=thread_id)
    replies = list(Reply.objects.filter(thread=thread).order_by("pk"))
    identities = resolve_identities(thread, [thread, *replies])
    html = PAGE.render(
        {
            "thread": thread,
            "thread_identity": identities[0],
            "replies": [
                {"reply": r, "identity": i} for r, i in zip(replies, identities[1:])
            ],
        }
    )
    from django.http import HttpResponse

    return HttpResponse(html)


def thread_json(request, thread_id):
    thread = Thread.objects.get(pk=thread_id)
    replies = list(Reply.objects.filter(thread=thread).order_by("pk"))
    identities = resolve_identities(thread, [thread, *replies])
    return JsonResponse(
        {"identities": [dataclasses.asdict(i) for i in identities]}
    )


urlpatterns = [
    path("t/<int:thread_id>/", thread_page),
    path("t/<int:thread_id>/json/", thread_json),
    path("admin/", admin.site.urls),
]


class ThreadForm(AnonymityFormMixin, forms.ModelForm):
    class Meta:
        model = Thread
        fields = ("title", "body")


class ReplyForm(AnonymityFormMixin, forms.ModelForm):
    class Meta:
        model = Reply
        fields = ("body",)


def submit_thread(user, channel, data):
    """What a thread view should do (Issue #32 integration contract)."""
    form = ThreadForm(data)
    if not form.is_valid():
        return None
    with transaction.atomic():
        thread = form.save(commit=False)
        thread.author = user
        thread.channel = channel
        thread.is_anonymous = form.is_anonymous_choice
        thread.save()
        ensure_alias_for_post(thread)
    return thread


def submit_reply(user, thread, data):
    """What a reply view should do (Issue #34 integration contract)."""
    form = ReplyForm(data)
    if not form.is_valid():
        return None
    with transaction.atomic():
        reply = form.save(commit=False)
        reply.author = user
        reply.thread = thread
        reply.is_anonymous = form.is_anonymous_choice
        reply.save()
        ensure_alias_for_post(reply)
    return reply


class PostingFlowTests(TestCase):
    def setUp(self):
        self.alice = make_user(40001, "Alice Starter", "alice.starter@example.edu")
        self.bob = make_user(40002, "Bob Replier", "bob.replier@example.edu")
        self.channel = make_channel(members=[self.alice, self.bob])

    def test_checkbox_decides_persisted_flag(self):
        named = submit_thread(self.alice, self.channel, {"title": "t", "body": "b"})
        anon = submit_thread(
            self.alice, self.channel, {"title": "t", "body": "b", "is_anonymous": "on"}
        )
        self.assertFalse(Thread.objects.get(pk=named.pk).is_anonymous)
        self.assertTrue(Thread.objects.get(pk=anon.pk).is_anonymous)

    def test_anonymous_thread_gets_alias_named_thread_does_not(self):
        named = submit_thread(self.alice, self.channel, {"title": "t", "body": "b"})
        anon = submit_thread(
            self.alice, self.channel, {"title": "t", "body": "b", "is_anonymous": "on"}
        )
        self.assertFalse(ThreadAlias.objects.filter(thread=named).exists())
        self.assertTrue(ThreadAlias.objects.filter(thread=anon, user=self.alice).exists())

    def test_forged_author_fields_cannot_change_the_author(self):
        thread = submit_thread(
            self.alice,
            self.channel,
            {"title": "t", "body": "b", "author": str(self.bob.pk),
             "author_id": str(self.bob.pk), "label": "CSS-00001"},
        )
        self.assertEqual(thread.author_id, self.alice.pk)

    def test_real_author_is_stored_for_anonymous_posts(self):
        anon = submit_thread(
            self.alice, self.channel, {"title": "t", "body": "b", "is_anonymous": "on"}
        )
        reply = submit_reply(self.bob, anon, {"body": "r", "is_anonymous": "on"})
        self.assertEqual(Thread.objects.get(pk=anon.pk).author_id, self.alice.pk)
        self.assertEqual(Reply.objects.get(pk=reply.pk).author_id, self.bob.pk)

    def test_reply_flag_is_stored_for_named_and_anonymous_replies(self):
        thread = submit_thread(self.alice, self.channel, {"title": "t", "body": "b"})
        named = submit_reply(self.bob, thread, {"body": "r"})
        anon = submit_reply(self.bob, thread, {"body": "r", "is_anonymous": "on"})
        self.assertFalse(Reply.objects.get(pk=named.pk).is_anonymous)
        self.assertTrue(Reply.objects.get(pk=anon.pk).is_anonymous)
        self.assertFalse(ThreadAlias.objects.filter(thread=thread, user=self.alice).exists())
        self.assertTrue(ThreadAlias.objects.filter(thread=thread, user=self.bob).exists())

    def test_non_member_cannot_post_anonymously_and_no_alias_is_left_behind(self):
        from django.core.exceptions import ValidationError

        outsider = make_user(77001, "Outside Person", "outside.person@example.edu")
        with self.assertRaises(ValidationError):
            submit_thread(
                outsider, self.channel, {"title": "t", "body": "b", "is_anonymous": "on"}
            )
        self.assertFalse(Thread.objects.filter(author=outsider).exists())
        self.assertFalse(ThreadAlias.objects.filter(user=outsider).exists())

    def test_invalid_form_creates_nothing(self):
        self.assertIsNone(submit_thread(self.alice, self.channel, {"body": "no title"}))
        self.assertEqual(ThreadAlias.objects.count(), 0)

    def test_failed_alias_allocation_rolls_back_the_post(self):
        from unittest import mock

        from apps.discussions.anonymity import service

        before = Thread.objects.count()
        with mock.patch.object(service, "LABEL_SPACE", 0):
            with self.assertRaises(service.AliasAllocationError):
                submit_thread(
                    self.alice, self.channel,
                    {"title": "t", "body": "b", "is_anonymous": "on"},
                )
        self.assertEqual(Thread.objects.count(), before)


class ResolveIdentitiesTests(TestCase):
    def setUp(self):
        self.alice = make_user(40001, "Alice Starter", "alice.starter@example.edu")
        self.bob = make_user(40002, "Bob Replier", "bob.replier@example.edu")
        self.carol = make_user(40003, "Carol Other", "carol.other@example.edu")
        self.channel = make_channel(members=[self.alice, self.bob, self.carol])

    def build(self, thread_anonymous):
        thread = make_thread(self.alice, channel=self.channel, anonymous=thread_anonymous)
        ensure_alias_for_post(thread)
        replies = [
            make_reply(thread, self.alice, anonymous=True),
            make_reply(thread, self.alice, anonymous=False),
            make_reply(thread, self.bob, anonymous=True),
            make_reply(thread, self.bob, anonymous=False),
            make_reply(thread, self.carol, anonymous=False),
        ]
        for reply in replies:
            ensure_alias_for_post(reply)
        return thread, replies

    def test_anonymous_thread_and_replies(self):
        thread, replies = self.build(thread_anonymous=True)
        t, a1, a2, b1, b2, c = resolve_identities(thread, [thread, *replies])
        self.assertTrue(t.is_anonymous)
        self.assertRegex(t.display_name, r"^CSS-\d{5}$")
        self.assertTrue(t.show_author_badge)  # anonymous thread keeps Author badge
        self.assertEqual(a1.display_name, t.display_name)  # same alias, same thread
        self.assertTrue(a1.show_author_badge)
        self.assertEqual(a2.display_name, "Alice Starter")
        self.assertFalse(a2.show_author_badge)  # anonymous thread, named reply -> suppress
        self.assertRegex(b1.display_name, r"^CSS-\d{5}$")
        self.assertNotEqual(b1.display_name, t.display_name)
        self.assertEqual(b2.display_name, "Bob Replier")
        self.assertEqual(c.display_name, "Carol Other")
        for identity in (b1, b2, c):
            self.assertFalse(identity.show_author_badge)

    def test_named_thread(self):
        thread, replies = self.build(thread_anonymous=False)
        t, a1, a2, *_ = resolve_identities(thread, [thread, *replies])
        self.assertEqual(t.display_name, "Alice Starter")
        self.assertTrue(t.show_author_badge)
        self.assertTrue(a1.is_anonymous)
        self.assertFalse(a1.show_author_badge)  # named thread, anonymous reply -> suppress
        self.assertTrue(a2.show_author_badge)   # named thread, named reply -> badge

    def test_two_queries_regardless_of_post_count(self):
        thread, replies = self.build(thread_anonymous=True)
        with self.assertNumQueries(2):
            resolve_identities(thread, [thread, *replies])

    def test_anonymous_post_without_alias_never_shows_the_real_name(self):
        thread = make_thread(self.alice, anonymous=True)  # no alias created
        with self.assertLogs("apps.discussions.anonymity.service", "ERROR"):
            (identity,) = resolve_identities(thread, [thread])
        self.assertEqual(identity.display_name, "Anonymous")

    def test_flag_in_database_alone_decides_display(self):
        thread, replies = self.build(thread_anonymous=False)
        reply = replies[3]  # Bob, named
        Reply.objects.filter(pk=reply.pk).update(is_anonymous=True)
        ensure_alias_for_post(Reply.objects.get(pk=reply.pk))
        reply.refresh_from_db()
        identities = resolve_identities(thread, [thread, reply])
        self.assertRegex(identities[1].display_name, r"^CSS-\d{5}$")

    def test_reply_from_another_thread_is_rejected(self):
        thread, _ = self.build(thread_anonymous=False)
        other = make_thread(self.alice, channel=thread.channel)
        stray = make_reply(other, self.bob)
        with self.assertRaises(ValueError):
            resolve_identities(thread, [thread, stray])

    def test_named_thread_named_reply_badge(self):
        thread = make_thread(self.alice, channel=self.channel, anonymous=False)
        ensure_alias_for_post(thread)
        reply = make_reply(thread, self.alice, anonymous=False)
        ensure_alias_for_post(reply)
        t, r = resolve_identities(thread, [thread, reply])
        self.assertTrue(t.show_author_badge)
        self.assertTrue(r.show_author_badge)

    def test_anonymous_thread_anonymous_reply_badge(self):
        thread = make_thread(self.alice, channel=self.channel, anonymous=True)
        ensure_alias_for_post(thread)
        reply = make_reply(thread, self.alice, anonymous=True)
        ensure_alias_for_post(reply)
        t, r = resolve_identities(thread, [thread, reply])
        self.assertTrue(t.show_author_badge)
        self.assertTrue(r.show_author_badge)
        self.assertEqual(r.display_name, t.display_name)  # same alias as thread

    def test_named_thread_anonymous_reply_no_badge(self):
        thread = make_thread(self.alice, channel=self.channel, anonymous=False)
        ensure_alias_for_post(thread)
        reply = make_reply(thread, self.alice, anonymous=True)
        ensure_alias_for_post(reply)
        t, r = resolve_identities(thread, [thread, reply])
        self.assertTrue(t.show_author_badge)
        self.assertFalse(r.show_author_badge)

    def test_anonymous_thread_named_reply_no_badge(self):
        thread = make_thread(self.alice, channel=self.channel, anonymous=True)
        ensure_alias_for_post(thread)
        reply = make_reply(thread, self.alice, anonymous=False)
        ensure_alias_for_post(reply)
        t, r = resolve_identities(thread, [thread, reply])
        self.assertTrue(t.show_author_badge)
        self.assertFalse(r.show_author_badge)

    def test_other_users_replies_never_badged(self):
        thread = make_thread(self.alice, channel=self.channel, anonymous=False)
        ensure_alias_for_post(thread)
        reply = make_reply(thread, self.bob, anonymous=False)
        ensure_alias_for_post(reply)
        t, r = resolve_identities(thread, [thread, reply])
        self.assertTrue(t.show_author_badge)
        self.assertFalse(r.show_author_badge)

        thread2 = make_thread(self.alice, channel=self.channel, anonymous=True)
        ensure_alias_for_post(thread2)
        reply2 = make_reply(thread2, self.bob, anonymous=True)
        ensure_alias_for_post(reply2)
        t2, r2 = resolve_identities(thread2, [thread2, reply2])
        self.assertTrue(t2.show_author_badge)
        self.assertFalse(r2.show_author_badge)


@override_settings(ROOT_URLCONF=__name__)
class RenderedLeakageTests(TestCase):
    def setUp(self):
        self.starter = make_user(48271, "Zed Quillfeather", "zed.quillfeather@example.edu")
        self.replier = make_user(53917, "Mina Harrowgate", "mina.harrowgate@example.edu")
        self.viewer = make_user(61003, "Viewer Person", "viewer.person@example.edu")
        self.channel = make_channel(members=[self.starter, self.replier, self.viewer])
        self.thread = make_thread(self.starter, channel=self.channel, anonymous=True)
        ensure_alias_for_post(self.thread)
        for author in (self.starter, self.replier):
            reply = make_reply(self.thread, author, anonymous=True)
            ensure_alias_for_post(reply)
        self.client.force_login(self.viewer)

    def test_html_exposes_no_identity_of_anonymous_authors(self):
        response = self.client.get(f"/t/{self.thread.pk}/")
        self.assertEqual(response.status_code, 200)
        for user in (self.starter, self.replier):
            assert_no_identity_leak(self, response, user)
        self.assertContains(response, "author-badge", count=2)  # thread + starter reply

    def test_json_exposes_no_identity_and_only_three_keys(self):
        response = self.client.get(f"/t/{self.thread.pk}/json/")
        for user in (self.starter, self.replier):
            assert_no_identity_leak(self, response, user)
        for item in response.json()["identities"]:
            self.assertEqual(
                set(item), {"display_name", "is_anonymous", "show_author_badge"}
            )

    def test_labels_are_stable_across_separate_requests(self):
        first = self.client.get(f"/t/{self.thread.pk}/").content
        second = self.client.get(f"/t/{self.thread.pk}/").content
        self.assertEqual(first, second)
        self.assertEqual(ThreadAlias.objects.filter(thread=self.thread).count(), 2)

    def test_the_authors_own_view_is_also_pseudonymous(self):
        self.client.force_login(self.starter)
        response = self.client.get(f"/t/{self.thread.pk}/")
        assert_no_identity_leak(self, response, self.starter)

    def test_named_posts_show_the_real_name(self):
        named = make_thread(self.starter, channel=self.channel, anonymous=False)
        response = self.client.get(f"/t/{named.pk}/")
        self.assertContains(response, "Zed Quillfeather")

    def test_leak_helper_detects_leaks(self):
        with self.assertRaises(AssertionError):
            assert_no_identity_leak(self, "<p>Zed Quillfeather</p>", self.starter)
        with self.assertRaises(AssertionError):
            assert_no_identity_leak(self, '<a data-author="1">x</a>', self.starter)
        with self.assertRaises(AssertionError):
            assert_no_identity_leak(self, "<i>48271</i>", self.starter)


class AccountabilityRegressionTests(TestCase):
    def test_discussion_models_are_not_registered_in_django_admin(self):
        from apps.discussions.anonymity.models import ThreadAlias as Alias

        for model in (Thread, Reply, Alias):
            self.assertFalse(
                admin.site.is_registered(model),
                f"{model.__name__} must not be exposed in Django admin: "
                "it would bypass the logged authorship-view procedure.",
            )

    def test_users_with_posts_cannot_be_hard_deleted(self):
        from django.db.models import ProtectedError

        user = make_user(40001)
        make_thread(user, anonymous=True)
        with self.assertRaises(ProtectedError):
            user.delete()

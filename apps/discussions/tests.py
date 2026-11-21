from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.channels.models import Channel, ChannelType
from apps.discussions.models import Reply, Thread
from apps.servers.models import Server


User = get_user_model()


class DiscussionModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="student@example.com",
            password="TestPassword123!",
            full_name="Test Student",
        )
        self.server = Server.objects.create(
            name="Test Server",
            slug="test-server",
            created_by=self.user,
        )
        self.channel = Channel.objects.create(
            server=self.server,
            name="General",
            slug="general",
            channel_type=ChannelType.SUBJECT,
        )

    def test_thread_creation(self):
        thread = Thread.objects.create(
            channel=self.channel,
            author=self.user,
            title="Test question",
            body="This is a test question.",
        )

        self.assertEqual(thread.author, self.user)
        self.assertEqual(thread.channel, self.channel)
        self.assertFalse(thread.is_anonymous)
        self.assertFalse(thread.is_edited)

    def test_reply_creation(self):
        thread = Thread.objects.create(
            channel=self.channel,
            author=self.user,
            title="Test question",
            body="This is a test question.",
        )
        reply = Reply.objects.create(
            thread=thread,
            author=self.user,
            body="This is a test reply.",
        )

        self.assertEqual(reply.author, self.user)
        self.assertEqual(reply.thread, thread)
        self.assertFalse(reply.is_anonymous)
        self.assertFalse(reply.is_edited)

    def test_anonymous_thread_retains_true_author(self):
        thread = Thread.objects.create(
            channel=self.channel,
            author=self.user,
            title="Anonymous question",
            body="This is an anonymous question.",
            is_anonymous=True,
        )

        thread.refresh_from_db()
        self.assertTrue(thread.is_anonymous)
        self.assertEqual(thread.author, self.user)
        self.assertEqual(thread.author_id, self.user.pk)

    def test_anonymous_reply_retains_true_author(self):
        thread = Thread.objects.create(
            channel=self.channel,
            author=self.user,
            title="Test question",
            body="This is a test question.",
        )
        reply = Reply.objects.create(
            thread=thread,
            author=self.user,
            body="Anonymous reply.",
            is_anonymous=True,
        )

        reply.refresh_from_db()
        self.assertTrue(reply.is_anonymous)
        self.assertEqual(reply.author, self.user)
        self.assertEqual(reply.author_id, self.user.pk)

    def test_thread_protects_author_deletion(self):
        Thread.objects.create(
            channel=self.channel,
            author=self.user,
            title="Test question",
            body="This is a test question.",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.user.delete()
    def test_reply_protects_author_deletion(self):
        reply_author = User.objects.create_user(
            email="reply@example.com",
            password="TestPassword123!",
            full_name="Reply Author",
        )
        thread = Thread.objects.create(
            channel=self.channel,
            author=self.user,
            title="Test question",
            body="This is a test question.",
        )
        Reply.objects.create(
            thread=thread,
            author=reply_author,
            body="Test reply.",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                reply_author.delete()

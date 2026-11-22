from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.channels.models import Channel, ChannelType
from apps.discussions.models import Reply, Thread
from apps.servers.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    MembershipSubject,
    Server,
)


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
        self.membership = Membership.objects.create(
            user=self.user,
            server=self.server,
            role=MembershipRole.STUDENT,
            status=MembershipStatus.ACTIVE,
        )
        MembershipSubject.objects.create(
            membership=self.membership,
            subject_code="general",
        )
        self.channel = Channel.objects.create(
            server=self.server,
            name="General",
            slug="general",
            subject_code="general",
            channel_type=ChannelType.SUBJECT,
        )
        self.default_channel = Channel.objects.create(
            server=self.server,
            name="Announcements",
            slug="announcements",
            channel_type=ChannelType.ANNOUNCEMENTS,
        )

    def create_user(self, email):
        return User.objects.create_user(
            email=email,
            password="TestPassword123!",
            full_name=email,
        )

    def create_membership(self, user, status=MembershipStatus.ACTIVE):
        return Membership.objects.create(
            user=user,
            server=self.server,
            role=MembershipRole.STUDENT,
            status=status,
        )

    def test_thread_creation(self):
        thread = Thread.objects.create(
            channel=self.channel,
            author=self.user,
            title="Test question",
            body="This is a test question.",
        )

        thread.refresh_from_db()
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

        reply.refresh_from_db()
        self.assertEqual(reply.author, self.user)
        self.assertEqual(reply.thread, thread)
        self.assertFalse(reply.is_anonymous)
        self.assertFalse(reply.is_edited)

    def test_thread_creation_in_default_channel(self):
        thread = Thread.objects.create(
            channel=self.default_channel,
            author=self.user,
            title="Class announcement question",
            body="This is a test question.",
        )

        self.assertEqual(thread.channel, self.default_channel)

    def test_reply_creation_in_default_channel(self):
        thread = Thread.objects.create(
            channel=self.default_channel,
            author=self.user,
            title="Class announcement question",
            body="This is a test question.",
        )

        reply = Reply.objects.create(
            thread=thread,
            author=self.user,
            body="This is a test reply.",
        )

        self.assertEqual(reply.thread, thread)

    def test_nonmember_cannot_create_thread(self):
        author = self.create_user("nonmember-thread@example.com")

        with self.assertRaises(ValidationError):
            Thread.objects.create(
                channel=self.channel,
                author=author,
                title="Unauthorized question",
                body="This should not be saved.",
            )

        self.assertFalse(Thread.objects.filter(author=author).exists())

    def test_nonmember_cannot_create_reply(self):
        thread = Thread.objects.create(
            channel=self.channel,
            author=self.user,
            title="Test question",
            body="This is a test question.",
        )
        author = self.create_user("nonmember-reply@example.com")

        with self.assertRaises(ValidationError):
            Reply.objects.create(
                thread=thread,
                author=author,
                body="This should not be saved.",
            )

        self.assertFalse(Reply.objects.filter(author=author).exists())

    def test_inactive_member_cannot_create_thread_or_reply(self):
        author = self.create_user("inactive-member@example.com")
        membership = self.create_membership(author, MembershipStatus.LEFT)
        MembershipSubject.objects.create(
            membership=membership,
            subject_code=self.channel.slug,
        )
        thread = Thread.objects.create(
            channel=self.channel,
            author=self.user,
            title="Test question",
            body="This is a test question.",
        )

        with self.assertRaises(ValidationError):
            Thread.objects.create(
                channel=self.channel,
                author=author,
                title="Unauthorized question",
                body="This should not be saved.",
            )
        with self.assertRaises(ValidationError):
            Reply.objects.create(
                thread=thread,
                author=author,
                body="This should not be saved.",
            )

        self.assertFalse(Thread.objects.filter(author=author).exists())
        self.assertFalse(Reply.objects.filter(author=author).exists())

    def test_member_without_subject_access_cannot_create_thread_or_reply(self):
        author = self.create_user("unapproved-subject@example.com")
        self.create_membership(author)
        thread = Thread.objects.create(
            channel=self.channel,
            author=self.user,
            title="Test question",
            body="This is a test question.",
        )

        with self.assertRaises(ValidationError):
            Thread.objects.create(
                channel=self.channel,
                author=author,
                title="Unauthorized question",
                body="This should not be saved.",
            )
        with self.assertRaises(ValidationError):
            Reply.objects.create(
                thread=thread,
                author=author,
                body="This should not be saved.",
            )

        self.assertFalse(Thread.objects.filter(author=author).exists())
        self.assertFalse(Reply.objects.filter(author=author).exists())

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

    def test_anonymous_reply_string_hides_author(self):
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

        self.assertEqual(str(reply), f"Anonymous reply on {thread}")
        self.assertNotIn(str(self.user), str(reply))

    def test_named_reply_string_includes_author(self):
        thread = Thread.objects.create(
            channel=self.channel,
            author=self.user,
            title="Test question",
            body="This is a test question.",
        )
        reply = Reply.objects.create(
            thread=thread,
            author=self.user,
            body="Named reply.",
        )

        self.assertEqual(str(reply), f"Reply by {self.user} on {thread}")

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
        reply_author = self.create_user("reply@example.com")
        reply_membership = self.create_membership(reply_author)
        MembershipSubject.objects.create(
            membership=reply_membership,
            subject_code=self.channel.slug,
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
class ThreadCreationViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="posting-student@example.com",
            password="TestPassword123!",
            full_name="Posting Student",
        )
        self.user.is_email_verified = True
        self.user.save(update_fields=["is_email_verified"])

        self.server = Server.objects.create(
            name="Posting Test Server",
            slug="posting-test-server",
            created_by=self.user,
        )

        self.membership = Membership.objects.create(
            user=self.user,
            server=self.server,
            role=MembershipRole.STUDENT,
            status=MembershipStatus.ACTIVE,
        )

        MembershipSubject.objects.create(
            membership=self.membership,
            subject_code="general",
        )

        self.channel = Channel.objects.create(
            server=self.server,
            name="General",
            slug="general",
            subject_code="general",
            channel_type=ChannelType.SUBJECT,
        )

        self.client.force_login(self.user)

        self.create_url = reverse(
            "channels:create_thread",
            args=[self.server.pk, self.channel.pk],
        )
        self.subject_url = reverse(
            "channels:subject",
            args=[self.server.pk, self.channel.pk],
        )

    def test_authorized_member_can_open_thread_form(self):
        response = self.client.get(self.create_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create a New Thread")

    def test_authorized_member_can_publish_thread(self):
        response = self.client.post(
            self.create_url,
            {
                "title": "How do we prepare for the exam?",
                "body": "I would like to discuss the review topics.",
            },
        )

        self.assertRedirects(response, self.subject_url)
        self.assertTrue(
            Thread.objects.filter(
                channel=self.channel,
                author=self.user,
                title="How do we prepare for the exam?",
            ).exists()
        )

    def test_empty_title_is_rejected(self):
        response = self.client.post(
            self.create_url,
            {
                "title": "   ",
                "body": "This is a valid question body.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please enter a question title.")
        self.assertEqual(Thread.objects.count(), 0)

    def test_title_over_255_characters_is_rejected(self):
        response = self.client.post(
            self.create_url,
            {
                "title": "T" * 256,
                "body": "This is a valid question body.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The title cannot exceed 255 characters.")
        self.assertEqual(Thread.objects.count(), 0)

    def test_body_over_10000_characters_is_rejected(self):
        response = self.client.post(
            self.create_url,
            {
                "title": "Valid question",
                "body": "B" * 10001,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "The question details cannot exceed 10,000 characters.",
        )
        self.assertEqual(Thread.objects.count(), 0)

    def test_posted_script_is_escaped_in_thread_feed(self):
        script_text = "<script>alert(1)</script>"

        self.client.post(
            self.create_url,
            {
                "title": "Security test",
                "body": script_text,
            },
        )

        response = self.client.get(self.subject_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "&lt;script&gt;alert(1)&lt;/script&gt;",
        )
        self.assertNotContains(response, script_text)

    def test_unauthorized_user_cannot_open_thread_form(self):
        outsider = User.objects.create_user(
            email="outsider@example.com",
            password="TestPassword123!",
            full_name="Outsider",
        )
        outsider.is_email_verified = True
        outsider.save(update_fields=["is_email_verified"])
        self.client.force_login(outsider)

        response = self.client.get(self.create_url)

        self.assertEqual(response.status_code, 404)

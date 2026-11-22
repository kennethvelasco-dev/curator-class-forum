
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.channels.models import Channel, ChannelType
from apps.discussions.models import Reply, Thread
from apps.servers.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Server,
)


User = get_user_model()


class SubjectChannelViewTests(TestCase):
    def setUp(self):
        self.officer = User.objects.create_user(
            email="officer@example.com",
            password="StrongPass123",
            full_name="Test Officer",
            is_email_verified=True,
        )
        self.student = User.objects.create_user(
            email="student@example.com",
            password="StrongPass123",
            full_name="Test Student",
            is_email_verified=True,
        )
        self.president = User.objects.create_user(
            email="president@example.com",
            password="StrongPass123",
            full_name="Test President",
            is_email_verified=True,
        )

        self.server = Server.objects.create(
            name="Class A",
            slug="class-a",
        )

        self.officer_membership = Membership.objects.create(
            user=self.officer,
            server=self.server,
            role=MembershipRole.OFFICER,
            status=MembershipStatus.ACTIVE,
        )
        Membership.objects.create(
            user=self.student,
            server=self.server,
            role=MembershipRole.STUDENT,
            status=MembershipStatus.ACTIVE,
        )
        Membership.objects.create(
            user=self.president,
            server=self.server,
            role=MembershipRole.PRESIDENT,
            status=MembershipStatus.ACTIVE,
        )

        self.channel = Channel.objects.create(
            server=self.server,
            name="Computer Science",
            slug="CS101",
            subject_code="CS101",
            channel_type=ChannelType.SUBJECT,
            professor_name="Professor Test",
            professor_email="professor@example.com",
            office_hours="Monday, 1 PM - 3 PM",
        )

    def create_thread(self, title, *, is_anonymous=False):
        return Thread.objects.create(
            channel=self.channel,
            author=self.officer,
            title=title,
            body=f"Body for {title}.",
            is_anonymous=is_anonymous,
        )

    def test_officer_can_create_subject_channel(self):
        self.client.force_login(self.officer)

        response = self.client.post(
            reverse(
                "channels:create_subject",
                args=[self.server.pk],
            ),
            {
                "subject_code": "MATH201",
                "name": "Mathematics",
                "professor_name": "Professor Math",
                "professor_email": "math@example.com",
                "office_hours": "Tuesday, 1 PM - 3 PM",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Channel.objects.filter(
                server=self.server,
                slug="MATH201",
                channel_type=ChannelType.SUBJECT,
            ).exists()
        )

    def test_officer_can_create_channel_with_long_normalized_subject_code(self):
        self.client.force_login(self.officer)

        response = self.client.post(
            reverse(
                "channels:create_subject",
                args=[self.server.pk],
            ),
            {
                "subject_code": " " * 65 + "MATH201",
                "name": "Mathematics",
                "professor_name": "Professor Math",
                "professor_email": "math@example.com",
                "office_hours": "Tuesday, 1 PM - 3 PM",
            },
        )

        self.assertEqual(response.status_code, 302)
        channel = Channel.objects.get(
            server=self.server,
            slug="MATH201",
            channel_type=ChannelType.SUBJECT,
        )
        self.assertEqual(channel.slug, "MATH201")

    def test_student_cannot_create_subject_channel(self):
        self.client.force_login(self.student)

        response = self.client.post(
            reverse(
                "channels:create_subject",
                args=[self.server.pk],
            ),
            {
                "subject_code": "MATH201",
                "name": "Mathematics",
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            Channel.objects.filter(slug="MATH201").exists()
        )

    def test_demoted_officer_cannot_create_subject_channel(self):
        self.client.force_login(self.officer)

        def revoke_officer_after_initial_check(user, server):
            self.officer_membership.role = MembershipRole.STUDENT
            self.officer_membership.save(update_fields=["role"])
            return True

        with patch(
            "apps.channels.views.can_view_server_member_list",
            side_effect=revoke_officer_after_initial_check,
        ):
            response = self.client.post(
                reverse(
                    "channels:create_subject",
                    args=[self.server.pk],
                ),
                {
                    "subject_code": "MATH201",
                    "name": "Mathematics",
                    "professor_name": "",
                    "professor_email": "",
                    "office_hours": "",
                },
            )

        self.assertEqual(response.status_code, 404)
        self.officer_membership.refresh_from_db()
        self.assertEqual(self.officer_membership.role, MembershipRole.STUDENT)
        self.assertFalse(
            Channel.objects.filter(
                server=self.server,
                slug="MATH201",
                channel_type=ChannelType.SUBJECT,
            ).exists()
        )

    def test_duplicate_subject_code_is_rejected(self):
        self.client.force_login(self.officer)

        response = self.client.post(
            reverse(
                "channels:create_subject",
                args=[self.server.pk],
            ),
            {
                "subject_code": "CS101",
                "name": "Duplicate Computer Science",
                "professor_name": "",
                "professor_email": "",
                "office_hours": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].has_error("subject_code"))
        self.assertEqual(
            Channel.objects.filter(
                server=self.server,
                slug="CS101",
            ).count(),
            1,
        )

    def test_officer_can_edit_subject_channel(self):
        self.client.force_login(self.officer)

        edit_url = reverse(
            "channels:edit_subject",
            args=[self.server.pk, self.channel.pk],
        )
        detail_response = self.client.get(
            reverse(
                "channels:subject",
                args=[self.server.pk, self.channel.pk],
            )
        )
        self.assertEqual(detail_response.status_code, 200)

        response = self.client.post(
            edit_url,
            {
                "edit_version": self.channel.edit_version,
                "name": "Updated Computer Science",
                "professor_name": "New Professor",
                "professor_email": "newprofessor@example.com",
                "office_hours": "Wednesday, 2 PM - 4 PM",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.redirect_chain[-1][0],
            reverse(
                "channels:edit_subject",
                args=[self.server.pk, self.channel.pk],
            ),
        )
        self.assertContains(response, 'value="Updated Computer Science"')

        self.channel.refresh_from_db()
        self.assertEqual(
            self.channel.name,
            "Updated Computer Science",
        )
        self.assertEqual(
            self.channel.professor_name,
            "New Professor",
        )
        self.assertEqual(self.channel.edit_version, 2)

    def test_edit_form_contains_current_edit_version(self):
        self.client.force_login(self.officer)

        response = self.client.get(
            reverse(
                "channels:edit_subject",
                args=[self.server.pk, self.channel.pk],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'name="edit_version" value="{self.channel.edit_version}"',
        )

    def test_stale_edit_is_rejected_without_overwriting_newer_values(self):
        self.client.force_login(self.officer)

        edit_url = reverse(
            "channels:edit_subject",
            args=[self.server.pk, self.channel.pk],
        )
        first_form = self.client.get(edit_url)
        second_form = self.client.get(edit_url)
        original_version = self.channel.edit_version

        self.assertContains(
            first_form,
            f'name="edit_version" value="{original_version}"',
        )
        self.assertContains(
            second_form,
            f'name="edit_version" value="{original_version}"',
        )

        first_response = self.client.post(
            edit_url,
            {
                "edit_version": original_version,
                "name": "First Update",
                "professor_name": "First Professor",
                "professor_email": "first@example.com",
                "office_hours": "Tuesday, 10 AM - 12 PM",
            },
        )
        self.assertEqual(first_response.status_code, 302)

        stale_response = self.client.post(
            edit_url,
            {
                "edit_version": original_version,
                "name": "Stale Update",
                "professor_name": "Stale Professor",
                "professor_email": "stale@example.com",
                "office_hours": "Friday, 2 PM - 4 PM",
            },
        )

        self.assertEqual(stale_response.status_code, 200)
        self.assertContains(
            stale_response,
            "Another officer has updated this channel. Reload this page "
            "before saving your changes.",
        )
        self.channel.refresh_from_db()
        self.assertEqual(self.channel.name, "First Update")
        self.assertEqual(self.channel.professor_name, "First Professor")
        self.assertEqual(self.channel.professor_email, "first@example.com")
        self.assertEqual(
            self.channel.office_hours,
            "Tuesday, 10 AM - 12 PM",
        )
        self.assertEqual(self.channel.edit_version, original_version + 1)

    def test_demoted_officer_cannot_edit_subject_channel(self):
        self.client.force_login(self.officer)

        def revoke_officer_after_initial_check(user, server):
            self.officer_membership.role = MembershipRole.STUDENT
            self.officer_membership.save(update_fields=["role"])
            return True

        with patch(
            "apps.channels.views.can_view_server_member_list",
            side_effect=revoke_officer_after_initial_check,
        ):
            response = self.client.post(
                reverse(
                    "channels:edit_subject",
                    args=[self.server.pk, self.channel.pk],
                ),
                {
                    "edit_version": self.channel.edit_version,
                    "name": "Unauthorized Update",
                    "professor_name": "Unauthorized Professor",
                    "professor_email": "unauthorized@example.com",
                    "office_hours": "Friday, 1 PM - 3 PM",
                },
            )

        self.assertEqual(response.status_code, 404)
        self.officer_membership.refresh_from_db()
        self.assertEqual(self.officer_membership.role, MembershipRole.STUDENT)
        self.channel.refresh_from_db()
        self.assertEqual(self.channel.name, "Computer Science")
        self.assertEqual(self.channel.professor_name, "Professor Test")
        self.assertEqual(
            self.channel.professor_email,
            "professor@example.com",
        )
        self.assertEqual(
            self.channel.office_hours,
            "Monday, 1 PM - 3 PM",
        )

    def test_president_can_edit_subject_channel_without_subject_access(self):
        self.client.force_login(self.president)

        response = self.client.post(
            reverse(
                "channels:edit_subject",
                args=[self.server.pk, self.channel.pk],
            ),
            {
                "edit_version": self.channel.edit_version,
                "name": "President Updated Computer Science",
                "professor_name": "President's Professor",
                "professor_email": "president.professor@example.com",
                "office_hours": "Thursday, 2 PM - 4 PM",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.redirect_chain[-1][0],
            reverse(
                "channels:edit_subject",
                args=[self.server.pk, self.channel.pk],
            ),
        )
        self.assertContains(response, 'value="President Updated Computer Science"')

        self.channel.refresh_from_db()
        self.assertEqual(self.channel.name, "President Updated Computer Science")

    def test_student_cannot_edit_subject_channel(self):
        self.client.force_login(self.student)

        response = self.client.post(
            reverse(
                "channels:edit_subject",
                args=[self.server.pk, self.channel.pk],
            ),
            {
                "name": "Unauthorized Update",
                "professor_name": "",
                "professor_email": "",
                "office_hours": "",
            },
        )

        self.assertEqual(response.status_code, 404)

        self.channel.refresh_from_db()
        self.assertEqual(self.channel.name, "Computer Science")

    def test_student_without_approved_subject_cannot_access_subject_channel(self):
        self.client.force_login(self.student)

        response = self.client.get(
            reverse(
                "channels:subject",
                args=[self.server.pk, self.channel.pk],
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_feed_shows_thread_metadata_and_creation_time_fallback(self):
        self.client.force_login(self.officer)
        thread = self.create_thread("No replies yet")

        response = self.client.get(
            reverse(
                "channels:subject",
                args=[self.server.pk, self.channel.pk],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No replies yet")
        self.assertContains(response, self.officer.full_name)
        self.assertContains(response, "0 replies")
        feed_thread = response.context["threads"][0]
        self.assertEqual(feed_thread.reply_count, 0)
        self.assertEqual(feed_thread.last_activity, thread.created_at)

    def test_latest_reply_moves_parent_thread_ahead_of_newer_thread(self):
        self.client.force_login(self.officer)
        now = timezone.now()
        older_thread = self.create_thread("Older, recently active")
        newer_thread = self.create_thread("Newer, inactive")
        Thread.objects.filter(pk=older_thread.pk).update(
            created_at=now - timedelta(hours=2)
        )
        Thread.objects.filter(pk=newer_thread.pk).update(
            created_at=now - timedelta(hours=1)
        )
        reply = Reply.objects.create(
            thread=older_thread,
            author=self.officer,
            body="A recent reply.",
        )
        Reply.objects.filter(pk=reply.pk).update(created_at=now)

        response = self.client.get(
            reverse(
                "channels:subject",
                args=[self.server.pk, self.channel.pk],
            )
        )

        threads = list(response.context["threads"])
        self.assertEqual(
            [thread.pk for thread in threads],
            [older_thread.pk, newer_thread.pk],
        )
        self.assertEqual(threads[0].last_activity, now)

    def test_equal_activity_uses_descending_primary_key_order(self):
        self.client.force_login(self.officer)
        first = self.create_thread("First thread")
        second = self.create_thread("Second thread")
        same_time = timezone.now() - timedelta(hours=1)
        Thread.objects.filter(pk__in=[first.pk, second.pk]).update(
            created_at=same_time
        )

        response = self.client.get(
            reverse(
                "channels:subject",
                args=[self.server.pk, self.channel.pk],
            )
        )

        self.assertEqual(
            [thread.pk for thread in response.context["threads"]],
            [second.pk, first.pk],
        )

    def test_feed_counts_multiple_replies_and_displays_reply_authors(self):
        self.client.force_login(self.officer)
        thread = self.create_thread("Thread with replies")
        first_reply = Reply.objects.create(
            thread=thread,
            author=self.officer,
            body="Named response.",
        )
        anonymous_reply = Reply.objects.create(
            thread=thread,
            author=self.officer,
            body="Anonymous response.",
            is_anonymous=True,
        )

        response = self.client.get(
            reverse(
                "channels:subject",
                args=[self.server.pk, self.channel.pk],
            )
        )

        feed_thread = response.context["threads"][0]
        self.assertEqual(feed_thread.reply_count, 2)
        self.assertEqual(
            feed_thread.last_activity,
            max(first_reply.created_at, anonymous_reply.created_at),
        )
        self.assertContains(response, "2 replies")
        self.assertContains(response, "Named response.")
        self.assertContains(response, "Anonymous response.")
        self.assertContains(response, self.officer.full_name)
        self.assertContains(response, self.officer.anonymous_id)
        self.assertNotContains(response, '<details class="thread-replies" open')

    def test_anonymous_thread_and_reply_hide_real_identity(self):
        self.client.force_login(self.officer)
        thread = self.create_thread(
            "Anonymous discussion",
            is_anonymous=True,
        )
        Reply.objects.create(
            thread=thread,
            author=self.officer,
            body="Anonymous reply content.",
            is_anonymous=True,
        )

        response = self.client.get(
            reverse(
                "channels:subject",
                args=[self.server.pk, self.channel.pk],
            )
        )

        self.assertEqual(
            response.content.decode().count(self.officer.anonymous_id),
            2,
        )
        self.assertNotContains(response, self.officer.full_name)
        self.assertNotContains(response, self.officer.email)

    def test_nonmember_cannot_view_anonymous_identifier(self):
        thread = self.create_thread(
            "Private channel thread",
            is_anonymous=True,
        )
        outsider = User.objects.create_user(
            email="outsider@example.com",
            password="StrongPass123",
            full_name="Channel Outsider",
            is_email_verified=True,
        )
        self.client.force_login(outsider)

        response = self.client.get(
            reverse(
                "channels:subject",
                args=[self.server.pk, self.channel.pk],
            )
        )

        self.assertEqual(response.status_code, 404)
        self.assertNotIn(thread.author.anonymous_id, response.content.decode())

    def test_pagination_covers_first_next_and_invalid_pages(self):
        self.client.force_login(self.officer)
        empty_response = self.client.get(
            reverse(
                "channels:subject",
                args=[self.server.pk, self.channel.pk],
            )
        )
        self.assertNotContains(empty_response, 'class="pagination"')

        created_threads = [
            self.create_thread(f"Pagination thread {index}")
            for index in range(21)
        ]
        url = reverse(
            "channels:subject",
            args=[self.server.pk, self.channel.pk],
        )

        first_page = self.client.get(url)
        self.assertEqual(first_page.context["page_obj"].number, 1)
        self.assertEqual(len(first_page.context["threads"]), 20)
        self.assertContains(first_page, "Next")
        self.assertContains(first_page, "Page 1 of 2")
        self.assertContains(first_page, 'rel="next"')

        second_page = self.client.get(url, {"page": "2"})
        self.assertEqual(second_page.context["page_obj"].number, 2)
        self.assertEqual(len(second_page.context["threads"]), 1)
        self.assertContains(second_page, "Previous")
        self.assertContains(second_page, "Page 2 of 2")
        self.assertContains(second_page, 'rel="prev"')
        self.assertEqual(
            second_page.context["threads"][0].pk,
            created_threads[0].pk,
        )

        invalid_page = self.client.get(url, {"page": "not-a-number"})
        self.assertEqual(invalid_page.context["page_obj"].number, 1)
        out_of_range_page = self.client.get(url, {"page": "999"})
        self.assertEqual(out_of_range_page.context["page_obj"].number, 2)

    def test_feed_query_count_does_not_grow_per_thread_or_reply(self):
        self.client.force_login(self.officer)
        first_thread = self.create_thread("First query-count thread")
        Reply.objects.create(
            thread=first_thread,
            author=self.officer,
            body="First reply.",
        )
        url = reverse(
            "channels:subject",
            args=[self.server.pk, self.channel.pk],
        )

        with CaptureQueriesContext(connection) as one_thread_queries:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        for index in range(4):
            thread = self.create_thread(f"Additional thread {index}")
            Reply.objects.create(
                thread=thread,
                author=self.officer,
                body=f"Reply {index}.",
            )

        with CaptureQueriesContext(connection) as several_thread_queries:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            len(one_thread_queries),
            len(several_thread_queries),
        )

    def test_cannot_edit_subject_channel_from_another_server(self):
        other_server = Server.objects.create(
            name="Class B",
            slug="class-b",
        )
        other_channel = Channel.objects.create(
            server=other_server,
            name="Physics",
            slug="PHY101",
            subject_code="PHY101",
            channel_type=ChannelType.SUBJECT,
        )

        self.client.force_login(self.officer)

        response = self.client.post(
            reverse(
                "channels:edit_subject",
                args=[self.server.pk, other_channel.pk],
            ),
            {
                "name": "Unauthorized Physics Update",
                "professor_name": "",
                "professor_email": "",
                "office_hours": "",
            },
        )

        self.assertEqual(response.status_code, 404)

        other_channel.refresh_from_db()
        self.assertEqual(other_channel.name, "Physics")


from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.channels.models import Channel, ChannelType
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

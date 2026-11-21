
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

        self.server = Server.objects.create(
            name="Class A",
            slug="class-a",
        )

        Membership.objects.create(
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

        self.channel = Channel.objects.create(
            server=self.server,
            name="Computer Science",
            slug="CS101",
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
        self.assertEqual(
            Channel.objects.filter(
                server=self.server,
                slug="CS101",
            ).count(),
            1,
        )

    def test_officer_can_edit_subject_channel(self):
        self.client.force_login(self.officer)

        response = self.client.post(
            reverse(
                "channels:edit_subject",
                args=[self.server.pk, self.channel.pk],
            ),
            {
                "name": "Updated Computer Science",
                "professor_name": "New Professor",
                "professor_email": "newprofessor@example.com",
                "office_hours": "Wednesday, 2 PM - 4 PM",
            },
        )

        self.assertEqual(response.status_code, 302)

        self.channel.refresh_from_db()
        self.assertEqual(
            self.channel.name,
            "Updated Computer Science",
        )
        self.assertEqual(
            self.channel.professor_name,
            "New Professor",
        )

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

    def test_cannot_edit_subject_channel_from_another_server(self):
        other_server = Server.objects.create(
            name="Class B",
            slug="class-b",
        )
        other_channel = Channel.objects.create(
            server=other_server,
            name="Physics",
            slug="PHY101",
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

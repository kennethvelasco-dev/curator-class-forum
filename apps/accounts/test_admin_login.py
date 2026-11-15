from urllib.parse import urlsplit, parse_qs

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.servers.models import Membership, MembershipRole, MembershipStatus, Server


class AdminLoginTests(TestCase):
    def setUp(self):
        self.login_url = reverse("accounts:login")
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="Str0ngP@ssw0rd",
            full_name="Platform Admin",
            is_staff=True,
            is_email_verified=True,
        )
        self.student = User.objects.create_user(
            email="student@example.com",
            password="Str0ngP@ssw0rd",
            full_name="Test Student",
            is_staff=False,
            is_email_verified=True,
        )

    def test_admin_login_through_existing_login_page(self):
        response = self.client.post(
            self.login_url,
            {
                "username": "admin@example.com",
                "password": "Str0ngP@ssw0rd",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_admin_redirects_to_review_queue_without_next(self):
        response = self.client.post(
            self.login_url,
            {
                "username": "admin@example.com",
                "password": "Str0ngP@ssw0rd",
            },
        )
        self.assertRedirects(
            response,
            reverse("servers:admin_server_request_queue"),
        )

    def test_unsafe_next_cannot_redirect_externally(self):
        response = self.client.post(
            self.login_url,
            {
                "username": "admin@example.com",
                "password": "Str0ngP@ssw0rd",
                "next": "https://evil.example.com/",
            },
        )
        self.assertEqual(response.status_code, 302)
        redirect_url = response.url
        self.assertNotIn("evil.example.com", redirect_url)

    def test_valid_safe_next_behavior_preserved(self):
        response = self.client.post(
            self.login_url,
            {
                "username": "admin@example.com",
                "password": "Str0ngP@ssw0rd",
                "next": "/servers/request/",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/servers/request/", response.url)

    def test_student_login_behavior_unchanged(self):
        response = self.client.post(
            self.login_url,
            {
                "username": "student@example.com",
                "password": "Str0ngP@ssw0rd",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("accounts:dashboard"))

    def test_invalid_credentials_rejected(self):
        response = self.client.post(
            self.login_url,
            {
                "username": "admin@example.com",
                "password": "WrongPassword",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid email or password.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_admin_cannot_log_in(self):
        inactive_admin = User.objects.create_user(
            email="inactive-admin@example.com",
            password="Str0ngP@ssw0rd",
            full_name="Inactive Admin",
            is_staff=True,
            is_active=False,
            is_email_verified=True,
        )
        response = self.client.post(
            self.login_url,
            {
                "username": "inactive-admin@example.com",
                "password": "Str0ngP@ssw0rd",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid email or password.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_admin_access_does_not_require_membership(self):
        self.client.login(
            email="admin@example.com",
            password="Str0ngP@ssw0rd",
        )
        response = self.client.get(reverse("servers:admin_server_request_queue"))
        self.assertEqual(response.status_code, 200)

    def test_student_access_to_protected_admin_endpoint_returns_403(self):
        self.client.login(
            email="student@example.com",
            password="Str0ngP@ssw0rd",
        )
        response = self.client.get(reverse("servers:admin_server_request_queue"))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_access_redirects_to_curator_login(self):
        response = self.client.get(reverse("servers:admin_server_request_queue"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url.split("?")[0],
            self.login_url,
        )
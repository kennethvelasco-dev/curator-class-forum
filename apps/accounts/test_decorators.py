from types import SimpleNamespace
from urllib.parse import urlsplit, parse_qs

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.decorators import admin_required, is_platform_admin
from apps.accounts.models import User


@admin_required
def protected_admin_view(request):
    return HttpResponse("ok")


class IsPlatformAdminPolicyTests(TestCase):
    def test_active_staff_is_platform_admin(self):
        user = User.objects.create_user(
            email="admin@example.com",
            password="StrongPass8",
            full_name="Platform Admin",
            is_staff=True,
            is_email_verified=True,
        )
        self.assertTrue(is_platform_admin(user))

    def test_inactive_staff_is_not_platform_admin(self):
        user = User.objects.create_user(
            email="inactive@example.com",
            password="StrongPass8",
            full_name="Inactive Staff",
            is_staff=True,
            is_active=False,
            is_email_verified=True,
        )
        self.assertFalse(is_platform_admin(user))

    def test_non_staff_is_not_platform_admin(self):
        user = User.objects.create_user(
            email="student@example.com",
            password="StrongPass8",
            full_name="Student",
            is_staff=False,
            is_email_verified=True,
        )
        self.assertFalse(is_platform_admin(user))

    def test_anonymous_user_is_not_platform_admin(self):
        self.assertFalse(is_platform_admin(AnonymousUser()))


class AdminRequiredTests(SimpleTestCase):
    def setUp(self):
        self.request_factory = RequestFactory()

    def test_anonymous_user_is_redirected_to_curator_login(self):
        request = self.request_factory.get("/admin-only/")
        request.user = AnonymousUser()

        response = protected_admin_view(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url.split("?")[0],
            reverse("accounts:login"),
        )
        query = parse_qs(urlsplit(response.url).query)
        self.assertEqual(query.get("next"), ["/admin-only/"])

    def test_next_preserved_on_login_redirect(self):
        request = self.request_factory.get("/server-requests/")
        request.user = AnonymousUser()

        response = protected_admin_view(request)

        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlsplit(response.url).query)
        self.assertEqual(query.get("next"), ["/server-requests/"])

    def test_active_staff_user_is_allowed(self):
        request = self.request_factory.get("/admin-only/")
        request.user = SimpleNamespace(
            is_active=True,
            is_staff=True,
            is_authenticated=True,
        )

        response = protected_admin_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_inactive_staff_user_is_denied(self):
        request = self.request_factory.get("/admin-only/")
        request.user = SimpleNamespace(
            is_active=False,
            is_staff=True,
            is_authenticated=True,
        )

        with self.assertRaises(PermissionDenied):
            protected_admin_view(request)

    def test_active_non_staff_user_is_denied(self):
        request = self.request_factory.get("/admin-only/")
        request.user = SimpleNamespace(
            is_active=True,
            is_staff=False,
            is_authenticated=True,
        )

        with self.assertRaises(PermissionDenied):
            protected_admin_view(request)

    def test_active_superuser_is_allowed(self):
        request = self.request_factory.get("/admin-only/")
        request.user = SimpleNamespace(
            is_active=True,
            is_staff=True,
            is_superuser=True,
            is_authenticated=True,
        )

        response = protected_admin_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

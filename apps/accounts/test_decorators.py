from types import SimpleNamespace
from urllib.parse import urlsplit

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from apps.accounts.decorators import admin_required


@admin_required
def protected_admin_view(request):
    return HttpResponse("ok")


class AdminRequiredTests(SimpleTestCase):
    def setUp(self):
        self.request_factory = RequestFactory()

    def test_anonymous_user_is_redirected_to_admin_login(self):
        request = self.request_factory.get("/admin-only/")
        request.user = AnonymousUser()

        response = protected_admin_view(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url.split("?")[0],
            reverse("admin:login"),
        )

    def test_active_staff_user_is_allowed(self):
        request = self.request_factory.get("/admin-only/")
        request.user = SimpleNamespace(
            is_active=True,
            is_staff=True,
        )

        response = protected_admin_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_inactive_staff_user_is_denied(self):
        request = self.request_factory.get("/admin-only/")
        request.user = SimpleNamespace(
            is_active=False,
            is_staff=True,
        )

        response = protected_admin_view(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response.url).path, reverse("admin:login"))
        self.assertNotEqual(response.content, b"ok")

    def test_active_non_staff_user_is_denied(self):
        request = self.request_factory.get("/admin-only/")
        request.user = SimpleNamespace(
            is_active=True,
            is_staff=False,
        )

        response = protected_admin_view(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response.url).path, reverse("admin:login"))
        self.assertNotEqual(response.content, b"ok")

    def test_active_superuser_is_allowed(self):
        request = self.request_factory.get("/admin-only/")
        request.user = SimpleNamespace(
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )

        response = protected_admin_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

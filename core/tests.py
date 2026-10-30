from django.test import TestCase
from django.urls import get_resolver, reverse


class HomePageTests(TestCase):
    def test_home_page_loads(self):
        response = self.client.get(reverse("core:home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/home.html")
        self.assertTemplateUsed(response, "base.html")
        self.assertContains(response, "Good ideas grow")
        self.assertContains(response, "/static/css/site.css")

    def test_feature_app_url_namespaces_are_mounted(self):
        routes = {
            "accounts/": "accounts",
            "servers/": "servers",
            "channels/": "channels",
            "discussions/": "discussions",
            "announcements/": "announcements",
            "moderation/": "moderation",
        }
        mounted_routes = {
            (pattern.pattern._route, pattern.namespace)
            for pattern in get_resolver().url_patterns
        }

        for route in routes.items():
            with self.subTest(route=route):
                self.assertIn(route, mounted_routes)

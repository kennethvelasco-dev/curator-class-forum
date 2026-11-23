import re
from pathlib import Path

from django import forms
from django.template.loader import render_to_string
from django.test import SimpleTestCase

from apps.discussions.anonymity.forms import AnonymityFormMixin
from apps.discussions.anonymity.identity import PostIdentity

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "discussions"
JS_FILE = Path(__file__).resolve().parents[2] / "static" / "js" / "anonymity.js"


class SampleForm(AnonymityFormMixin, forms.Form):
    body = forms.CharField()


class IdentityPartialTests(SimpleTestCase):
    def render(self, **kwargs):
        return render_to_string(
            "discussions/_identity.html", {"identity": PostIdentity(**kwargs)}
        )

    def test_anonymous_label_and_badge(self):
        html = self.render(
            display_name="CSS-00042", is_anonymous=True, show_author_badge=True
        )
        self.assertIn("CSS-00042", html)
        self.assertIn("author-badge", html)
        self.assertIn("author-identity--anonymous", html)

    def test_no_badge_when_not_author(self):
        html = self.render(
            display_name="Ana", is_anonymous=False, show_author_badge=False
        )
        self.assertNotIn("author-badge", html)
        self.assertNotIn("author-identity--anonymous", html)

    def test_display_name_is_escaped(self):
        html = self.render(
            display_name="<script>x</script>", is_anonymous=False, show_author_badge=False
        )
        self.assertNotIn("<script>", html)

    def test_partial_has_no_attributes_beyond_class(self):
        html = self.render(
            display_name="CSS-00042", is_anonymous=True, show_author_badge=True
        )
        attrs = set(re.findall(r"\s([a-zA-Z_-]+)=", html))
        self.assertEqual(attrs, {"class"})


class NoticePartialTests(SimpleTestCase):
    def html(self):
        form = SampleForm()
        return render_to_string(
            "discussions/_anonymity_field.html", {"field": form["is_anonymous"]}
        )

    def test_checkbox_label_and_notice_present(self):
        html = self.html()
        self.assertIn('type="checkbox"', html)
        self.assertIn("Post Anonymously", html)
        self.assertIn("data-anonymity-notice", html)

    def test_notice_covers_fr_026_to_028_points(self):
        html = self.html()
        for phrase in ("President", "Admin", "reason", "audit log", "notified"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, html)

    def test_notice_is_visible_without_javascript(self):
        html = self.html()
        notice_tag = re.search(r"<div[^>]*data-anonymity-notice[^>]*>", html).group(0)
        self.assertNotIn("hidden", notice_tag)

    def test_checkbox_starts_unchecked(self):
        self.assertNotIn("checked", self.html())


class StaticLeakageTests(SimpleTestCase):
    FORBIDDEN = (
        r"\.author\b", r"author_id", r"\.email", r"\.pk\b", r"\.id\b",
        r"full_name", r"data-author", r"data-user", r"username", r"request\.user",
    )

    def test_discussion_partials_never_reference_user_data(self):
        for path in TEMPLATE_DIR.glob("_*.html"):
            text = re.sub(r"\{% comment %\}.*?\{% endcomment %\}", "", path.read_text(), flags=re.S)
            for pattern in self.FORBIDDEN:
                with self.subTest(file=path.name, pattern=pattern):
                    self.assertIsNone(re.search(pattern, text), path.name)

    def test_script_only_touches_anonymity_hooks(self):
        text = JS_FILE.read_text()
        self.assertIn("data-anonymity-toggle", text)
        for token in ("fetch(", "XMLHttpRequest", "localStorage", "email", "user"):
            self.assertNotIn(token, text)

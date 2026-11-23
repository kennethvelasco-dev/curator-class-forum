from django import forms
from django.test import SimpleTestCase

from apps.discussions.anonymity.forms import AnonymityFormMixin


class SamplePostForm(AnonymityFormMixin, forms.Form):
    body = forms.CharField()


class AnonymityFormTests(SimpleTestCase):
    def test_default_is_unchecked_and_labelled(self):
        form = SamplePostForm()
        self.assertFalse(form.fields["is_anonymous"].initial)
        self.assertEqual(form.fields["is_anonymous"].label, "Post Anonymously")
        self.assertFalse(form.fields["is_anonymous"].required)

    def test_missing_value_means_named(self):
        form = SamplePostForm({"body": "hi"})
        self.assertTrue(form.is_valid())
        self.assertFalse(form.is_anonymous_choice)

    def test_checked_means_anonymous(self):
        for raw in ("on", "true", "True", "1"):
            with self.subTest(raw=raw):
                form = SamplePostForm({"body": "hi", "is_anonymous": raw})
                self.assertTrue(form.is_valid())
                self.assertTrue(form.is_anonymous_choice)

    def test_false_strings_mean_named(self):
        for raw in ("false", "False", ""):
            with self.subTest(raw=raw):
                form = SamplePostForm({"body": "hi", "is_anonymous": raw})
                self.assertTrue(form.is_valid())
                self.assertFalse(form.is_anonymous_choice)

    def test_identity_fields_are_never_form_fields(self):
        form = SamplePostForm(
            {"body": "hi", "author": "9", "author_id": "9", "label": "CSS-00001",
             "alias": "CSS-00001", "is_anonymous": "on"}
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(set(form.cleaned_data), {"body", "is_anonymous"})
        self.assertEqual(set(form.fields), {"body", "is_anonymous"})

    def test_widget_marks_checkbox_for_the_notice_script(self):
        widget = SamplePostForm().fields["is_anonymous"].widget
        self.assertIn("data-anonymity-toggle", widget.attrs)

    def test_unrecognised_non_empty_values_fail_safe_to_anonymous(self):
        # Django's CheckboxInput only maps "", "false" and "False" to unchecked.
        # A crafted value such as "0" therefore counts as checked, which errs on
        # the side of hiding the author rather than exposing them.
        form = SamplePostForm({"body": "hi", "is_anonymous": "0"})
        self.assertTrue(form.is_valid())
        self.assertTrue(form.is_anonymous_choice)

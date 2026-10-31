from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.forms import CONSENT_NOTICE_VERSION, RegistrationForm
from apps.accounts.models import User


@override_settings(INSTITUTIONAL_EMAIL_DOMAIN="iskolarngbayan.pup.edu.ph")
class RegistrationFormTests(TestCase):
    def valid_data(self, **overrides):
        data = {
            "full_name": "Ada Lovelace",
            "email": "ada@iskolarngbayan.pup.edu.ph",
            "password1": "StrongPass8",
            "password2": "StrongPass8",
            "consent": "on",
        }
        data.update(overrides)
        return data

    def test_registration_creates_unverified_user_and_records_consent(self):
        form = RegistrationForm(self.valid_data())

        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()

        self.assertEqual(user.full_name, "Ada Lovelace")
        self.assertEqual(user.email, "ada@iskolarngbayan.pup.edu.ph")
        self.assertTrue(user.check_password("StrongPass8"))
        self.assertFalse(user.is_email_verified)
        self.assertTrue(user.consent_accepted)
        self.assertIsNotNone(user.consent_at)
        self.assertEqual(user.consent_version, CONSENT_NOTICE_VERSION)

    def test_registration_rejects_non_institutional_email(self):
        form = RegistrationForm(
            self.valid_data(email="ada@example.com"),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_registration_rejects_lookalike_email_domain(self):
        form = RegistrationForm(
            self.valid_data(email="ada@notiskolarngbayan.pup.edu.ph"),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_registration_rejects_duplicate_email_case_insensitively(self):
        User.objects.create_user(
            email="ada@iskolarngbayan.pup.edu.ph",
            password="StrongPass8",
            full_name="Existing User",
        )
        form = RegistrationForm(
            self.valid_data(email="ADA@ISKOLARNGBAYAN.PUP.EDU.PH"),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_registration_requires_consent(self):
        form = RegistrationForm(self.valid_data(consent=""))

        self.assertFalse(form.is_valid())
        self.assertIn("consent", form.errors)
        self.assertEqual(User.objects.count(), 0)

    def test_registration_requires_matching_passwords(self):
        form = RegistrationForm(
            self.valid_data(password2="DifferentPass8"),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)

    def test_registration_enforces_password_requirements(self):
        weak_passwords = (
            "shortA1",
            "lowercase8",
            "UPPERCASE8",
            "NoDigitsHere",
        )

        for password in weak_passwords:
            with self.subTest(password=password):
                form = RegistrationForm(
                    self.valid_data(password1=password, password2=password),
                )
                self.assertFalse(form.is_valid())
                self.assertIn("password1", form.errors)

    def test_registration_accepts_special_characters_in_password(self):
        password = "Strong!Pass8"
        form = RegistrationForm(
            self.valid_data(password1=password, password2=password),
        )

        self.assertTrue(form.is_valid(), form.errors)


@override_settings(INSTITUTIONAL_EMAIL_DOMAIN="iskolarngbayan.pup.edu.ph")
class RegistrationViewTests(TestCase):
    def test_registration_page_renders_privacy_notice_and_consent(self):
        response = self.client.get(reverse("accounts:register"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/register.html")
        self.assertContains(response, "Account Registration and Privacy Notice")
        self.assertContains(
            response,
            "I have read and understood the privacy notice. I consent to the "
            "processing of my personal information for account management, "
            "CoR enrollment verification, and the authorship-accountability "
            "procedures described above.",
        )
        self.assertContains(response, "At least 8 characters")
        self.assertContains(response, "At least one uppercase letter")
        self.assertContains(response, "At least one lowercase letter")
        self.assertContains(response, "At least one digit")
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_valid_registration_redirects_to_unverified_confirmation(self):
        response = self.client.post(
            reverse("accounts:register"),
            RegistrationFormTests().valid_data(),
        )

        self.assertRedirects(
            response,
            reverse("accounts:registration_complete"),
        )
        user = User.objects.get(email="ada@iskolarngbayan.pup.edu.ph")
        self.assertFalse(user.is_email_verified)

        response = self.client.get(reverse("accounts:registration_complete"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "you cannot sign in until verification")

    def test_invalid_registration_does_not_create_account(self):
        response = self.client.post(
            reverse("accounts:register"),
            RegistrationFormTests().valid_data(consent=""),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "consent", "This field is required.")
        self.assertEqual(User.objects.count(), 0)

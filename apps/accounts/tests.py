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
import hashlib
import re
from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.forms import CONSENT_NOTICE_VERSION, RegistrationForm
from apps.accounts.models import EmailVerificationToken, User


REGISTRATION_DOMAIN = "iskolarngbayan.pup.edu.ph"


def registration_data(**overrides):
    data = {
        "full_name": "Ada Lovelace",
        "email": f"ada@{REGISTRATION_DOMAIN}",
        "password1": "StrongPass8",
        "password2": "StrongPass8",
        "consent": "on",
    }
    data.update(overrides)
    return data


@override_settings(INSTITUTIONAL_EMAIL_DOMAIN=REGISTRATION_DOMAIN)
class RegistrationFormTests(TestCase):
    def valid_data(self, **overrides):
        return registration_data(**overrides)

    def test_registration_creates_unverified_user_and_records_consent(self):
        form = RegistrationForm(self.valid_data())

        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()

        self.assertEqual(user.full_name, "Ada Lovelace")
        self.assertEqual(user.email, f"ada@{REGISTRATION_DOMAIN}")
        self.assertTrue(user.check_password("StrongPass8"))
        self.assertFalse(user.is_email_verified)
        self.assertTrue(user.consent_accepted)
        self.assertIsNotNone(user.consent_at)
        self.assertEqual(user.consent_version, CONSENT_NOTICE_VERSION)

    def test_registration_rejects_non_institutional_email(self):
        form = RegistrationForm(self.valid_data(email="ada@example.com"))

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_registration_rejects_lookalike_email_domain(self):
        form = RegistrationForm(
            self.valid_data(email="ada@notiskolarngbayan.pup.edu.ph")
        )

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_registration_rejects_duplicate_email_case_insensitively(self):
        User.objects.create_user(
            email=f"ada@{REGISTRATION_DOMAIN}",
            password="StrongPass8",
            full_name="Existing User",
        )
        form = RegistrationForm(
            self.valid_data(email=f"ADA@{REGISTRATION_DOMAIN.upper()}")
        )

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_registration_requires_consent(self):
        form = RegistrationForm(self.valid_data(consent=""))

        self.assertFalse(form.is_valid())
        self.assertIn("consent", form.errors)
        self.assertEqual(User.objects.count(), 0)

    def test_registration_requires_matching_passwords(self):
        form = RegistrationForm(self.valid_data(password2="DifferentPass8"))

        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)

    def test_registration_enforces_password_requirements(self):
        for password in ("shortA1", "lowercase8", "UPPERCASE8", "NoDigitsHere"):
            with self.subTest(password=password):
                form = RegistrationForm(
                    self.valid_data(password1=password, password2=password)
                )
                self.assertFalse(form.is_valid())
                self.assertIn("password1", form.errors)

    def test_registration_accepts_special_characters_in_password(self):
        password = "Strong!Pass8"
        form = RegistrationForm(
            self.valid_data(password1=password, password2=password)
        )

        self.assertTrue(form.is_valid(), form.errors)


@override_settings(
    INSTITUTIONAL_EMAIL_DOMAIN=REGISTRATION_DOMAIN,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
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

    def test_valid_registration_sends_verification_message(self):
        response = self.client.post(
            reverse("accounts:register"),
            registration_data(),
        )

        self.assertRedirects(response, reverse("accounts:registration_complete"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Verify your Curator email address", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, [f"ada@{REGISTRATION_DOMAIN}"])
        self.assertIn("expires in 24 hours", mail.outbox[0].body)
        self.assertEqual(EmailVerificationToken.objects.count(), 1)

        user = User.objects.get(email=f"ada@{REGISTRATION_DOMAIN}")
        self.assertFalse(user.is_email_verified)
        stored_hash = EmailVerificationToken.objects.get().token_hash
        raw_token = re.search(r"/verify/\d+/([^/]+)/", mail.outbox[0].body).group(1)
        self.assertEqual(
            stored_hash,
            hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        )

    def test_invalid_registration_does_not_create_account(self):
        response = self.client.post(
            reverse("accounts:register"),
            registration_data(consent=""),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "consent",
            "This field is required.",
        )
        self.assertEqual(User.objects.count(), 0)


@override_settings(
    INSTITUTIONAL_EMAIL_DOMAIN=REGISTRATION_DOMAIN,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class EmailVerificationTests(TestCase):
    def create_verification(self):
        self.client.post(reverse("accounts:register"), registration_data())
        self.user = User.objects.get(email=f"ada@{REGISTRATION_DOMAIN}")
        link = re.search(r"https?://\S+", mail.outbox[0].body).group()
        path = re.search(r"https?://[^/]+(/.*)", link).group(1)
        return path

    def test_get_displays_confirmation_without_verifying(self):
        path = self.create_verification()

        response = self.client.get(path)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/verify_email.html")
        self.assertContains(response, "Confirm your email")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_email_verified)

    def test_post_confirms_email_and_token_cannot_be_reused(self):
        path = self.create_verification()

        response = self.client.post(path)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your email address is verified")
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_email_verified)
        verification = EmailVerificationToken.objects.get()
        self.assertIsNotNone(verification.used_at)

        response = self.client.post(path)
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_email_verified)

    def test_invalid_token_does_not_verify_account(self):
        path = self.create_verification()
        invalid_path = f"{path.rsplit('/', 2)[0]}/invalid-token/"

        response = self.client.post(invalid_path)

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_email_verified)

    def test_expired_token_does_not_verify_account(self):
        path = self.create_verification()
        EmailVerificationToken.objects.filter(user=self.user).update(
            created_at=timezone.now() - timedelta(hours=25)
        )

        response = self.client.post(path)

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_email_verified)

    def test_token_cannot_verify_a_different_account(self):
        path = self.create_verification()
        other_user = User.objects.create_user(
            email=f"other@{REGISTRATION_DOMAIN}",
            password="StrongPass8",
            full_name="Other Student",
        )
        token = path.split("/")[-2]
        wrong_user_path = reverse(
            "accounts:verify_email",
            args=[other_user.pk, token],
        )

        response = self.client.post(wrong_user_path)

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        other_user.refresh_from_db()
        self.assertFalse(self.user.is_email_verified)
        self.assertFalse(other_user.is_email_verified)

    def test_get_after_expiration_does_not_offer_confirmation(self):
        path = self.create_verification()
        EmailVerificationToken.objects.filter(user=self.user).update(
            created_at=timezone.now() - timedelta(hours=25)
        )

        response = self.client.get(path)

        self.assertEqual(response.status_code, 400)
        self.assertTemplateUsed(response, "accounts/verification_result.html")
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_email_verified)

import hashlib
import re
from datetime import timedelta

from django.conf import settings
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.forms import CONSENT_NOTICE_VERSION, RegistrationForm
from apps.accounts.models import EmailVerificationToken, User
from apps.accounts.tokens import (
    is_email_verification_token_valid,
    issue_email_verification_token,
)


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
    def test_registration_creates_unverified_user_and_records_consent(self):
        form = RegistrationForm(registration_data())

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
        form = RegistrationForm(registration_data(email="ada@example.com"))

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_registration_rejects_lookalike_email_domain(self):
        form = RegistrationForm(
            registration_data(email="ada@notiskolarngbayan.pup.edu.ph")
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
            registration_data(email=f"ADA@{REGISTRATION_DOMAIN.upper()}")
        )

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_registration_requires_consent(self):
        form = RegistrationForm(registration_data(consent=""))

        self.assertFalse(form.is_valid())
        self.assertIn("consent", form.errors)
        self.assertEqual(User.objects.count(), 0)

    def test_registration_requires_matching_passwords(self):
        form = RegistrationForm(
            registration_data(password2="DifferentPass8")
        )

        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)

    def test_registration_enforces_password_requirements(self):
        for password in ("shortA1", "lowercase8", "UPPERCASE8", "NoDigitsHere"):
            with self.subTest(password=password):
                form = RegistrationForm(
                    registration_data(password1=password, password2=password)
                )
                self.assertFalse(form.is_valid())
                self.assertIn("password1", form.errors)

    def test_registration_accepts_special_characters_in_password(self):
        password = "Strong!Pass8"
        form = RegistrationForm(
            registration_data(password1=password, password2=password)
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
        raw_token = re.search(
            r"/verify/\d+/([^/]+)/",
            mail.outbox[0].body,
        ).group(1)
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
        return re.search(r"https?://[^/]+(/.*)", link).group(1)

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
        self.assertTemplateUsed(
            response,
            "accounts/verification_result.html",
        )
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_email_verified)

    def test_issuing_a_new_token_invalidates_the_previous_token(self):
        self.create_verification()
        old_token = re.search(
            r"/verify/\d+/([^/]+)/",
            mail.outbox[0].body,
        ).group(1)

        new_token = issue_email_verification_token(self.user)

        self.assertFalse(
            is_email_verification_token_valid(self.user.pk, old_token)
        )
        self.assertTrue(
            is_email_verification_token_valid(self.user.pk, new_token)
        )

    def test_csrf_protects_verification_post(self):
        path = self.create_verification()
        csrf_client = Client(enforce_csrf_checks=True)

        get_response = csrf_client.get(path)
        post_response = csrf_client.post(path)

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(post_response.status_code, 403)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_email_verified)


class EmailAuthenticationTests(TestCase):
    def create_user(self, email="student@example.com", verified=True):
        return User.objects.create_user(
            email=email,
            password="StrongPass8",
            full_name="Test Student",
            is_email_verified=verified,
        )

    def test_verified_user_can_sign_in_with_email(self):
        self.create_user()

        response = self.client.post(
            reverse("accounts:login"),
            {"username": "student@example.com", "password": "StrongPass8"},
        )

        self.assertRedirects(response, reverse("accounts:dashboard"))
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_email_login_is_case_insensitive(self):
        self.create_user(email="student@example.com")

        response = self.client.post(
            reverse("accounts:login"),
            {"username": "STUDENT@EXAMPLE.COM", "password": "StrongPass8"},
        )

        self.assertRedirects(response, reverse("accounts:dashboard"))
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_unverified_user_cannot_sign_in(self):
        self.create_user(verified=False)

        response = self.client.post(
            reverse("accounts:login"),
            {"username": "student@example.com", "password": "StrongPass8"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid email or password.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_invalid_password_is_rejected(self):
        self.create_user()

        response = self.client.post(
            reverse("accounts:login"),
            {"username": "student@example.com", "password": "WrongPass8"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid email or password.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_requires_post_and_clears_session(self):
        user = self.create_user()
        self.client.force_login(user)

        get_response = self.client.get(reverse("accounts:logout"))
        self.assertEqual(get_response.status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)

        post_response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(post_response, reverse("accounts:login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_csrf_protects_login_post(self):
        self.create_user()
        csrf_client = Client(enforce_csrf_checks=True)

        get_response = csrf_client.get(reverse("accounts:login"))
        post_response = csrf_client.post(
            reverse("accounts:login"),
            {"username": "student@example.com", "password": "StrongPass8"},
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(post_response.status_code, 403)
        self.assertNotIn("_auth_user_id", csrf_client.session)

    def test_session_and_secure_cookie_settings(self):
        self.assertEqual(settings.SESSION_COOKIE_AGE, 14 * 24 * 60 * 60)
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Lax")

    def test_login_page_has_csrf_token_and_email_label(self):
        response = self.client.get(reverse("accounts:login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Institutional email")
        self.assertContains(response, "csrfmiddlewaretoken")


class AccountAdminTests(TestCase):
    def test_user_admin_renders_custom_fields_and_add_form(self):
        admin_user = User.objects.create_superuser(
            email="admin@example.com",
            password="StrongPass8",
            full_name="Site Administrator",
        )
        self.client.force_login(admin_user)

        change_response = self.client.get(
            reverse("admin:accounts_user_changelist")
        )
        add_response = self.client.get(reverse("admin:accounts_user_add"))

        self.assertEqual(change_response.status_code, 200)
        self.assertEqual(add_response.status_code, 200)
        self.assertContains(add_response, 'name="email"')
        self.assertContains(add_response, 'name="full_name"')
        self.assertNotContains(add_response, 'name="username"')

    def test_admin_login_requires_verified_superuser(self):
        User.objects.create_superuser(
            email="admin@example.com",
            password="StrongPass8",
            full_name="Site Administrator",
        )
        response = self.client.post(
            reverse("admin:login"),
            {
                "username": "admin@example.com",
                "password": "StrongPass8",
                "next": "/admin/",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_admin_login_rejects_unverified_staff_user(self):
        User.objects.create_user(
            email="staff@example.com",
            password="StrongPass8",
            full_name="Unverified Staff",
            is_staff=True,
        )
        response = self.client.post(
            reverse("admin:login"),
            {
                "username": "staff@example.com",
                "password": "StrongPass8",
                "next": "/admin/",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid email or password.")
        self.assertNotIn("_auth_user_id", self.client.session)


class AccountDashboardTests(TestCase):
    def create_user(self, verified=True):
        return User.objects.create_user(
            email="student@example.com",
            password="StrongPass8",
            full_name="Test Student",
            is_email_verified=verified,
        )

    def test_anonymous_visitor_is_redirected_to_login(self):
        response = self.client.get(reverse("accounts:dashboard"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('accounts:dashboard')}",
        )

    def test_verified_user_can_view_dashboard(self):
        user = self.create_user()
        self.client.force_login(user)

        response = self.client.get(reverse("accounts:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/dashboard.html")
        self.assertContains(response, "Welcome, Test Student")
        self.assertContains(response, "student@example.com")
        self.assertContains(response, "Sign out")
        self.assertContains(response, 'action="/accounts/logout/"')
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_unverified_authenticated_user_is_denied_dashboard_access(self):
        user = self.create_user(verified=False)
        self.client.force_login(user)

        response = self.client.get(reverse("accounts:dashboard"))

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(
            response,
            "accounts/verification_required.html",
        )

    def test_dashboard_escapes_user_controlled_name(self):
        user = self.create_user()
        user.full_name = "<script>alert(1)</script>"
        user.save(update_fields=["full_name"])
        self.client.force_login(user)

        response = self.client.get(reverse("accounts:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;")

    def test_dashboard_logout_button_ends_authenticated_session(self):
        user = self.create_user()
        self.client.force_login(user)

        response = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(response, reverse("accounts:login"))
        self.assertNotIn("_auth_user_id", self.client.session)

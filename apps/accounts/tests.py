import hashlib
import io
import logging
import re
import smtplib
import socket
from datetime import timedelta
from importlib import import_module
from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import (
    Client,
    RequestFactory,
    TestCase,
    TransactionTestCase,
    override_settings,
)
from django.urls import reverse
from django.utils.log import AdminEmailHandler
from django.utils import timezone

from apps.accounts.forms import (
    CONSENT_NOTICE_VERSION,
    RegistrationEmailForm,
    RegistrationForm,
)
from apps.accounts.logging import RedactVerificationTokenFilter
from apps.accounts.models import EmailVerificationToken, PendingRegistration, User
from apps.accounts.tokens import issue_email_verification_token


REGISTRATION_DOMAIN = "iskolarngbayan.pup.edu.ph"


def registration_data(**overrides):
    data = {"email": f"ada@{REGISTRATION_DOMAIN}"}
    data.update(overrides)
    return data


def completion_data(**overrides):
    data = {
        "full_name": "Ada Lovelace",
        "password1": "StrongPass8",
        "password2": "StrongPass8",
        "consent": "on",
    }
    data.update(overrides)
    return data


def emailed_path(message):
    link = re.search(r"https?://\S+", message.body).group()
    return re.search(r"https?://[^/]+(/.*)", link).group(1)


@override_settings(INSTITUTIONAL_EMAIL_DOMAIN=REGISTRATION_DOMAIN)
class RegistrationFormTests(TestCase):
    def test_new_user_defaults_to_unverified(self):
        user = User.objects.create_user(
            email="new@example.com",
            password="StrongPass8",
            full_name="New User",
        )

        self.assertFalse(user.is_email_verified)

    def test_saving_user_normalizes_email(self):
        user = User.objects.create_user(
            email="  ADA@Example.COM ",
            password="StrongPass8",
            full_name="Ada Lovelace",
        )

        self.assertEqual(user.email, "ada@example.com")

    def test_database_enforces_case_insensitive_email_uniqueness(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.bulk_create(
                    [
                        User(email="ada@example.com", full_name="Ada"),
                        User(email="ADA@EXAMPLE.COM", full_name="Duplicate"),
                    ]
                )

    def test_registration_email_form_normalizes_and_validates_domain(self):
        form = RegistrationEmailForm(
            registration_data(email=f"ADA@{REGISTRATION_DOMAIN.upper()}")
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["email"], f"ada@{REGISTRATION_DOMAIN}")

    def test_registration_rejects_non_institutional_and_lookalike_domains(self):
        for email in (
            "ada@example.com",
            "ada@notiskolarngbayan.pup.edu.ph",
        ):
            with self.subTest(email=email):
                form = RegistrationEmailForm(registration_data(email=email))
                self.assertFalse(form.is_valid())
                self.assertIn("email", form.errors)

    def test_registration_completion_creates_verified_user_and_records_consent(self):
        email = f"ada@{REGISTRATION_DOMAIN}"
        form = RegistrationForm(completion_data(), email=email)

        self.assertTrue(form.is_valid(), form.errors)
        user = form.create_user(email)

        self.assertEqual(user.full_name, "Ada Lovelace")
        self.assertEqual(user.email, email)
        self.assertTrue(user.check_password("StrongPass8"))
        self.assertTrue(user.is_email_verified)
        self.assertTrue(user.consent_accepted)
        self.assertIsNotNone(user.consent_at)
        self.assertEqual(user.consent_version, CONSENT_NOTICE_VERSION)

    def test_registration_completion_requires_consent_and_matching_passwords(self):
        email = f"ada@{REGISTRATION_DOMAIN}"
        missing_consent = RegistrationForm(completion_data(consent=""), email=email)
        mismatch = RegistrationForm(
            completion_data(password2="DifferentPass8"),
            email=email,
        )

        self.assertFalse(missing_consent.is_valid())
        self.assertIn("consent", missing_consent.errors)
        self.assertFalse(mismatch.is_valid())
        self.assertIn("password2", mismatch.errors)
        self.assertEqual(User.objects.count(), 0)

    def test_registration_completion_enforces_password_requirements(self):
        for password in ("shortA1", "lowercase8", "UPPERCASE8", "NoDigitsHere"):
            with self.subTest(password=password):
                form = RegistrationForm(
                    completion_data(password1=password, password2=password),
                    email=f"ada@{REGISTRATION_DOMAIN}",
                )
                self.assertFalse(form.is_valid())
                self.assertIn("password1", form.errors)

    def test_registration_completion_accepts_special_characters(self):
        form = RegistrationForm(
            completion_data(
                password1="Strong!Pass8",
                password2="Strong!Pass8",
            ),
            email=f"ada@{REGISTRATION_DOMAIN}",
        )

        self.assertTrue(form.is_valid(), form.errors)


@override_settings(
    INSTITUTIONAL_EMAIL_DOMAIN=REGISTRATION_DOMAIN,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class RegistrationViewTests(TestCase):
    def test_registration_page_collects_only_institutional_email(self):
        response = self.client.get(reverse("accounts:register"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/register.html")
        self.assertContains(response, "institutional email")
        self.assertNotContains(response, 'name="password1"')
        self.assertNotContains(response, 'name="consent"')
        self.assertContains(response, 'href="/accounts/login/"')
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_initial_registration_creates_no_user_or_password(self):
        response = self.client.post(
            reverse("accounts:register"),
            registration_data(
                full_name="Attacker Supplied Name",
                password1="AttackerPass8",
                password2="AttackerPass8",
                consent="on",
            ),
        )

        self.assertRedirects(response, reverse("accounts:registration_complete"))
        self.assertEqual(User.objects.count(), 0)
        pending = PendingRegistration.objects.get()
        self.assertEqual(pending.email, f"ada@{REGISTRATION_DOMAIN}")
        self.assertEqual(len(mail.outbox), 1)
        raw_token = re.search(
            r"/verify-registration/\d+/([^/]+)/",
            mail.outbox[0].body,
        ).group(1)
        self.assertEqual(
            pending.token_hash,
            hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        )
        self.assertNotIn("AttackerPass8", mail.outbox[0].body)

    def test_invalid_registration_does_not_create_pending_registration(self):
        response = self.client.post(
            reverse("accounts:register"),
            registration_data(email="ada@example.com"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(PendingRegistration.objects.count(), 0)
        self.assertEqual(mail.outbox, [])

    def test_duplicate_registration_does_not_create_user_or_rotate_link(self):
        first_response = self.client.post(
            reverse("accounts:register"),
            registration_data(),
        )
        first_hash = PendingRegistration.objects.get().token_hash
        second_response = self.client.post(
            reverse("accounts:register"),
            registration_data(email=f"ADA@{REGISTRATION_DOMAIN.upper()}"),
        )

        self.assertRedirects(first_response, reverse("accounts:registration_complete"))
        self.assertRedirects(second_response, reverse("accounts:registration_complete"))
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(PendingRegistration.objects.count(), 1)
        self.assertEqual(PendingRegistration.objects.get().token_hash, first_hash)
        self.assertEqual(len(mail.outbox), 1)

    def test_verified_duplicate_does_not_disclose_account_existence(self):
        User.objects.create_user(
            email=f"ada@{REGISTRATION_DOMAIN}",
            password="StrongPass8",
            full_name="Existing User",
            is_email_verified=True,
        )

        response = self.client.post(
            reverse("accounts:register"),
            registration_data(),
        )

        self.assertRedirects(response, reverse("accounts:registration_complete"))
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(PendingRegistration.objects.count(), 0)
        self.assertEqual(mail.outbox, [])

    def test_expired_request_can_be_restarted(self):
        self.client.post(reverse("accounts:register"), registration_data())
        pending = PendingRegistration.objects.get()
        old_path = emailed_path(mail.outbox[0])
        PendingRegistration.objects.filter(pk=pending.pk).update(
            created_at=timezone.now() - timedelta(hours=25)
        )

        response = self.client.post(
            reverse("accounts:register"),
            registration_data(),
        )

        new_path = emailed_path(mail.outbox[1])
        self.assertRedirects(response, reverse("accounts:registration_complete"))
        self.assertEqual(self.client.get(old_path).status_code, 400)
        new_link_response = self.client.get(new_path)
        self.assertEqual(new_link_response.status_code, 302)
        self.assertEqual(self.client.get(new_link_response.url).status_code, 200)
        self.assertEqual(PendingRegistration.objects.count(), 1)
        self.assertEqual(User.objects.count(), 0)

    @patch("apps.accounts.views.send_mail", return_value=0)
    def test_failed_email_send_rolls_back_pending_registration(self, send):
        response = self.client.post(
            reverse("accounts:register"),
            registration_data(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "We could not send the verification email")
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(PendingRegistration.objects.count(), 0)
        send.assert_called_once()

    @patch(
        "apps.accounts.views.send_mail",
        side_effect=smtplib.SMTPException("SMTP unavailable"),
    )
    def test_smtp_exception_rolls_back_pending_registration(self, send):
        response = self.client.post(
            reverse("accounts:register"),
            registration_data(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "We could not send the verification email")
        self.assertEqual(PendingRegistration.objects.count(), 0)
        send.assert_called_once()

    @patch(
        "apps.accounts.views.send_mail",
        side_effect=OSError("Network unavailable"),
    )
    def test_os_error_rolls_back_pending_registration(self, send):
        response = self.client.post(
            reverse("accounts:register"),
            registration_data(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "We could not send the verification email")
        self.assertEqual(PendingRegistration.objects.count(), 0)
        send.assert_called_once()


@override_settings(
    INSTITUTIONAL_EMAIL_DOMAIN=REGISTRATION_DOMAIN,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class EmailVerificationTests(TestCase):
    def create_verification(self):
        self.client.post(reverse("accounts:register"), registration_data())
        self.verification_link = emailed_path(mail.outbox[0])
        response = self.client.get(self.verification_link)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertNotIn(self.verification_link, response.url)
        return response.url

    def test_get_displays_completion_form_without_creating_account(self):
        path = self.create_verification()

        response = self.client.get(path)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/complete_registration.html")
        self.assertEqual(
            response.context["verification_email"],
            f"ada@{REGISTRATION_DOMAIN}",
        )
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertContains(response, 'href="/accounts/login/"')
        self.assertContains(response, 'href="/accounts/register/"')
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(PendingRegistration.objects.count(), 1)
        self.assertNotContains(response, self.verification_link.rsplit("/", 2)[-2])

    def test_email_owner_sets_password_and_completes_registration(self):
        path = self.create_verification()

        response = self.client.post(path, completion_data())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your email is verified")
        user = User.objects.get(email=f"ada@{REGISTRATION_DOMAIN}")
        self.assertTrue(user.is_email_verified)
        self.assertTrue(user.check_password("StrongPass8"))
        self.assertTrue(user.consent_accepted)
        self.assertIsNotNone(user.consent_at)
        self.assertEqual(user.consent_version, CONSENT_NOTICE_VERSION)
        self.assertEqual(PendingRegistration.objects.count(), 0)

    def test_verification_link_cannot_be_reused(self):
        path = self.create_verification()
        first_response = self.client.post(path, completion_data())

        response = self.client.post(path, completion_data())

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 1)
        self.assertNotIn(
            "accounts.registration_verification",
            self.client.session,
        )

    def test_invalid_or_expired_link_cannot_establish_password(self):
        path = self.create_verification()
        invalid_path = f"{self.verification_link.rsplit('/', 2)[0]}/invalid-token/"

        invalid_response = self.client.get(invalid_path)
        PendingRegistration.objects.update(
            created_at=timezone.now() - timedelta(hours=25)
        )
        expired_response = self.client.post(path, completion_data())

        self.assertEqual(invalid_response.status_code, 400)
        self.assertEqual(expired_response.status_code, 400)
        self.assertEqual(User.objects.count(), 0)
        self.assertNotIn(
            str(PendingRegistration.objects.get().pk),
            self.client.session.get("accounts.registration_verification", {}),
        )

    def test_unverified_email_cannot_login_or_access_dashboard(self):
        path = self.create_verification()
        email = f"ada@{REGISTRATION_DOMAIN}"
        login_response = self.client.post(
            reverse("accounts:login"),
            {"username": email, "password": "StrongPass8"},
        )
        dashboard_response = self.client.get(reverse("accounts:dashboard"))

        self.assertEqual(login_response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertRedirects(
            dashboard_response,
            f"{reverse('accounts:login')}?next={reverse('accounts:dashboard')}",
        )
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(PendingRegistration.objects.count(), 1)
        self.assertNotEqual(path, "")

    def test_owner_can_replace_password_on_legacy_unverified_account(self):
        user = User.objects.create_user(
            email=f"ada@{REGISTRATION_DOMAIN}",
            password="AttackerPass8",
            full_name="Unverified Account",
            consent_accepted=True,
        )
        path = self.create_verification()

        response = self.client.post(
            path,
            completion_data(full_name="Legitimate Owner"),
        )

        user.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(user.full_name, "Legitimate Owner")
        self.assertTrue(user.check_password("StrongPass8"))
        self.assertFalse(user.check_password("AttackerPass8"))
        self.assertTrue(user.is_email_verified)

    def test_legacy_verification_template_uses_verification_email_context(self):
        user = User.objects.create_user(
            email=f"ada@{REGISTRATION_DOMAIN}",
            password="StrongPass8",
            full_name="Ada Lovelace",
        )
        token = issue_email_verification_token(user)
        path = reverse("accounts:verify_email", args=[user.pk, token])

        response = self.client.get(path)
        clean_path = reverse("accounts:verify_email_form", args=[user.pk])
        clean_response = self.client.get(response.url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, clean_path)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertEqual(clean_response.status_code, 200)
        self.assertEqual(clean_response["Referrer-Policy"], "same-origin")
        self.assertEqual(clean_response.context["verification_email"], user.email)
        self.assertContains(clean_response, user.email)
        self.assertContains(clean_response, 'href="/accounts/login/"')
        self.assertContains(clean_response, 'href="/accounts/register/"')

    def test_legacy_verification_requires_post_and_is_single_use(self):
        user = User.objects.create_user(
            email=f"ada@{REGISTRATION_DOMAIN}",
            password="StrongPass8",
            full_name="Ada Lovelace",
        )
        token = issue_email_verification_token(user)
        path = reverse("accounts:verify_email", args=[user.pk, token])

        get_response = self.client.get(path)
        user.refresh_from_db()
        self.assertEqual(get_response.status_code, 302)
        self.assertFalse(user.is_email_verified)

        post_response = self.client.post(get_response.url)
        user.refresh_from_db()
        self.assertEqual(post_response.status_code, 200)
        self.assertTrue(user.is_email_verified)
        self.assertEqual(self.client.post(get_response.url).status_code, 400)

    def test_legacy_invalid_and_expired_links_are_rejected(self):
        user = User.objects.create_user(
            email=f"ada@{REGISTRATION_DOMAIN}",
            password="StrongPass8",
            full_name="Ada Lovelace",
        )
        token = issue_email_verification_token(user)
        path = reverse("accounts:verify_email", args=[user.pk, token])
        invalid_path = reverse(
            "accounts:verify_email",
            args=[user.pk, "invalid-token"],
        )

        invalid_response = self.client.get(invalid_path)
        entry_response = self.client.get(path)
        EmailVerificationToken.objects.filter(user=user).update(
            created_at=timezone.now()
            - timedelta(seconds=settings.EMAIL_VERIFICATION_TOKEN_TTL + 1)
        )
        expired_response = self.client.get(entry_response.url)

        self.assertEqual(invalid_response.status_code, 400)
        self.assertEqual(entry_response.status_code, 302)
        self.assertEqual(expired_response.status_code, 400)
        user.refresh_from_db()
        self.assertFalse(user.is_email_verified)
        self.assertNotIn(
            str(user.pk),
            self.client.session.get("accounts.email_verification", {}),
        )

    def test_csrf_protects_completion_post(self):
        self.create_verification()
        csrf_client = Client(enforce_csrf_checks=True)

        get_response = csrf_client.get(self.verification_link, follow=True)
        post_response = csrf_client.post(
            get_response.request["PATH_INFO"],
            completion_data(),
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(post_response.status_code, 403)
        self.assertEqual(User.objects.count(), 0)


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

        change_response = self.client.get(reverse("admin:accounts_user_changelist"))
        add_response = self.client.get(reverse("admin:accounts_user_add"))

        self.assertEqual(change_response.status_code, 200)
        self.assertEqual(add_response.status_code, 200)
        self.assertContains(add_response, 'name="email"')
        self.assertContains(add_response, 'name="full_name"')
        self.assertNotContains(add_response, 'name="username"')

    def test_user_admin_can_create_account_without_username(self):
        admin_user = User.objects.create_superuser(
            email="admin@example.com",
            password="StrongPass8",
            full_name="Site Administrator",
        )
        self.client.force_login(admin_user)

        response = self.client.post(
            reverse("admin:accounts_user_add"),
            {
                "email": "new-user@example.com",
                "full_name": "New User",
                "password1": "StrongPass8",
                "password2": "StrongPass8",
                "_save": "Save",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email="new-user@example.com")
        self.assertEqual(user.full_name, "New User")
        self.assertTrue(user.check_password("StrongPass8"))

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
        self.assertTemplateUsed(response, "accounts/verification_required.html")

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


@override_settings(
    INSTITUTIONAL_EMAIL_DOMAIN=REGISTRATION_DOMAIN,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class AccountFlowIntegrationTests(TestCase):
    def test_complete_registration_login_dashboard_logout_flow(self):
        response = self.client.post(
            reverse("accounts:register"),
            registration_data(),
        )
        self.assertRedirects(response, reverse("accounts:registration_complete"))
        self.assertEqual(User.objects.count(), 0)

        path = emailed_path(mail.outbox[0])
        entry_response = self.client.get(path)
        self.assertEqual(entry_response.status_code, 302)
        clean_path = entry_response.url
        get_response = self.client.get(clean_path)
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(User.objects.count(), 0)

        completion_response = self.client.post(clean_path, completion_data())
        user = User.objects.get(email=f"ada@{REGISTRATION_DOMAIN}")
        self.assertEqual(completion_response.status_code, 200)
        self.assertTrue(user.is_email_verified)
        self.assertTrue(user.check_password("StrongPass8"))

        login_response = self.client.post(
            reverse("accounts:login"),
            {
                "username": f"ADA@{REGISTRATION_DOMAIN.upper()}",
                "password": "StrongPass8",
            },
        )
        self.assertRedirects(login_response, reverse("accounts:dashboard"))
        dashboard_response = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertContains(dashboard_response, "Ada Lovelace")

        logout_response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(logout_response, reverse("accounts:login"))
        dashboard_response = self.client.get(reverse("accounts:dashboard"))
        self.assertRedirects(
            dashboard_response,
            f"{reverse('accounts:login')}?next={reverse('accounts:dashboard')}",
        )


class LegacyVerificationMigrationTests(TransactionTestCase):
    migrate_from = ("accounts", "0004_alter_user_options_and_more")
    migrate_to = ("accounts", "0005_pendingregistration")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        HistoricalUser = old_apps.get_model("accounts", "User")

        self.legacy_user_id = HistoricalUser.objects.create(
            email="legacy@example.com",
            full_name="Legacy User",
            password="!",
        ).pk
        self.staff_user_id = HistoricalUser.objects.create(
            email="staff@example.com",
            full_name="Legacy Staff",
            password="!",
            is_staff=True,
            consent_accepted=True,
        ).pk
        self.superuser_id = HistoricalUser.objects.create(
            email="admin@example.com",
            full_name="Legacy Admin",
            password="!",
            is_staff=True,
            is_superuser=True,
            consent_accepted=True,
        ).pk
        self.pending_user_id = HistoricalUser.objects.create(
            email="pending@example.com",
            full_name="Pending User",
            password="!",
            consent_accepted=True,
        ).pk
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_migration_preserves_staff_access_and_leaves_other_users_unverified(self):
        migrated_apps = MigrationExecutor(connection).loader.project_state(
            [self.migrate_to]
        ).apps
        MigratedUser = migrated_apps.get_model("accounts", "User")

        legacy_user = MigratedUser.objects.get(pk=self.legacy_user_id)
        staff_user = MigratedUser.objects.get(pk=self.staff_user_id)
        superuser = MigratedUser.objects.get(pk=self.superuser_id)
        pending_user = MigratedUser.objects.get(pk=self.pending_user_id)

        self.assertFalse(legacy_user.is_email_verified)
        self.assertTrue(staff_user.is_email_verified)
        self.assertTrue(staff_user.is_staff)
        self.assertTrue(superuser.is_email_verified)
        self.assertTrue(superuser.is_staff)
        self.assertTrue(superuser.is_superuser)
        self.assertFalse(pending_user.is_email_verified)


class LegacyFullNameConstraintMigrationTests(TransactionTestCase):
    migrate_from = ("accounts", "0001_initial")
    migrate_to = ("accounts", "0006_user_full_name_not_blank")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        HistoricalUser = old_apps.get_model("accounts", "User")

        self.empty_name_user_id = HistoricalUser.objects.create(
            username="legacy-empty-name",
            email="legacy-empty@example.com",
            first_name="",
            last_name="",
            password="!",
        ).pk
        self.whitespace_name_user_id = HistoricalUser.objects.create(
            username="legacy-whitespace-name",
            email="legacy-whitespace@example.com",
            first_name="   ",
            last_name="\t",
            password="!",
        ).pk

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_migration_backfills_legacy_users_without_usable_names(self):
        migrated_apps = MigrationExecutor(connection).loader.project_state(
            [self.migrate_to]
        ).apps
        MigratedUser = migrated_apps.get_model("accounts", "User")

        empty_name_user = MigratedUser.objects.get(pk=self.empty_name_user_id)
        whitespace_name_user = MigratedUser.objects.get(
            pk=self.whitespace_name_user_id
        )

        self.assertEqual(empty_name_user.full_name, "Unknown User")
        self.assertEqual(whitespace_name_user.full_name, "Unknown User")

    def test_database_constraint_rejects_whitespace_only_full_names(self):
        migrated_apps = MigrationExecutor(connection).loader.project_state(
            [self.migrate_to]
        ).apps
        MigratedUser = migrated_apps.get_model("accounts", "User")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MigratedUser.objects.create(
                    email="blank-name@example.com",
                    full_name=" \t ",
                    password="!",
                )


class VerificationFormOriginTests(TestCase):
    """Verification forms post from clean URLs while CSRF checks remain enabled."""

    def setUp(self):
        self.client.post(reverse("accounts:register"), registration_data())
        self.verification_link = emailed_path(mail.outbox[0])
        self.csrf_client = Client(enforce_csrf_checks=True)

    def csrf_token(self, response):
        match = re.search(
            r'name="csrfmiddlewaretoken" value="([^"]+)"',
            response.content.decode(),
        )
        return match.group(1)

    def test_token_links_redirect_to_clean_form_urls(self):
        user = User.objects.create_user(
            email="legacy@example.com",
            password="LegacyPass8",
            full_name="Legacy User",
        )
        legacy_path = reverse(
            "accounts:verify_email",
            args=[user.pk, issue_email_verification_token(user)],
        )

        registration_response = self.client.get(self.verification_link)
        legacy_response = self.client.get(legacy_path)

        for response, token_path in (
            (registration_response, self.verification_link),
            (legacy_response, legacy_path),
        ):
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response["Referrer-Policy"], "no-referrer")
            self.assertNotIn(token_path, response.url)
            clean_page = self.client.get(response.url)
            self.assertEqual(clean_page.status_code, 200)
            self.assertEqual(clean_page["Referrer-Policy"], "same-origin")
            self.assertNotContains(clean_page, token_path.rsplit("/", 2)[-2])

    def test_verification_entry_rotates_session_and_preserves_existing_data(self):
        session = self.client.session
        session["unrelated_session_value"] = "preserved"
        session.save()
        registration_session_key = session.session_key

        registration_response = self.client.get(self.verification_link)
        registration_session = self.client.session
        registration_state = registration_session.get(
            "accounts.registration_verification"
        )

        self.assertEqual(registration_response.status_code, 302)
        self.assertNotEqual(registration_session.session_key, registration_session_key)
        self.assertEqual(
            registration_session["unrelated_session_value"],
            "preserved",
        )
        session_store = import_module(settings.SESSION_ENGINE).SessionStore
        self.assertFalse(session_store(session_key=registration_session_key).exists(
            registration_session_key
        ))
        self.assertIn(str(PendingRegistration.objects.get().pk), registration_state)

        legacy_user = User.objects.create_user(
            email="legacy@example.com",
            password="LegacyPass8",
            full_name="Legacy User",
        )
        token_path = reverse(
            "accounts:verify_email",
            args=[legacy_user.pk, issue_email_verification_token(legacy_user)],
        )
        legacy_session_key = registration_session.session_key

        legacy_response = self.client.get(token_path)
        legacy_session = self.client.session

        self.assertEqual(legacy_response.status_code, 302)
        self.assertNotEqual(legacy_session.session_key, legacy_session_key)
        self.assertEqual(legacy_session["unrelated_session_value"], "preserved")
        self.assertIn(
            str(legacy_user.pk),
            legacy_session["accounts.email_verification"],
        )

    def test_multiple_registration_links_keep_independent_state(self):
        second_email = f"grace@{REGISTRATION_DOMAIN}"
        second_response = self.client.post(
            reverse("accounts:register"),
            registration_data(email=second_email),
        )
        self.assertRedirects(
            second_response,
            reverse("accounts:registration_complete"),
        )
        second_link = emailed_path(mail.outbox[1])

        first_entry = self.client.get(self.verification_link)
        first_clean_path = first_entry.url
        second_entry = self.client.get(second_link)
        second_clean_path = second_entry.url
        session_state = self.client.session["accounts.registration_verification"]

        self.assertEqual(first_entry.status_code, 302)
        self.assertEqual(second_entry.status_code, 302)
        first_registration_id = PendingRegistration.objects.get(
            email=f"ada@{REGISTRATION_DOMAIN}"
        ).pk
        second_registration_id = PendingRegistration.objects.get(
            email=second_email
        ).pk
        self.assertIn(str(first_registration_id), session_state)
        self.assertIn(str(second_registration_id), session_state)
        self.assertEqual(self.client.get(first_clean_path).status_code, 200)
        self.assertEqual(self.client.get(second_clean_path).status_code, 200)

    def test_post_with_same_origin_header_passes_csrf_check(self):
        page = self.csrf_client.get(self.verification_link, follow=True)
        data = completion_data(csrfmiddlewaretoken=self.csrf_token(page))

        response = self.csrf_client.post(
            page.request["PATH_INFO"], data, HTTP_ORIGIN="http://testserver"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(email=f"ada@{REGISTRATION_DOMAIN}").exists())
        self.assertNotIn(
            "accounts.registration_verification",
            self.csrf_client.session,
        )

    def test_post_with_null_origin_is_rejected(self):
        page = self.csrf_client.get(self.verification_link, follow=True)
        data = completion_data(csrfmiddlewaretoken=self.csrf_token(page))

        response = self.csrf_client.post(
            page.request["PATH_INFO"],
            data,
            HTTP_ORIGIN="null",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(email=f"ada@{REGISTRATION_DOMAIN}").exists())

    def test_missing_and_invalid_csrf_tokens_are_rejected(self):
        page = self.csrf_client.get(self.verification_link, follow=True)
        token = self.csrf_token(page)
        path = page.request["PATH_INFO"]

        missing_response = self.csrf_client.post(
            path,
            completion_data(),
            HTTP_ORIGIN="http://testserver",
        )
        invalid_response = self.csrf_client.post(
            path,
            completion_data(csrfmiddlewaretoken="invalid-csrf-token"),
            HTTP_ORIGIN="http://testserver",
        )
        valid_token_response = self.csrf_client.post(
            path,
            completion_data(csrfmiddlewaretoken=token),
            HTTP_ORIGIN="http://testserver",
        )

        self.assertEqual(missing_response.status_code, 403)
        self.assertEqual(invalid_response.status_code, 403)
        self.assertEqual(valid_token_response.status_code, 200)

    def test_post_with_invalid_origin_is_rejected(self):
        page = self.csrf_client.get(self.verification_link, follow=True)
        data = completion_data(csrfmiddlewaretoken=self.csrf_token(page))

        response = self.csrf_client.post(
            page.request["PATH_INFO"],
            data,
            HTTP_ORIGIN="https://attacker.example",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(email=f"ada@{REGISTRATION_DOMAIN}").exists())

    def test_email_verification_post_uses_clean_url_and_csrf(self):
        user = User.objects.create_user(
            email="legacy@example.com",
            password="LegacyPass8",
            full_name="Legacy User",
        )
        token = issue_email_verification_token(user)
        token_path = reverse("accounts:verify_email", args=[user.pk, token])

        page = self.csrf_client.get(token_path, follow=True)
        response = self.csrf_client.post(
            page.request["PATH_INFO"],
            {"csrfmiddlewaretoken": self.csrf_token(page)},
            HTTP_ORIGIN="http://testserver",
        )

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.is_email_verified)
        self.assertNotIn(
            "accounts.email_verification",
            self.csrf_client.session,
        )

    def test_legacy_missing_and_invalid_csrf_tokens_are_rejected(self):
        user = User.objects.create_user(
            email="legacy@example.com",
            password="LegacyPass8",
            full_name="Legacy User",
        )
        token_path = reverse(
            "accounts:verify_email",
            args=[user.pk, issue_email_verification_token(user)],
        )
        page = self.csrf_client.get(token_path, follow=True)
        path = page.request["PATH_INFO"]

        missing_response = self.csrf_client.post(
            path,
            {},
            HTTP_ORIGIN="http://testserver",
        )
        invalid_response = self.csrf_client.post(
            path,
            {"csrfmiddlewaretoken": "invalid-csrf-token"},
            HTTP_ORIGIN="http://testserver",
        )
        null_origin_response = self.csrf_client.post(
            path,
            {"csrfmiddlewaretoken": self.csrf_token(page)},
            HTTP_ORIGIN="null",
        )
        untrusted_origin_response = self.csrf_client.post(
            path,
            {"csrfmiddlewaretoken": self.csrf_token(page)},
            HTTP_ORIGIN="https://attacker.example",
        )
        user.refresh_from_db()

        self.assertEqual(missing_response.status_code, 403)
        self.assertEqual(invalid_response.status_code, 403)
        self.assertEqual(null_origin_response.status_code, 403)
        self.assertEqual(untrusted_origin_response.status_code, 403)
        self.assertFalse(user.is_email_verified)

    def test_legacy_failed_consumption_clears_state(self):
        user = User.objects.create_user(
            email="legacy@example.com",
            password="LegacyPass8",
            full_name="Legacy User",
        )
        token_path = reverse(
            "accounts:verify_email",
            args=[user.pk, issue_email_verification_token(user)],
        )
        page = self.csrf_client.get(token_path, follow=True)

        with patch(
            "apps.accounts.views.consume_email_verification_token_hash",
            return_value=False,
        ):
            response = self.csrf_client.post(
                page.request["PATH_INFO"],
                {"csrfmiddlewaretoken": self.csrf_token(page)},
                HTTP_ORIGIN="http://testserver",
            )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn(
            "accounts.email_verification",
            self.csrf_client.session,
        )

    @override_settings(DEBUG=True)
    def test_configured_console_handler_redacts_verification_tokens(self):
        token = "sensitive-test-token"
        path = f"/accounts/verify-registration/123/{token}/"
        logger = logging.getLogger("django")
        handler = next(
            handler
            for handler in logger.handlers
            if any(
                isinstance(filter_, RedactVerificationTokenFilter)
                for filter_ in handler.filters
            )
        )
        output = io.StringIO()
        record = logger.makeRecord(
            logger.name,
            logging.INFO,
            __file__,
            1,
            "GET %s HTTP/1.1",
            (path,),
            None,
        )

        with patch.object(handler, "stream", output):
            logger.handle(record)

        self.assertNotIn(token, output.getvalue())
        self.assertIn("[redacted]", output.getvalue())

    def test_development_server_handler_does_not_apply_request_filter(self):
        token = "sensitive-test-token"
        path = f"/accounts/verify-registration/123/{token}/"
        logger = logging.getLogger("django.server")
        handler = logger.handlers[0]
        self.assertFalse(
            any(
                isinstance(filter_, RedactVerificationTokenFilter)
                for filter_ in handler.filters
            )
        )
        request = RequestFactory().get(path)
        request.META["TEST_SOCKET"] = socket.socket()
        output = io.StringIO()
        record = logger.makeRecord(
            logger.name,
            logging.INFO,
            __file__,
            1,
            '"GET %s HTTP/1.1" %s %s',
            (path, 302, 0),
            None,
            extra={"request": request, "status_code": 302},
        )

        try:
            with patch.object(handler, "stream", output):
                logger.handle(record)
        finally:
            request.META["TEST_SOCKET"].close()

        self.assertIn(token, output.getvalue())
        self.assertEqual(request.path, path)

    @override_settings(ADMINS=[("Admin", "admin@example.com")])
    def test_verification_tokens_are_redacted_from_admin_error_reports(self):
        token = "sensitive-test-token"
        path = f"/accounts/verify-registration/123/{token}/"
        request = RequestFactory().get(path)
        record = logging.LogRecord(
            "django.request",
            logging.ERROR,
            __file__,
            1,
            "Internal Server Error: %s",
            (path,),
            None,
        )
        record.request = request

        self.assertTrue(RedactVerificationTokenFilter().filter(record))
        self.assertIs(record.request._request, request)
        self.assertEqual(request.path, path)
        self.assertEqual(request.META["PATH_INFO"], path)
        handler = AdminEmailHandler(include_html=True)
        with patch.object(handler, "send_mail") as send_mail:
            handler.emit(record)

        message = send_mail.call_args.args[1]
        html_message = send_mail.call_args.kwargs["html_message"]
        self.assertNotIn(token, message)
        self.assertNotIn(token, html_message)
        self.assertIn("[redacted]", message)
        self.assertIn("[redacted]", html_message)
        self.assertIn("127.0.0.1", message)

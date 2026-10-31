"""Forms for account registration and authentication."""

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import User


CONSENT_NOTICE_VERSION = "1.0"


class RegistrationEmailForm(forms.Form):
    email = forms.EmailField(
        label="Institutional email",
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"])
        allowed_domain = settings.INSTITUTIONAL_EMAIL_DOMAIN.strip().lower()
        email_domain = email.rsplit("@", 1)[-1]

        if email_domain != allowed_domain:
            raise ValidationError(
                "Use your institutional email address ending in @%(domain)s.",
                code="invalid_institutional_domain",
                params={"domain": allowed_domain},
            )

        return email


class RegistrationForm(forms.Form):
    full_name = forms.CharField(
        label="Full name",
        max_length=255,
        strip=True,
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )
    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    consent = forms.BooleanField(
        required=True,
        label=(
            "I have read and understood the privacy notice. I consent to the "
            "processing of my personal information for account management, "
            "CoR enrollment verification, and the authorship-accountability "
            "procedures described above."
        ),
    )

    def __init__(self, *args, email, **kwargs):
        self.email = User.objects.normalize_email(email)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The passwords do not match.")

        full_name = cleaned_data.get("full_name")
        if password1 and full_name:
            user = User(email=self.email, full_name=full_name)
            try:
                validate_password(password1, user=user)
            except ValidationError as error:
                self.add_error("password1", error)

        return cleaned_data

    def create_user(self, email):
        if not self.is_valid():
            raise ValueError("Registration form must be valid before completion.")

        normalized_email = User.objects.normalize_email(email)
        if normalized_email != self.email:
            raise ValueError("Registration email does not match the verified address.")
        user = User.objects.filter(email=normalized_email).first()
        if user is not None and user.is_email_verified:
            raise ValueError("This email address already has a verified account.")
        if user is None:
            user = User(email=normalized_email)

        user.full_name = self.cleaned_data["full_name"]
        user.set_password(self.cleaned_data["password1"])
        user.is_email_verified = True
        user.consent_accepted = True
        user.consent_at = timezone.now()
        user.consent_version = CONSENT_NOTICE_VERSION
        user.save()
        return user


class EmailAuthenticationForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Invalid email or password.",
    }

    username = forms.EmailField(
        label="Institutional email",
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}),
    )

    def clean_username(self):
        return User.objects.normalize_email(self.cleaned_data["username"])

    def confirm_login_allowed(self, user):
        if not user.is_active or not user.is_email_verified:
            raise ValidationError(
                "Invalid email or password.",
                code="invalid_login",
            )
        super().confirm_login_allowed(user)

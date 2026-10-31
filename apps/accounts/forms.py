"""Forms for account registration."""

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import User


CONSENT_NOTICE_VERSION = "1.0"


class RegistrationForm(forms.Form):
    full_name = forms.CharField(
        label="Full name",
        max_length=255,
        strip=True,
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )
    email = forms.EmailField(
        label="Institutional email",
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
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

        if User.objects.filter(email=email).exists():
            raise ValidationError(
                "An account with this email address already exists.",
                code="duplicate_email",
            )

        return email

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The passwords do not match.")

        if password1 and cleaned_data.get("email") and cleaned_data.get("full_name"):
            user = User(
                email=cleaned_data["email"],
                full_name=cleaned_data["full_name"],
            )
            try:
                validate_password(password1, user=user)
            except ValidationError as error:
                self.add_error("password1", error)

        return cleaned_data

    def save(self):
        if not self.is_valid():
            raise ValueError("Registration form must be valid before saving.")

        return User.objects.create_user(
            email=self.cleaned_data["email"],
            password=self.cleaned_data["password1"],
            full_name=self.cleaned_data["full_name"],
            consent_accepted=True,
            consent_at=timezone.now(),
            consent_version=CONSENT_NOTICE_VERSION,
        )


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

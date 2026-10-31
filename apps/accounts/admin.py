from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.core.exceptions import ValidationError

from apps.accounts.models import User


class AdminEmailAuthenticationForm(AdminAuthenticationForm):
    error_messages = {
        **AdminAuthenticationForm.error_messages,
        "invalid_login": "Invalid email or password.",
    }

    def clean_username(self):
        return User.objects.normalize_email(self.cleaned_data["username"])

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_email_verified:
            raise ValidationError(
                "Invalid email or password.",
                code="invalid_login",
            )


admin.site.login_form = AdminEmailAuthenticationForm


class CuratorUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "full_name")

    def clean_email(self):
        return User.objects.normalize_email(self.cleaned_data["email"])


class CuratorUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class CuratorUserAdmin(UserAdmin):
    add_form = CuratorUserCreationForm
    form = CuratorUserChangeForm
    model = User
    ordering = ("email",)
    list_display = (
        "email",
        "full_name",
        "is_email_verified",
        "is_staff",
        "is_active",
    )
    list_filter = ("is_email_verified", "is_staff", "is_active", "is_superuser")
    search_fields = ("email", "full_name")
    readonly_fields = (
        "last_login",
        "date_joined",
        "consent_accepted",
        "consent_at",
        "consent_version",
    )
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("full_name",)}),
        (
            "Consent and verification",
            {
                "fields": (
                    "is_email_verified",
                    "consent_accepted",
                    "consent_at",
                    "consent_version",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "full_name", "password1", "password2"),
            },
        ),
    )

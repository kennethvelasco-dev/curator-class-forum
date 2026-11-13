"""Forms for class-server and join-request submissions."""

from django import forms

from apps.servers.models import Server
from apps.servers.subject_codes import (
    SUBJECT_CODE_MAX_LENGTH,
    SubjectCodeError,
    canonicalize_subject_code,
)
from apps.servers.validators import validate_cor_file


class ServerRequestForm(forms.Form):
    """Collect proposed server details and validate a private CoR PDF."""

    proposed_name = forms.CharField(
        label="Proposed server name",
        max_length=255,
        strip=True,
    )
    proposed_section = forms.CharField(
        label="Section (optional)",
        max_length=64,
        required=False,
        strip=True,
    )
    cor_file = forms.FileField(
        label="Certificate of Registration (PDF)",
        help_text="PDF only; maximum file size is 6 MB.",
        widget=forms.ClearableFileInput(
            attrs={"accept": ".pdf,application/pdf"},
        ),
        validators=[validate_cor_file],
    )


class JoinRequestForm(forms.Form):
    """Collect a verified student's subject selections and private CoR."""

    server = forms.ModelChoiceField(
        label="Class server",
        queryset=Server.objects.none(),
        empty_label="Select a server",
    )
    registered_name = forms.CharField(
        label="Registered name",
        max_length=255,
        strip=True,
    )
    student_number = forms.CharField(
        label="Student number",
        max_length=64,
        strip=True,
    )
    subject_entries = forms.CharField(
        label="Subject codes",
        help_text=(
            "Enter one subject code per line (or separate codes with commas). "
            "Each entry is normalized (leading/trailing spaces removed; internal "
            "whitespace collapsed) and must be non-empty, at most "
            f"{SUBJECT_CODE_MAX_LENGTH} characters, and contain only printable "
            "characters. Official subject codes from your Certificate of "
            "Registration are recommended."
        ),
        strip=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    cor_file = forms.FileField(
        label="Certificate of Registration (PDF)",
        help_text=(
            "Block out your contact number on your CoR before uploading it. "
            "PDF only; maximum file size is 6 MB."
        ),
        widget=forms.ClearableFileInput(
            attrs={"accept": ".pdf,application/pdf"},
        ),
        validators=[validate_cor_file],
    )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        self.fields["server"].queryset = Server.objects.filter(
            is_active=True,
        ).order_by("name", "section", "slug")

    def clean_registered_name(self):
        cleaned_name = (self.cleaned_data.get("registered_name") or "").strip()
        if self.request is not None and self.request.user.is_authenticated:
            if cleaned_name != self.request.user.full_name.strip():
                raise forms.ValidationError(
                    "The submitted name must match your registered name."
                )
        return cleaned_name

    def clean_student_number(self):
        value = (self.cleaned_data.get("student_number") or "").strip()
        if not value:
            raise forms.ValidationError("A student number is required.")
        return value

    def clean_subject_entries(self):
        """Parse, canonicalize, and de-duplicate subject codes.

        Every token produced by newline/comma splitting is validated — empty
        tokens from trailing newlines, blank lines, or repeated commas are
        rejected, not discarded. Case-insensitive duplicate detection is
        applied after canonicalization so that capitalization of the first
        occurrence is preserved.
        """
        raw_value = self.cleaned_data.get("subject_entries") or ""
        entries = []
        seen = set()
        normalized_newlines = raw_value.replace("\r\n", "\n").replace("\r", "\n")
        for entry in normalized_newlines.split("\n"):
            for item in entry.split(","):
                # Do not skip empty/whitespace tokens — canonicalize rejects them.
                try:
                    candidate = canonicalize_subject_code(item)
                except SubjectCodeError as exc:
                    raise forms.ValidationError(str(exc)) from None
                key = candidate.casefold()
                if key in seen:
                    raise forms.ValidationError(
                        "Duplicate subject entries are not allowed."
                    )
                seen.add(key)
                entries.append(candidate)
        if not entries:
            raise forms.ValidationError(
                "At least one subject code is required."
            )
        return entries


class ServerRequestDecisionForm(forms.Form):
    """Collect and validate a platform Admin's server-request decision."""

    decision = forms.ChoiceField(
        choices=(
            ("approved", "Approve"),
            ("rejected", "Reject"),
        ),
        label="Decision",
    )
    decision_reason = forms.CharField(
        label="Reason",
        strip=True,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class JoinRequestDecisionForm(forms.Form):
    """Collect a President's decision for a pending join request."""

    decision = forms.ChoiceField(
        choices=(
            ("approved", "Approve"),
            ("rejected", "Reject"),
        ),
        label="Decision",
    )
    decision_reason = forms.CharField(
        label="Reason",
        strip=True,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    membership_role = forms.ChoiceField(
        choices=(
            ("student", "Student"),
            ("officer", "Officer"),
        ),
        required=False,
        label="Returning member role",
    )


class ServerSwitchForm(forms.Form):
    """Select an authorized active server context."""

    server_id = forms.IntegerField(min_value=1)


class PresidentTransferForm(forms.Form):
    """Confirm President title transfer with password re-authentication."""

    target_membership_id = forms.IntegerField(
        min_value=1,
        label="Transfer to member",
    )
    password = forms.CharField(
        label="Confirm your password",
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
        strip=False,
    )
    confirm = forms.BooleanField(
        label="I understand this permanently transfers President authority",
        required=True,
    )


class MembershipRoleChangeForm(forms.Form):
    """Choose only the Student or Officer role for a server member."""

    expected_role = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,
    )
    new_role = forms.ChoiceField(
        choices=(
            ("", "Select a role"),
            ("student", "Student"),
            ("officer", "Officer"),
        ),
        label="New role",
    )

    def clean_expected_role(self):
        val = self.cleaned_data.get("expected_role") or self.data.get("current_role") or ""
        return val.strip().lower()

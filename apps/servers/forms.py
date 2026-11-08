"""Forms for class-server and join-request submissions."""

from django import forms

from apps.servers.models import Server
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
        label="Subject / section",
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
        raw_value = self.cleaned_data.get("subject_entries") or ""
        entries = []
        seen = set()
        normalized_newlines = raw_value.replace("\r\n", "\n").replace("\r", "\n")
        for entry in normalized_newlines.split("\n"):
            for item in entry.split(","):
                candidate = " ".join((item or "").split()).strip()
                if not candidate:
                    raise forms.ValidationError(
                        "Blank subject or section entries are not allowed."
                    )
                if len(candidate) > 64:
                    raise forms.ValidationError(
                        "Each subject or section entry must be 64 characters or fewer."
                    )
                key = candidate.casefold()
                if key in seen:
                    raise forms.ValidationError(
                        "Duplicate subject entries are not allowed."
                    )
                seen.add(key)
                entries.append(candidate)
        if not entries:
            raise forms.ValidationError(
                "At least one subject or section entry is required."
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

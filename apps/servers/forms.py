"""Forms for server-request submissions."""

from django import forms

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

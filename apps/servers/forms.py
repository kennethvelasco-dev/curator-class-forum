from django import forms

from apps.servers.validators import validate_cor_file


class ServerRequestForm(forms.Form):
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

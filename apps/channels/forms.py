
"""Forms for class channel creation."""

from django import forms

from apps.servers.subject_codes import (
    SUBJECT_CODE_MAX_LENGTH,
    SubjectCodeError,
    canonicalize_subject_code,
)


class SubjectChannelForm(forms.Form):
    """Collect subject channel details and professor contact information."""

    subject_code = forms.CharField(
        label="Subject code",
        max_length=SUBJECT_CODE_MAX_LENGTH,
        strip=False,
        help_text="Enter the official subject code from the Certificate of Registration.",
    )
    name = forms.CharField(
        label="Subject name",
        max_length=100,
        strip=True,
    )
    professor_name = forms.CharField(
        label="Professor name",
        max_length=255,
        required=False,
        strip=True,
    )
    professor_email = forms.EmailField(
        label="Professor official email",
        max_length=254,
        required=False,
    )
    office_hours = forms.CharField(
        label="Office hours",
        max_length=255,
        required=False,
        strip=True,
        widget=forms.TextInput(
            attrs={"placeholder": "Example: Monday, 1:00 PM - 3:00 PM"}
        ),
    )

    def clean_subject_code(self):
        raw_code = self.cleaned_data.get("subject_code", "")
        try:
            return canonicalize_subject_code(raw_code)
        except SubjectCodeError as exc:
            raise forms.ValidationError(str(exc)) from None

class SubjectChannelEditForm(forms.Form):
    """Edit subject channel details and professor contact information."""

    name = forms.CharField(
        label="Subject name",
        max_length=100,
        strip=True,
    )
    professor_name = forms.CharField(
        label="Professor name",
        max_length=255,
        required=False,
        strip=True,
    )
    professor_email = forms.EmailField(
        label="Professor official email",
        max_length=254,
        required=False,
    )
    office_hours = forms.CharField(
        label="Consultation information",
        max_length=255,
        required=False,
        strip=True,
    )

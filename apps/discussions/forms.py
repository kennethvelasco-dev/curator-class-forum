"""Forms for class discussion threads."""

from django import forms

from apps.discussions.anonymity.forms import AnonymityFormMixin


class ThreadCreateForm(AnonymityFormMixin, forms.Form):
    """Validate a new discussion thread."""

    title = forms.CharField(
        label="Question title",
        max_length=255,
        strip=True,
        error_messages={
            "required": "Please enter a question title.",
            "max_length": "The title cannot exceed 255 characters.",
        },
    )
    body = forms.CharField(
        label="Question details",
        strip=True,
        max_length=10000,
        widget=forms.Textarea(
            attrs={
                "rows": 8,
                "placeholder": "Describe your question or discussion topic...",
            }
        ),
        error_messages={
            "required": "Please enter your question details.",
            "max_length": "The question details cannot exceed 10,000 characters.",
        },
    )

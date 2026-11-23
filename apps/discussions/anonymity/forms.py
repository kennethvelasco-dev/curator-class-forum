"""The per-post "Post Anonymously" choice (FR-019)."""

from django import forms

ANONYMITY_FIELD_NAME = "is_anonymous"
ANONYMITY_FIELD_LABEL = "Post Anonymously"


class AnonymityFormMixin:
    """Add the anonymity checkbox to a thread or reply form.

    Works with ``forms.Form`` and ``forms.ModelForm`` (list the mixin first).
    The view must copy ``is_anonymous_choice`` onto the instance explicitly;
    the author is always ``request.user`` and is never a form field.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields[ANONYMITY_FIELD_NAME] = forms.BooleanField(
            required=False,
            initial=False,
            label=ANONYMITY_FIELD_LABEL,
            widget=forms.CheckboxInput(attrs={"data-anonymity-toggle": ""}),
        )

    @property
    def is_anonymous_choice(self):
        """The validated choice. Only valid after ``is_valid()``."""
        return bool(self.cleaned_data.get(ANONYMITY_FIELD_NAME, False))

"""Validation helpers for CoR uploads."""

from pathlib import Path

from django.core.exceptions import ValidationError


MAX_COR_FILE_SIZE = 6 * 1024 * 1024
PDF_HEADER = b"%PDF-"
PDF_HEADER_SEARCH_SIZE = 1024


def validate_cor_file(uploaded_file):
    """Require a PDF upload no larger than 6 MiB."""
    if uploaded_file.size > MAX_COR_FILE_SIZE:
        raise ValidationError(
            "CoR files must be no larger than 6 MB.",
            code="cor_file_too_large",
        )

    if Path(uploaded_file.name).suffix.lower() != ".pdf":
        raise ValidationError(
            "Upload a PDF file.",
            code="cor_file_not_pdf",
        )

    original_position = uploaded_file.tell()
    try:
        uploaded_file.seek(0)
        header = uploaded_file.read(PDF_HEADER_SEARCH_SIZE)
    finally:
        uploaded_file.seek(original_position)

    if PDF_HEADER not in header:
        raise ValidationError(
            "The uploaded file is not a valid PDF.",
            code="cor_file_invalid_pdf",
        )

"""Validation helpers for CoR uploads."""

import re
from pathlib import Path

from django.core.exceptions import ValidationError
from pypdf import PdfReader
from pypdf.errors import DependencyError, PyPdfError


MAX_COR_FILE_SIZE = 6 * 1024 * 1024
PDF_HEADER = b"%PDF-"
PDF_HEADER_SEARCH_SIZE = 1024
PDF_WHITESPACE = b"\x00\t\n\f\r "
PDF_HEADER_PATTERN = re.compile(rb"%PDF-(?:1\.[0-7]|2\.0)(?=[\r\n]|\Z)")


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
        header_window = uploaded_file.read(PDF_HEADER_SEARCH_SIZE)
        header_position = header_window.find(PDF_HEADER)
        if (
            header_position < 0
            or header_window[:header_position].strip(PDF_WHITESPACE)
            or not PDF_HEADER_PATTERN.match(header_window, header_position)
        ):
            raise ValidationError(
                "The uploaded file is not a valid PDF.",
                code="cor_file_invalid_pdf",
            )

        uploaded_file.seek(0)
        try:
            reader = PdfReader(uploaded_file)
            if reader.is_encrypted or not reader.pages:
                raise ValidationError(
                    "The uploaded file is not a valid PDF.",
                    code="cor_file_invalid_pdf",
                )
        except (
            DependencyError,
            PyPdfError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise ValidationError(
                "The uploaded file is not a valid PDF.",
                code="cor_file_invalid_pdf",
            ) from error
    finally:
        uploaded_file.seek(original_position)

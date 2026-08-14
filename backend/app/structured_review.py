import re
from typing import Protocol

from .models import DocumentType


class StructuredFieldReviewer(Protocol):
    """Validate and normalize a human correction for an extraction schema."""

    def validate(
        self, document_type: DocumentType, field_name: str, value: str
    ) -> str: ...


class StructuredFieldReviewError(ValueError):
    """Raised when a field correction is unsupported or invalid."""


class LocalStructuredFieldReviewer:
    """Validate deterministic field corrections without external services."""

    _supported_fields = {
        DocumentType.invoice: {
            "invoice_number",
            "invoice_date",
            "vendor",
            "total_amount",
        },
        DocumentType.resume: {"name", "email", "phone"},
        DocumentType.contract: {
            "party",
            "effective_date",
            "execution_date",
            "termination_date",
            "expiration_date",
        },
        DocumentType.other: set(),
        DocumentType.unknown: set(),
    }
    _date_pattern = re.compile(
        r"(?:[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}"
        r"|\d{4}-\d{1,2}-\d{1,2}"
        r"|\d{1,2}/\d{1,2}/\d{2,4})"
    )
    _email_pattern = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
    _amount_pattern = re.compile(r"(?:USD\s*)?\$?\s?\d[\d,]*(?:\.\d{2})?")

    def validate(
        self, document_type: DocumentType, field_name: str, value: str
    ) -> str:
        if field_name not in self._supported_fields[document_type]:
            raise StructuredFieldReviewError("unsupported_field_name")

        normalized = value.strip()
        if not normalized:
            raise StructuredFieldReviewError("invalid_field_value")
        if field_name.endswith("_date") and not self._date_pattern.fullmatch(normalized):
            raise StructuredFieldReviewError("invalid_field_value")
        if field_name == "email" and not self._email_pattern.fullmatch(normalized):
            raise StructuredFieldReviewError("invalid_field_value")
        if field_name == "phone" and len(re.sub(r"\D", "", normalized)) < 7:
            raise StructuredFieldReviewError("invalid_field_value")
        if field_name == "total_amount" and not self._amount_pattern.fullmatch(normalized):
            raise StructuredFieldReviewError("invalid_field_value")
        return normalized

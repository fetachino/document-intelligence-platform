import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from .models import DocumentType


@dataclass(frozen=True)
class StructuredTextPage:
    page_number: int
    text: str


@dataclass(frozen=True)
class ExtractedStructuredField:
    field_name: str
    value: str
    page_number: int
    value_index: int = 0


@dataclass(frozen=True)
class StructuredExtractionResult:
    document_type: DocumentType
    extractor_version: str
    extraction_method: str
    fields: list[ExtractedStructuredField]


class StructuredExtractor(Protocol):
    """Extract schema-specific values from stored page text."""

    version: str
    method: str

    async def extract(
        self, document_type: DocumentType, pages: Sequence[StructuredTextPage]
    ) -> StructuredExtractionResult: ...


class LocalStructuredExtractor:
    """Conservative deterministic field extraction from stored page text."""

    version = "local_regex_v1"
    method = "deterministic_regex"
    _date_value = (
        r"(?:[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}"
        r"|\d{4}-\d{1,2}-\d{1,2}"
        r"|\d{1,2}/\d{1,2}/\d{2,4})"
    )

    async def extract(
        self, document_type: DocumentType, pages: Sequence[StructuredTextPage]
    ) -> StructuredExtractionResult:
        if document_type == DocumentType.invoice:
            fields = self._extract_invoice(pages)
        elif document_type == DocumentType.resume:
            fields = self._extract_resume(pages)
        elif document_type == DocumentType.contract:
            fields = self._extract_contract(pages)
        else:
            fields = []
        return StructuredExtractionResult(
            document_type=document_type,
            extractor_version=self.version,
            extraction_method=self.method,
            fields=fields,
        )

    def _extract_invoice(
        self, pages: Sequence[StructuredTextPage]
    ) -> list[ExtractedStructuredField]:
        fields = []
        invoice_number = self._first_match(
            pages,
            r"^\s*invoice\s*(?:number|no\.?|#)\s*[:#-]?\s*"
            r"([A-Z0-9][A-Z0-9./-]*)\s*$",
        )
        invoice_date = self._first_match(
            pages, rf"^\s*invoice\s+date\s*:\s*({self._date_value})\s*$"
        )
        vendor = self._first_match(
            pages, r"^\s*(?:vendor|seller|from)\s*:\s*(.+?)\s*$"
        )
        total_amount = self._first_match(
            pages,
            r"^\s*(?:total amount|amount due|total)\s*:\s*"
            r"((?:USD\s*)?\$?\s?\d[\d,]*(?:\.\d{2})?)\s*$",
        )
        for field_name, match in (
            ("invoice_number", invoice_number),
            ("invoice_date", invoice_date),
            ("vendor", vendor),
            ("total_amount", total_amount),
        ):
            if match is not None:
                value, page_number = match
                fields.append(ExtractedStructuredField(field_name, value, page_number))
        return fields

    def _extract_resume(
        self, pages: Sequence[StructuredTextPage]
    ) -> list[ExtractedStructuredField]:
        fields = []
        name = self._first_match(
            pages, r"^\s*name\s*:\s*([A-Za-z][A-Za-z .'-]{1,100})\s*$"
        )
        if name is None:
            name = self._resume_header_name(pages)
        email = self._first_match(
            pages, r"\b([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})\b"
        )
        phone = self._first_match(
            pages,
            r"(?<!\d)((?:\+?1[ .-]?)?(?:\(\d{3}\)|\d{3})"
            r"[ .-]\d{3}[ .-]\d{4})(?!\d)",
        )
        for field_name, match in (("name", name), ("email", email), ("phone", phone)):
            if match is not None:
                value, page_number = match
                fields.append(ExtractedStructuredField(field_name, value, page_number))
        return fields

    def _extract_contract(
        self, pages: Sequence[StructuredTextPage]
    ) -> list[ExtractedStructuredField]:
        fields = self._contract_parties(pages)
        for field_name, label in (
            ("effective_date", "effective date"),
            ("execution_date", "execution date"),
            ("termination_date", "termination date"),
            ("expiration_date", "expiration date"),
        ):
            match = self._first_match(
                pages, rf"^\s*{label}\s*:\s*({self._date_value})\s*$"
            )
            if match is not None:
                value, page_number = match
                fields.append(ExtractedStructuredField(field_name, value, page_number))
        return fields

    def _contract_parties(
        self, pages: Sequence[StructuredTextPage]
    ) -> list[ExtractedStructuredField]:
        found: list[tuple[str, int]] = []
        for page in pages:
            labelled = re.finditer(
                r"^\s*party(?:\s+[AB12])?\s*:\s*(.+?)\s*$",
                page.text,
                re.IGNORECASE | re.MULTILINE,
            )
            found.extend((match.group(1).strip(), page.page_number) for match in labelled)
            between = re.search(
                r"^\s*(?:agreement\s+)?between\s+(.+?)\s+and\s+(.+?)(?:\.|$)",
                page.text,
                re.IGNORECASE | re.MULTILINE,
            )
            if between is not None:
                found.extend(
                    [
                        (between.group(1).strip(), page.page_number),
                        (between.group(2).strip(), page.page_number),
                    ]
                )

        unique: list[tuple[str, int]] = []
        seen = set()
        for value, page_number in found:
            key = value.casefold()
            if value and key not in seen:
                seen.add(key)
                unique.append((value, page_number))
        return [
            ExtractedStructuredField("party", value, page_number, index)
            for index, (value, page_number) in enumerate(unique)
        ]

    def _resume_header_name(
        self, pages: Sequence[StructuredTextPage]
    ) -> tuple[str, int] | None:
        for page in pages:
            for line in page.text.splitlines():
                candidate = line.strip()
                if candidate.lower() in {"resume", "curriculum vitae"}:
                    continue
                if re.fullmatch(
                    r"[A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,3}", candidate
                ):
                    return candidate, page.page_number
                if candidate:
                    break
        return None

    @staticmethod
    def _first_match(
        pages: Sequence[StructuredTextPage], pattern: str
    ) -> tuple[str, int] | None:
        for page in pages:
            match = re.search(pattern, page.text, re.IGNORECASE | re.MULTILINE)
            if match is not None:
                value = match.group(1).strip()
                if value:
                    return value, page.page_number
        return None

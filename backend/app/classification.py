from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from .models import DocumentType


@dataclass(frozen=True)
class ClassificationResult:
    document_type: DocumentType
    classifier_version: str


class DocumentClassifier(Protocol):
    """Classify stored page text behind a replaceable provider boundary."""

    async def classify(self, pages: Sequence[str]) -> ClassificationResult: ...


class LocalKeywordClassifier:
    """Deterministic baseline classifier for locally extracted text."""

    version = "local_keyword_v1"
    _keywords = {
        DocumentType.invoice: (
            "invoice",
            "invoice number",
            "bill to",
            "amount due",
            "subtotal",
        ),
        DocumentType.resume: (
            "curriculum vitae",
            "work experience",
            "professional experience",
            "education",
            "skills",
        ),
        DocumentType.contract: (
            "agreement",
            "contract",
            "effective date",
            "governing law",
            "terms and conditions",
        ),
    }

    async def classify(self, pages: Sequence[str]) -> ClassificationResult:
        text = "\n".join(pages).strip().lower()
        if not text:
            return ClassificationResult(DocumentType.unknown, self.version)

        scores = {
            document_type: sum(keyword in text for keyword in keywords)
            for document_type, keywords in self._keywords.items()
        }
        highest_score = max(scores.values())
        if highest_score == 0:
            return ClassificationResult(DocumentType.other, self.version)

        winners = [
            document_type
            for document_type, score in scores.items()
            if score == highest_score
        ]
        if len(winners) != 1:
            return ClassificationResult(DocumentType.other, self.version)
        return ClassificationResult(winners[0], self.version)

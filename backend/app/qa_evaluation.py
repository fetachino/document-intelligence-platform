import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .models import QaAnswerStatus, QaResponse


@dataclass(frozen=True)
class EvaluationDocument:
    key: str
    pages: tuple[str, ...]


@dataclass(frozen=True)
class ExpectedCitation:
    document_key: str
    page_number: int
    chunk_index: int


@dataclass(frozen=True)
class QaEvaluationCase:
    name: str
    question: str
    document_scope: tuple[str, ...] | None
    retrieval_limit: int
    expected_status: QaAnswerStatus
    expected_answer_contains: tuple[str, ...]
    expected_citations: tuple[ExpectedCitation, ...]


@dataclass(frozen=True)
class QaEvaluationDataset:
    documents: tuple[EvaluationDocument, ...]
    cases: tuple[QaEvaluationCase, ...]


@dataclass(frozen=True)
class QaEvaluationMetrics:
    case_count: int
    status_accuracy: float
    answer_content_accuracy: float
    citation_accuracy: float
    citation_grounding_accuracy: float
    retrieval_relevance_accuracy: float


class QaEvaluationRunner(Protocol):
    async def __call__(
        self,
        question: str,
        document_ids: Sequence[str] | None,
        retrieval_limit: int,
    ) -> QaResponse: ...


def load_qa_evaluation_dataset(path: Path | None = None) -> QaEvaluationDataset:
    """Load the deterministic local Q&A evaluation cases from JSON."""

    dataset_path = path or (
        Path(__file__).resolve().parents[1] / "evaluation" / "qa_dataset.json"
    )
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    documents = tuple(
        EvaluationDocument(item["key"], tuple(item["pages"]))
        for item in payload["documents"]
    )
    cases = tuple(
        QaEvaluationCase(
            name=item["name"],
            question=item["question"],
            document_scope=(
                tuple(item["document_scope"])
                if item["document_scope"] is not None
                else None
            ),
            retrieval_limit=item["retrieval_limit"],
            expected_status=QaAnswerStatus(item["expected_status"]),
            expected_answer_contains=tuple(item["expected_answer_contains"]),
            expected_citations=tuple(
                ExpectedCitation(
                    citation["document_key"],
                    citation["page_number"],
                    citation["chunk_index"],
                )
                for citation in item["expected_citations"]
            ),
        )
        for item in payload["cases"]
    )
    return QaEvaluationDataset(documents, cases)


async def evaluate_qa_dataset(
    dataset: QaEvaluationDataset,
    document_ids: Mapping[str, str],
    runner: QaEvaluationRunner,
) -> QaEvaluationMetrics:
    """Compute local metrics from actual pipeline responses for every dataset case."""

    status_results = []
    answer_results = []
    citation_results = []
    grounding_results = []
    retrieval_results = []
    reverse_document_ids = {value: key for key, value in document_ids.items()}

    for case in dataset.cases:
        scope = (
            [document_ids[key] for key in case.document_scope]
            if case.document_scope is not None
            else None
        )
        response = await runner(case.question, scope, case.retrieval_limit)
        status_results.append(response.status == case.expected_status)
        answer_results.append(
            all(
                expected.casefold() in response.answer.casefold()
                for expected in case.expected_answer_contains
            )
        )

        expected_keys = {
            (citation.document_key, citation.page_number, citation.chunk_index)
            for citation in case.expected_citations
        }
        actual_keys = {
            (
                reverse_document_ids.get(citation.document_id, citation.document_id),
                citation.page_number,
                citation.chunk_index,
            )
            for citation in response.citations
        }
        citation_results.append(actual_keys == expected_keys)

        retrieved_by_key = {
            (result.document_id, result.page_number, result.chunk_index): result
            for result in response.retrieval.results
        }
        grounding_results.append(
            all(
                (
                    citation.document_id,
                    citation.page_number,
                    citation.chunk_index,
                )
                in retrieved_by_key
                and citation.source_snippet
                == retrieved_by_key[
                    (
                        citation.document_id,
                        citation.page_number,
                        citation.chunk_index,
                    )
                ].text
                for citation in response.citations
            )
        )
        retrieved_keys = {
            (
                reverse_document_ids.get(result.document_id, result.document_id),
                result.page_number,
                result.chunk_index,
            )
            for result in response.retrieval.results
        }
        retrieval_results.append(expected_keys.issubset(retrieved_keys))

    case_count = len(dataset.cases)
    if case_count == 0:
        raise ValueError("empty_qa_evaluation_dataset")
    return QaEvaluationMetrics(
        case_count=case_count,
        status_accuracy=_accuracy(status_results),
        answer_content_accuracy=_accuracy(answer_results),
        citation_accuracy=_accuracy(citation_results),
        citation_grounding_accuracy=_accuracy(grounding_results),
        retrieval_relevance_accuracy=_accuracy(retrieval_results),
    )


def _accuracy(results: Sequence[bool]) -> float:
    return sum(results) / len(results)

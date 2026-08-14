import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from .embeddings import EmbeddingProvider, LocalHashEmbeddingProvider
from .models import (
    QaAnswerStatus,
    QaCitation,
    QaResponse,
    QaRetrievalMetadata,
    SemanticSearchResult,
)
from .search import semantic_search

INSUFFICIENT_EVIDENCE_ANSWER = "Insufficient evidence in the retrieved documents."


@dataclass(frozen=True)
class GeneratedAnswer:
    answer: str
    status: QaAnswerStatus
    evidence_indices: tuple[int, ...] = ()


class AnswerGenerator(Protocol):
    """Generate an answer using only supplied context text and evidence indexes."""

    model: str

    async def generate(
        self, question: str, contexts: Sequence[str]
    ) -> GeneratedAnswer: ...


class LocalExtractiveAnswerGenerator:
    """Select grounded sentences with deterministic question-term coverage."""

    model = "local_extractive_v1"
    _token_pattern = re.compile(r"[A-Za-z0-9]+")
    _sentence_pattern = re.compile(r"(?<=[.!?])\s+")
    _stopwords = {
        "a",
        "an",
        "and",
        "are",
        "according",
        "document",
        "documents",
        "do",
        "does",
        "for",
        "from",
        "in",
        "is",
        "me",
        "of",
        "on",
        "the",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
    }

    async def generate(
        self, question: str, contexts: Sequence[str]
    ) -> GeneratedAnswer:
        question_terms = self._content_terms(question)
        if not question_terms:
            return self._insufficient()

        candidates: list[tuple[int, int, str, set[str]]] = []
        minimum_overlap = 1 if len(question_terms) == 1 else 2
        for context_index, context in enumerate(contexts):
            best: tuple[int, str, set[str]] | None = None
            for sentence in self._sentences(context):
                overlap = question_terms & self._content_terms(sentence)
                score = len(overlap)
                if score >= minimum_overlap and (best is None or score > best[0]):
                    best = (score, sentence, overlap)
            if best is not None:
                candidates.append((best[0], context_index, best[1], best[2]))

        candidates.sort(key=lambda item: (-item[0], item[1]))
        selected = []
        covered_terms: set[str] = set()
        for candidate in candidates:
            if candidate[3] - covered_terms:
                selected.append(candidate)
                covered_terms.update(candidate[3])
            if question_terms.issubset(covered_terms) or len(selected) == 3:
                break
        if not question_terms.issubset(covered_terms):
            return self._insufficient()

        answer_parts = []
        evidence_indices = []
        for _, context_index, sentence, _ in selected:
            if sentence not in answer_parts:
                answer_parts.append(sentence)
                evidence_indices.append(context_index)
        return GeneratedAnswer(
            answer=" ".join(answer_parts),
            status=QaAnswerStatus.answered,
            evidence_indices=tuple(evidence_indices),
        )

    def _content_terms(self, text: str) -> set[str]:
        return {
            self._normalize_token(token)
            for token in self._token_pattern.findall(text.casefold())
            if token not in self._stopwords
        }

    @staticmethod
    def _normalize_token(token: str) -> str:
        if len(token) > 4 and token.endswith("s"):
            return token[:-1]
        return token

    def _sentences(self, text: str) -> list[str]:
        return [
            sentence.strip()
            for sentence in self._sentence_pattern.split(text.strip())
            if sentence.strip()
        ]

    @staticmethod
    def _insufficient() -> GeneratedAnswer:
        return GeneratedAnswer(
            answer=INSUFFICIENT_EVIDENCE_ANSWER,
            status=QaAnswerStatus.insufficient_evidence,
        )


async def answer_question(
    session: AsyncSession,
    question: str,
    document_ids: Sequence[str] | None = None,
    retrieval_limit: int = 5,
    generator: AnswerGenerator | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> QaResponse:
    """Retrieve context, generate from it, and bind evidence to stored provenance."""

    active_generator = generator or LocalExtractiveAnswerGenerator()
    active_embedding_provider = embedding_provider or LocalHashEmbeddingProvider()
    retrieved = await semantic_search(
        session,
        question,
        retrieval_limit,
        active_embedding_provider,
        document_ids,
    )
    generated = await active_generator.generate(
        question, [result.text for result in retrieved]
    )
    evidence_indices = _validated_evidence_indices(generated, len(retrieved))
    citations = [_citation_from_result(retrieved[index]) for index in evidence_indices]
    return QaResponse(
        answer=generated.answer,
        status=generated.status,
        citations=citations,
        retrieval=QaRetrievalMetadata(
            result_count=len(retrieved),
            retrieval_limit=retrieval_limit,
            document_ids=list(document_ids) if document_ids is not None else None,
            embedding_model=active_embedding_provider.model,
            results=retrieved,
        ),
        answer_provider=active_generator.model,
    )


def _validated_evidence_indices(
    generated: GeneratedAnswer, result_count: int
) -> tuple[int, ...]:
    indices = tuple(dict.fromkeys(generated.evidence_indices))
    if any(index < 0 or index >= result_count for index in indices):
        raise ValueError("invalid_answer_evidence")
    if generated.status == QaAnswerStatus.answered and not indices:
        raise ValueError("answered_without_evidence")
    if generated.status == QaAnswerStatus.insufficient_evidence and indices:
        raise ValueError("insufficient_answer_has_evidence")
    return indices


def _citation_from_result(result: SemanticSearchResult) -> QaCitation:
    return QaCitation(
        document_id=result.document_id,
        page_number=result.page_number,
        chunk_index=result.chunk_index,
        source_snippet=result.text,
        distance=result.distance,
    )

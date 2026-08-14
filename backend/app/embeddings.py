import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import delete
from sqlmodel import col

from .database import get_session
from .models import DocumentChunk

EMBEDDING_DIMENSIONS = 128


@dataclass(frozen=True)
class EmbeddingSourcePage:
    page_number: int
    text: str


@dataclass(frozen=True)
class TextChunk:
    page_number: int
    chunk_index: int
    text: str


class EmbeddingProvider(Protocol):
    """Generate fixed-size vectors behind a replaceable provider boundary."""

    model: str
    dimensions: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class TextChunker(Protocol):
    """Split stored page text while retaining page and chunk provenance."""

    def chunk(self, pages: Sequence[EmbeddingSourcePage]) -> list[TextChunk]: ...


class LocalHashEmbeddingProvider:
    """Deterministic normalized token hashing for local retrieval development."""

    model = "local_hash_v1"
    dimensions = EMBEDDING_DIMENSIONS
    _token_pattern = re.compile(r"[A-Za-z0-9]+")

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in self._token_pattern.findall(text.casefold()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign
        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude:
            return [value / magnitude for value in vector]
        return vector


class PageTextChunker:
    """Create deterministic, page-bounded word chunks with overlap."""

    def __init__(self, max_words: int = 120, overlap_words: int = 20) -> None:
        if max_words <= 0 or overlap_words < 0 or overlap_words >= max_words:
            raise ValueError("invalid_chunk_configuration")
        self.max_words = max_words
        self.overlap_words = overlap_words

    def chunk(self, pages: Sequence[EmbeddingSourcePage]) -> list[TextChunk]:
        chunks = []
        for page in pages:
            words = page.text.split()
            start = 0
            chunk_index = 0
            while start < len(words):
                end = min(start + self.max_words, len(words))
                text = " ".join(words[start:end]).strip()
                if text:
                    chunks.append(TextChunk(page.page_number, chunk_index, text))
                    chunk_index += 1
                if end == len(words):
                    break
                start = end - self.overlap_words
        return chunks


async def index_document_pages(
    document_id: str,
    pages: Sequence[EmbeddingSourcePage],
    provider: EmbeddingProvider | None = None,
    chunker: TextChunker | None = None,
) -> None:
    """Compute a full replacement index, then swap it in one transaction."""

    active_provider = provider or LocalHashEmbeddingProvider()
    chunks = (chunker or PageTextChunker()).chunk(pages)
    vectors = await active_provider.embed([chunk.text for chunk in chunks])
    if len(vectors) != len(chunks) or any(
        len(vector) != active_provider.dimensions for vector in vectors
    ):
        raise ValueError("invalid_embedding_dimensions")

    async for session in get_session():
        await session.execute(
            delete(DocumentChunk).where(col(DocumentChunk.document_id) == document_id)
        )
        session.add_all(
            [
                DocumentChunk(
                    document_id=document_id,
                    page_number=chunk.page_number,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    embedding=vector,
                    embedding_model=active_provider.model,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
        )
        await session.commit()
        return

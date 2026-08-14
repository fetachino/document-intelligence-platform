import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Column,
    Enum as SQLAlchemyEnum,
    ForeignKeyConstraint,
    Index,
    Text,
    text,
)
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ProcessingStatus(str, Enum):
    uploaded = "uploaded"
    processing = "processing"
    processed = "processed"
    failed = "failed"


class ProcessingJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class ExtractionMethod(str, Enum):
    native = "native"
    ocr = "ocr"


class DocumentType(str, Enum):
    invoice = "invoice"
    resume = "resume"
    contract = "contract"
    other = "other"
    unknown = "unknown"


class ClassificationSource(str, Enum):
    classifier = "classifier"
    human = "human"


class StructuredExtractionStatus(str, Enum):
    processing = "processing"
    completed = "completed"
    failed = "failed"


class StructuredFieldReviewStatus(str, Enum):
    active = "active"
    superseded = "superseded"
    orphaned = "orphaned"


class QaAnswerStatus(str, Enum):
    answered = "answered"
    insufficient_evidence = "insufficient_evidence"


class Document(SQLModel, table=True):
    id: Optional[str] = Field(
        default_factory=lambda: str(uuid.uuid4()), primary_key=True
    )
    filename: str
    content_type: str
    size: int
    storage_path: str
    status: ProcessingStatus = Field(
        default=ProcessingStatus.uploaded,
        sa_column=Column(
            SQLAlchemyEnum(
                ProcessingStatus, native_enum=False, create_constraint=False
            ),
            nullable=False,
        ),
    )
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DocumentProcessingJob(SQLModel, table=True):
    """Durable lifecycle record for one document processing request."""

    __tablename__ = "document_processing_job"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="ck_processing_job_attempt_count"),
        CheckConstraint("max_attempts > 0", name="ck_processing_job_max_attempts"),
        Index(
            "uq_processing_job_active_document",
            "document_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    document_id: str = Field(
        foreign_key="document.id", ondelete="CASCADE", index=True
    )
    status: ProcessingJobStatus = Field(
        default=ProcessingJobStatus.queued,
        sa_column=Column(
            SQLAlchemyEnum(
                ProcessingJobStatus, native_enum=False, create_constraint=False
            ),
            nullable=False,
        ),
    )
    attempt_count: int = 0
    max_attempts: int = 2
    last_error_code: Optional[str] = None
    queued_at: datetime = Field(default_factory=utc_now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=utc_now)


class ProcessingJobResponse(SQLModel):
    id: str
    document_id: str
    status: ProcessingJobStatus
    attempt_count: int
    max_attempts: int
    last_error_code: Optional[str]
    queued_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    updated_at: datetime


class DocumentPage(SQLModel, table=True):
    __tablename__ = "document_page"
    __table_args__ = (
        CheckConstraint("page_number > 0", name="ck_document_page_number_positive"),
    )

    document_id: str = Field(
        foreign_key="document.id", ondelete="CASCADE", primary_key=True
    )
    page_number: int = Field(primary_key=True)
    text: str = Field(sa_column=Column(Text, nullable=False))
    extraction_method: ExtractionMethod = Field(
        sa_column=Column(
            SQLAlchemyEnum(
                ExtractionMethod, native_enum=False, create_constraint=False
            ),
            nullable=False,
        )
    )
    created_at: datetime = Field(default_factory=utc_now)


class DocumentClassification(SQLModel, table=True):
    __tablename__ = "document_classification"

    document_id: str = Field(
        foreign_key="document.id", ondelete="CASCADE", primary_key=True
    )
    predicted_type: DocumentType = Field(
        sa_column=Column(
            SQLAlchemyEnum(DocumentType, native_enum=False, create_constraint=False),
            nullable=False,
        )
    )
    effective_type: DocumentType = Field(
        sa_column=Column(
            SQLAlchemyEnum(DocumentType, native_enum=False, create_constraint=False),
            nullable=False,
        )
    )
    source: ClassificationSource = Field(
        sa_column=Column(
            SQLAlchemyEnum(
                ClassificationSource, native_enum=False, create_constraint=False
            ),
            nullable=False,
        )
    )
    classifier_version: str
    classified_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    reviewed_at: Optional[datetime] = None


class DocumentClassificationReview(SQLModel, table=True):
    __tablename__ = "document_classification_review"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    document_id: str = Field(
        foreign_key="document.id", ondelete="CASCADE", index=True
    )
    previous_type: DocumentType = Field(
        sa_column=Column(
            SQLAlchemyEnum(DocumentType, native_enum=False, create_constraint=False),
            nullable=False,
        )
    )
    corrected_type: DocumentType = Field(
        sa_column=Column(
            SQLAlchemyEnum(DocumentType, native_enum=False, create_constraint=False),
            nullable=False,
        )
    )
    created_at: datetime = Field(default_factory=utc_now)


class ClassificationReviewRequest(SQLModel):
    document_type: DocumentType


class DocumentStructuredExtraction(SQLModel, table=True):
    __tablename__ = "document_structured_extraction"

    document_id: str = Field(
        foreign_key="document.id", ondelete="CASCADE", primary_key=True
    )
    document_type: DocumentType = Field(
        sa_column=Column(
            SQLAlchemyEnum(DocumentType, native_enum=False, create_constraint=False),
            nullable=False,
        )
    )
    status: StructuredExtractionStatus = Field(
        sa_column=Column(
            SQLAlchemyEnum(
                StructuredExtractionStatus,
                native_enum=False,
                create_constraint=False,
            ),
            nullable=False,
        )
    )
    extractor_version: str
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=utc_now)


class DocumentStructuredField(SQLModel, table=True):
    __tablename__ = "document_structured_field"
    __table_args__ = (
        CheckConstraint("page_number > 0", name="ck_structured_field_page_positive"),
        CheckConstraint(
            "value_index >= 0", name="ck_structured_field_value_index_nonnegative"
        ),
    )

    document_id: str = Field(
        foreign_key="document_structured_extraction.document_id",
        ondelete="CASCADE",
        primary_key=True,
    )
    field_name: str = Field(primary_key=True)
    value_index: int = Field(primary_key=True)
    value: str = Field(sa_column=Column(Text, nullable=False))
    page_number: int
    extraction_method: str
    extractor_version: str
    created_at: datetime = Field(default_factory=utc_now)


class DocumentStructuredFieldCorrection(SQLModel, table=True):
    __tablename__ = "document_structured_field_correction"
    __table_args__ = (
        CheckConstraint(
            "value_index >= 0",
            name="ck_structured_field_correction_value_index_nonnegative",
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    document_id: str = Field(
        foreign_key="document_structured_extraction.document_id",
        ondelete="CASCADE",
        index=True,
    )
    field_name: str
    value_index: int
    automatic_value: str = Field(sa_column=Column(Text, nullable=False))
    previous_effective_value: str = Field(sa_column=Column(Text, nullable=False))
    corrected_value: str = Field(sa_column=Column(Text, nullable=False))
    reviewer_id: str
    created_at: datetime = Field(default_factory=utc_now)


class DocumentChunk(SQLModel, table=True):
    __tablename__ = "document_chunk"
    __table_args__ = (
        CheckConstraint("page_number > 0", name="ck_document_chunk_page_positive"),
        CheckConstraint(
            "chunk_index >= 0", name="ck_document_chunk_index_nonnegative"
        ),
        ForeignKeyConstraint(
            ["document_id", "page_number"],
            ["document_page.document_id", "document_page.page_number"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_document_chunk_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    document_id: str = Field(primary_key=True)
    page_number: int = Field(primary_key=True)
    chunk_index: int = Field(primary_key=True)
    text: str = Field(sa_column=Column(Text, nullable=False))
    embedding: list[float] = Field(
        sa_column=Column(Vector(128), nullable=False)
    )
    embedding_model: str
    created_at: datetime = Field(default_factory=utc_now)


class StructuredFieldCorrectionRequest(SQLModel):
    value: str = Field(min_length=1, max_length=2000)
    reviewer_id: str = Field(min_length=1, max_length=100)


class StructuredFieldResponse(SQLModel):
    field_name: str
    value_index: int
    value: str
    effective_value: str
    reviewed: bool = False
    reviewer_id: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    page_number: int
    extraction_method: str
    extractor_version: str


class StructuredExtractionResponse(SQLModel):
    document_id: str
    document_type: DocumentType
    status: StructuredExtractionStatus
    extractor_version: str
    started_at: datetime
    completed_at: Optional[datetime]
    fields: list[StructuredFieldResponse] = Field(default_factory=list)


class StructuredFieldCorrectionResponse(SQLModel):
    id: str
    document_id: str
    field_name: str
    value_index: int
    automatic_value: str
    previous_effective_value: str
    corrected_value: str
    effective_value: Optional[str]
    reviewer_id: str
    created_at: datetime
    status: StructuredFieldReviewStatus


class StructuredFieldReviewHistoryResponse(SQLModel):
    document_id: str
    corrections: list[StructuredFieldCorrectionResponse] = Field(default_factory=list)


class SemanticSearchResult(SQLModel):
    document_id: str
    page_number: int
    chunk_index: int
    text: str
    embedding_model: str
    distance: float


class SemanticSearchResponse(SQLModel):
    query: str
    results: list[SemanticSearchResult] = Field(default_factory=list)


class QaRequest(SQLModel):
    question: str = Field(min_length=1, max_length=500)
    document_ids: Optional[list[str]] = Field(default=None, max_length=20)
    retrieval_limit: int = Field(default=5, ge=1, le=10)


class QaCitation(SQLModel):
    document_id: str
    page_number: int
    chunk_index: int
    source_snippet: str
    distance: float


class QaRetrievalMetadata(SQLModel):
    result_count: int
    retrieval_limit: int
    document_ids: Optional[list[str]]
    embedding_model: str
    results: list[SemanticSearchResult] = Field(default_factory=list)


class QaResponse(SQLModel):
    answer: str
    status: QaAnswerStatus
    citations: list[QaCitation] = Field(default_factory=list)
    retrieval: QaRetrievalMetadata
    answer_provider: str

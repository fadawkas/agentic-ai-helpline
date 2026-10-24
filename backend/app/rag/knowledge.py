import logging
import asyncio
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator
from qdrant_client import AsyncQdrantClient, models

from app.core.config import Settings
from app.rag.chunks import (
    CHUNK_OVERLAP_CHARACTERS,
    MAX_CHUNK_CHARACTERS,
    TextBlock,
    chunk_blocks,
)

logger = logging.getLogger(__name__)
EMBEDDING_BATCH_SIZE = 32
CHUNK_CHARACTERS = MAX_CHUNK_CHARACTERS
CHUNK_OVERLAP = CHUNK_OVERLAP_CHARACTERS
CHUNKING_VERSION = "structure-v2"
DENSE_CANDIDATE_LIMIT = 20
SPARSE_CANDIDATE_LIMIT = 20


KnowledgeCategoryValue = Literal[
    "mental_health_education",
    "emotional_wellbeing",
    "coping_strategy",
    "help_seeking",
    "referral_resource",
]


class KnowledgeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9._-]+$")
    title: str = Field(min_length=1, max_length=240)
    publisher: str = Field(min_length=1, max_length=160)
    source_url: HttpUrl
    language: Literal["id", "en"] = "id"
    category: KnowledgeCategoryValue
    verified_at: date
    verification_status: Literal["VERIFIED"]
    content: str = Field(min_length=1, max_length=200_000)
    region: str | None = Field(default=None, max_length=160)
    contact_details: str | None = Field(default=None, max_length=1000)
    eligibility: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_verified_referral_details(self):
        if not self.content.strip():
            raise ValueError("Knowledge content must not be blank")
        if self.verified_at > date.today():
            raise ValueError("verified_at cannot be in the future")
        if self.category == "referral_resource":
            if not self.region or not self.contact_details:
                raise ValueError(
                    "Verified referral documents require region and contact_details"
                )
        return self


class KnowledgeChunk(BaseModel):
    chunk_id: str = ""
    content_version: str = ""
    document_id: str
    title: str
    publisher: str
    source_url: str
    category: KnowledgeCategoryValue
    verified_at: date
    text: str
    score: float
    section: str = ""
    page: int | None = None
    region: str | None = None
    contact_details: str | None = None
    eligibility: str | None = None


def content_version_for(document: KnowledgeDocument) -> str:
    version_data = document.model_dump(mode="json", exclude={"verification_status"})
    version_data["chunking_version"] = CHUNKING_VERSION
    return hashlib.sha256(
        json.dumps(version_data, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def split_into_chunks(text: str) -> list[str]:
    return [
        chunk.text
        for chunk in chunk_blocks(
            [TextBlock(text)], title="", publisher="", category="mental_health_education"
        )
    ]


class KnowledgeBase:
    def __init__(
        self,
        settings: Settings,
        qdrant: AsyncQdrantClient,
        embeddings_client: AsyncOpenAI | None = None,
        postgres_pool=None,
        reranker_client=None,
        query_rewriter=None,
    ):
        if settings.openrouter_api_key is None:
            raise ValueError("OPENROUTER_API_KEY is required for knowledge embeddings")
        self._settings = settings
        self._qdrant = qdrant
        self._postgres = postgres_pool
        from app.rag.bm25 import BM25Index

        self._bm25 = BM25Index()
        self._pending_chunks: dict[str, list[KnowledgeChunk]] = {}
        self._reranker = reranker_client
        self._query_rewriter = query_rewriter
        if self._query_rewriter is None and settings.rag_query_rewrite_enabled:
            from app.rag.retrieval import QueryTransformer

            self._query_rewriter = QueryTransformer(settings)
        self._embeddings = embeddings_client or AsyncOpenAI(
            api_key=settings.openrouter_api_key.get_secret_value(),
            base_url=settings.openrouter_base_url,
            timeout=30.0,
            max_retries=1,
        )

    async def close(self) -> None:
        await self._embeddings.close()
        if self._query_rewriter is not None:
            await self._query_rewriter.close()
        if self._reranker is not None:
            await self._reranker.close()

    async def initialize(self) -> None:
        collection = self._settings.rag_collection_name
        if await self._qdrant.collection_exists(collection):
            info = await self._qdrant.get_collection(collection)
            vectors = info.config.params.vectors
            size = vectors.size if isinstance(vectors, models.VectorParams) else None
            if size != self._settings.rag_embedding_dimensions:
                raise ValueError(
                    f"Knowledge collection {collection} has incompatible vector dimensions"
                )
        else:
            await self._qdrant.create_collection(
                collection_name=collection,
                vectors_config=models.VectorParams(
                    size=self._settings.rag_embedding_dimensions,
                    distance=models.Distance.COSINE,
                ),
            )
        for field_name, field_schema in (
            ("verification_status", models.PayloadSchemaType.KEYWORD),
            ("category", models.PayloadSchemaType.KEYWORD),
            ("region", models.PayloadSchemaType.KEYWORD),
            ("document_id", models.PayloadSchemaType.KEYWORD),
            ("content_version", models.PayloadSchemaType.KEYWORD),
            ("verified_at_epoch", models.PayloadSchemaType.INTEGER),
        ):
            await self._qdrant.create_payload_index(
                collection_name=collection,
                field_name=field_name,
                field_schema=field_schema,
            )

    async def ingest(
        self, document: KnowledgeDocument, *, blocks: list[TextBlock] | None = None
    ) -> int:
        content_version = content_version_for(document)
        chunks = chunk_blocks(
            blocks or [TextBlock(document.content)],
            title=document.title,
            publisher=document.publisher,
            category=document.category,
            region=document.region,
        )
        if not chunks:
            raise ValueError("Document produced no searchable chunks")
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
            batch = chunks[start : start + EMBEDDING_BATCH_SIZE]
            vectors.extend(await self._embed([f"passage: {chunk.embedding_text}" for chunk in batch]))
        point_ids = [
            str(uuid5(NAMESPACE_URL, f"{document.document_id}:{content_version}:{index}"))
            for index in range(len(chunks))
        ]
        metadata = document.model_dump(mode="json", exclude={"content"})
        metadata["verified_at_epoch"] = int(
            datetime.combine(document.verified_at, datetime.min.time(), tzinfo=timezone.utc).timestamp()
        )
        points = [
            models.PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    **metadata,
                    "chunk_index": index,
                    "text": chunk.text,
                    "section": chunk.section,
                    "page": chunk.page,
                    "chunking_version": CHUNKING_VERSION,
                    "content_version": content_version,
                    "verification_status": "INDEXING",
                },
            )
            for index, (point_id, vector, chunk) in enumerate(zip(point_ids, vectors, chunks))
        ]
        await self._qdrant.upsert(
            collection_name=self._settings.rag_collection_name,
            points=points,
            wait=True,
        )
        self._pending_chunks[document.document_id] = [
            KnowledgeChunk(
                chunk_id=point_id,
                content_version=content_version,
                document_id=document.document_id,
                title=document.title,
                publisher=document.publisher,
                source_url=str(document.source_url),
                category=document.category,
                verified_at=document.verified_at,
                text=chunk.text,
                score=0.0,
                section=chunk.section,
                page=chunk.page,
                region=document.region,
                contact_details=document.contact_details,
                eligibility=document.eligibility,
            )
            for point_id, chunk in zip(point_ids, chunks)
        ]
        return len(points)

    def pending_chunks(self, document_id: str) -> list[KnowledgeChunk]:
        return self._pending_chunks.pop(document_id, [])

    def activate_sparse_document(self, document_id: str, chunks: list[KnowledgeChunk]) -> None:
        self._bm25.replace_document(document_id, chunks)

    def remove_sparse_document(self, document_id: str) -> None:
        self._bm25.remove_document(document_id)

    async def activate_document_version(
        self, document_id: str, content_version: str, previous_version: str | None
    ) -> None:
        document_condition = models.FieldCondition(
            key="document_id", match=models.MatchValue(value=document_id)
        )
        new_version_condition = models.FieldCondition(
            key="content_version", match=models.MatchValue(value=content_version)
        )
        await self._qdrant.set_payload(
            collection_name=self._settings.rag_collection_name,
            payload={"verification_status": "DISABLED"},
            points=models.FilterSelector(
                filter=models.Filter(must=[document_condition], must_not=[new_version_condition])
            ),
            wait=True,
        )
        try:
            await self._qdrant.set_payload(
                collection_name=self._settings.rag_collection_name,
                payload={"verification_status": "VERIFIED"},
                points=models.FilterSelector(
                    filter=models.Filter(must=[document_condition, new_version_condition])
                ),
                wait=True,
            )
        except Exception:
            if previous_version:
                previous_filter = models.Filter(must=[document_condition])
                if previous_version != "legacy":
                    previous_filter.must.append(models.FieldCondition(
                        key="content_version", match=models.MatchValue(value=previous_version)
                    ))
                else:
                    previous_filter.must_not = [new_version_condition]
                await self._qdrant.set_payload(
                    collection_name=self._settings.rag_collection_name,
                    payload={"verification_status": "VERIFIED"},
                    points=models.FilterSelector(filter=previous_filter),
                    wait=True,
                )
            else:
                await self.set_document_active(document_id, False)
            raise

    async def restore_document_version(
        self, document_id: str, previous_version: str | None, failed_version: str
    ) -> None:
        document_condition = models.FieldCondition(
            key="document_id", match=models.MatchValue(value=document_id)
        )
        failed_condition = models.FieldCondition(
            key="content_version", match=models.MatchValue(value=failed_version)
        )
        await self._qdrant.set_payload(
            collection_name=self._settings.rag_collection_name,
            payload={"verification_status": "DISABLED"},
            points=models.FilterSelector(
                filter=models.Filter(must=[document_condition, failed_condition])
            ),
            wait=True,
        )
        if previous_version is None:
            return
        previous_filter = models.Filter(must=[document_condition])
        if previous_version != "legacy":
            previous_filter.must.append(models.FieldCondition(
                key="content_version", match=models.MatchValue(value=previous_version)
            ))
        else:
            previous_filter.must_not = [failed_condition]
        await self._qdrant.set_payload(
            collection_name=self._settings.rag_collection_name,
            payload={"verification_status": "VERIFIED"},
            points=models.FilterSelector(filter=previous_filter),
            wait=True,
        )

    async def delete_other_versions(self, document_id: str, content_version: str) -> None:
        await self._qdrant.delete(
            collection_name=self._settings.rag_collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[models.FieldCondition(
                        key="document_id", match=models.MatchValue(value=document_id)
                    )],
                    must_not=[models.FieldCondition(
                        key="content_version", match=models.MatchValue(value=content_version)
                    )],
                )
            ),
            wait=True,
        )

    async def load_sparse_index(self) -> None:
        if self._postgres is None:
            return
        rows = await self._postgres.fetch(
            "SELECT c.chunk_id,c.document_id,c.title,c.publisher,c.source_url,c.category,"
            "c.verified_at,c.text,c.region,c.contact_details,c.eligibility,c.section,c.page,c.content_version "
            "FROM knowledge_chunks c JOIN knowledge_documents d USING(document_id) "
            "WHERE d.status!='DISABLED' AND d.active_content_version=c.content_version "
            "AND d.chunking_version=$1",
            CHUNKING_VERSION,
        )
        self._bm25.replace_all([KnowledgeChunk(**dict(row), score=0.0) for row in rows])

    async def delete_document(self, document_id: str) -> None:
        await self._qdrant.delete(
            collection_name=self._settings.rag_collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[models.FieldCondition(
                        key="document_id", match=models.MatchValue(value=document_id)
                    )]
                )
            ),
            wait=True,
        )

    async def set_document_active(self, document_id: str, active: bool) -> None:
        await self._qdrant.set_payload(
            collection_name=self._settings.rag_collection_name,
            payload={"verification_status": "VERIFIED" if active else "DISABLED"},
            points=models.FilterSelector(
                filter=models.Filter(
                    must=[models.FieldCondition(
                        key="document_id", match=models.MatchValue(value=document_id)
                    )]
                )
            ),
            wait=True,
        )

    async def search(
        self,
        query: str,
        *,
        categories: list[KnowledgeCategoryValue] | None = None,
        region: str | None = None,
        limit: int | None = None,
        minimum_rerank_score: float | None = None,
    ) -> list[KnowledgeChunk]:
        from app.rag.retrieval import MAX_REWRITE_QUERIES, reciprocal_rank_fusion

        final_limit = limit or self._settings.rag_max_results
        search_queries = [query]
        if self._query_rewriter is not None:
            try:
                rewrite = await self._query_rewriter.transform(query)
                rewritten = rewrite.search_query.strip()
                if rewritten and rewritten.casefold() != query.casefold():
                    exact_terms = " ".join(rewrite.exact_terms)
                    search_queries.append(f"{rewritten} {exact_terms}".strip())
            except Exception as error:
                logger.warning("RAG query rewrite failed; using original query: %s", type(error).__name__)
        search_queries = list(dict.fromkeys(q for q in search_queries if q))[:MAX_REWRITE_QUERIES]
        vectors = await self._embed([f"query: {search_query}" for search_query in search_queries])
        conditions = [
            models.FieldCondition(
                key="verification_status", match=models.MatchValue(value="VERIFIED")
            )
        ]
        if categories:
            conditions.append(
                models.FieldCondition(
                    key="category",
                    match=models.MatchAny(any=categories),
                )
            )
        if region:
            conditions.append(
                models.FieldCondition(
                    key="region",
                    match=models.MatchAny(any=[region, "Nasional", "Indonesia"]),
                )
            )
        if categories and "referral_resource" in categories:
            one_year_ago = int(
                datetime.combine(
                    date.today() - timedelta(days=365),
                    datetime.min.time(),
                    tzinfo=timezone.utc,
                ).timestamp()
            )
            conditions.append(
                models.FieldCondition(
                    key="verified_at_epoch",
                    range=models.Range(gte=one_year_ago),
                )
            )
        else:
            # General searches may match referrals too; exclude stale referral records.
            one_year_ago = int(
                datetime.combine(
                    date.today() - timedelta(days=365),
                    datetime.min.time(),
                    tzinfo=timezone.utc,
                ).timestamp()
            )
            conditions.append(
                models.Filter(
                    should=[
                        models.FieldCondition(
                            key="category",
                            match=models.MatchExcept(**{"except": ["referral_resource"]}),
                        ),
                        models.Filter(
                            must=[
                                models.FieldCondition(
                                    key="category",
                                    match=models.MatchValue(value="referral_resource"),
                                ),
                                models.FieldCondition(
                                    key="verified_at_epoch",
                                    range=models.Range(gte=one_year_ago),
                                ),
                            ]
                        ),
                    ]
                )
            )
        async def dense_search(vector: list[float]) -> list[KnowledgeChunk]:
            response = await self._qdrant.query_points(
                collection_name=self._settings.rag_collection_name,
                query=vector,
                query_filter=models.Filter(must=conditions),
                limit=DENSE_CANDIDATE_LIMIT,
                score_threshold=self._settings.rag_min_similarity,
                with_payload=True,
            )
            return self._chunks_from_points(response.points)

        dense_rankings = await asyncio.gather(*(dense_search(vector) for vector in vectors))
        sparse_rankings = [
            self._bm25.search(
                search_query,
                categories=categories,
                region=region,
                limit=SPARSE_CANDIDATE_LIMIT,
            )
            for search_query in search_queries
        ]
        fused = reciprocal_rank_fusion(
            [*dense_rankings, *sparse_rankings], limit=DENSE_CANDIDATE_LIMIT
        )
        if fused and self._postgres is not None:
            document_ids = list({chunk.document_id for chunk in fused})
            rows = await self._postgres.fetch(
                "SELECT document_id,active_content_version FROM knowledge_documents "
                "WHERE document_id=ANY($1::text[]) AND status!='DISABLED' "
                "AND active_content_version IS NOT NULL",
                document_ids,
            )
            active_versions = {row["document_id"]: row["active_content_version"] for row in rows}
            fused = [
                chunk for chunk in fused
                if active_versions.get(chunk.document_id) == chunk.content_version
            ]
        if not fused:
            return []
        if self._reranker is None:
            from app.rag.retrieval import CohereReranker

            self._reranker = CohereReranker(self._settings)
        reranked = await self._reranker.rerank(
            query,
            fused,
            limit=final_limit,
        )
        gate = (
            self._settings.rag_rerank_min_score
            if minimum_rerank_score is None
            else minimum_rerank_score
        )
        return [chunk for chunk in reranked if chunk.score >= gate]

    @staticmethod
    def _chunks_from_points(points) -> list[KnowledgeChunk]:
        results = []
        for point in points:
            payload = point.payload or {}
            if payload.get("verification_status") != "VERIFIED":
                continue
            results.append(KnowledgeChunk(
                chunk_id=str(point.id),
                content_version=payload.get("content_version", "legacy"),
                document_id=payload["document_id"],
                title=payload["title"],
                publisher=payload["publisher"],
                source_url=payload["source_url"],
                category=payload["category"],
                verified_at=payload["verified_at"],
                text=payload["text"],
                score=point.score,
                region=payload.get("region"),
                contact_details=payload.get("contact_details"),
                eligibility=payload.get("eligibility"),
                section=payload.get("section", ""),
                page=payload.get("page"),
            ))
        return results

    async def _embed(self, inputs: list[str]) -> list[list[float]]:
        vectors: list[list[float] | None] = [None] * len(inputs)
        for start in range(0, len(inputs), EMBEDDING_BATCH_SIZE):
            batch = inputs[start : start + EMBEDDING_BATCH_SIZE]
            response = await self._embeddings.embeddings.create(
                model=self._settings.rag_embedding_model,
                input=batch,
            )
            for item in response.data:
                vector = [float(value) for value in item.embedding]
                if len(vector) != self._settings.rag_embedding_dimensions:
                    raise ValueError("Embedding provider returned an incompatible vector size")
                if not all(value == value and abs(value) != float("inf") for value in vector):
                    raise ValueError("Embedding provider returned non-finite vector values")
                vectors[start + item.index] = vector
        if any(vector is None for vector in vectors):
            raise ValueError("Embedding provider returned an incomplete batch")
        return [vector for vector in vectors if vector is not None]

    async def _delete_obsolete_chunks(self, document_id: str, retained_ids: set[str]) -> None:
        offset = None
        obsolete_ids: list[str] = []
        while True:
            points, offset = await self._qdrant.scroll(
                collection_name=self._settings.rag_collection_name,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id", match=models.MatchValue(value=document_id)
                        )
                    ]
                ),
                limit=256,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            obsolete_ids.extend(str(point.id) for point in points if str(point.id) not in retained_ids)
            if offset is None:
                break
        if obsolete_ids:
            await self._qdrant.delete(
                collection_name=self._settings.rag_collection_name,
                points_selector=models.PointIdsList(points=obsolete_ids),
                wait=True,
            )

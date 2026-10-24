import json
from typing import Any

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.rag.knowledge import KnowledgeChunk

MAX_REWRITE_QUERIES = 2
MAX_RERANK_DOCUMENTS = 24
RRF_K = 60


class QueryRewrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search_query: str = Field(min_length=2, max_length=1200)
    exact_terms: list[str] = Field(max_length=12)


class QueryTransformer:
    def __init__(self, settings: Settings, client: Any | None = None):
        if not settings.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is required for query rewriting")
        self._client = client or AsyncOpenAI(
            api_key=settings.openrouter_api_key.get_secret_value(),
            base_url=settings.openrouter_base_url,
            timeout=4.0,
            max_retries=0,
        )
        self._model = settings.llm_classifier_model

    async def close(self) -> None:
        await self._client.close()

    async def transform(self, query: str) -> QueryRewrite:
        completion = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Rewrite this one Indonesian knowledge-search question as a concise retrieval query. "
                        "Preserve all names, acronyms, numbers, negations, and explicit constraints. Do not "
                        "invent a location, date, category, or user fact. Return the original exact terms too. "
                        "Do not answer the question."
                    ),
                },
                {"role": "user", "content": query},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "knowledge_query_rewrite",
                    "strict": True,
                    "schema": QueryRewrite.model_json_schema(),
                },
            },
            temperature=0,
            max_tokens=160,
            extra_body={"reasoning": {"effort": "none"}},
        )
        content = completion.choices[0].message.content
        if not content:
            raise ValueError("Query rewrite returned no content")
        return QueryRewrite.model_validate_json(content)


class CohereReranker:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        if not settings.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is required for reranking")
        self._url = f"{settings.openrouter_base_url.rstrip('/')}/rerank"
        self._api_key = settings.openrouter_api_key.get_secret_value()
        self._model = settings.rag_rerank_model
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(4.0))
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def rerank(self, query: str, chunks: list[KnowledgeChunk], *, limit: int) -> list[KnowledgeChunk]:
        if not chunks:
            return []
        candidates = chunks[:MAX_RERANK_DOCUMENTS]
        response = await self._client.post(
            self._url,
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            json={
                "model": self._model,
                "query": query,
                "documents": [self._document_text(chunk) for chunk in candidates],
                "top_n": min(limit, len(candidates)),
            },
        )
        response.raise_for_status()
        body = response.json()
        ranked: list[KnowledgeChunk] = []
        for result in body.get("results", []):
            index = result.get("index")
            score = result.get("relevance_score")
            if not isinstance(index, int) or not 0 <= index < len(candidates):
                raise ValueError("Reranker returned an invalid candidate index")
            if not isinstance(score, (float, int)):
                raise ValueError("Reranker returned an invalid score")
            ranked.append(candidates[index].model_copy(update={"score": float(score)}))
        if not ranked:
            raise ValueError("Reranker returned no ranked candidates")
        return ranked

    @staticmethod
    def _document_text(chunk: KnowledgeChunk) -> str:
        section = f" Section: {chunk.section}." if chunk.section else ""
        region = f" Region: {chunk.region}." if chunk.region else ""
        return (
            f"Title: {chunk.title}.{section} Category: {chunk.category}."
            f"{region} Content: {chunk.text}"
        )


def reciprocal_rank_fusion(
    rankings: list[list[KnowledgeChunk]], *, limit: int, k: int = RRF_K
) -> list[KnowledgeChunk]:
    scores: dict[str, float] = {}
    candidates: dict[str, KnowledgeChunk] = {}
    for ranking in rankings:
        seen: set[str] = set()
        for rank, chunk in enumerate(ranking, start=1):
            chunk_id = chunk.chunk_id or f"{chunk.document_id}:{chunk.text[:48]}"
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            candidates[chunk_id] = chunk
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    ordered = sorted(scores, key=scores.__getitem__, reverse=True)[:limit]
    return [candidates[chunk_id].model_copy(update={"score": scores[chunk_id]}) for chunk_id in ordered]

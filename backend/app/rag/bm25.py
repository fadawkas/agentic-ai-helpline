import math
import re
from collections import Counter
from datetime import date, timedelta

from app.rag.knowledge import KnowledgeChunk, KnowledgeCategoryValue

TOKEN_PATTERN = re.compile(r"[\w]+", re.UNICODE)
BM25_K1 = 1.5
BM25_B = 0.75


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.casefold())


class BM25Index:
    """Small, in-memory CPU BM25 index over active curated chunks."""

    def __init__(self) -> None:
        self._chunks: list[KnowledgeChunk] = []
        self._tokens: list[list[str]] = []
        self._term_frequencies: list[Counter[str]] = []
        self._document_frequencies: Counter[str] = Counter()
        self._average_length = 0.0

    def replace_document(self, document_id: str, chunks: list[KnowledgeChunk]) -> None:
        retained = [chunk for chunk in self._chunks if chunk.document_id != document_id]
        self._chunks = [*retained, *chunks]
        self._rebuild()

    def replace_all(self, chunks: list[KnowledgeChunk]) -> None:
        self._chunks = list(chunks)
        self._rebuild()

    def remove_document(self, document_id: str) -> None:
        self._chunks = [chunk for chunk in self._chunks if chunk.document_id != document_id]
        self._rebuild()

    def search(
        self,
        query: str,
        *,
        categories: list[KnowledgeCategoryValue] | None,
        region: str | None,
        limit: int,
        max_referral_age_days: int = 365,
    ) -> list[KnowledgeChunk]:
        query_terms = set(tokenize(query))
        if not query_terms or not self._chunks:
            return []
        scored: list[tuple[float, int]] = []
        total = len(self._chunks)
        for index, (chunk, frequencies, tokens) in enumerate(
            zip(self._chunks, self._term_frequencies, self._tokens)
        ):
            if categories and chunk.category not in categories:
                continue
            if region and not self._region_matches(chunk.region, region):
                continue
            if chunk.category == "referral_resource" and (
                date.today() - chunk.verified_at
            ).days > max_referral_age_days:
                continue
            length = len(tokens)
            score = 0.0
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                document_frequency = self._document_frequencies[term]
                inverse_frequency = math.log1p(
                    (total - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                normalization = frequency + BM25_K1 * (
                    1 - BM25_B + BM25_B * length / max(self._average_length, 1.0)
                )
                score += inverse_frequency * frequency * (BM25_K1 + 1) / normalization
            if score > 0:
                scored.append((score, index))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            self._chunks[index].model_copy(update={"score": score})
            for score, index in scored[:limit]
        ]

    @staticmethod
    def _region_matches(document_region: str | None, requested_region: str) -> bool:
        if not document_region:
            return False
        if document_region.casefold().strip() in {"nasional", "indonesia"}:
            return True
        return document_region.casefold().strip() == requested_region.casefold().strip()

    def _rebuild(self) -> None:
        self._tokens = [tokenize(f"{chunk.title} {chunk.section or ''} {chunk.text}") for chunk in self._chunks]
        self._term_frequencies = [Counter(tokens) for tokens in self._tokens]
        self._document_frequencies = Counter(
            term for frequencies in self._term_frequencies for term in frequencies
        )
        self._average_length = (
            sum(map(len, self._tokens)) / len(self._tokens) if self._tokens else 0.0
        )

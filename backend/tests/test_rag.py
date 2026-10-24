import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from pathlib import Path

import pytest
import httpx
from pydantic import SecretStr, ValidationError
from qdrant_client import models

from app.core.config import Settings
from app.rag.knowledge import (
    KnowledgeBase,
    KnowledgeDocument,
    split_into_chunks,
)
from app.rag.tools import KnowledgeTools
from app.rag.evaluate import ranking_metrics, summarize_evaluation
from app.rag.bm25 import BM25Index
from app.rag.chunks import MAX_CHUNK_CHARACTERS, TextBlock, chunk_blocks
from app.rag.retrieval import CohereReranker, reciprocal_rank_fusion
from app.rag.validator import (
    DocumentAssessment,
    DocumentValidator,
    _quoted_evidence_matches,
    publisher_for_url,
)
from app.rag.management import (
    check_password,
    create_session_token,
    extract_document_text,
    password_hash,
    valid_session_token,
)
from app.rag.extraction import MIN_PAGE_CHARACTERS, _paragraph_blocks, deserialize_blocks, serialize_blocks


def rag_settings() -> Settings:
    return Settings(
        postgres_password=SecretStr("postgres"),
        asterisk_ari_username="ari-user",
        asterisk_ari_password=SecretStr("ari-password"),
        openrouter_api_key=SecretStr("openrouter"),
        rag_query_rewrite_enabled=False,
    )


def document(**overrides) -> KnowledgeDocument:
    values = {
        "document_id": "coping-guide-v1",
        "title": "Panduan dukungan",
        "publisher": "Organisasi ditinjau",
        "source_url": "https://example.org/guide",
        "language": "id",
        "category": "coping_strategy",
        "verified_at": date.today().isoformat(),
        "verification_status": "VERIFIED",
        "content": "Tarik napas perlahan dan perhatikan lingkungan sekitar." * 20,
    }
    values.update(overrides)
    return KnowledgeDocument.model_validate(values)


class FakeEmbeddingClient:
    def __init__(self):
        self.inputs = []
        self.embeddings = SimpleNamespace(create=self.create)

    async def create(self, *, model, input):
        self.inputs.extend(input)
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=index, embedding=[float(index + 1)] * 1024)
                for index in range(len(input))
            ]
        )

    async def close(self):
        pass


class FakeQdrant:
    def __init__(self):
        self.upserted = []
        self.deleted = []
        self.scroll_records = []
        self.query_args = None

    async def upsert(self, **kwargs):
        self.upserted.extend(kwargs["points"])

    async def scroll(self, **kwargs):
        records, self.scroll_records = self.scroll_records, []
        return records, None

    async def delete(self, **kwargs):
        self.deleted.extend(kwargs["points_selector"].points)

    async def query_points(self, **kwargs):
        self.query_args = kwargs
        return SimpleNamespace(points=[])


def test_chunking_is_bounded_and_overlaps_adjacent_segments() -> None:
    text = "kata " * 900

    chunks = split_into_chunks(text)

    assert len(chunks) > 1
    assert all(len(chunk) <= MAX_CHUNK_CHARACTERS for chunk in chunks)
    assert chunks[0][-80:] in chunks[1]


def test_structure_aware_chunks_keep_headings_overlap_and_source_metadata() -> None:
    blocks = [
        TextBlock("Panduan koping", section="Panduan koping", kind="heading"),
        TextBlock("Latihan grounding membantu memperhatikan keadaan sekarang. " * 36, section="Panduan koping", page=4),
        TextBlock("Latihan berikutnya menjaga rutinitas harian.", section="Panduan koping", page=4),
    ]

    chunks = chunk_blocks(
        blocks, title="Panduan", publisher="WHO", category="coping_strategy", region="Indonesia"
    )

    assert len(chunks) > 1
    assert all(len(chunk.text) <= MAX_CHUNK_CHARACTERS for chunk in chunks)
    assert all(chunk.section == "Panduan koping" for chunk in chunks)
    assert all("Region: Indonesia" in chunk.embedding_text for chunk in chunks)
    assert chunks[0].text[-80:] in chunks[1].text


def test_extraction_blocks_preserve_page_and_heading_order_on_roundtrip() -> None:
    blocks = _paragraph_blocks("HEADING\n\nIsi halaman dua.", 2, "")
    restored = deserialize_blocks(serialize_blocks(blocks))

    assert [block.page for block in restored] == [2, 2]
    assert restored[0].kind == "heading"
    assert restored[1].section == "HEADING"
    assert MIN_PAGE_CHARACTERS == 40


def test_cpu_bm25_finds_exact_terms_and_observes_region_category_filters() -> None:
    from app.rag.knowledge import KnowledgeChunk

    chunks = [
        KnowledgeChunk(
            chunk_id="a", document_id="a", title="Layanan XYZ-119", publisher="WHO",
            source_url="https://who.int", category="help_seeking", verified_at=date.today(),
            text="Akses layanan XYZ-119 di Jakarta", score=0, region="DKI Jakarta",
        ),
        KnowledgeChunk(
            chunk_id="b", document_id="b", title="Panduan umum", publisher="WHO",
            source_url="https://who.int", category="coping_strategy", verified_at=date.today(),
            text="Latihan mengelola stres", score=0, region="Nasional",
        ),
    ]
    index = BM25Index()
    index.replace_all(chunks)

    found = index.search("XYZ-119", categories=["help_seeking"], region="DKI Jakarta", limit=5)

    assert [item.document_id for item in found] == ["a"]
    assert found[0].score > 0


def test_reciprocal_rank_fusion_combines_dense_and_sparse_results() -> None:
    from app.rag.knowledge import KnowledgeChunk

    def chunk(document_id: str) -> KnowledgeChunk:
        return KnowledgeChunk(
            chunk_id=document_id, document_id=document_id, title=document_id, publisher="WHO",
            source_url="https://who.int", category="coping_strategy", verified_at=date.today(),
            text=document_id, score=0,
        )

    fused = reciprocal_rank_fusion([[chunk("a"), chunk("b")], [chunk("b"), chunk("a")]], limit=2)

    assert [item.document_id for item in fused] == ["a", "b"]


@pytest.mark.asyncio
async def test_cohere_reranker_uses_openrouter_response_order() -> None:
    from app.rag.knowledge import KnowledgeChunk

    def response(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "cohere/rerank-4-fast"
        return httpx.Response(200, json={"results": [
            {"index": 1, "relevance_score": 0.91},
            {"index": 0, "relevance_score": 0.42},
        ]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(response))
    reranker = CohereReranker(rag_settings(), client=client)
    items = [
        KnowledgeChunk(
            chunk_id=doc, document_id=doc, title=doc, publisher="WHO", source_url="https://who.int",
            category="coping_strategy", verified_at=date.today(), text=doc, score=0,
        )
        for doc in ["weak", "strong"]
    ]

    ranked = await reranker.rerank("query", items, limit=2)

    assert [item.document_id for item in ranked] == ["strong", "weak"]
    assert [item.score for item in ranked] == [0.91, 0.42]
    await client.aclose()


def test_referral_records_require_reviewed_region_and_contacts() -> None:
    with pytest.raises(ValidationError, match="region and contact_details"):
        document(category="referral_resource")

    referral = document(
        category="referral_resource",
        region="Jawa Barat",
        contact_details="Kontak sumber resmi",
    )
    assert referral.verification_status == "VERIFIED"


def test_admin_credentials_are_hashed_and_session_tokens_are_signed() -> None:
    encoded = password_hash("a-long-admin-password")
    token = create_session_token("test-session-secret")

    assert encoded != "a-long-admin-password"
    assert check_password("a-long-admin-password", encoded)
    assert not check_password("wrong-password", encoded)
    assert valid_session_token("test-session-secret", token)
    assert not valid_session_token("different-secret", token)
    assert not valid_session_token("test-session-secret", "invalid")


def test_downloaded_baseline_source_and_seed_records_are_present() -> None:
    knowledge_dir = Path(__file__).parents[1] / "knowledge"
    extracted = extract_document_text(
        knowledge_dir / "WHO-Doing-What-Matters-in-Times-of-Stress.pdf"
    )
    baseline = json.loads((knowledge_dir / "baseline.json").read_text(encoding="utf-8"))

    assert len(extracted) > 1000
    assert len(baseline) >= 3
    assert all(document["verification_status"] == "VERIFIED" for document in baseline)


def test_retrieval_evaluation_reports_ranking_and_no_answer_metrics() -> None:
    metrics = ranking_metrics(["wrong", "right", "right"], ["right"], 4)
    report = summarize_evaluation([
        {"relevant_document_ids": ["right"], "retrieved_document_ids": ["wrong"], "metrics": metrics},
        {"relevant_document_ids": [], "retrieved_document_ids": [], "metrics": ranking_metrics([], [], 4)},
    ], 4)

    assert metrics["precision@4"] == 0.25
    assert metrics["recall@4"] == 1.0
    assert metrics["mrr@4"] == 0.5
    assert report["metrics"]["no_answer_accuracy"] == 1.0

    judged = summarize_evaluation([
        {
            "relevant_document_ids": ["right"], "retrieved_document_ids": ["right"],
            "metrics": ranking_metrics(["right"], ["right"], 4),
            "judge": {"context_relevance": 1.0, "faithfulness": 0.9,
                      "answer_correctness": 1.0, "correctness_available": True,
                      "abstained_appropriately": False},
        },
        {
            "relevant_document_ids": [], "retrieved_document_ids": [],
            "metrics": ranking_metrics([], [], 4),
            "judge": {"context_relevance": 0.0, "faithfulness": 1.0,
                      "answer_correctness": 0.0, "correctness_available": False,
                      "abstained_appropriately": True},
        },
    ], 4)

    assert judged["metrics"]["mean_faithfulness"] == 0.95
    assert judged["metrics"]["mean_answer_correctness"] == 1.0
    assert judged["metrics"]["appropriate_abstention_rate"] == 1.0


def test_validator_only_accepts_allowlisted_publishers_and_exact_publisher_name() -> None:
    assert publisher_for_url("https://www.who.int/publications/guide") == "World Health Organization"
    assert publisher_for_url("https://notwho.int/publications/guide") is None
    assert publisher_for_url("http://www.who.int/publications/guide") is None
    assert _quoted_evidence_matches(
        "Part 1: Grounding ... Refocus on the world around you.",
        "Part 1: Grounding begins here. Refocus on the world around you.",
    )
    assert _quoted_evidence_matches(
        "Stress can be due to major threats… \"Stress\" means feeling troubled or threatened by life.",
        "Stress can be due to major threats… “Stress” means feeling troubled or threatened by life.",
    )
    assert not _quoted_evidence_matches("Invented evidence ... made up sentence", "Real official text only")


@pytest.mark.asyncio
async def test_official_document_validation_requires_supported_assessment() -> None:
    class FakeValidatorClient:
        def __init__(self):
            assessment = DocumentAssessment(
                scope="IN_SCOPE", source_correspondence="SUPPORTED",
                category="coping_strategy", findings=[], summary="Didukung sumber resmi.",
                supporting_evidence=[{
                    "document_excerpt": ("Tarik napas perlahan dan perhatikan lingkungan sekitar." * 2)[:80],
                    "source_excerpt": "Bukti resmi " * 2,
                    "supported_claim": "Latihan perhatian sederhana membantu menghadapi stres.",
                }],
            )
            response = SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=assessment.model_dump_json()))]
            )
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(return_value=response))
            )

        async def close(self):
            pass

    client = FakeValidatorClient()
    validator = DocumentValidator(rag_settings(), client=client)
    valid = document(
        publisher="World Health Organization",
        source_url="https://www.who.int/publications/i/item/guide",
    )
    unsupported = document(source_url="https://notwho.int/publications/guide")

    decision = await validator.validate(valid, source_evidence="Bukti resmi " * 40, source_sha256="abc")
    rejected_source = await validator.validate(unsupported, source_evidence="Bukti resmi " * 40)

    assert decision.outcome == "PASS"
    assert decision.reason_codes == []
    assert rejected_source.outcome == "UNVERIFIABLE"
    assert rejected_source.reason_codes == ["SOURCE_NOT_ALLOWLISTED"]
    client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingestion_uses_passage_embeddings_and_stable_chunk_ids() -> None:
    qdrant = FakeQdrant()
    embedder = FakeEmbeddingClient()
    knowledge = KnowledgeBase(rag_settings(), qdrant, embeddings_client=embedder)

    count = await knowledge.ingest(document())

    assert count == len(qdrant.upserted) > 0
    assert embedder.inputs[0].startswith("passage: ")
    assert len(qdrant.upserted[0].vector) == 1024
    assert qdrant.upserted[0].payload["verification_status"] == "INDEXING"
    assert qdrant.upserted[0].payload["source_url"] == "https://example.org/guide"


@pytest.mark.asyncio
async def test_search_uses_query_prefix_and_verified_category_filters() -> None:
    qdrant = FakeQdrant()
    embedder = FakeEmbeddingClient()
    knowledge = KnowledgeBase(rag_settings(), qdrant, embeddings_client=embedder)

    results = await knowledge.search(
        "dukungan untuk menenangkan pikiran",
        categories=["coping_strategy"],
    )

    assert results == []
    assert embedder.inputs == ["query: dukungan untuk menenangkan pikiran"]
    filters = qdrant.query_args["query_filter"].must
    assert [(condition.key) for condition in filters[:2]] == [
        "verification_status",
        "category",
    ]
    assert filters[2].should[0].match.except_ == ["referral_resource"]
    assert qdrant.query_args["limit"] == 20


class FakeKnowledge:
    def __init__(self, results=None):
        self.results = results or []
        self.search = AsyncMock(return_value=self.results)


def tool_params(arguments, text="", *, function_name="get_mental_health_information"):
    from app.rag.tools import (
        KnowledgeTools,
        _EDUCATION_CATEGORIES,
    )
    from pipecat.processors.aggregators.llm_context import LLMContext

    class Callback:
        def __init__(self):
            self.calls = []

        async def __call__(self, result, *, properties=None):
            self.calls.append((result, properties))

    callback = Callback()
    context = LLMContext()
    if text:
        context.add_message({"role": "user", "content": text})
    return SimpleNamespace(
        arguments=arguments,
        context=context,
        result_callback=callback,
        callback=callback,
        function_name=function_name,
    )


@pytest.mark.asyncio
async def test_knowledge_tool_validates_and_returns_empty_as_no_verified_source() -> None:
    knowledge = FakeKnowledge()
    tools = KnowledgeTools(knowledge)
    params = tool_params({"query": "coping"})

    await tools.get_mental_health_information(params)

    assert params.callback.calls[0][0] == {"status": "no_verified_sources", "results": []}
    knowledge.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_knowledge_tool_prioritizes_safety_without_searching() -> None:
    knowledge = FakeKnowledge()
    tools = KnowledgeTools(knowledge)
    params = tool_params(
        {"query": "strategi dukungan"},
        "Saya akan bunuh diri sekarang.",
    )

    await tools.get_mental_health_information(params)

    knowledge.search.assert_not_awaited()
    assert params.callback.calls[0][0]["status"] == "safety_priority"


@pytest.mark.asyncio
async def test_knowledge_lookup_acknowledges_only_when_search_exceeds_delay() -> None:
    import asyncio

    from app.rag.tools import KnowledgeTools

    class SlowKnowledge(FakeKnowledge):
        def __init__(self):
            self.results = []

        async def search(self, *args, **kwargs):
            await asyncio.sleep(0.02)
            return []

    playback = SimpleNamespace(speak_acknowledgment=AsyncMock())
    tools = KnowledgeTools(
        SlowKnowledge(), tts=object(), playback=playback
    )
    tools.ACKNOWLEDGMENT_DELAY_SECONDS = 0.001
    params = tool_params({"query": "cara menghadapi stres"}, "Saya ingin tahu cara menghadapi stres.")

    await tools.get_mental_health_information(params)

    playback.speak_acknowledgment.assert_awaited_once_with(
        tools._tts, tools.ACKNOWLEDGMENT, timeout=5.0
    )
    assert params.callback.calls[0][0]["status"] == "no_verified_sources"


@pytest.mark.asyncio
async def test_fast_knowledge_lookup_does_not_play_acknowledgment() -> None:
    from app.rag.tools import KnowledgeTools

    playback = SimpleNamespace(speak_acknowledgment=AsyncMock())
    tools = KnowledgeTools(FakeKnowledge(), tts=object(), playback=playback)
    tools.ACKNOWLEDGMENT_DELAY_SECONDS = 1.0
    params = tool_params({"query": "cara menghadapi stres"}, "Saya ingin tahu cara menghadapi stres.")

    await tools.get_mental_health_information(params)

    playback.speak_acknowledgment.assert_not_awaited()


def test_knowledge_response_guidance_supports_synthesis_instead_of_reading_sources() -> None:
    from app.voice.pipeline import SYSTEM_INSTRUCTIONS
    from app.agent.jev import AgentPersonality, personality_instruction

    assert "bukan mesin faq" in SYSTEM_INSTRUCTIONS.casefold()
    assert "jangan membacakan kutipan" in SYSTEM_INSTRUCTIONS.casefold()
    assert "jangan membacakan kutipan" in personality_instruction(
        AgentPersonality.GENTLE_GUIDE
    ).casefold()

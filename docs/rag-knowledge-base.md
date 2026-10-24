# Curated RAG knowledge base

## Design

- Qdrant stores dense vectors and reviewed source payloads in `voice_support_knowledge_v1`; PostgreSQL persists structure-aware chunks for CPU BM25.
- Embeddings use OpenRouter's `intfloat/multilingual-e5-large`, a multilingual 1,024-dimension model. Its model card specifies `passage: ` prefixes for documents and `query: ` prefixes for search queries. OpenRouter currently lists it at $0.01 per million input tokens; verify current pricing before production use.
- Admin ingestion is managed from the authenticated dashboard. PostgreSQL stores document records, validation reports, structured chunks, and ingestion status; a private Docker named volume stores uploaded source files. Re-ingestion uses stable dense chunk IDs and replaces BM25 rows after successful Qdrant upsert.
- Only records that passed the official-source document validator are indexed with `verification_status: "VERIFIED"`. Referral records require region and source-supported contact details and are retrieved only when verified within the last 365 days.
- Retrieval rewrites only the search question (preserving exact terms), runs dense Qdrant and CPU BM25 concurrently over the original and rewritten queries, fuses rankings with reciprocal-rank fusion, then calls OpenRouter Cohere `cohere/rerank-4-fast`. The initial `RAG_RERANK_MIN_SCORE=0.4` came from the small provisional dev set; it is not calibrated for production. Results below it are withheld. Reranker failures fail closed; tools return an unavailable result rather than silently falling back to unranked evidence.
- CPU BM25 is maintained in memory from active PostgreSQL chunks at startup and updated after each successful index. It uses case-folded Unicode word tokens and Okapi BM25 parameters; category, region, active status, and referral freshness filters apply before scoring. Dense and BM25 candidates are deduplicated and capped before reranking.
- Search returns a bounded set of relevant excerpts and source citations. The final reranker threshold is a starting value, not calibrated confidence. No suitable result returns `no_verified_sources`; the agent must not fill gaps from model memory.
- `backend/knowledge/baseline.json` contains a small Indonesian baseline derived from the downloaded WHO stress guide. `baseline-manifest.json` records the landing page, download URL, date, license, and SHA-256. The backend seeds these records idempotently when the embedding provider is configured.
- Never ingest caller audio, transcripts, or private conversations.

## Document format

Create a JSON array with records shaped like:

```json
{
  "document_id": "stable-source-id-v1",
  "title": "Reviewed source title",
  "publisher": "Source publisher",
  "source_url": "https://publisher.example/reviewed-page",
  "language": "id",
  "category": "coping_strategy",
  "verified_at": "2026-10-23",
  "verification_status": "VERIFIED",
  "content": "Reviewed excerpt or authored summary with source support."
}
```

Categories: `mental_health_education`, `emotional_wellbeing`, `coping_strategy`, `help_seeking`, `referral_resource`. Referral records also require `region` and `contact_details`; include eligibility and access conditions in the content/metadata when verified. `verified_at` must not be in the future.

## Admin dashboard

Set unique `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and `ADMIN_SESSION_SECRET` values in `.env` before startup. The configured admin account is bootstrapped on first startup; admin access is not public registration. Admin login uses a signed, HttpOnly, SameSite cookie backed by a PostgreSQL session. The session secret should be a long random value.

Supported uploads are PDF, DOCX, TXT, Markdown, PNG, and JPEG. PDFs are extracted page by page; pages with fewer than 40 non-whitespace characters use OCRmyPDF/Tesseract with Indonesian and English language data, orientation correction, and deskewing. Images are OCRed automatically. The backend image supplies OCR dependencies; no external OCR credential is needed. Uploads are limited to 20 MB and 100 PDF pages, one OCR task runs concurrently, each OCR page has a 60-second timeout, and total document OCR is bounded to 10 minutes. Image pixel dimensions are capped at 40 million. Extraction progress is shown as "Mengekstrak teks" or "Menjalankan OCR". Unreadable or insufficient OCR output fails closed and is not indexed. Metadata required at upload includes publisher, official source URL, and verification date. Admin can replace a source file, disable/enable it, delete it, view processing status, and test retrieval. User call audio and transcripts are not persisted by this knowledge-management feature.

Before ingestion, the document validator requires an HTTPS URL on the allowlist in `app/rag/validator.py`, verifies the publisher label, fetches bounded source evidence, and uses a structured classifier following Jev's Pydantic/output-schema pattern to assess scope, source correspondence, category, and unsafe findings. Python makes the final PASS/REJECT/UNVERIFIABLE decision; model confidence cannot publish a document. Exact approved hosts, public DNS checks, redirect checks, response size limits, and timeouts constrain source fetching. Only PASS records proceed to embeddings. Validation decisions and source hashes are recorded in PostgreSQL. Existing indexed documents without a PASS report are disabled and revalidated on startup.

The initial allowlist covers WHO and selected Kementerian Kesehatan RI sites. Other publishers remain UNVERIFIABLE until explicitly reviewed and added. A website outage, ambiguous assessment, unsupported claim, mismatched publisher, or missing source evidence does not enter retrieval. The model classifier is an assistive check—not a clinical authority or cryptographic proof that all claims are safe. Uploaded content longer than 24,000 characters is held UNVERIFIABLE.

Replacement documents are validated before re-indexing. Qdrant points are staged as `INDEXING`, PostgreSQL chunks are updated transactionally, then Qdrant points become searchable. A chunking-version change schedules a rebuild. Source files use Docker named-volume storage.

Chunking preserves page, heading/section, paragraph, and table boundaries where extraction exposes them. DOCX tables are represented with headers; Markdown headings are attached to sections; PDF page numbers are stored. Paragraphs are combined within a section, long text splits at sentence/word boundaries, and adjacent chunks overlap by up to 160 characters. Embedded text is enriched with title, publisher, category, section, and region; citations retain the unmodified passage text.

## Operations

For optional manual ingestion of a reviewed JSON file, place it in `backend/knowledge/`, then run:

```bash
docker compose exec backend python -m app.rag.ingest --file /app/knowledge/reviewed.json
```

The backend creates/validates the collection at startup when OpenRouter embeddings are configured. The baseline is automatically indexed at startup and the native tools available to the model are:

- `search_knowledge_base`
- `get_mental_health_information`
- `get_verified_referral_resources`

Retrieved passages are evidence only, never trusted instructions. Safety policies remain independent and take priority over retrieved content.

## Retrieval evaluation

`backend/knowledge/rag-evaluation.json` is a small provisional labeled set, including paraphrases and no-answer cases. Its labels are derived from the baseline records and must be reviewed before treating scores as a benchmark. Run the retrieval evaluator through Compose:

```bash
docker compose exec backend python -m app.rag.evaluate --file /app/knowledge/rag-evaluation.json --k 4
```

The report includes document-level Precision@k, Recall@k, F1@k, Hit Rate@k, MRR@k, nDCG@k, no-answer accuracy, and LLM-as-a-judge means for context relevance, faithfulness, answer correctness, and appropriate abstention. Correctness is scored only for cases with a reference answer. Duplicate chunks from the same document count once; Precision@k divides by k. The run generates an answer from retrieved context, then independently judges it against retrieved passages and optional reference answers. Judge scores are model assessments, not ground truth.

Labels and references are provisional examples derived from the baseline, not a benchmark. Review them independently and expand development and held-out sets before tuning thresholds or claiming product quality. Judge evaluation sends synthetic evaluation questions and retrieved passages to OpenRouter; never point it at saved caller transcripts.

## Verification

Test Indonesian paraphrase retrieval, source metadata, threshold/no-result behavior, referral region/verification filters, repeated ingestion, document replacement, Qdrant outage, embedding-provider errors, and hostile instructions embedded inside a source. Evaluate validator false accepts and false rejects separately from retrieval ranking and answer faithfulness.

## Sources

- [OpenRouter embeddings API](https://openrouter.ai/docs/api/api-reference/embeddings/create-embeddings)
- [OpenRouter embedding model record](https://openrouter.ai/api/v1/model/intfloat/multilingual-e5-large)
- [Multilingual-E5 model card](https://huggingface.co/intfloat/multilingual-e5-large)
- [WHO — Doing What Matters in Times of Stress](https://www.who.int/publications/i/item/9789240003927), source PDF and license recorded in `backend/knowledge/baseline-manifest.json`.

# Reviewed knowledge source files

Place reviewed, non-personal JSON files here for Docker-managed ingestion. Do not put call transcripts or private user content in this collection.

The JSON file must be an array of documents accepted by `app.rag.knowledge.KnowledgeDocument`. Every document requires a stable `document_id`, title, publisher, source URL, language, category, verified date, `verification_status: "VERIFIED"`, and reviewed content. Referral records additionally require a region and verified contact details.

Ingest from the project root after reviewing the source records:

```bash
docker compose exec backend python -m app.rag.ingest --file /app/knowledge/reviewed.json
```

Supported categories: `mental_health_education`, `emotional_wellbeing`, `coping_strategy`, `help_seeking`, and `referral_resource`. Re-ingesting a document ID replaces its chunks. Use a new ID when preserving a separately reviewed version.

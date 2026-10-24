import argparse
import asyncio
import json
from pathlib import Path

from qdrant_client import AsyncQdrantClient

from app.core.config import settings
from app.db.postgres import create_postgres_pool
from app.rag.knowledge import KnowledgeBase, KnowledgeDocument
from app.rag.management import KnowledgeManager, initialize_knowledge_tables
from app.rag.validator import DocumentValidator


async def ingest_file(path: Path) -> None:
    if settings.openrouter_api_key is None or not settings.openrouter_api_key.get_secret_value().strip():
        raise ValueError("Set OPENROUTER_API_KEY in .env before ingesting knowledge")
    raw_documents = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_documents, list) or not raw_documents:
        raise ValueError("Input file must contain a non-empty JSON array of verified documents")
    documents = [KnowledgeDocument.model_validate(item) for item in raw_documents]
    postgres = await create_postgres_pool(settings)
    qdrant = AsyncQdrantClient(url=settings.qdrant_url, timeout=30)
    await initialize_knowledge_tables(postgres, settings)
    knowledge = KnowledgeBase(settings, qdrant, postgres_pool=postgres)
    validator = DocumentValidator(settings)
    manager = KnowledgeManager(postgres, knowledge, validator, settings)
    try:
        await knowledge.initialize()
        counts = []
        for document in documents:
            decision = await validator.validate(document)
            if decision.outcome != "PASS":
                raise ValueError(
                    f"Document {document.document_id} did not pass validation: "
                    f"{', '.join(decision.reason_codes)}"
                )
            chunk_count = await manager.ingest_prevalidated_document(document, decision)
            counts.append((document.document_id, chunk_count))
        print(f"Validated and indexed {len(counts)} documents into {settings.rag_collection_name}.")
        for document_id, chunk_count in counts:
            print(f"{document_id}: {chunk_count} chunks")
    finally:
        await knowledge.close()
        await validator.close()
        await qdrant.close()
        await postgres.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest reviewed knowledge documents into Qdrant")
    parser.add_argument("--file", required=True, type=Path, help="JSON array of verified documents")
    arguments = parser.parse_args()
    asyncio.run(ingest_file(arguments.file))


if __name__ == "__main__":
    main()

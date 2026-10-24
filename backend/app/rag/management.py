import asyncio
import hashlib
import json
import logging
import secrets
from datetime import date
from pathlib import Path
from uuid import uuid4

import asyncpg
import bcrypt
from fastapi import HTTPException, Request, UploadFile
from pydantic import ValidationError

from app.core.config import Settings
from app.rag.chunks import MAX_CHUNK_CHARACTERS, TextBlock
from app.rag.knowledge import (
    CHUNKING_VERSION,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    content_version_for,
)
from app.rag.validator import DocumentValidator, ValidationDecision, VALIDATOR_VERSION

ALLOWED_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg"}
SESSION_COOKIE = "voice_support_admin"
SESSION_TTL_SECONDS = 60 * 60 * 12
logger = logging.getLogger(__name__)


def password_hash(password: str) -> str:
    if not 12 <= len(password.encode()) <= 72:
        raise ValueError("Admin password must be 12–72 bytes long")
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password: str, encoded: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), encoded.encode())
    except ValueError:
        return False


def _signature(secret: str, value: str) -> str:
    import hmac

    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def create_session_token(secret: str) -> str:
    session_id = secrets.token_urlsafe(32)
    return f"{session_id}.{_signature(secret, session_id)}"


def valid_session_token(secret: str, token: str) -> bool:
    import hmac

    try:
        session_id, signature = token.split(".", 1)
    except ValueError:
        return False
    return bool(session_id) and hmac.compare_digest(signature, _signature(secret, session_id))


async def initialize_knowledge_tables(pool: asyncpg.Pool, settings: Settings) -> None:
    async with pool.acquire() as connection:
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS admin_accounts (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token_hash TEXT PRIMARY KEY,
                username TEXT NOT NULL REFERENCES admin_accounts(username) ON DELETE CASCADE,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS knowledge_documents (
                document_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                publisher TEXT NOT NULL,
                source_url TEXT NOT NULL,
                language TEXT NOT NULL,
                category TEXT NOT NULL,
                verified_at DATE NOT NULL,
                content TEXT NOT NULL,
                region TEXT,
                contact_details TEXT,
                eligibility TEXT,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_sha256 TEXT NOT NULL UNIQUE,
                extracted_blocks JSONB,
                extraction_report JSONB,
                status TEXT NOT NULL CHECK (status IN ('EXTRACTING','OCR','VALIDATING','PROCESSING','ACTIVE','FAILED','DISABLED','REJECTED','UNVERIFIABLE')),
                error_message TEXT,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                chunking_version TEXT,
                active_content_version TEXT,
                pending_content_version TEXT,
                previous_file_path TEXT,
                is_baseline BOOLEAN NOT NULL DEFAULT FALSE,
                updated_by TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS knowledge_documents_updated_idx
                ON knowledge_documents(updated_at DESC);
            CREATE TABLE IF NOT EXISTS knowledge_jobs (
                id BIGSERIAL PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES knowledge_documents(document_id) ON DELETE CASCADE,
                state TEXT NOT NULL,
                error_message TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS knowledge_baseline_catalog (
                document_id TEXT PRIMARY KEY,
                enabled BOOLEAN NOT NULL DEFAULT TRUE
            );
            CREATE TABLE IF NOT EXISTS knowledge_validations (
                id BIGSERIAL PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES knowledge_documents(document_id) ON DELETE CASCADE,
                outcome TEXT NOT NULL CHECK (outcome IN ('PASS','REJECT','UNVERIFIABLE')),
                report JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                chunk_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES knowledge_documents(document_id) ON DELETE CASCADE,
                content_version TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                title TEXT NOT NULL,
                publisher TEXT NOT NULL,
                source_url TEXT NOT NULL,
                category TEXT NOT NULL,
                verified_at DATE NOT NULL,
                text TEXT NOT NULL,
                section TEXT NOT NULL DEFAULT '',
                page INTEGER,
                region TEXT,
                contact_details TEXT,
                eligibility TEXT
            );
            CREATE INDEX IF NOT EXISTS knowledge_chunks_document_idx ON knowledge_chunks(document_id);
        """)
        await connection.execute("ALTER TABLE knowledge_documents DROP CONSTRAINT IF EXISTS knowledge_documents_status_check")
        await connection.execute(
            "ALTER TABLE knowledge_documents ADD CONSTRAINT knowledge_documents_status_check "
            "CHECK (status IN ('EXTRACTING','OCR','VALIDATING','PROCESSING','ACTIVE','FAILED','DISABLED','REJECTED','UNVERIFIABLE'))"
        )
        await connection.execute("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS region TEXT")
        await connection.execute("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS contact_details TEXT")
        await connection.execute("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS eligibility TEXT")
        await connection.execute("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS chunking_version TEXT")
        await connection.execute("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS active_content_version TEXT")
        await connection.execute("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS pending_content_version TEXT")
        await connection.execute("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS previous_file_path TEXT")
        await connection.execute("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS extracted_blocks JSONB")
        await connection.execute("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS extraction_report JSONB")
        await connection.execute("ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS content_version TEXT")
        await connection.execute(
            "UPDATE knowledge_chunks SET content_version='legacy' WHERE content_version IS NULL"
        )
        await connection.execute("ALTER TABLE knowledge_chunks ALTER COLUMN content_version SET NOT NULL")
        await connection.execute(
            "ALTER TABLE knowledge_chunks DROP CONSTRAINT IF EXISTS knowledge_chunks_document_id_chunk_index_key"
        )
        await connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS knowledge_chunks_doc_version_idx "
            "ON knowledge_chunks(document_id,content_version,chunk_index)"
        )
        await connection.execute(
            "UPDATE knowledge_documents d SET active_content_version='legacy' "
            "WHERE d.active_content_version IS NULL AND d.status='ACTIVE' AND EXISTS "
            "(SELECT 1 FROM knowledge_chunks c WHERE c.document_id=d.document_id)"
        )
        if settings.admin_password and settings.admin_password.get_secret_value().strip():
            hashed = password_hash(settings.admin_password.get_secret_value())
            await connection.execute(
                "INSERT INTO admin_accounts(username,password_hash) VALUES($1,$2) "
                "ON CONFLICT(username) DO NOTHING",
                settings.admin_username,
                hashed,
            )


def extract_document_blocks(path: Path) -> list[TextBlock]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        blocks: list[TextBlock] = []
        section = ""
        for page_number, page in enumerate(reader.pages, start=1):
            for paragraph in (page.extract_text() or "").split("\n\n"):
                text = " ".join(paragraph.split())
                if not text:
                    continue
                if len(text) < 100 and text.isupper():
                    section = text
                    blocks.append(TextBlock(text=text, section=section, page=page_number, kind="heading"))
                    continue
                blocks.append(TextBlock(text=text, section=section, page=page_number))
        return blocks
    if suffix in {".png", ".jpg", ".jpeg"}:
        raise ValueError("IMAGE_EXTRACTION_REQUIRES_ASYNC")
    if suffix == ".docx":
        from docx import Document

        document = Document(path)
        blocks = []
        section = ""
        for paragraph in document.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue
            if paragraph.style and paragraph.style.name.startswith("Heading"):
                section = text
                blocks.append(TextBlock(text=text, section=section, kind="heading"))
            else:
                blocks.append(TextBlock(text=text, section=section))
        for table_index, table in enumerate(document.tables, start=1):
            rows = [" | ".join(" ".join(cell.text.split()) for cell in row.cells) for row in table.rows]
            if rows:
                header = rows[0]
                table_rows = [header]
                for row in rows[1:]:
                    if len("\n".join([*table_rows, row])) > MAX_CHUNK_CHARACTERS:
                        blocks.append(TextBlock(
                            text=f"Tabel {table_index}:\n" + "\n".join(table_rows),
                            section=section,
                            kind="table",
                        ))
                        table_rows = [header]
                    table_rows.append(row)
                blocks.append(TextBlock(
                    text=f"Tabel {table_index}:\n" + "\n".join(table_rows),
                    section=section,
                    kind="table",
                ))
        return blocks
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if suffix == ".md":
        blocks = []
        section = ""
        for line in text.splitlines():
            heading = line.strip()
            if heading.startswith("#"):
                section = heading.lstrip("# ").strip()
                if section:
                    blocks.append(TextBlock(section, section=section, kind="heading"))
            elif heading:
                blocks.append(TextBlock(heading, section=section))
        return blocks
    return [TextBlock(paragraph.strip()) for paragraph in text.split("\n\n") if paragraph.strip()]


def extract_document_text(path: Path) -> str:
    return "\n\n".join(block.text for block in extract_document_blocks(path)).strip()


class KnowledgeManager:
    def __init__(self, pool: asyncpg.Pool, knowledge: KnowledgeBase, validator: DocumentValidator, settings: Settings):
        self.pool = pool
        self.knowledge = knowledge
        self.validator = validator
        self.settings = settings
        self._jobs: set[asyncio.Task] = set()
        self._document_locks: dict[str, asyncio.Lock] = {}

    def queue_ingestion(self, document_id: str) -> None:
        task = asyncio.create_task(self._extract_validate_and_ingest(document_id))
        self._jobs.add(task)
        task.add_done_callback(self._jobs.discard)

    async def close(self) -> None:
        for task in self._jobs:
            task.cancel()
        if self._jobs:
            await asyncio.gather(*self._jobs, return_exceptions=True)

    async def _extract_validate_and_ingest(self, document_id: str) -> None:
        from app.rag.extraction import extract_blocks, serialize_blocks

        lock = self._document_locks.setdefault(document_id, asyncio.Lock())
        async with lock:
            row = await self.pool.fetchrow(
                "SELECT file_path,status FROM knowledge_documents WHERE document_id=$1", document_id
            )
            if row is None or row["status"] not in {"EXTRACTING", "OCR"}:
                return
            file_path = Path(row["file_path"])
            await self.pool.execute(
                "UPDATE knowledge_documents SET status=$2 WHERE document_id=$1 AND status IN ('EXTRACTING','OCR')",
                document_id, "OCR" if file_path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg"} else "EXTRACTING",
            )
            try:
                result = await extract_blocks(file_path)
                content = "\n\n".join(block.text for block in result.blocks).strip()
                if not content:
                    raise ValueError("EXTRACTION_NO_USABLE_TEXT")
                await self.pool.execute(
                    "UPDATE knowledge_documents SET content=$2,extracted_blocks=$3::jsonb,"
                    "extraction_report=$4::jsonb,status='VALIDATING',updated_at=now() "
                    "WHERE document_id=$1 AND status IN ('EXTRACTING','OCR')",
                    document_id, content, serialize_blocks(result.blocks),
                    json.dumps({"page_count": result.page_count, "ocr_pages": result.ocr_pages,
                                "unreadable_pages": result.unreadable_pages}),
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                reason = str(error) if str(error).isupper() else f"EXTRACTION_FAILED_{type(error).__name__.upper()}"
                await self.pool.execute(
                "UPDATE knowledge_documents SET status=CASE WHEN active_content_version IS NULL "
                "THEN 'FAILED' ELSE 'ACTIVE' END,error_message=$2,extracted_blocks=NULL,"
                    "extraction_report=$3::jsonb,updated_at=now() WHERE document_id=$1 "
                    "AND status IN ('EXTRACTING','OCR')",
                    document_id, reason, json.dumps({"failure_reason": reason}),
                )
                return
        await self._validate_and_ingest(document_id)

    async def resume_jobs(self) -> None:
        rows = await self.pool.fetch(
            "SELECT d.document_id,d.status, "
            "(SELECT v.outcome FROM knowledge_validations v WHERE v.document_id=d.document_id "
            "ORDER BY v.created_at DESC LIMIT 1) AS validation_outcome, "
            "(SELECT v.report->>'validator_version' FROM knowledge_validations v "
            "WHERE v.document_id=d.document_id ORDER BY v.created_at DESC LIMIT 1) AS validator_version "
            ", d.chunking_version,d.active_content_version FROM knowledge_documents d WHERE d.status IN "
            "('ACTIVE','EXTRACTING','OCR','VALIDATING','PROCESSING','FAILED','REJECTED','UNVERIFIABLE')"
        )
        for row in rows:
            if row["status"] in {"REJECTED", "UNVERIFIABLE"} and row["validator_version"] == VALIDATOR_VERSION:
                continue
            if (
                row["status"] == "ACTIVE"
                and row["validation_outcome"] == "PASS"
                and row["validator_version"] == VALIDATOR_VERSION
                and row["chunking_version"] == CHUNKING_VERSION
                and row["active_content_version"]
                and row["active_content_version"] not in {None, "legacy"}
            ):
                continue
            needs_validation = (
                row["status"] == "VALIDATING"
                or row["validator_version"] != VALIDATOR_VERSION
                or row["validation_outcome"] != "PASS"
            )
            if needs_validation:
                if row["status"] == "ACTIVE":
                    await self.knowledge.set_document_active(row["document_id"], False)
                await self.pool.execute(
                    "UPDATE knowledge_documents SET status='VALIDATING' WHERE document_id=$1",
                    row["document_id"],
                )
                self.queue_ingestion(row["document_id"])
            else:
                if row["status"] == "ACTIVE":
                    await self.knowledge.set_document_active(row["document_id"], False)
                    self.knowledge.remove_sparse_document(row["document_id"])
                await self.pool.execute(
                    "UPDATE knowledge_documents SET status='PROCESSING' WHERE document_id=$1",
                    row["document_id"],
                )
                task = asyncio.create_task(self._ingest(row["document_id"]))
                self._jobs.add(task)
                task.add_done_callback(self._jobs.discard)

    async def seed_baseline(self, manifest_path: Path) -> None:
        documents_path = manifest_path.parent / "baseline.json"
        if not documents_path.exists():
            return
        records = json.loads(documents_path.read_text(encoding="utf-8"))
        source_file = manifest_path.parent / "WHO-Doing-What-Matters-in-Times-of-Stress.pdf"
        for raw in records:
            document = KnowledgeDocument.model_validate(raw)
            await self.pool.execute(
                "INSERT INTO knowledge_baseline_catalog(document_id) VALUES($1) "
                "ON CONFLICT(document_id) DO NOTHING", document.document_id,
            )
            if not await self.pool.fetchval(
                "SELECT enabled FROM knowledge_baseline_catalog WHERE document_id=$1",
                document.document_id,
            ):
                continue
            digest = hashlib.sha256(document.content.encode()).hexdigest()
            await self.pool.execute(
                "INSERT INTO knowledge_documents(document_id,title,publisher,source_url,language,"
                "category,verified_at,content,file_name,file_path,file_sha256,status,is_baseline,updated_by) "
                "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'VALIDATING',TRUE,'baseline') "
                "ON CONFLICT(document_id) DO NOTHING",
                document.document_id, document.title, document.publisher, str(document.source_url),
                document.language, document.category, document.verified_at, document.content,
                source_file.name if source_file.exists() else "baseline-source-unavailable",
                f"baseline:{source_file.name}" if source_file.exists() else "baseline:source-unavailable",
                digest,
            )
            await self.pool.execute(
                "UPDATE knowledge_documents SET error_message=NULL "
                "WHERE document_id=$1 AND status='VALIDATING'", document.document_id
            )

    async def _validate_and_ingest(
        self, document_id: str, *, baseline_manifest: Path | None = None
    ) -> None:
        lock = self._document_locks.setdefault(document_id, asyncio.Lock())
        async with lock:
            row = await self.pool.fetchrow(
                "SELECT * FROM knowledge_documents WHERE document_id=$1", document_id
            )
            if row is None or row["status"] != "VALIDATING":
                return
            try:
                content = row["content"]
                if not content.strip():
                    raw_blocks = row["extracted_blocks"]
                    if isinstance(raw_blocks, str):
                        raw_blocks = json.loads(raw_blocks)
                    content = "\n\n".join(block["text"] for block in raw_blocks)
                    await self.pool.execute(
                        "UPDATE knowledge_documents SET content=$2 WHERE document_id=$1 "
                        "AND status='VALIDATING'", document_id, content,
                    )
                document = KnowledgeDocument(
                    document_id=row["document_id"], title=row["title"],
                    publisher=row["publisher"], source_url=row["source_url"],
                    language=row["language"], category=row["category"],
                    verified_at=row["verified_at"], verification_status="VERIFIED",
                    content=content, region=row["region"],
                    contact_details=row["contact_details"], eligibility=row["eligibility"],
                )
                evidence = None
                evidence_hash = None
                if str(row["file_path"]).startswith("baseline:"):
                    if baseline_manifest is None:
                        baseline_manifest = Path("/app/knowledge/baseline-manifest.json")
                    manifest = json.loads(baseline_manifest.read_text(encoding="utf-8"))
                    source_path = baseline_manifest.parent / manifest["local_file"]
                    source_bytes = source_path.read_bytes()
                    evidence_hash = hashlib.sha256(source_bytes).hexdigest()
                    if evidence_hash != manifest["sha256"] or manifest["source_landing_page"] != str(document.source_url):
                        raise ValueError("BASELINE_SOURCE_CHECKSUM_MISMATCH")
                    evidence = extract_document_text(source_path)[:24_000]
                    extracted_blocks = None
                elif not str(row["file_path"]).startswith("manual:"):
                    extracted_blocks = row["extracted_blocks"]
                    if isinstance(extracted_blocks, str):
                        extracted_blocks = json.loads(extracted_blocks)
                    if not extracted_blocks:
                        raise ValueError("EXTRACTION_RESULT_MISSING")
                    evidence = "\n\n".join(
                        block["text"] if isinstance(block, dict) else block.text
                        for block in extracted_blocks
                    )[:24_000]
                decision = await self.validator.validate(
                    document, source_evidence=evidence, source_sha256=evidence_hash
                )
                if decision.outcome == "PASS" and decision.assessment is None:
                    decision = ValidationDecision(
                        outcome="UNVERIFIABLE", reason_codes=["ASSESSMENT_MISSING"],
                        source_url=str(document.source_url),
                        explanation="Validasi tidak menghasilkan assessment terstruktur.",
                    )
                await self._save_validation(document_id, decision)
                if decision.outcome != "PASS" or decision.assessment is None:
                    message = ", ".join(decision.reason_codes) or decision.explanation
                    if row["active_content_version"]:
                        message += "; versi aktif sebelumnya tetap digunakan"
                    await self.pool.execute(
                        "UPDATE knowledge_documents SET status=$2,error_message=$3,updated_at=now() "
                        "WHERE document_id=$1", document_id, decision.outcome, message,
                    )
                    return
                await self.pool.execute(
                    "UPDATE knowledge_documents SET category=$2,status='PROCESSING',error_message=NULL,updated_at=now() "
                    "WHERE document_id=$1", document_id, decision.assessment.category,
                )
            except Exception as error:
                reason = str(error) if str(error).isupper() else f"VALIDATION_FAILED_{type(error).__name__.upper()}"
                decision = ValidationDecision(
                    outcome="UNVERIFIABLE", reason_codes=[reason], source_url=str(row["source_url"]),
                    explanation="Dokumen belum dapat diverifikasi; tidak masuk ke knowledge retrieval.",
                )
                await self._save_validation(document_id, decision)
                await self.pool.execute(
                    "UPDATE knowledge_documents SET status='UNVERIFIABLE',error_message=$2,updated_at=now() "
                    "WHERE document_id=$1", document_id, reason,
                )
                return
        await self._ingest(document_id)

    async def _save_validation(self, document_id: str, decision: ValidationDecision) -> None:
        await self.pool.execute(
            "INSERT INTO knowledge_validations(document_id,outcome,report) VALUES($1,$2,$3::jsonb)",
            document_id, decision.outcome,
            json.dumps(decision.model_dump(mode="json"), ensure_ascii=False),
        )

    async def ingest_prevalidated_document(
        self,
        document: KnowledgeDocument,
        decision: ValidationDecision,
        *,
        username: str = "manual-ingest",
    ) -> int:
        if decision.outcome != "PASS" or decision.assessment is None:
            raise ValueError("Document must pass validation before indexing")
        digest = hashlib.sha256(
            f"{document.document_id}:{document.content}".encode()
        ).hexdigest()
        content_version = content_version_for(document)
        await self.pool.execute(
            "INSERT INTO knowledge_documents(document_id,title,publisher,source_url,language,category,"
            "verified_at,content,region,contact_details,eligibility,file_name,file_path,file_sha256,"
            "pending_content_version,status,updated_by) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'manual:json',$13,$14,'PROCESSING',$15) "
            "ON CONFLICT(document_id) DO UPDATE SET title=EXCLUDED.title,publisher=EXCLUDED.publisher,"
            "source_url=EXCLUDED.source_url,language=EXCLUDED.language,category=EXCLUDED.category,"
            "verified_at=EXCLUDED.verified_at,content=EXCLUDED.content,region=EXCLUDED.region,"
            "contact_details=EXCLUDED.contact_details,eligibility=EXCLUDED.eligibility,"
            "file_name=EXCLUDED.file_name,file_path=EXCLUDED.file_path,file_sha256=EXCLUDED.file_sha256,"
            "pending_content_version=EXCLUDED.pending_content_version,"
            "status='PROCESSING',error_message=NULL,updated_by=EXCLUDED.updated_by,updated_at=now()",
            document.document_id, document.title, document.publisher, str(document.source_url),
            document.language, document.category, document.verified_at, document.content,
            document.region, document.contact_details, document.eligibility,
            f"{document.document_id}.json", digest, content_version, username,
        )
        await self._save_validation(document.document_id, decision)
        await self._ingest(document.document_id)
        status = await self.pool.fetchval(
            "SELECT status FROM knowledge_documents WHERE document_id=$1", document.document_id
        )
        if status != "ACTIVE":
            raise ValueError(f"Indexing failed for document {document.document_id}")
        return await self.pool.fetchval(
            "SELECT chunk_count FROM knowledge_documents WHERE document_id=$1", document.document_id
        )

    async def _ingest(self, document_id: str) -> None:
        lock = self._document_locks.setdefault(document_id, asyncio.Lock())
        async with lock:
            row = await self.pool.fetchrow(
                "SELECT * FROM knowledge_documents WHERE document_id=$1", document_id
            )
            if row is None or row["status"] != "PROCESSING":
                return
            version = row["pending_content_version"]
            if not version or version == "pending-extraction":
                version = content_version_for(KnowledgeDocument(
                    document_id=row["document_id"], title=row["title"], publisher=row["publisher"],
                    source_url=row["source_url"], language=row["language"], category=row["category"],
                    verified_at=row["verified_at"], verification_status="VERIFIED", content=row["content"],
                    region=row["region"], contact_details=row["contact_details"], eligibility=row["eligibility"],
                ))
                await self.pool.execute(
                    "UPDATE knowledge_documents SET pending_content_version=$2 WHERE document_id=$1",
                    document_id, version,
                )
                row = await self.pool.fetchrow(
                    "SELECT * FROM knowledge_documents WHERE document_id=$1", document_id
                )
            previous_version = row["active_content_version"]
            previous_file_path = row["previous_file_path"]
            activated = False
            database_activated = False
            content_version = ""
            try:
                doc = KnowledgeDocument(
                    document_id=row["document_id"], title=row["title"],
                    publisher=row["publisher"], source_url=row["source_url"],
                    language=row["language"], category=row["category"],
                    verified_at=row["verified_at"], verification_status="VERIFIED",
                    content=row["content"], region=row["region"],
                    contact_details=row["contact_details"], eligibility=row["eligibility"],
                )
                if str(row["file_path"]).startswith(("baseline:", "manual:")):
                    blocks = [TextBlock(row["content"])]
                elif row["extracted_blocks"]:
                    from app.rag.extraction import deserialize_blocks

                    raw_blocks = row["extracted_blocks"]
                    if not isinstance(raw_blocks, str):
                        raw_blocks = json.dumps(raw_blocks, ensure_ascii=False)
                    blocks = deserialize_blocks(raw_blocks)
                else:
                    raise ValueError("EXTRACTION_RESULT_MISSING")
                content_version = content_version_for(doc)
                if (
                    previous_version == content_version
                    and row["chunking_version"] == CHUNKING_VERSION
                ):
                    await self.knowledge.set_document_active(document_id, True)
                    chunks = [
                        KnowledgeChunk(**dict(chunk_row), score=0.0)
                        for chunk_row in await self.pool.fetch(
                            "SELECT chunk_id,content_version,document_id,title,publisher,source_url,category,"
                            "verified_at,text,section,page,region,contact_details,eligibility "
                            "FROM knowledge_chunks WHERE document_id=$1 AND content_version=$2 "
                            "ORDER BY chunk_index", document_id, content_version,
                        )
                    ]
                    self.knowledge.activate_sparse_document(document_id, chunks)
                    await self.pool.execute(
                        "UPDATE knowledge_documents SET status='ACTIVE',error_message=NULL,"
                        "pending_content_version=NULL WHERE document_id=$1", document_id,
                    )
                    return
                count = await self.knowledge.ingest(doc, blocks=blocks)
                chunks = self.knowledge.pending_chunks(document_id)
                async with self.pool.acquire() as connection:
                    async with connection.transaction():
                        await connection.executemany(
                            "INSERT INTO knowledge_chunks(chunk_id,document_id,content_version,chunk_index,title,publisher,"
                            "source_url,category,verified_at,text,section,page,region,contact_details,eligibility) "
                            "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)",
                            [
                                (
                                    chunk.chunk_id, chunk.document_id, chunk.content_version, index,
                                    chunk.title, chunk.publisher, chunk.source_url, chunk.category,
                                    chunk.verified_at, chunk.text, chunk.section, chunk.page,
                                    chunk.region, chunk.contact_details, chunk.eligibility,
                                )
                                for index, chunk in enumerate(chunks)
                            ],
                        )
                await self.knowledge.activate_document_version(
                    document_id, content_version, previous_version
                )
                activated = True
                async with self.pool.acquire() as connection:
                    async with connection.transaction():
                        await connection.execute(
                            "UPDATE knowledge_documents SET status='ACTIVE',error_message=NULL,"
                            "chunk_count=$2,chunking_version=$3,active_content_version=$4,"
                            "pending_content_version=NULL,previous_file_path=NULL,updated_at=now() "
                            "WHERE document_id=$1",
                            document_id, count, CHUNKING_VERSION, content_version,
                        )
                database_activated = True
                self.knowledge.activate_sparse_document(document_id, chunks)
                try:
                    await self.knowledge.delete_other_versions(document_id, content_version)
                except Exception as cleanup_error:
                    logger.warning("Could not remove obsolete dense chunks: %s", type(cleanup_error).__name__)
                try:
                    async with self.pool.acquire() as connection:
                        async with connection.transaction():
                            await connection.execute(
                                "DELETE FROM knowledge_chunks WHERE document_id=$1 AND content_version<>$2",
                                document_id, content_version,
                            )
                    await self.pool.execute(
                        "INSERT INTO knowledge_jobs(document_id,state) VALUES($1,'ACTIVE')", document_id
                    )
                except Exception as cleanup_error:
                    logger.warning("Could not clean obsolete knowledge records: %s", type(cleanup_error).__name__)
                if previous_file_path and not previous_file_path.startswith(("baseline:", "manual:")):
                    try:
                        Path(previous_file_path).unlink(missing_ok=True)
                    except OSError as cleanup_error:
                        logger.warning(
                            "Could not remove prior knowledge source file: %s",
                            type(cleanup_error).__name__,
                        )
            except Exception as error:
                if activated and not database_activated:
                    try:
                        await self.knowledge.restore_document_version(
                            document_id,
                            previous_version,
                            content_version,
                        )
                    except Exception as restore_error:
                        logger.warning("Could not restore previous knowledge version: %s", type(restore_error).__name__)
                if previous_version is None:
                    self.knowledge.remove_sparse_document(document_id)
                message = f"Pengindeksan gagal ({type(error).__name__})."
                await self.pool.execute(
                    "UPDATE knowledge_documents SET status=$2,error_message=$3,updated_at=now() "
                    "WHERE document_id=$1", document_id,
                    "ACTIVE" if previous_version else "FAILED",
                    f"{message} Versi aktif sebelumnya tetap digunakan." if previous_version else message,
                )

    async def upload(self, upload: UploadFile, metadata: dict, username: str) -> str:
        filename = Path(upload.filename or "document").name
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(400, "Format file tidak didukung.")
        root = Path(self.settings.knowledge_storage_path)
        root.mkdir(parents=True, exist_ok=True)
        document_id = metadata.get("document_id") or f"upload-{uuid4().hex}"
        if not document_id.replace("-", "").replace("_", "").isalnum() or len(document_id) > 120:
            raise HTTPException(400, "ID dokumen tidak valid.")
        prior = await self.pool.fetchrow(
            "SELECT file_path,previous_file_path,status,active_content_version "
            "FROM knowledge_documents WHERE document_id=$1", document_id
        )
        temp_path = root / f"{uuid4().hex}{suffix}"
        content = bytearray()
        while chunk := await upload.read(1024 * 1024):
            content.extend(chunk)
            if len(content) > self.settings.knowledge_max_upload_bytes:
                temp_path.unlink(missing_ok=True)
                raise HTTPException(413, "Ukuran file melebihi batas.")
        digest = hashlib.sha256(content).hexdigest()
        existing = await self.pool.fetchrow(
            "SELECT document_id FROM knowledge_documents WHERE file_sha256=$1", digest
        )
        if existing and existing["document_id"] != document_id:
            raise HTTPException(409, "File ini sudah digunakan oleh dokumen lain.")
        if not content:
            raise HTTPException(422, "File kosong.")
        temp_path.write_bytes(content)
        values = {
            "document_id": document_id,
            "title": metadata.get("title") or Path(filename).stem,
            "publisher": metadata.get("publisher"),
            "source_url": metadata.get("source_url"),
            "language": metadata.get("language") or "id",
            "category": metadata.get("category") or "mental_health_education",
            "verified_at": metadata.get("verified_at") or date.today().isoformat(),
            "verification_status": "VERIFIED",
            "content": "",
            "region": metadata.get("region"),
            "contact_details": metadata.get("contact_details"),
            "eligibility": metadata.get("eligibility"),
        }
        if not values["publisher"] or not values["source_url"] or not metadata.get("verified_at"):
            temp_path.unlink(missing_ok=True)
            raise HTTPException(422, "Penerbit, URL sumber resmi, dan tanggal verifikasi wajib diisi.")
        try:
            metadata_values = {key: value for key, value in values.items() if key != "content"}
            doc = KnowledgeDocument.model_validate({**metadata_values, "content": "Validasi metadata sementara"})
        except ValidationError as error:
            temp_path.unlink(missing_ok=True)
            if any("verified_at cannot be in the future" in item["msg"] for item in error.errors()):
                raise HTTPException(422, f"Tanggal verifikasi tidak boleh melewati tanggal server ({date.today().isoformat()}).") from error
            raise HTTPException(422, "Metadata dokumen tidak valid. Periksa judul, penerbit, URL, dan tanggal verifikasi.") from error
        validation = doc.model_dump(mode="python")
        final_path = root / f"{document_id}-{uuid4().hex}{suffix}"
        temp_path.replace(final_path)
        content_version = None
        try:
            await self.pool.execute(
                "INSERT INTO knowledge_documents(document_id,title,publisher,source_url,language,"
                "category,verified_at,content,region,contact_details,eligibility,file_name,file_path,file_sha256,"
                "extracted_blocks,extraction_report,pending_content_version,status,updated_by) "
                "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,NULL,NULL,NULL,'EXTRACTING',$15) "
                "ON CONFLICT(document_id) DO UPDATE SET title=EXCLUDED.title, "
                "publisher=EXCLUDED.publisher,source_url=EXCLUDED.source_url,language=EXCLUDED.language, "
                "category=EXCLUDED.category,verified_at=EXCLUDED.verified_at,content=EXCLUDED.content, "
                "region=EXCLUDED.region,contact_details=EXCLUDED.contact_details,eligibility=EXCLUDED.eligibility, "
                "file_name=EXCLUDED.file_name,file_path=EXCLUDED.file_path,file_sha256=EXCLUDED.file_sha256, "
                "extracted_blocks=NULL,extraction_report=NULL, "
                "pending_content_version=EXCLUDED.pending_content_version, "
                "previous_file_path=CASE WHEN knowledge_documents.active_content_version IS NULL THEN NULL "
                "ELSE COALESCE(knowledge_documents.previous_file_path,knowledge_documents.file_path) END, "
                "status='EXTRACTING',error_message=NULL,updated_by=EXCLUDED.updated_by,updated_at=now()",
                validation["document_id"], validation["title"], validation["publisher"], str(validation["source_url"]), validation["language"],
                validation["category"], validation["verified_at"], "", validation["region"], validation["contact_details"],
                validation["eligibility"], filename, str(final_path), digest, username,
            )
        except Exception:
            final_path.unlink(missing_ok=True)
            raise
        if prior:
            old_pending = prior["file_path"]
            if (
                old_pending and old_pending != prior["previous_file_path"]
                and not old_pending.startswith(("baseline:", "manual:"))
                and old_pending != str(final_path)
            ):
                Path(old_pending).unlink(missing_ok=True)
        self.queue_ingestion(doc.document_id)
        return doc.document_id

    async def delete(self, document_id: str) -> None:
        lock = self._document_locks.setdefault(document_id, asyncio.Lock())
        async with lock:
            await self.pool.execute(
                "UPDATE knowledge_documents SET status='DISABLED',updated_at=now() WHERE document_id=$1",
                document_id,
            )
            await self.knowledge.set_document_active(document_id, False)
            self.knowledge.remove_sparse_document(document_id)
            for task in tuple(self._jobs):
                if not task.done():
                    task.cancel()
            is_baseline = await self.pool.fetchval(
                "SELECT is_baseline FROM knowledge_documents WHERE document_id=$1", document_id
            )
            await self.knowledge.delete_document(document_id)
            self.knowledge.remove_sparse_document(document_id)
            row = await self.pool.fetchrow(
                "DELETE FROM knowledge_documents WHERE document_id=$1 RETURNING file_path", document_id
            )
            if row:
                file_path = row["file_path"]
                if not file_path.startswith(("baseline:", "manual:")):
                    Path(file_path).unlink(missing_ok=True)
            if is_baseline:
                await self.pool.execute(
                    "UPDATE knowledge_baseline_catalog SET enabled=FALSE WHERE document_id=$1",
                    document_id,
                )

    async def disable(self, document_id: str) -> bool:
        lock = self._document_locks.setdefault(document_id, asyncio.Lock())
        async with lock:
            row = await self.pool.fetchrow(
                "SELECT document_id FROM knowledge_documents WHERE document_id=$1", document_id
            )
            if row is None:
                return False
            await self.pool.execute(
                "UPDATE knowledge_documents SET status='DISABLED',updated_at=now() WHERE document_id=$1",
                document_id,
            )
            for task in tuple(self._jobs):
                if not task.done():
                    task.cancel()
            await self.knowledge.set_document_active(document_id, False)
            self.knowledge.remove_sparse_document(document_id)
            await self.pool.execute(
                "UPDATE knowledge_baseline_catalog SET enabled=FALSE WHERE document_id=$1",
                document_id,
            )
            return True


async def admin_user(request: Request) -> str:
    settings: Settings = request.app.state.settings
    secret = settings.admin_session_secret
    token = request.cookies.get(SESSION_COOKIE)
    if not secret or not token:
        raise HTTPException(401, "Autentikasi admin diperlukan.")
    if not valid_session_token(secret.get_secret_value(), token):
        raise HTTPException(401, "Sesi admin tidak valid.")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = await request.app.state.postgres_pool.fetchrow(
        "SELECT username FROM admin_sessions WHERE token_hash=$1 AND expires_at>now()", token_hash
    )
    if row is None:
        raise HTTPException(401, "Sesi admin telah berakhir.")
    return row["username"]


async def create_admin_session(pool: asyncpg.Pool, username: str, token: str) -> None:
    await pool.execute(
        "INSERT INTO admin_sessions(token_hash,username,expires_at) VALUES($1,$2,now()+$3*interval '1 second')",
        hashlib.sha256(token.encode()).hexdigest(), username, SESSION_TTL_SECONDS,
    )

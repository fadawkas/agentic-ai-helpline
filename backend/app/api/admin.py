import hashlib
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from app.rag.management import (
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    KnowledgeManager,
    admin_user,
    check_password,
    create_admin_session,
    create_session_token,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


@router.post("/login")
async def login(body: LoginInput, request: Request, response: Response) -> dict[str, str]:
    row = await request.app.state.postgres_pool.fetchrow(
        "SELECT username,password_hash FROM admin_accounts WHERE username=$1", body.username
    )
    if row is None or not check_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Nama pengguna atau kata sandi salah.")
    secret = request.app.state.settings.admin_session_secret
    if secret is None or len(secret.get_secret_value().encode()) < 32:
        raise HTTPException(503, "ADMIN_SESSION_SECRET minimal 32 byte dan harus dikonfigurasi.")
    token = create_session_token(secret.get_secret_value())
    await create_admin_session(request.app.state.postgres_pool, body.username, token)
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, secure=request.url.scheme == "https",
        samesite="strict", max_age=SESSION_TTL_SECONDS, path="/api/admin",
    )
    return {"username": body.username}


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, str]:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await request.app.state.postgres_pool.execute(
            "DELETE FROM admin_sessions WHERE token_hash=$1", hashlib.sha256(token.encode()).hexdigest()
        )
    response.delete_cookie(SESSION_COOKIE, path="/api/admin")
    return {"status": "ok"}


@router.get("/session")
async def session(username: str = Depends(admin_user)) -> dict[str, str]:
    return {"username": username}


@router.get("/documents")
async def documents(request: Request, _username: str = Depends(admin_user)) -> list[dict]:
    rows = await request.app.state.postgres_pool.fetch(
        "SELECT document_id,title,publisher,source_url,language,category,verified_at,region,"
        "contact_details,eligibility,status,error_message,chunk_count,is_baseline,file_name,updated_at,extraction_report, "
        "(SELECT report FROM knowledge_validations v WHERE v.document_id=knowledge_documents.document_id "
        "ORDER BY v.created_at DESC LIMIT 1) AS validation_report "
        "FROM knowledge_documents ORDER BY updated_at DESC"
    )
    documents = []
    for row in rows:
        document = dict(row)
        if isinstance(document["validation_report"], str):
            document["validation_report"] = json.loads(document["validation_report"])
        documents.append(document)
    return documents


@router.post("/documents")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(""),
    publisher: str = Form(""),
    source_url: str = Form(""),
    category: str = Form("mental_health_education"),
    language: str = Form("id"),
    verified_at: str = Form(""),
    document_id: str = Form(""),
    region: str = Form(""),
    contact_details: str = Form(""),
    eligibility: str = Form(""),
    username: str = Depends(admin_user),
) -> dict[str, str]:
    manager: KnowledgeManager = request.app.state.knowledge_manager
    if manager is None:
        raise HTTPException(503, "Knowledge indexing belum dikonfigurasi.")
    metadata = {
        "title": title or None, "publisher": publisher or None,
        "source_url": source_url or None, "category": category,
        "language": language, "verified_at": verified_at or None,
        "document_id": document_id or None,
        "region": region or None,
        "contact_details": contact_details or None,
        "eligibility": eligibility or None,
    }
    document_id = await manager.upload(file, metadata, username)
    return {"document_id": document_id, "status": "EXTRACTING"}


@router.put("/documents/{document_id}")
async def update_document(
    document_id: str,
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(""),
    publisher: str = Form(""),
    source_url: str = Form(""),
    category: str = Form("mental_health_education"),
    language: str = Form("id"),
    verified_at: str = Form(""),
    region: str = Form(""),
    contact_details: str = Form(""),
    eligibility: str = Form(""),
    username: str = Depends(admin_user),
) -> dict[str, str]:
    manager: KnowledgeManager = request.app.state.knowledge_manager
    if manager is None:
        raise HTTPException(503, "Knowledge indexing belum dikonfigurasi.")
    exists = await request.app.state.postgres_pool.fetchval(
        "SELECT 1 FROM knowledge_documents WHERE document_id=$1", document_id
    )
    if not exists:
        raise HTTPException(404, "Dokumen tidak ditemukan.")
    metadata = {
        "document_id": document_id,
        "title": title or None,
        "publisher": publisher or None,
        "source_url": source_url or None,
        "category": category,
        "language": language,
        "verified_at": verified_at or None,
        "region": region or None,
        "contact_details": contact_details or None,
        "eligibility": eligibility or None,
    }
    result_id = await manager.upload(file, metadata, username)
    return {"document_id": result_id, "status": "EXTRACTING"}


@router.post("/documents/{document_id}/disable")
async def disable_document(
    document_id: str, request: Request, _username: str = Depends(admin_user)
) -> dict[str, str]:
    manager = request.app.state.knowledge_manager
    if manager is None:
        raise HTTPException(503, "Knowledge indexing belum dikonfigurasi.")
    if not await manager.disable(document_id):
        raise HTTPException(404, "Dokumen tidak ditemukan.")
    return {"status": "DISABLED"}


@router.post("/documents/{document_id}/enable")
async def enable_document(
    document_id: str, request: Request, _username: str = Depends(admin_user)
) -> dict[str, str]:
    manager: KnowledgeManager = request.app.state.knowledge_manager
    if manager is None:
        raise HTTPException(503, "Knowledge indexing belum dikonfigurasi.")
    row = await request.app.state.postgres_pool.fetchrow(
        "SELECT document_id FROM knowledge_documents WHERE document_id=$1", document_id
    )
    if row is None:
        raise HTTPException(404, "Dokumen tidak ditemukan.")
    await request.app.state.postgres_pool.execute(
        "UPDATE knowledge_documents SET status='VALIDATING',updated_at=now() WHERE document_id=$1",
        document_id,
    )
    await request.app.state.postgres_pool.execute(
        "UPDATE knowledge_baseline_catalog SET enabled=TRUE WHERE document_id=$1", document_id
    )
    manager.queue_ingestion(document_id)
    return {"status": "VALIDATING"}


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str, request: Request, _username: str = Depends(admin_user)
) -> dict[str, str]:
    if request.app.state.knowledge_manager is None:
        raise HTTPException(503, "Knowledge indexing belum dikonfigurasi.")
    await request.app.state.knowledge_manager.delete(document_id)
    return {"status": "DELETED"}


@router.post("/search")
async def search_documents(
    body: dict,
    request: Request,
    _username: str = Depends(admin_user),
) -> dict:
    query = body.get("query")
    if not isinstance(query, str) or not 2 <= len(query) <= 1200:
        raise HTTPException(422, "Masukkan pertanyaan 2–1200 karakter.")
    if request.app.state.knowledge_base is None:
        raise HTTPException(503, "Knowledge indexing belum dikonfigurasi.")
    results = await request.app.state.knowledge_base.search(query)
    return {"results": [result.model_dump(mode="json") for result in results]}

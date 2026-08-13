"""FastAPI app: auth, upload, job status, engineer & manager views, static serving.

Phase 7 (SOLID refactor): routes depend on abstract service providers from
``dependencies.py`` rather than importing concrete module globals directly.
``app.dependency_overrides`` can be used in tests to inject alternative
implementations without monkeypatching module-level singletons.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlencode

from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import aggregator
from .auth import AuthenticatedUser, get_auth, require_admin, require_user
from .config import settings
from .dependencies import (
    get_analysis_cache,
    get_analyzer_service,
    get_acronym_glossary_store,
    get_knowledge_ingestion,
    get_knowledge_retriever,
    get_knowledge_store,
    get_orchestrator,
    get_registry,
)
from .knowledge import parsing
from .knowledge.summarizer import ProductKnowledgeError, is_llm_backend_available
from .logging_config import setup_backend_logging, write_frontend_log
from .models import AcronymUpsertRequest, AdminLoginRequest, FrontendLogRequest
from .record_views import group_units_by_serial
from .upload_storage import UploadStorageError, save_uploads

setup_backend_logging(settings.APP_DEBUG)
log = logging.getLogger("cotrace.main")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    log.info("Backend started. Provider: %s. Debug: %s. Work dir: %s.", settings.LLM_PROVIDER, settings.APP_DEBUG, settings.WORK_DIR)
    get_registry().load_from_disk()
    yield
    log.info("Backend stopped.")


app = FastAPI(title="Co-Trace — Manufacturing Log Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    if settings.APP_DEBUG:
        log.debug("%s %s started.", request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        log.exception("%s %s failed after %s ms.", request.method, request.url.path, elapsed_ms)
        raise
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    if settings.APP_DEBUG:
        log.debug(
            "%s %s -> %s in %s ms.",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
    elif response.status_code >= 400:
        log.warning(
            "%s %s returned %s in %s ms.",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
    return response

os.makedirs(settings.WORK_DIR, exist_ok=True)


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
def _frontend_redirect(**params: str) -> str:
    if not params:
        return settings.FRONTEND_URL
    separator = "&" if "?" in settings.FRONTEND_URL else "?"
    return f"{settings.FRONTEND_URL}{separator}{urlencode(params)}"


def _clear_oauth_state_cookie(response: Response) -> None:
    response.delete_cookie(
        settings.OAUTH_STATE_COOKIE_NAME,
        path="/",
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


@app.get("/api/auth/github")
def github_login() -> RedirectResponse:
    auth = get_auth()
    state = auth.new_state()
    response = RedirectResponse(auth.authorize_url(state), status_code=302)
    response.set_cookie(
        settings.OAUTH_STATE_COOKIE_NAME,
        state,
        max_age=settings.OAUTH_STATE_TTL_S,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return response


@app.get("/api/auth/github/callback")
async def github_callback(
    code: str | None = None,
    state: str | None = None,
    state_cookie: str | None = Cookie(default=None, alias=settings.OAUTH_STATE_COOKIE_NAME),
) -> RedirectResponse:
    if not state or not state_cookie or not secrets.compare_digest(state, state_cookie):
        response = RedirectResponse(_frontend_redirect(auth_error="state_mismatch"), status_code=302)
        _clear_oauth_state_cookie(response)
        return response
    if not code:
        response = RedirectResponse(_frontend_redirect(auth_error="missing_code"), status_code=302)
        _clear_oauth_state_cookie(response)
        return response
    try:
        user = await get_auth().authenticate_code(code)
    except HTTPException as exc:
        log.warning("GitHub OAuth callback failed: %s.", exc.detail)
        response = RedirectResponse(_frontend_redirect(auth_error="oauth_failed"), status_code=302)
        _clear_oauth_state_cookie(response)
        return response

    token = get_auth().create_session_token(user)
    response = RedirectResponse(settings.FRONTEND_URL, status_code=302)
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        token,
        max_age=settings.SESSION_TTL_S,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    _clear_oauth_state_cookie(response)
    log.info("User signed in with GitHub: %s%s.", user.login, " (admin)" if user.is_admin else "")
    return response


@app.post("/api/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(
        settings.SESSION_COOKIE_NAME,
        path="/",
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True}


@app.post("/api/auth/admin/login")
def admin_login(body: AdminLoginRequest, response: Response) -> dict:
    user = get_auth().authenticate_admin(body.username, body.password)
    token = get_auth().create_session_token(user, auth_method="admin_local")
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        token,
        max_age=settings.SESSION_TTL_S,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    log.info("Admin signed in via local credentials: %s.", user.login)
    return {
        "ok": True,
        "user": {
            "username": user.login,
            "login": user.login,
            "github_id": user.github_id,
            "is_admin": user.is_admin,
            "role": "admin",
            "name": user.name,
            "avatar_url": user.avatar_url,
        },
    }


@app.get("/api/me")
def me(user: AuthenticatedUser = Depends(require_user)) -> dict:
    return {
        "username": user.login,
        "login": user.login,
        "github_id": user.github_id,
        "is_admin": user.is_admin,
        "role": "admin" if user.is_admin else "user",
        "name": user.name,
        "avatar_url": user.avatar_url,
    }


def _get_owned_job(job_id: str, user: AuthenticatedUser, reg: Any) -> Any:
    job = reg.get(job_id)
    if job is None or job.owner_id != user.github_id:
        raise HTTPException(404, "Job not found")
    return job


# --------------------------------------------------------------------------
# Upload + jobs
# --------------------------------------------------------------------------
def _safe_join(base: str, rel: str) -> str:
    """Prevent path traversal from client-supplied relative paths."""
    rel = rel.replace("\\", "/").lstrip("/")
    target = os.path.normpath(os.path.join(base, rel))
    if not target.startswith(os.path.normpath(base) + os.sep) and target != os.path.normpath(base):
        raise HTTPException(400, "Invalid file path")
    return target


@app.post("/api/upload")
async def upload(
    background: BackgroundTasks,
    files: list[UploadFile] = File(...),
    paths: list[str] = Form(default=[]),
    force_refresh: bool = Form(default=False),
    user: AuthenticatedUser = Depends(require_user),
    reg: Any = Depends(get_registry),
    orch: Any = Depends(get_orchestrator),
) -> dict:
    if not files:
        raise HTTPException(400, "No files uploaded")

    job_id = uuid.uuid4().hex
    workdir = os.path.join(settings.WORK_DIR, job_id)
    os.makedirs(workdir, exist_ok=True)
    log.info("Upload started: %s files from %s (job %s).", len(files), user.login, job_id[:8])

    try:
        saved = await save_uploads(files, paths, workdir, job_id[:8])
    except UploadStorageError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - normalize upload storage failures
        shutil.rmtree(workdir, ignore_errors=True)
        log.exception("Upload failed while storing files for job %s.", job_id[:8])
        raise HTTPException(400, f"Upload failed: {type(exc).__name__}: {exc}") from exc
    log.info("Stored upload for job %s: %s files, %s zip archives.", job_id[:8], saved.file_count, saved.zip_count)

    job = reg.create(
        job_id,
        workdir,
        owner_id=user.github_id,
        owner_login=user.login,
        owner_role="admin" if user.is_admin else "user",
        force_refresh=force_refresh,
    )
    background.add_task(orch.run_job, job_id)
    log.info("Upload queued for processing (job %s).", job_id[:8])
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}/status")
def job_status(job_id: str, user: AuthenticatedUser = Depends(require_user),
               reg: Any = Depends(get_registry)) -> dict:
    job = _get_owned_job(job_id, user, reg)
    return job.to_status().model_dump()


@app.post("/api/jobs/{job_id}/stop")
def stop_job(job_id: str, user: AuthenticatedUser = Depends(require_user),
             reg: Any = Depends(get_registry)) -> dict:
    _get_owned_job(job_id, user, reg)
    job = reg.request_cancel(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    log.info("Stop requested for job %s.", job_id[:8])
    return job.to_status().model_dump()


# --------------------------------------------------------------------------
# Engineer view
# --------------------------------------------------------------------------
@app.get("/api/jobs/{job_id}/units")
def units(job_id: str, user: AuthenticatedUser = Depends(require_user),
          reg: Any = Depends(get_registry)) -> dict:
    job = _get_owned_job(job_id, user, reg)
    groups = group_units_by_serial(job.records)
    classification_counts = {"first_pass": 0, "retry_pass": 0, "fail": 0, "unknown": 0}
    for g in groups:
        classification_counts[g.classification] += 1
    return {
        "units": [g.model_dump() for g in groups],
        "run_count": len(job.records),
        "unique_serial_count": len(groups),
        "classification_counts": classification_counts,
    }


@app.post("/api/jobs/{job_id}/units/{unit_id}/reanalyze")
def reanalyze(job_id: str, unit_id: str, user: AuthenticatedUser = Depends(require_user),
              reg: Any = Depends(get_registry),
              analyzer_svc: Any = Depends(get_analyzer_service)) -> dict:
    job = _get_owned_job(job_id, user, reg)
    rec = analyzer_svc.reanalyze_unit(job, unit_id)
    if rec is None:
        raise HTTPException(404, "Unit not found")
    return rec.model_dump()


@app.delete("/api/jobs/{job_id}/cache")
def clear_job_cache(job_id: str, user: AuthenticatedUser = Depends(require_admin),
                    reg: Any = Depends(get_registry),
                    cache: Any = Depends(get_analysis_cache)) -> dict:
    """Delete only the analysis cache entries used by this job's records.

    Cross-upload cache entries not referenced by the currently loaded job are
    left untouched.
    """
    job = _get_owned_job(job_id, user, reg)
    keys = {rec.analysis_cache_key for rec in job.records if rec.analysis_cache_key}
    deleted = 0
    for key in keys:
        if cache.delete_entry(key, actor_id=user.github_id, actor_is_admin=user.is_admin):
            deleted += 1
        rec_matches = [rec for rec in job.records if rec.analysis_cache_key == key]
        for rec in rec_matches:
            rec.analysis_cache_key = None
    log.info("Cleared %s analysis cache entr%s for job %s.", deleted,
             "y" if deleted == 1 else "ies", job_id[:8])
    return {"job_id": job_id, "deleted": deleted}


# --------------------------------------------------------------------------
# Manager view
# --------------------------------------------------------------------------
@app.get("/api/jobs/{job_id}/manager")
def manager(job_id: str, user: AuthenticatedUser = Depends(require_user),
            reg: Any = Depends(get_registry)) -> dict:
    job = _get_owned_job(job_id, user, reg)
    return aggregator.build_manager_view(job.records)


@app.post("/api/logs/frontend")
async def frontend_log(body: FrontendLogRequest) -> dict:
    write_frontend_log(body.level, body.message, body.context)
    return {"ok": True}


@app.get("/api/cache/analysis")
def list_analysis_cache(user: AuthenticatedUser = Depends(require_user),
                        cache: Any = Depends(get_analysis_cache)) -> dict:
    return {"entries": cache.list_entries(actor_is_admin=user.is_admin)}


@app.delete("/api/cache/analysis/{cache_key}")
def clear_analysis_cache(cache_key: str, user: AuthenticatedUser = Depends(require_admin),
                         cache: Any = Depends(get_analysis_cache)) -> dict:
    return {
        "cache_key": cache_key,
        "deleted": cache.delete_entry(cache_key, actor_id=user.github_id, actor_is_admin=user.is_admin),
    }


# --------------------------------------------------------------------------
# Product-aware diagnosis: knowledge pack management
# --------------------------------------------------------------------------
_ALLOWED_DOC_EXTS = {".pdf", ".docx", ".xlsx"}
_KNOWLEDGE_JOB_LIMIT = 50
_knowledge_job_lock = threading.Lock()
_knowledge_jobs: dict[str, dict[str, Any]] = {}


def _sanitize_filename(name: str) -> str:
    base = os.path.basename((name or "").replace("\\", "/"))
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip()
    return cleaned or "document"


def _knowledge_status(store: Any) -> dict:
    manifest = store.load_manifest()
    return {
        "enabled": settings.PRODUCT_KNOWLEDGE_ENABLED,
        "llm_available": is_llm_backend_available(),
        "summary_model": settings.PRODUCT_KNOWLEDGE_SUMMARY_MODEL,
        "source_dirs": settings.PRODUCT_KNOWLEDGE_SOURCE_DIRS,
        "docs_dir": settings.PRODUCT_KNOWLEDGE_DOCS_DIR,
        "manifest": manifest.model_dump() if manifest else None,
    }


@app.get("/api/knowledge")
def knowledge_status(user: str = Depends(require_user),  # noqa: ARG001
                     store: Any = Depends(get_knowledge_store)) -> dict:
    return _knowledge_status(store)


@app.get("/api/knowledge/scan")
def knowledge_scan(user: str = Depends(require_user),  # noqa: ARG001
                   store: Any = Depends(get_knowledge_store)) -> dict:  # noqa: ARG001
    docs = parsing.scan_source_documents()
    return {
        "documents": [
            {
                "doc_id": d.doc_id,
                "filename": d.filename,
                "product_code": d.product_code,
                "category": d.category,
                "source_root": d.source_root,
                "size_bytes": d.size_bytes,
                "warnings": d.warnings,
            }
            for d in docs
        ]
    }


@app.get("/api/knowledge/sections")
def knowledge_sections(product: str | None = None,
                       user: str = Depends(require_user),  # noqa: ARG001
                       store: Any = Depends(get_knowledge_store)) -> dict:
    sections = store.iter_sections()
    if product:
        sections = [s for s in sections if (s.product_code or "UNKNOWN") == product]
    return {"sections": [s.model_dump() for s in sections]}


@app.get("/api/knowledge/sections/{section_id}")
def knowledge_section(section_id: str,
                      user: str = Depends(require_user),  # noqa: ARG001
                      store: Any = Depends(get_knowledge_store)) -> dict:
    for section in store.iter_sections():
        if section.section_id == section_id:
            return section.model_dump()
    raise HTTPException(404, "Section not found")


@app.get("/api/knowledge/acronyms")
def list_acronyms(product: str | None = None, status: str | None = None,
                  user: str = Depends(require_user),  # noqa: ARG001
                  store: Any = Depends(get_acronym_glossary_store)) -> dict:
    entries = store.list_entries(product_code=product, status=status)
    return {
        "enabled": settings.PRODUCT_ACRONYM_GLOSSARY_ENABLED,
        "unknown_append_enabled": settings.PRODUCT_ACRONYM_UNKNOWN_APPEND_ENABLED,
        "entries": [e.model_dump() for e in entries],
    }


@app.post("/api/knowledge/acronyms")
def upsert_acronym(req: AcronymUpsertRequest,
                   user: AuthenticatedUser = Depends(require_admin),  # noqa: ARG001
                   store: Any = Depends(get_acronym_glossary_store)) -> dict:
    acronym = (req.acronym or "").strip()
    if not acronym:
        raise HTTPException(400, "acronym is required")
    if req.status == "approved" and not (req.definition or "").strip():
        raise HTTPException(400, "definition is required to approve an acronym")
    entry = store.upsert_entry(
        acronym=acronym,
        definition=req.definition,
        product_code=req.product_code,
        status=req.status,
        notes=req.notes,
        source="manual",
    )
    log.info("Acronym glossary upsert: %s (%s) -> %s.", entry.acronym, entry.product_code or "global", entry.status)
    return entry.model_dump()


@app.delete("/api/knowledge/acronyms")
def delete_acronym(acronym: str, product: str | None = None,
                   user: AuthenticatedUser = Depends(require_admin),  # noqa: ARG001
                   store: Any = Depends(get_acronym_glossary_store)) -> dict:
    if not store.delete_entry(acronym, product):
        raise HTTPException(404, "Acronym not found")
    log.info("Deleted acronym glossary entry %s (%s).", acronym.upper(), product or "global")
    return {"deleted": acronym.upper(), "product_code": product}


@app.post("/api/knowledge/upload")
async def knowledge_upload(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(require_admin),  # noqa: ARG001
    ingestion: Any = Depends(get_knowledge_ingestion),
    retriever: Any = Depends(get_knowledge_retriever),
) -> dict:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_DOC_EXTS:
        raise HTTPException(400, f"Unsupported document type: {ext or 'unknown'} (PDF/DOCX/XLSX only)")
    os.makedirs(settings.PRODUCT_KNOWLEDGE_DOCS_DIR, exist_ok=True)
    dest = os.path.join(settings.PRODUCT_KNOWLEDGE_DOCS_DIR, _sanitize_filename(file.filename))
    size = 0
    limit = settings.PRODUCT_KNOWLEDGE_UPLOAD_MAX_BYTES
    try:
        with open(dest, "wb") as fh:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    fh.close()
                    os.remove(dest)
                    raise HTTPException(400, f"Document exceeds size limit ({limit} bytes)")
                fh.write(chunk)
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(400, f"Could not store document: {exc}") from exc
    log.info("Product doc uploaded: %s (%s bytes).", os.path.basename(dest), size)
    job = _create_knowledge_job("upload", os.path.basename(dest))
    background.add_task(_run_uploaded_document_knowledge_job, job["job_id"], ingestion, retriever, dest)
    return {"filename": os.path.basename(dest), "job_id": job["job_id"], "job": job}


@app.get("/api/knowledge/jobs/{job_id}")
def knowledge_job(job_id: str, user: str = Depends(require_user)) -> dict:  # noqa: ARG001
    job = _knowledge_job_snapshot(job_id)
    if job is None:
        raise HTTPException(404, "Knowledge job not found")
    return job


@app.post("/api/knowledge/rebuild")
def knowledge_rebuild(user: AuthenticatedUser = Depends(require_admin),  # noqa: ARG001
                      ingestion: Any = Depends(get_knowledge_ingestion),
                      retriever: Any = Depends(get_knowledge_retriever)) -> dict:
    return {"manifest": _rebuild_knowledge(ingestion, retriever)}


@app.delete("/api/knowledge/documents/{doc_id}")
def knowledge_delete_document(doc_id: str,
                              user: AuthenticatedUser = Depends(require_admin),  # noqa: ARG001
                              ingestion: Any = Depends(get_knowledge_ingestion),
                              retriever: Any = Depends(get_knowledge_retriever)) -> dict:
    search_dirs = [*settings.PRODUCT_KNOWLEDGE_SOURCE_DIRS, settings.PRODUCT_KNOWLEDGE_DOCS_DIR]
    allowed_roots = [
        os.path.normcase(os.path.abspath(root))
        for root in search_dirs
        if root and os.path.isdir(root)
    ]
    target = next(
        (doc for doc in parsing.scan_source_documents(source_dirs=search_dirs)
         if doc.doc_id == doc_id),
        None,
    )
    removed_filename: str | None = None
    if target is not None:
        doc_path = os.path.abspath(target.path)
        if not any(
            os.path.normcase(doc_path).startswith(root + os.sep) for root in allowed_roots
        ):
            raise HTTPException(403, "Document is outside the allowed knowledge directories.")
        try:
            os.remove(doc_path)
        except OSError as exc:
            raise HTTPException(500, f"Could not delete document: {type(exc).__name__}") from exc
        removed_filename = target.filename
    # Prune the doc from the curated pack directly — no LLM rebuild needed, so
    # deletion is instant and works even without a summarization backend.
    manifest, pruned = ingestion.remove_document(doc_id)
    if target is None and not pruned:
        raise HTTPException(404, "Document not found in the product-knowledge sources.")
    retriever.invalidate()
    log.info("Deleted product doc %s (%s).", doc_id, removed_filename or doc_id)
    return {
        "deleted": removed_filename or doc_id,
        "manifest": manifest.model_dump() if manifest else None,
    }


@app.delete("/api/knowledge")
def knowledge_delete_pack(user: AuthenticatedUser = Depends(require_admin),  # noqa: ARG001
                          store: Any = Depends(get_knowledge_store),
                          retriever: Any = Depends(get_knowledge_retriever)) -> dict:
    store.delete_pack()
    retriever.invalidate()
    log.info("Deleted the entire product-knowledge pack.")
    return {"ok": True}


def _rebuild_knowledge(ingestion: Any, retriever: Any) -> dict | None:
    try:
        manifest = ingestion.rebuild()
    except ProductKnowledgeError as exc:
        raise HTTPException(503, str(exc)) from exc
    retriever.invalidate()
    return manifest.model_dump()


def _build_uploaded_document_knowledge(
    ingestion: Any,
    retriever: Any,
    path: str,
    progress: Any | None = None,
) -> dict | None:
    doc = parsing.describe_document(path, source_root=settings.PRODUCT_KNOWLEDGE_DOCS_DIR)
    try:
        if hasattr(ingestion, "build"):
            manifest = ingestion.build([doc], progress=progress)
        else:
            manifest = ingestion.rebuild()
    except ProductKnowledgeError as exc:
        raise HTTPException(503, str(exc)) from exc
    retriever.invalidate()
    return manifest.model_dump()


def _create_knowledge_job(kind: str, filename: str | None = None) -> dict:
    job = {
        "job_id": uuid.uuid4().hex,
        "kind": kind,
        "filename": filename,
        "status": "pending",
        "progress": {"processed": 0, "total": 1},
        "message": "Queued",
        "error": None,
        "manifest": None,
    }
    with _knowledge_job_lock:
        _knowledge_jobs[job["job_id"]] = job
        while len(_knowledge_jobs) > _KNOWLEDGE_JOB_LIMIT:
            oldest = next(iter(_knowledge_jobs))
            _knowledge_jobs.pop(oldest, None)
    return _copy_knowledge_job(job)


def _knowledge_job_snapshot(job_id: str) -> dict | None:
    with _knowledge_job_lock:
        job = _knowledge_jobs.get(job_id)
        return _copy_knowledge_job(job) if job else None


def _update_knowledge_job(job_id: str, **updates: Any) -> None:
    with _knowledge_job_lock:
        job = _knowledge_jobs.get(job_id)
        if job is None:
            return
        job.update(updates)


def _copy_knowledge_job(job: dict[str, Any]) -> dict[str, Any]:
    copied = dict(job)
    copied["progress"] = dict(job.get("progress") or {})
    return copied


def _run_uploaded_document_knowledge_job(
    job_id: str, ingestion: Any, retriever: Any, path: str
) -> None:
    filename = os.path.basename(path)
    _update_knowledge_job(
        job_id,
        status="running",
        progress={"processed": 0, "total": 1},
        message=f"Preparing {filename}",
    )

    def progress(processed: int, total: int, message: str) -> None:
        _update_knowledge_job(
            job_id,
            status="running",
            progress={"processed": processed, "total": max(1, total)},
            message=message,
        )

    try:
        manifest = _build_uploaded_document_knowledge(ingestion, retriever, path, progress=progress)
    except Exception as exc:  # noqa: BLE001 - surface ingestion failures through job status
        detail = getattr(exc, "detail", None) or str(exc) or type(exc).__name__
        log.exception("Knowledge upload job %s failed for %s.", job_id[:8], filename)
        _update_knowledge_job(job_id, status="error", message=str(detail), error=str(detail))
        return

    _update_knowledge_job(
        job_id,
        status="done",
        progress={"processed": 1, "total": 1},
        message=f"Ingested {filename}",
        manifest=manifest,
    )


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "llm_provider": settings.LLM_PROVIDER, "debug": settings.APP_DEBUG}


# --------------------------------------------------------------------------
# Static frontend (built React assets), served last so /api takes precedence.
# --------------------------------------------------------------------------
_FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.isdir(_FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(_FRONTEND_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        index = os.path.join(_FRONTEND_DIST, "index.html")
        return FileResponse(index)

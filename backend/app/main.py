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
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import aggregator
from .auth import get_auth, require_user
from .config import settings
from .dependencies import (
    get_analysis_cache,
    get_analyzer_service,
    get_knowledge_ingestion,
    get_knowledge_retriever,
    get_knowledge_store,
    get_orchestrator,
    get_registry,
)
from .knowledge import parsing
from .knowledge.summarizer import ProductKnowledgeError, is_llm_backend_available
from .logging_config import setup_backend_logging, write_frontend_log
from .models import FrontendLogRequest, LoginRequest, LoginResponse
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
@app.post("/api/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    token = get_auth().login(body.username, body.password)
    log.info("User signed in: %s.", body.username)
    return LoginResponse(token=token, username=body.username)


@app.get("/api/me")
def me(user: str = Depends(require_user)) -> dict:
    return {"username": user}


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
    user: str = Depends(require_user),
    reg: Any = Depends(get_registry),
    orch: Any = Depends(get_orchestrator),
) -> dict:
    if not files:
        raise HTTPException(400, "No files uploaded")

    job_id = uuid.uuid4().hex
    workdir = os.path.join(settings.WORK_DIR, job_id)
    os.makedirs(workdir, exist_ok=True)
    log.info("Upload started: %s files from %s (job %s).", len(files), user, job_id[:8])

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

    reg.create(job_id, workdir)
    background.add_task(orch.run_job, job_id)
    log.info("Upload queued for processing (job %s).", job_id[:8])
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}/status")
def job_status(job_id: str, user: str = Depends(require_user),
               reg: Any = Depends(get_registry)) -> dict:
    job = reg.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job.to_status().model_dump()


@app.post("/api/jobs/{job_id}/stop")
def stop_job(job_id: str, user: str = Depends(require_user),  # noqa: ARG001
             reg: Any = Depends(get_registry)) -> dict:
    job = reg.request_cancel(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    log.info("Stop requested for job %s.", job_id[:8])
    return job.to_status().model_dump()


# --------------------------------------------------------------------------
# Engineer view
# --------------------------------------------------------------------------
@app.get("/api/jobs/{job_id}/units")
def units(job_id: str, user: str = Depends(require_user),
          reg: Any = Depends(get_registry)) -> dict:
    job = reg.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
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
def reanalyze(job_id: str, unit_id: str, user: str = Depends(require_user),
              reg: Any = Depends(get_registry),
              analyzer_svc: Any = Depends(get_analyzer_service)) -> dict:
    job = reg.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    rec = analyzer_svc.reanalyze_unit(job, unit_id)
    if rec is None:
        raise HTTPException(404, "Unit not found")
    return rec.model_dump()


@app.delete("/api/jobs/{job_id}/cache")
def clear_job_cache(job_id: str, user: str = Depends(require_user),  # noqa: ARG001
                    reg: Any = Depends(get_registry),
                    cache: Any = Depends(get_analysis_cache)) -> dict:
    """Delete only the analysis cache entries used by this job's records.

    Cross-upload cache entries not referenced by the currently loaded job are
    left untouched.
    """
    job = reg.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    keys = {rec.analysis_cache_key for rec in job.records if rec.analysis_cache_key}
    deleted = 0
    for key in keys:
        if cache.delete_entry(key):
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
def manager(job_id: str, user: str = Depends(require_user),
            reg: Any = Depends(get_registry)) -> dict:
    job = reg.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return aggregator.build_manager_view(job.records)


@app.post("/api/logs/frontend")
async def frontend_log(body: FrontendLogRequest) -> dict:
    write_frontend_log(body.level, body.message, body.context)
    return {"ok": True}


@app.get("/api/cache/analysis")
def list_analysis_cache(user: str = Depends(require_user),
                        cache: Any = Depends(get_analysis_cache)) -> dict:  # noqa: ARG001
    return {"entries": cache.list_entries()}


@app.delete("/api/cache/analysis/{cache_key}")
def clear_analysis_cache(cache_key: str, user: str = Depends(require_user),
                         cache: Any = Depends(get_analysis_cache)) -> dict:  # noqa: ARG001
    return {"cache_key": cache_key, "deleted": cache.delete_entry(cache_key)}


# --------------------------------------------------------------------------
# Product-aware diagnosis: knowledge pack management
# --------------------------------------------------------------------------
_ALLOWED_DOC_EXTS = {".pdf", ".docx"}


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


@app.post("/api/knowledge/upload")
async def knowledge_upload(
    file: UploadFile = File(...),
    user: str = Depends(require_user),  # noqa: ARG001
    ingestion: Any = Depends(get_knowledge_ingestion),
    retriever: Any = Depends(get_knowledge_retriever),
) -> dict:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_DOC_EXTS:
        raise HTTPException(400, f"Unsupported document type: {ext or 'unknown'} (PDF/DOCX only)")
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
    manifest = await run_in_threadpool(_build_uploaded_document_knowledge, ingestion, retriever, dest)
    return {"filename": os.path.basename(dest), "manifest": manifest}


@app.post("/api/knowledge/rebuild")
def knowledge_rebuild(user: str = Depends(require_user),  # noqa: ARG001
                      ingestion: Any = Depends(get_knowledge_ingestion),
                      retriever: Any = Depends(get_knowledge_retriever)) -> dict:
    return {"manifest": _rebuild_knowledge(ingestion, retriever)}


@app.delete("/api/knowledge/documents/{doc_id}")
def knowledge_delete_document(doc_id: str,
                              user: str = Depends(require_user),  # noqa: ARG001
                              ingestion: Any = Depends(get_knowledge_ingestion),
                              retriever: Any = Depends(get_knowledge_retriever)) -> dict:
    docs_dir = settings.PRODUCT_KNOWLEDGE_DOCS_DIR
    removed = None
    if os.path.isdir(docs_dir):
        for name in os.listdir(docs_dir):
            path = os.path.join(docs_dir, name)
            if not os.path.isfile(path):
                continue
            if parsing.describe_document(path, source_root=docs_dir).doc_id == doc_id:
                os.remove(path)
                removed = name
                break
    if removed is None:
        raise HTTPException(
            404,
            "Document not found among uploaded product docs "
            "(only uploaded docs are deletable).",
        )
    log.info("Deleted product doc %s (%s).", doc_id, removed)
    return {"deleted": removed, "manifest": _rebuild_knowledge(ingestion, retriever)}


@app.delete("/api/knowledge")
def knowledge_delete_pack(user: str = Depends(require_user),  # noqa: ARG001
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


def _build_uploaded_document_knowledge(ingestion: Any, retriever: Any, path: str) -> dict | None:
    doc = parsing.describe_document(path, source_root=settings.PRODUCT_KNOWLEDGE_DOCS_DIR)
    try:
        if hasattr(ingestion, "build"):
            manifest = ingestion.build([doc])
        else:
            manifest = ingestion.rebuild()
    except ProductKnowledgeError as exc:
        raise HTTPException(503, str(exc)) from exc
    retriever.invalidate()
    return manifest.model_dump()


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

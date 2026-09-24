"""FastAPI app: auth, upload, job status, engineer & manager views, static serving.

Phase 7 (SOLID refactor): routes depend on abstract service providers from
``dependencies.py`` rather than importing concrete module globals directly.
``app.dependency_overrides`` can be used in tests to inject alternative
implementations without monkeypatching module-level singletons.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import aggregator, comparison
from .auth import AuthenticatedUser, get_auth, require_admin, require_user
from .config import settings
from .dependencies import (
    get_analysis_cache,
    get_analyzer_service,
    get_acronym_glossary_store,
    get_feedback_store,
    get_investigation_action_store,
    get_knowledge_ingestion,
    get_knowledge_retriever,
    get_knowledge_store,
    get_orchestrator,
    get_playbook_store,
    get_registry,
)
from .knowledge import parsing
from .knowledge.models import PlaybookCreateRequest, PlaybookUpdateRequest
from .knowledge.summarizer import ProductKnowledgeError, is_llm_backend_available
from .logging_config import setup_backend_logging, write_frontend_log
from .models import AcronymUpsertRequest, AdminLoginRequest, BatchMetadata, FeedbackCreateRequest, FeedbackEntry, FrontendLogRequest, InvestigationActionCreateRequest, InvestigationActionEntry, InvestigationActionEvent, InvestigationActionUpdateRequest, JobListResponse, JobSummary
from .investigation_action_store import ActionNotFound, ActionStoreUnavailable, ActionVersionConflict
from .redaction import redact
from .record_views import build_debug_packet, group_units_by_serial
from .upload_storage import UploadStorageError, save_uploads

setup_backend_logging(settings.APP_DEBUG)
log = logging.getLogger("cotrace.main")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    settings.validate_enterprise_only()
    log.info(
        "Backend started. Provider: %s. Debug: %s. Work dir: %s. Copilot host: %s. Copilot token configured: %s.",
        settings.LLM_PROVIDER,
        settings.APP_DEBUG,
        settings.WORK_DIR,
        settings.COPILOT_GH_HOST,
        bool(settings.COPILOT_GITHUB_TOKEN),
    )
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
    if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        allowed_origins = {*settings.CORS_ORIGINS, settings.FRONTEND_URL.rstrip("/")}
        if (origin and origin not in allowed_origins) or (
            not origin and request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return JSONResponse(status_code=403, content={"detail": "Request origin is not allowed"})
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
@app.get("/api/auth/github")
@app.get("/api/auth/github/callback")
def github_login_unavailable() -> None:
    raise HTTPException(410, "GitHub sign-in is no longer used. Open the shared workspace.")


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
    token = get_auth().create_session_token(user, auth_method="admin_shared")
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
            "workspace_id": user.github_id,
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
        "workspace_id": user.github_id,
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
        batch=BatchMetadata(
            display_name=_batch_display_name(paths, files, job_id),
            source_file_count=saved.file_count,
            source_zip_count=saved.zip_count,
        ),
    )
    background.add_task(orch.run_job, job_id)
    log.info("Upload queued for processing (job %s).", job_id[:8])
    return {"job_id": job_id}


def _batch_display_name(paths: list[str], files: list[UploadFile], job_id: str) -> str:
    normalized = [path.replace("\\", "/").strip("/") for path in paths if path]
    roots = {path.split("/", 1)[0] for path in normalized if "/" in path}
    if len(roots) == 1:
        return next(iter(roots))[:120]
    filenames = [os.path.basename(path) for path in normalized] or [upload.filename or "" for upload in files]
    if len(filenames) == 1 and filenames[0]:
        return filenames[0][:120]
    return f"Batch {job_id[:8]}"


@app.get("/api/jobs/{job_id}/status")
def job_status(job_id: str, user: AuthenticatedUser = Depends(require_user),
               reg: Any = Depends(get_registry)) -> dict:
    job = _get_owned_job(job_id, user, reg)
    return job.to_status().model_dump()


def _encode_job_cursor(job: Any) -> str:
    payload = json.dumps([job.created_at, job.job_id], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_job_cursor(cursor: str | None) -> tuple[float, str] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if not isinstance(value, list) or len(value) != 2 or not isinstance(value[1], str):
            raise ValueError
        return float(value[0]), value[1]
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "Invalid jobs cursor") from exc


@app.get("/api/jobs", response_model=JobListResponse)
def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    user: AuthenticatedUser = Depends(require_user),
    reg: Any = Depends(get_registry),
) -> JobListResponse:
    jobs, has_more = reg.list_owned(
        user.github_id,
        limit=limit,
        before=_decode_job_cursor(cursor),
    )
    items = [
        JobSummary(
            job_id=job.job_id,
            display_name=job.batch.display_name or f"Batch {job.job_id[:8]}",
            status=job.status,
            progress=job.to_status().progress,
            message=job.message,
            created_at=job.created_at,
            completed_at=job.completed_at,
            result_available=job.status == "done",
            unit_count=len(job.records),
            batch=job.batch,
        )
        for job in jobs
    ]
    next_cursor = _encode_job_cursor(jobs[-1]) if has_more and jobs else None
    return JobListResponse(items=items, next_cursor=next_cursor)


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


@app.get("/api/jobs/{job_id}/clusters")
def clusters(job_id: str, user: AuthenticatedUser = Depends(require_user),
             reg: Any = Depends(get_registry)) -> dict:
    job = _get_owned_job(job_id, user, reg)
    return {"clusters": aggregator.compute_failure_clusters(job.records)}


@app.get("/api/jobs/{job_id}/debug-packet", response_class=PlainTextResponse)
def debug_packet(job_id: str, unit_id: str | None = None, signature: str | None = None,
                 user: AuthenticatedUser = Depends(require_user),
                 reg: Any = Depends(get_registry)) -> PlainTextResponse:
    job = _get_owned_job(job_id, user, reg)
    try:
        content = build_debug_packet(job.records, unit_id=unit_id, signature=signature)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return PlainTextResponse(
        content,
        media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="co-trace-debug-packet.md"'},
    )


@app.get("/api/jobs/{job_id}/feedback")
def list_feedback(job_id: str, user: AuthenticatedUser = Depends(require_user),
                  reg: Any = Depends(get_registry),
                  store: Any = Depends(get_feedback_store)) -> dict:
    _get_owned_job(job_id, user, reg)
    entries = store.list_for_job(job_id, user.github_id)
    return {"entries": [entry.model_dump() for entry in entries]}


@app.post("/api/jobs/{job_id}/feedback")
def create_feedback(req: FeedbackCreateRequest, job_id: str,
                    user: AuthenticatedUser = Depends(require_user),
                    reg: Any = Depends(get_registry),
                    store: Any = Depends(get_feedback_store)) -> dict:
    job = _get_owned_job(job_id, user, reg)
    record = next((item for item in job.records if item.unit_id == req.unit_id), None)
    if record is None or record.result != "FAIL":
        raise HTTPException(404, "Failed attempt not found")
    entry = FeedbackEntry(
        feedback_id=uuid.uuid4().hex,
        job_id=job_id,
        owner_id=user.github_id,
        owner_login=user.login,
        unit_id=record.unit_id,
        signature=record.signature,
        cache_key=record.analysis_cache_key,
        product_code=record.product_code,
        op_id=record.op_id,
        error_code=record.error_code,
        error_message=redact(record.error_message)[:500] or None,
        failing_step=record.failing_step,
        analysis_source=record.analysis_source,
        action=req.action,
        note=redact(req.note)[:2000] or None,
        created_at=datetime.now(timezone.utc).isoformat(),
        expires_at=job.created_at + settings.JOB_TTL_S,
    )
    store.add(entry)
    return entry.model_dump()


@app.get("/api/jobs/{job_id}/actions")
def list_investigation_actions(
    job_id: str,
    user: AuthenticatedUser = Depends(require_user),
    reg: Any = Depends(get_registry),
    store: Any = Depends(get_investigation_action_store),
) -> dict:
    _get_owned_job(job_id, user, reg)
    try:
        entries = store.list_for_job(job_id, user.github_id)
    except ActionStoreUnavailable as exc:
        raise _action_store_unavailable() from exc
    return {"entries": [entry.model_dump() for entry in entries]}


@app.post("/api/jobs/{job_id}/actions")
def create_investigation_action(
    request: InvestigationActionCreateRequest,
    job_id: str,
    user: AuthenticatedUser = Depends(require_user),
    reg: Any = Depends(get_registry),
    store: Any = Depends(get_investigation_action_store),
) -> dict:
    job = _get_owned_job(job_id, user, reg)
    if bool(request.unit_id) == bool(request.signature):
        raise HTTPException(400, "Provide exactly one unit_id or signature")
    matching = [
        record for record in job.records
        if record.result == "FAIL" and (
            (request.unit_id and record.unit_id == request.unit_id) or
            (request.signature and record.signature == request.signature)
        )
    ]
    if not matching:
        raise HTTPException(404, "Failed attempt or failure family not found")
    now = datetime.now(timezone.utc).isoformat()
    next_action = redact(request.next_action)[:2000].strip()
    if not next_action:
        raise HTTPException(400, "Next action is empty after redaction")
    assignee = redact(request.assignee)[:120].strip() or None
    representative = matching[0]
    event = InvestigationActionEvent(
        version=1,
        actor_id=user.github_id,
        actor_login=user.login,
        changed_at=now,
        status=request.status,
        assignee=assignee,
        next_action=next_action,
    )
    entry = InvestigationActionEntry(
        action_id=uuid.uuid4().hex,
        job_id=job_id,
        owner_id=user.github_id,
        owner_login=user.login,
        unit_id=request.unit_id,
        signature=request.signature,
        product_code=representative.product_code,
        error_code=representative.error_code,
        assignee=assignee,
        next_action=next_action,
        status=request.status,
        created_at=now,
        updated_at=now,
        expires_at=job.created_at + settings.JOB_TTL_S,
        history=[event],
    )
    try:
        return store.create(entry).model_dump()
    except ActionStoreUnavailable as exc:
        raise _action_store_unavailable() from exc


@app.patch("/api/jobs/{job_id}/actions/{action_id}")
def update_investigation_action(
    request: InvestigationActionUpdateRequest,
    job_id: str,
    action_id: str,
    user: AuthenticatedUser = Depends(require_user),
    reg: Any = Depends(get_registry),
    store: Any = Depends(get_investigation_action_store),
) -> dict:
    _get_owned_job(job_id, user, reg)
    fields_set = set(request.model_fields_set)
    next_action = redact(request.next_action)[:2000].strip() if request.next_action is not None else None
    assignee = redact(request.assignee)[:120].strip() if request.assignee is not None else None
    if "next_action" in fields_set and not next_action:
        raise HTTPException(400, "Next action is empty after redaction")
    try:
        updated = store.update(
            action_id,
            job_id,
            user.github_id,
            request.expected_version,
            actor_id=user.github_id,
            actor_login=user.login,
            assignee=assignee,
            next_action=next_action,
            status=request.status,
            fields_set=fields_set,
        )
    except ActionNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except ActionVersionConflict as exc:
        raise HTTPException(409, {"message": str(exc), "current": exc.current.model_dump()}) from exc
    except ActionStoreUnavailable as exc:
        raise _action_store_unavailable() from exc
    return updated.model_dump()


def _action_store_unavailable() -> HTTPException:
    return HTTPException(503, {
        "error": "actions_unavailable",
        "message": "Investigation actions are temporarily unavailable. Retry or contact the administrator.",
    })


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
def manager(
    job_id: str,
    product: list[str] = Query(default=[]),
    lot: list[str] = Query(default=[]),
    station: list[str] = Query(default=[]),
    start_time: str | None = Query(default=None),
    end_time: str | None = Query(default=None),
    user: AuthenticatedUser = Depends(require_user),
    reg: Any = Depends(get_registry),
) -> dict:
    job = _get_owned_job(job_id, user, reg)
    try:
        view = aggregator.build_manager_view(
            job.records,
            product_codes=set(product),
            lot_ids=set(lot),
            station_keys=set(station),
            start_time=start_time,
            end_time=end_time,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    view["batch"] = job.batch.model_dump()
    return view


@app.get("/api/jobs/{job_id}/comparison")
def manager_comparison(
    job_id: str,
    product: list[str] = Query(default=[]),
    lot: list[str] = Query(default=[]),
    station: list[str] = Query(default=[]),
    target_metric: str | None = Query(default=None),
    target_percent: float | None = Query(default=None, ge=0, le=100),
    user: AuthenticatedUser = Depends(require_user),
    reg: Any = Depends(get_registry),
) -> dict:
    job = _get_owned_job(job_id, user, reg)
    candidates, next_cursor = reg.list_owned(user.github_id, limit=10000)
    return comparison.compare_jobs(
        job,
        candidates,
        product_codes=set(product),
        lot_ids=set(lot),
        station_keys=set(station),
        target_metric=target_metric,
        target_percent=target_percent,
        history_complete=next_cursor is None,
    )


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


def _uploaded_document_state(filename: str, store: Any) -> dict:
    safe_filename = _sanitize_filename(filename)
    dest = os.path.join(settings.PRODUCT_KNOWLEDGE_DOCS_DIR, safe_filename)
    exists = os.path.isfile(dest)
    doc_id = None
    product_code = None
    category = None
    size_bytes = 0
    knowledge_exists = False
    if exists:
        doc = parsing.describe_document(dest, source_root=settings.PRODUCT_KNOWLEDGE_DOCS_DIR)
        doc_id = doc.doc_id
        product_code = doc.product_code
        category = doc.category
        size_bytes = doc.size_bytes
        manifest = store.load_manifest()
        knowledge_exists = bool(
            manifest and any(meta.doc_id == doc.doc_id for meta in manifest.documents)
        )
    return {
        "filename": safe_filename,
        "exists": exists,
        "knowledge_exists": knowledge_exists,
        "doc_id": doc_id,
        "product_code": product_code,
        "category": category,
        "size_bytes": size_bytes,
    }


@app.get("/api/knowledge")
def knowledge_status(user: str = Depends(require_user),  # noqa: ARG001
                     store: Any = Depends(get_knowledge_store)) -> dict:
    return _knowledge_status(store)


@app.get("/api/knowledge/upload/check")
def knowledge_upload_check(filename: str,
                           user: AuthenticatedUser = Depends(require_admin),  # noqa: ARG001
                           store: Any = Depends(get_knowledge_store)) -> dict:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in _ALLOWED_DOC_EXTS:
        raise HTTPException(400, f"Unsupported document type: {ext or 'unknown'} (PDF/DOCX/XLSX only)")
    return _uploaded_document_state(filename, store)


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


@app.get("/api/knowledge/playbooks")
def list_playbooks(product: str | None = None, status: str | None = None,
                   user: AuthenticatedUser = Depends(require_user),  # noqa: ARG001
                   store: Any = Depends(get_playbook_store)) -> dict:
    return {"entries": [
        entry.model_dump()
        for entry in store.list_entries(product_code=product, review_status=status)
    ]}


@app.post("/api/knowledge/playbooks")
def create_playbook(req: PlaybookCreateRequest,
                    user: AuthenticatedUser = Depends(require_admin),
                    store: Any = Depends(get_playbook_store)) -> dict:
    entry = store.create(uuid.uuid4().hex, req, owner=user.login)
    return entry.model_dump()


@app.patch("/api/knowledge/playbooks/{playbook_id}")
def update_playbook(playbook_id: str, req: PlaybookUpdateRequest,
                    user: AuthenticatedUser = Depends(require_admin),  # noqa: ARG001
                    store: Any = Depends(get_playbook_store)) -> dict:
    entry = store.update(playbook_id, req)
    if entry is None:
        raise HTTPException(404, "Playbook not found")
    return entry.model_dump()


@app.delete("/api/knowledge/playbooks/{playbook_id}")
def retire_playbook(playbook_id: str,
                    user: AuthenticatedUser = Depends(require_admin),  # noqa: ARG001
                    store: Any = Depends(get_playbook_store)) -> dict:
    entry = store.retire(playbook_id)
    if entry is None:
        raise HTTPException(404, "Playbook not found")
    return entry.model_dump()


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
    duplicate_policy: str = Form("error"),
    user: AuthenticatedUser = Depends(require_admin),  # noqa: ARG001
    ingestion: Any = Depends(get_knowledge_ingestion),
    retriever: Any = Depends(get_knowledge_retriever),
    store: Any = Depends(get_knowledge_store),
) -> dict:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_DOC_EXTS:
        raise HTTPException(400, f"Unsupported document type: {ext or 'unknown'} (PDF/DOCX/XLSX only)")
    os.makedirs(settings.PRODUCT_KNOWLEDGE_DOCS_DIR, exist_ok=True)
    existing = _uploaded_document_state(file.filename or "", store)
    policy = (duplicate_policy or "error").strip().lower()
    if policy not in {"error", "replace", "keep"}:
        raise HTTPException(400, "duplicate_policy must be one of: error, replace, keep")
    dest = os.path.join(settings.PRODUCT_KNOWLEDGE_DOCS_DIR, existing["filename"])
    if existing["exists"] and policy == "error":
        raise HTTPException(409, f"{existing['filename']} already exists in the product-docs folder.")
    if existing["exists"] and policy == "keep":
        await file.close()
        if existing["knowledge_exists"]:
            return {
                "filename": existing["filename"],
                "job_id": None,
                "job": None,
                "kept_existing": True,
                "knowledge_exists": True,
                "message": f"Kept existing {existing['filename']}; knowledge already exists.",
            }
        job = _create_knowledge_job("upload", existing["filename"])
        background.add_task(_run_uploaded_document_knowledge_job, job["job_id"], ingestion, retriever, dest)
        return {
            "filename": existing["filename"],
            "job_id": job["job_id"],
            "job": job,
            "kept_existing": True,
            "knowledge_exists": False,
        }
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
    return {
        "filename": os.path.basename(dest),
        "job_id": job["job_id"],
        "job": job,
        "replaced_existing": existing["exists"] and policy == "replace",
    }


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
    removed_filename: str | None = target.filename if target is not None else None
    if target is not None:
        doc_path = os.path.abspath(target.path)
        if not any(
            os.path.normcase(doc_path).startswith(root + os.sep) for root in allowed_roots
        ):
            raise HTTPException(403, "Document is outside the allowed knowledge directories.")
    # Prune the doc from the curated pack directly — no LLM rebuild needed, so
    # deletion is instant and works even without a summarization backend.
    manifest, pruned = ingestion.remove_document(doc_id)
    if target is None and not pruned:
        raise HTTPException(404, "Document not found in the product-knowledge sources.")
    retriever.invalidate()
    log.info("Removed product doc %s (%s) from knowledge pack.", doc_id, removed_filename or doc_id)
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
    source_dirs = [*settings.PRODUCT_KNOWLEDGE_SOURCE_DIRS, settings.PRODUCT_KNOWLEDGE_DOCS_DIR]
    docs = parsing.scan_source_documents(source_dirs=source_dirs)
    try:
        if hasattr(ingestion, "build"):
            manifest = ingestion.build(docs, progress=progress)
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
    from . import copilot_client  # noqa: PLC0415

    return {
        "status": "ok",
        "llm_provider": settings.LLM_PROVIDER,
        "copilot_gh_host": settings.COPILOT_GH_HOST,
        "debug": settings.APP_DEBUG,
        "llm_auth": {
            "copilot_sdk_available": copilot_client.is_available(),
            "copilot_token_configured": bool(settings.COPILOT_GITHUB_TOKEN),
        },
    }


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

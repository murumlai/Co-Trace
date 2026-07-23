"""FastAPI app: auth, upload, job status, engineer & manager views, static serving.

Phase 7 (SOLID refactor): routes depend on abstract service providers from
``dependencies.py`` rather than importing concrete module globals directly.
``app.dependency_overrides`` can be used in tests to inject alternative
implementations without monkeypatching module-level singletons.
"""
from __future__ import annotations

import logging
import os
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import aggregator
from .auth import get_auth, require_user
from .config import settings
from .dependencies import get_analysis_cache, get_analyzer_service, get_orchestrator, get_registry
from .logging_config import setup_backend_logging, write_frontend_log
from .models import FrontendLogRequest, LoginRequest, LoginResponse
from .record_views import latest_records_by_serial
from .upload_storage import UploadStorageError, save_uploads

setup_backend_logging(settings.APP_DEBUG)
log = logging.getLogger("cotrace.main")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    log.info("Backend started. Provider: %s. Debug: %s. Work dir: %s.", settings.LLM_PROVIDER, settings.APP_DEBUG, settings.WORK_DIR)
    get_registry().load_from_disk()
    yield
    log.info("Backend stopped.")


app = FastAPI(title="Co_Trace — Manufacturing Log Dashboard", lifespan=lifespan)

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
    latest_units = latest_records_by_serial(job.records)
    return {
        "units": [r.model_dump() for r in latest_units],
        "run_count": len(job.records),
        "unique_serial_count": len(latest_units),
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

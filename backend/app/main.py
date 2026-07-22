"""FastAPI app: auth, upload, job status, engineer & manager views, static serving."""
from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import aggregator, analyzer, orchestrator
from .auth import get_auth, require_user
from .config import settings
from .job_registry import registry
from .logging_config import setup_backend_logging, write_frontend_log
from .models import FrontendLogRequest, LoginRequest, LoginResponse

setup_backend_logging(settings.APP_DEBUG)
log = logging.getLogger("cotrace.main")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    log.info("backend startup provider=%s debug=%s work_dir=%s", settings.LLM_PROVIDER, settings.APP_DEBUG, settings.WORK_DIR)
    registry.load_from_disk()
    yield
    log.info("backend shutdown")


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
        log.debug("request start method=%s path=%s", request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        log.exception("request failed method=%s path=%s elapsed_ms=%s", request.method, request.url.path, elapsed_ms)
        raise
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    if settings.APP_DEBUG:
        log.debug(
            "request done method=%s path=%s status=%s elapsed_ms=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
    elif response.status_code >= 400:
        log.warning(
            "request warning method=%s path=%s status=%s elapsed_ms=%s",
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
    log.info("login success username=%s", body.username)
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
) -> dict:
    if not files:
        raise HTTPException(400, "No files uploaded")

    job_id = uuid.uuid4().hex
    workdir = os.path.join(settings.WORK_DIR, job_id)
    os.makedirs(workdir, exist_ok=True)
    log.info("upload start job_id=%s user=%s file_count=%s", job_id, user, len(files))

    for i, uf in enumerate(files):
        rel = paths[i] if i < len(paths) and paths[i] else (uf.filename or f"file_{i}")
        dest = _safe_join(workdir, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as out:
            out.write(await uf.read())
        if settings.APP_DEBUG:
            log.debug("upload saved job_id=%s rel=%s", job_id, rel)

    registry.create(job_id, workdir)
    background.add_task(orchestrator.run_job, job_id)
    log.info("upload queued job_id=%s", job_id)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}/status")
def job_status(job_id: str, user: str = Depends(require_user)) -> dict:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job.to_status().model_dump()


# --------------------------------------------------------------------------
# Engineer view
# --------------------------------------------------------------------------
@app.get("/api/jobs/{job_id}/units")
def units(job_id: str, user: str = Depends(require_user)) -> dict:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return {"units": [r.model_dump() for r in job.records]}


@app.post("/api/jobs/{job_id}/units/{unit_id}/reanalyze")
def reanalyze(job_id: str, unit_id: str, user: str = Depends(require_user)) -> dict:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    rec = analyzer.reanalyze_unit(job, unit_id)
    if rec is None:
        raise HTTPException(404, "Unit not found")
    return rec.model_dump()


# --------------------------------------------------------------------------
# Manager view
# --------------------------------------------------------------------------
@app.get("/api/jobs/{job_id}/manager")
def manager(job_id: str, user: str = Depends(require_user)) -> dict:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return aggregator.build_manager_view(job.records)


@app.post("/api/logs/frontend")
async def frontend_log(body: FrontendLogRequest) -> dict:
    write_frontend_log(body.level, body.message, body.context)
    return {"ok": True}


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

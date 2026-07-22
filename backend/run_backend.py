"""Run the Co_Trace backend with run-scoped file logging.

Examples:
    python backend/run_backend.py
    python backend/run_backend.py --debug
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Co_Trace FastAPI backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload")
    parser.add_argument("--debug", action="store_true", help="Enable verbose Co_Trace logging")
    args = parser.parse_args()

    if args.debug:
        os.environ["COTRACE_DEBUG"] = "1"
    else:
        os.environ.setdefault("COTRACE_DEBUG", "0")

    backend_dir = Path(__file__).resolve().parent
    uvicorn.run(
        "app.main:app",
        app_dir=str(backend_dir),
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="debug" if args.debug else "info",
        access_log=args.debug,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
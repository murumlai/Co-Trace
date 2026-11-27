"""Run the Co_Trace backend with run-scoped file logging.

Examples:
    python backend/run_backend.py
    python backend/run_backend.py --debug
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import uvicorn

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _non_loopback_cli_warning(host: str, provider: str | None) -> str | None:
    if (provider or "").strip().lower() != "copilot_cli":
        return None
    if (host or "").strip().lower() in _LOOPBACK_HOSTS:
        return None
    return (
        f"WARNING: LLM_PROVIDER=copilot_cli is intended for local loopback use only "
        f"(got --host {host!r}). It uses this machine's interactive Copilot CLI sign-in; "
        f"use LLM_PROVIDER=copilot_http for shared/IIS deployments."
    )


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

    warning = _non_loopback_cli_warning(args.host, os.getenv("LLM_PROVIDER"))
    if warning:
        print(warning, file=sys.stderr)

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
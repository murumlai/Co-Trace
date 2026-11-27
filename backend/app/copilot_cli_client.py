"""Locked-down local GitHub Copilot CLI transport adapter.

Runs the locally installed ``copilot`` binary as a non-agentic, text-in /
text-out LLM gateway for developer and single-user laptop workflows. Prompts
are delivered on UTF-8 ``stdin`` (never via shell interpolation or command-line
arguments), all CLI tools and MCP servers are disabled, execution runs inside
an empty temporary working directory, and ephemeral session state is cleaned up
after each call.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .config import normalize_cli_auto_tier, resolve_copilot_cli_executable, settings
from .copilot_client import (
    CopilotAuthError,
    CopilotCompletion,
    CopilotConfigError,
    CopilotResponseError,
    CopilotTransientError,
)
from .redaction import redact

log = logging.getLogger("cotrace.copilot.cli")

_SECRET_TOKEN_RE = re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]+\b")
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_AUTH_ERROR_HINTS = (
    "not logged in",
    "copilot login",
    "unauthorized",
    "authentication",
    "not authenticated",
    "forbidden",
    "401",
    "403",
    "subscription",
    "no copilot",
)
_CONFIG_ERROR_HINTS = (
    "is not available",
    "unknown model",
    "invalid model",
    "unknown option",
    "unexpected argument",
    "unsupported model",
)


@dataclass(frozen=True)
class CliProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


ProcessRunner = Callable[[list[str], bytes, str, dict[str, str], float], CliProcessResult]


def _default_process_runner(
    cmd: list[str],
    stdin_bytes: bytes,
    cwd: str,
    env: dict[str, str],
    timeout_s: float,
) -> CliProcessResult:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=env,
        shell=False,
        creationflags=creationflags,
    )
    try:
        stdout_bytes, stderr_bytes = proc.communicate(input=stdin_bytes, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _terminate_process(proc)
        raise CopilotTransientError(f"Copilot CLI timed out after {int(timeout_s)}s") from None
    except FileNotFoundError:
        raise CopilotConfigError("Copilot CLI executable was not found") from None
    except OSError as exc:
        raise CopilotTransientError(f"Copilot CLI failed to start: {type(exc).__name__}") from None
    return CliProcessResult(
        returncode=proc.returncode if proc.returncode is not None else 1,
        stdout=stdout_bytes or b"",
        stderr=stderr_bytes or b"",
    )


def _terminate_process(proc: subprocess.Popen[bytes]) -> None:
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.communicate(timeout=5)
    except Exception:  # noqa: BLE001 - best-effort pipe drain after kill
        pass


def _combine_prompts(system_prompt: str, user_prompt: str) -> str:
    return (
        "SYSTEM INSTRUCTIONS (authoritative — obey strictly):\n"
        f"{system_prompt.strip()}\n\n"
        "USER INPUT:\n"
        f"{user_prompt.strip()}\n"
    )


def _sanitize_error_detail(raw: str) -> str:
    cleaned = _ANSI_ESCAPE_RE.sub("", raw or "")
    cleaned = redact(_SECRET_TOKEN_RE.sub("[REDACTED]", cleaned))
    cleaned = " ".join(cleaned.split()).strip()
    if len(cleaned) > 200:
        cleaned = f"{cleaned[:197]}..."
    return cleaned


def _classify_cli_error(returncode: int, stderr_text: str) -> Exception:
    detail = _sanitize_error_detail(stderr_text)
    lowered = detail.lower()
    suffix = f": {detail}" if detail else f" (exit code {returncode})"
    if any(hint in lowered for hint in _AUTH_ERROR_HINTS):
        return CopilotAuthError(f"Copilot CLI authentication/authorization failed{suffix}")
    if any(hint in lowered for hint in _CONFIG_ERROR_HINTS):
        return CopilotConfigError(f"Copilot CLI configuration/model error{suffix}")
    return CopilotTransientError(f"Copilot CLI execution failed{suffix}")


_AUTO_TIER_MODELS = frozenset({"auto", "fusion"})


def _extract_jsonl_error(stdout_text: str) -> str:
    """Return the last ``session.error`` message from JSONL stdout, if any."""
    last_error = ""
    for raw_line in (stdout_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "session.error":
            data = event.get("data")
            if isinstance(data, dict) and isinstance(data.get("message"), str):
                last_error = data["message"]
    return last_error


def _parse_jsonl_stdout(stdout_text: str) -> tuple[str, int | None, int | None]:
    """Extract unwrapped assistant text (and optional usage) from ``--output-format json`` JSONL."""
    messages: list[str] = []
    usage_in: int | None = None
    usage_out: int | None = None
    parsed_any = False
    for raw_line in (stdout_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            continue
        parsed_any = True
        event_type = event["type"]
        data = event.get("data")
        if event_type == "assistant.message" and isinstance(data, dict):
            content = data.get("content")
            if isinstance(content, str) and content.strip():
                messages.append(content.strip())
        elif event_type == "session.usage_checkpoint" and isinstance(data, dict):
            snapshot = data.get("accountingSnapshot")
            if isinstance(snapshot, dict):
                snap_in, snap_out = _extract_usage_from_dict(snapshot)
                if snap_in is not None or snap_out is not None:
                    usage_in, usage_out = snap_in, snap_out
    if messages:
        return messages[-1], usage_in, usage_out
    if parsed_any:
        return "", usage_in, usage_out
    return stdout_text.strip(), None, None


def _extract_usage_from_dict(data: dict[str, Any]) -> tuple[int | None, int | None]:
    model_metrics = data.get("modelMetrics")
    if isinstance(model_metrics, dict) and model_metrics:
        in_total = 0
        out_total = 0
        found = False
        for entry in model_metrics.values():
            if not isinstance(entry, dict):
                continue
            usage = entry.get("usage")
            if not isinstance(usage, dict):
                continue
            inp = usage.get("inputTokens")
            out = usage.get("outputTokens")
            if isinstance(inp, int) and not isinstance(inp, bool) and inp >= 0:
                in_total += inp
                found = True
            if isinstance(out, int) and not isinstance(out, bool) and out >= 0:
                out_total += out
                found = True
        if found and (in_total > 0 or out_total > 0):
            return in_total, out_total

    last_in = data.get("lastCallInputTokens")
    last_out = data.get("lastCallOutputTokens")
    valid_in = last_in if isinstance(last_in, int) and not isinstance(last_in, bool) and last_in > 0 else None
    valid_out = last_out if isinstance(last_out, int) and not isinstance(last_out, bool) and last_out > 0 else None
    return valid_in, valid_out


def _parse_usage_file(usage_path: str) -> tuple[int | None, int | None]:
    if not os.path.isfile(usage_path):
        return None, None
    try:
        with open(usage_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    return _extract_usage_from_dict(data)


def _copilot_home_dir(env: dict[str, str]) -> str:
    configured = (env.get("COPILOT_HOME") or "").strip()
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    return os.path.join(os.path.expanduser("~"), ".copilot")


def _cleanup_session_dir(env: dict[str, str], session_id: str) -> None:
    session_dir = os.path.join(_copilot_home_dir(env), "session-state", session_id)
    if os.path.isdir(session_dir):
        shutil.rmtree(session_dir, ignore_errors=True)


class CopilotCliTransport:
    """Locked-down non-agentic completion transport backed by local Copilot CLI."""

    def __init__(
        self,
        *,
        executable: str,
        timeout_s: float = 90.0,
        max_response_bytes: int = 1024 * 1024,
        max_concurrency: int = 1,
        cleanup_session: bool = True,
        auto_tier: str = "balance",
        reasoning_effort: str = "",
        proxy: str = "",
        ca_bundle: str = "",
        runner: ProcessRunner | None = None,
    ) -> None:
        self._executable = executable
        self._timeout_s = timeout_s
        self._max_response_bytes = max_response_bytes
        self._cleanup_session = cleanup_session
        self._auto_tier = normalize_cli_auto_tier(auto_tier)
        self._reasoning_effort = (reasoning_effort or "").strip().lower()
        self._proxy = (proxy or "").strip()
        self._ca_bundle = (ca_bundle or "").strip()
        self._runner: ProcessRunner = runner or _default_process_runner
        self._semaphore = threading.BoundedSemaphore(max(1, int(max_concurrency)))

    def build_command(self, model: str, session_id: str, usage_file: str) -> list[str]:
        clean_model = (model or "").strip()
        if not clean_model or clean_model.startswith("-"):
            raise CopilotConfigError("Copilot CLI model name is invalid")
        cmd = [
            self._executable,
            "--model",
            clean_model,
            "--output-format",
            "json",
            "--no-color",
            "--stream",
            "off",
            "--no-ask-user",
            "--disable-builtin-mcps",
            "--no-custom-instructions",
            "--disallow-temp-dir",
            "--no-auto-update",
            "--disable-client-telemetry",
            "--sync-session=off",
            "--log-level",
            "none",
            "--available-tools",
            "__none__",
            "--deny-tool",
            "shell",
            "--deny-tool",
            "write",
            "--deny-tool",
            "url",
            "--session-id",
            session_id,
            "--usage-output-file",
            usage_file,
        ]
        if self._auto_tier and clean_model.lower() in _AUTO_TIER_MODELS:
            cmd.extend(["--auto-tier", self._auto_tier])
        if self._reasoning_effort:
            cmd.extend(["--reasoning-effort", self._reasoning_effort])
        return cmd

    def build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        # Prevent ambient shell flags from re-enabling autonomous tool approval.
        env.pop("COPILOT_ALLOW_ALL", None)
        env.pop("COPILOT_ASSISTED_APPROVAL", None)
        env["COPILOT_AUTO_UPDATE"] = "false"
        env["COPILOT_DISABLE_DESKTOP_NOTIFICATIONS"] = "1"
        env["COPILOT_PLUGIN_DIR_ONLY"] = "true"
        env["NO_COLOR"] = "1"
        if self._proxy:
            env["HTTPS_PROXY"] = self._proxy
            env["HTTP_PROXY"] = self._proxy
            env.setdefault("NO_PROXY", "localhost,127.0.0.1")
        if self._ca_bundle:
            env["NODE_EXTRA_CA_CERTS"] = self._ca_bundle
        return env

    def complete(self, system_prompt: str, user_prompt: str, model: str) -> CopilotCompletion:
        session_id = str(uuid.uuid4())
        payload = _combine_prompts(system_prompt, user_prompt).encode("utf-8")
        env = self.build_env()

        with self._semaphore:
            with tempfile.TemporaryDirectory(prefix="cotrace_cli_") as scratch_dir:
                usage_file = os.path.join(scratch_dir, "usage.json")
                cmd = self.build_command(model, session_id, usage_file)
                try:
                    result = self._runner(cmd, payload, scratch_dir, env, self._timeout_s)
                    if len(result.stdout) > self._max_response_bytes:
                        raise CopilotResponseError(
                            f"Copilot CLI response exceeded {self._max_response_bytes} bytes"
                        )
                    stdout_text = result.stdout.decode("utf-8", errors="replace").strip()
                    stderr_text = result.stderr.decode("utf-8", errors="replace").strip()
                    if result.returncode != 0:
                        error_text = stderr_text or _extract_jsonl_error(stdout_text)
                        raise _classify_cli_error(result.returncode, error_text)
                    content_text, event_in, event_out = _parse_jsonl_stdout(stdout_text)
                    if not content_text:
                        raise CopilotResponseError("Copilot CLI returned empty output")
                    input_tokens, output_tokens = _parse_usage_file(usage_file)
                    if input_tokens is None and output_tokens is None:
                        input_tokens, output_tokens = event_in, event_out
                    return CopilotCompletion(
                        text=content_text,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
                finally:
                    if self._cleanup_session:
                        _cleanup_session_dir(env, session_id)


_transport_lock = threading.Lock()
_transport: CopilotCliTransport | None = None


def build_transport_from_settings(runner: ProcessRunner | None = None) -> CopilotCliTransport:
    try:
        executable = resolve_copilot_cli_executable(settings.COPILOT_CLI_PATH)
    except ValueError as exc:
        raise CopilotConfigError(str(exc)) from None
    return CopilotCliTransport(
        executable=executable,
        timeout_s=settings.COPILOT_CLI_TIMEOUT_S,
        max_response_bytes=settings.COPILOT_MAX_RESPONSE_BYTES,
        max_concurrency=settings.COPILOT_CLI_MAX_CONCURRENCY,
        cleanup_session=settings.COPILOT_CLI_CLEANUP_SESSION,
        auto_tier=settings.COPILOT_CLI_AUTO_TIER,
        reasoning_effort=settings.COPILOT_CLI_REASONING_EFFORT,
        proxy=settings.COPILOT_PROXY,
        ca_bundle=settings.COPILOT_CA_BUNDLE,
        runner=runner,
    )


def _get_transport() -> CopilotCliTransport:
    global _transport
    with _transport_lock:
        if _transport is None:
            _transport = build_transport_from_settings()
        return _transport


def close() -> None:
    """Drop the cached CLI transport instance (FastAPI shutdown / test reset)."""
    global _transport
    with _transport_lock:
        _transport = None


def is_available() -> bool:
    """True when ``copilot_cli`` is selected and validates locally. Never spawns a subprocess."""
    if settings.LLM_PROVIDER != "copilot_cli":
        return False
    try:
        settings.validate_copilot_cli()
    except RuntimeError:
        return False
    return True


def complete(system_prompt: str, user_prompt: str, model: str) -> CopilotCompletion:
    """Run one locked-down completion via the locally installed Copilot CLI."""
    if not is_available():
        raise CopilotConfigError("Copilot CLI provider is not configured")
    return _get_transport().complete(system_prompt, user_prompt, model)

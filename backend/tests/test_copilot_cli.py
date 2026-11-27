"""Tests for the local GitHub Copilot CLI gateway configuration and transport."""
from __future__ import annotations

import os
import stat

import pytest

from app.config import COPILOT_ENTERPRISE_HOST, resolve_copilot_cli_executable, settings


@pytest.fixture
def fake_cli_executable(tmp_path):
    exe = tmp_path / ("copilot.exe" if os.name == "nt" else "copilot")
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    if os.name != "nt":
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return str(exe)


@pytest.fixture
def cli_configured(monkeypatch, fake_cli_executable):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "copilot_cli")
    monkeypatch.setattr(settings, "COPILOT_GH_HOST", COPILOT_ENTERPRISE_HOST)
    monkeypatch.setattr(settings, "COPILOT_CLI_PATH", fake_cli_executable)
    monkeypatch.setattr(settings, "COPILOT_CLI_TIMEOUT_S", 90.0)
    monkeypatch.setattr(settings, "COPILOT_CLI_MAX_CONCURRENCY", 1)
    monkeypatch.setattr(settings, "COPILOT_CLI_CLEANUP_SESSION", True)
    monkeypatch.setattr(settings, "COPILOT_CLI_REASONING_EFFORT", "")
    monkeypatch.setattr(settings, "COPILOT_MAX_RESPONSE_BYTES", 1024 * 1024)
    monkeypatch.setattr(settings, "COPILOT_PROXY", "")
    monkeypatch.setattr(settings, "COPILOT_CA_BUNDLE", "")
    # No PAT or HTTP auth mode is required for copilot_cli.
    monkeypatch.setattr(settings, "COPILOT_GITHUB_TOKEN", "")
    monkeypatch.setattr(settings, "COPILOT_AUTH_MODE", "")
    return settings


def test_copilot_cli_validates_without_pat(cli_configured):
    cli_configured.validate_enterprise_only()
    assert cli_configured.LLM_PROVIDER == "copilot_cli"


def test_copilot_cli_rejects_public_github_host(cli_configured, monkeypatch):
    for host in ("", "github.com", "api.github.com", "www.github.com"):
        monkeypatch.setattr(settings, "COPILOT_GH_HOST", host)
        with pytest.raises(RuntimeError, match="public GitHub host"):
            cli_configured.validate_enterprise_only()


def test_copilot_cli_rejects_missing_executable(cli_configured, monkeypatch, tmp_path):
    missing = str(tmp_path / "does-not-exist.exe")
    monkeypatch.setattr(settings, "COPILOT_CLI_PATH", missing)
    with pytest.raises(RuntimeError, match="existing file"):
        cli_configured.validate_enterprise_only()


def test_copilot_cli_resolves_command_via_path(monkeypatch, fake_cli_executable):
    monkeypatch.setattr("app.config.shutil.which", lambda name: fake_cli_executable if name == "copilot" else None)
    assert resolve_copilot_cli_executable("copilot") == os.path.abspath(fake_cli_executable)

    with pytest.raises(ValueError, match="not found on PATH"):
        resolve_copilot_cli_executable("missing-cli")


def test_copilot_cli_validates_numeric_and_effort_bounds(cli_configured, monkeypatch):
    monkeypatch.setattr(settings, "COPILOT_CLI_TIMEOUT_S", 0)
    with pytest.raises(RuntimeError, match="COPILOT_CLI_TIMEOUT_S"):
        cli_configured.validate_enterprise_only()

    monkeypatch.setattr(settings, "COPILOT_CLI_TIMEOUT_S", 30.0)
    monkeypatch.setattr(settings, "COPILOT_CLI_MAX_CONCURRENCY", 0)
    with pytest.raises(RuntimeError, match="COPILOT_CLI_MAX_CONCURRENCY"):
        cli_configured.validate_enterprise_only()

    monkeypatch.setattr(settings, "COPILOT_CLI_MAX_CONCURRENCY", 2)
    monkeypatch.setattr(settings, "COPILOT_CLI_REASONING_EFFORT", "turbo")
    with pytest.raises(RuntimeError, match="COPILOT_CLI_REASONING_EFFORT"):
        cli_configured.validate_enterprise_only()

    monkeypatch.setattr(settings, "COPILOT_CLI_REASONING_EFFORT", "medium")
    cli_configured.validate_enterprise_only()


def test_copilot_cli_validates_proxy_and_ca_bundle(cli_configured, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "COPILOT_PROXY", "socks5://proxy.local:1080")
    with pytest.raises(RuntimeError, match="COPILOT_PROXY"):
        cli_configured.validate_enterprise_only()

    monkeypatch.setattr(settings, "COPILOT_PROXY", "http://proxy-us.intel.com:912")
    monkeypatch.setattr(settings, "COPILOT_CA_BUNDLE", str(tmp_path / "missing.pem"))
    with pytest.raises(RuntimeError, match="COPILOT_CA_BUNDLE"):
        cli_configured.validate_enterprise_only()

    ca_file = tmp_path / "corp.pem"
    ca_file.write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")
    monkeypatch.setattr(settings, "COPILOT_CA_BUNDLE", str(ca_file))
    cli_configured.validate_enterprise_only()

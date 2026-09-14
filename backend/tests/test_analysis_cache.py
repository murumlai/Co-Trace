"""Tests for persisted analysis cache visibility and deletion policy."""
from __future__ import annotations

import json

from app import analysis_cache


def _save_entry(cache_key: str, *, created_by: str, role: str = "user", protected: bool = False) -> None:
    analysis_cache.set_entry(
        cache_key,
        root_cause="root",
        suggested_solution="solution",
        source="llm",
        metadata={
            "created_by": created_by,
            "created_by_login": f"{created_by}-login",
            "created_by_role": role,
            "protected": protected,
            "unit_id": "private-unit-id",
            "product_code": "M79060-001",
            "signature": "sig",
        },
    )


def test_user_can_delete_own_non_protected_entry(isolated_settings):
    _save_entry("own-key", created_by="42")

    assert analysis_cache.delete_entry("own-key", actor_id="42", actor_is_admin=False) is True
    assert analysis_cache.get_entry("own-key") is None


def test_user_cannot_delete_other_user_entry(isolated_settings):
    _save_entry("other-key", created_by="42")

    assert analysis_cache.delete_entry("other-key", actor_id="99", actor_is_admin=False) is False
    assert analysis_cache.get_entry("other-key") is not None


def test_user_cannot_delete_admin_protected_entry(isolated_settings):
    _save_entry("admin-key", created_by="1", role="admin")

    assert analysis_cache.delete_entry("admin-key", actor_id="1", actor_is_admin=False) is False
    assert analysis_cache.get_entry("admin-key") is not None


def test_admin_can_delete_any_entry(isolated_settings):
    _save_entry("admin-delete-key", created_by="42")

    assert analysis_cache.delete_entry("admin-delete-key", actor_id="1", actor_is_admin=True) is True
    assert analysis_cache.get_entry("admin-delete-key") is None


def test_normal_listing_hides_creator_and_private_unit_id(isolated_settings):
    _save_entry("visible-key", created_by="42")

    entry = analysis_cache.list_entries(actor_is_admin=False)[0]

    assert "created_by" not in entry
    assert "created_by_login" not in entry
    assert "unit_id" not in entry["metadata"]
    assert entry["metadata"]["product_code"] == "M79060-001"


def test_admin_listing_includes_creator_metadata(isolated_settings):
    _save_entry("admin-visible-key", created_by="42")

    entry = analysis_cache.list_entries(actor_is_admin=True)[0]

    assert entry["created_by"] == "42"
    assert entry["created_by_login"] == "42-login"
    assert entry["metadata"]["unit_id"] == "private-unit-id"


def test_user_save_does_not_overwrite_admin_protected_entry(isolated_settings):
    _save_entry("shared-key", created_by="1", role="admin")

    analysis_cache.set_entry(
        "shared-key",
        root_cause="user root",
        suggested_solution="user solution",
        source="llm",
        metadata={
            "created_by": "42",
            "created_by_login": "octocat",
            "created_by_role": "user",
            "product_code": "M79060-001",
            "signature": "sig",
        },
    )

    entries = analysis_cache.list_entries(actor_is_admin=True)
    protected = next(entry for entry in entries if entry["cache_key"] == "shared-key")
    revision = next(entry for entry in entries if entry.get("canonical_cache_key") == "shared-key")
    assert protected["root_cause"] == "root"
    assert protected["created_by_role"] == "admin"
    assert revision["root_cause"] == "user root"
    assert revision["created_by"] == "42"


def test_analysis_v4_entry_remains_listable_but_v5_lookup_misses(
    isolated_settings, monkeypatch
):
    key_args = {
        "error_code": "E1",
        "error_message": "failure",
        "context": "context",
        "context_source": "error_message",
        "signature": "sig",
    }
    monkeypatch.setattr(analysis_cache, "_CACHE_PROMPT_VERSION", "analysis-v4")
    old_key = analysis_cache.make_key(**key_args)
    monkeypatch.setattr(analysis_cache, "_CACHE_PROMPT_VERSION", "analysis-v5")
    current_key = analysis_cache.make_key(**key_args)
    with open(analysis_cache.settings.ANALYSIS_CACHE_FILE, "w", encoding="utf-8") as handle:
        json.dump({
            "schema_version": 1,
            "entries": {
                old_key: {
                    "cache_key": old_key,
                    "root_cause": "v4 root",
                    "suggested_solution": "v4 solution",
                    "source": "llm",
                    "prompt_version": "analysis-v4",
                }
            },
        }, handle)

    assert old_key != current_key
    assert analysis_cache.get_entry(current_key) is None
    assert analysis_cache.list_entries(actor_is_admin=True)[0]["prompt_version"] == "analysis-v4"
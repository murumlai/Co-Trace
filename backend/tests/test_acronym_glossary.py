"""Tests for the authoritative acronym glossary: extraction, store, analyzer
integration, prompt composition, and cache invalidation."""
from __future__ import annotations

from app.analysis_cache import DiskAnalysisCache
from app.analyzer import _compose_knowledge_prompt, analyze_job
from app.config import settings
from app.job_registry import Job
from app.knowledge.acronym_glossary import (
    AcronymGlossaryContext,
    AcronymGlossaryEntry,
    AcronymGlossaryService,
    AcronymGlossaryStore,
    extract_acronyms,
)
from app.knowledge.models import KnowledgeContext
from app.models import UnitRecord
from app import copilot_client, llm_client


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _store(tmp_path) -> AcronymGlossaryStore:
    return AcronymGlossaryStore(path=str(tmp_path / "product_acronyms.json"))


def _fail_rec(unit_id: str = "u1", **kwargs) -> UnitRecord:
    base = dict(
        unit_id=unit_id, result="FAIL", product_code="M79060-001",
        error_code="E1", error_message="voltage droop", run_folder=unit_id,
    )
    base.update(kwargs)
    return UnitRecord(**base)


def _job(records: list[UnitRecord]) -> Job:
    job = Job(job_id="g-job", workdir="")
    job.records = records
    return job


class NoopCache:
    def make_key(self, **kwargs) -> str:  # noqa: ANN003, ARG002
        return "cache-key"

    def get(self, cache_key: str):  # noqa: ANN201, ARG002
        return None

    def put(self, cache_key: str, **kwargs) -> None:  # noqa: ANN003, ARG002
        return None


# ---------------------------------------------------------------------------
# extraction / filtering
# ---------------------------------------------------------------------------

class TestExtraction:
    def test_extracts_uppercase_tokens_and_counts(self):
        counts, fields = extract_acronyms({
            "failing_step": "MB_PAN_TEST failed",
            "error_message": "PAN comms lost on AIC",
        })
        assert counts["PAN"] == 2
        assert counts["AIC"] == 1
        assert counts["MB"] == 1
        assert fields["PAN"] == {"failing_step", "error_message"}

    def test_ignores_product_codes_numbers_and_camelcase(self):
        counts, _ = extract_acronyms({
            "context": "M79060-001 ran FTRunner at 20251128090115 for STC_WW4622",
        })
        # product code parts with digits are excluded; CamelCase FTRunner excluded
        assert "M79060" not in counts
        assert "FTRUNNER" not in counts
        assert "WW4622" not in counts
        # STC is a pure-uppercase token → captured
        assert counts.get("STC") == 1

    def test_stopwords_and_length_filters(self):
        counts, _ = extract_acronyms({
            "error_message": "TEST PASS FAIL ERROR with X and TOOLONGWORD",
        })
        assert "PASS" not in counts
        assert "FAIL" not in counts
        assert "ERROR" not in counts
        assert "TEST" not in counts
        assert "X" not in counts  # below min length
        assert "TOOLONGWORD" not in counts  # above max length

    def test_lowercase_tokens_ignored(self):
        counts, _ = extract_acronyms({"error_message": "pan aic dut"})
        assert counts == {}


# ---------------------------------------------------------------------------
# store read/write/upsert + lookup
# ---------------------------------------------------------------------------

class TestStore:
    def test_upsert_and_persist_roundtrip(self, tmp_path):
        store = _store(tmp_path)
        store.upsert_entry(
            acronym="pan", definition="Board assembly", product_code="M79060-001",
            status="approved",
        )
        # A fresh store reads the same file (persistence + coercion of "pan").
        reread = _store(tmp_path)
        entries = reread.list_entries()
        assert len(entries) == 1
        assert entries[0].acronym == "PAN"
        assert entries[0].definition == "Board assembly"
        assert entries[0].status == "approved"

    def test_product_definition_overrides_global(self, tmp_path):
        store = _store(tmp_path)
        store.upsert_entry(acronym="PAN", definition="Global PAN", product_code=None, status="approved")
        store.upsert_entry(acronym="PAN", definition="Product PAN", product_code="M79060-001", status="approved")
        service = AcronymGlossaryService(store)
        ctx = service.glossary_for(_fail_rec(error_message="PAN failed"))
        assert "PAN = Product PAN" in ctx.trusted_text
        assert "Global PAN" not in ctx.trusted_text

    def test_global_used_when_no_product_specific(self, tmp_path):
        store = _store(tmp_path)
        store.upsert_entry(acronym="AIC", definition="Add-In Card", product_code=None, status="approved")
        service = AcronymGlossaryService(store)
        ctx = service.glossary_for(_fail_rec(error_message="AIC not seated"))
        assert "AIC = Add-In Card" in ctx.trusted_text
        assert "AIC" in ctx.used_acronyms

    def test_pending_entries_are_not_authoritative(self, tmp_path):
        store = _store(tmp_path)
        store.upsert_entry(acronym="XYZ", definition="Should not be used", product_code="M79060-001",
                           status="needs_review")
        service = AcronymGlossaryService(store)
        ctx = service.glossary_for(_fail_rec(error_message="XYZ tripped"))
        assert "Should not be used" not in ctx.trusted_text
        assert "XYZ" in ctx.unknown_acronyms

    def test_rejected_entries_excluded_and_not_rerecorded(self, tmp_path):
        store = _store(tmp_path)
        store.upsert_entry(acronym="WW", definition=None, product_code=None, status="rejected")
        service = AcronymGlossaryService(store)
        ctx = service.glossary_for(_fail_rec(error_message="WW tag seen"))
        assert "WW" not in ctx.unknown_acronyms
        service.record_unknowns(_fail_rec(error_message="WW tag seen"), ctx)
        # still only the single rejected entry, no new needs_review WW added
        assert [e.acronym for e in store.list_entries()] == ["WW"]

    def test_set_status_and_delete(self, tmp_path):
        store = _store(tmp_path)
        store.upsert_entry(acronym="ABC", definition=None, product_code="P1", status="needs_review")
        updated = store.set_status("ABC", "P1", "approved", definition="A Big Component")
        assert updated is not None and updated.status == "approved"
        assert updated.definition == "A Big Component"
        assert store.delete_entry("ABC", "P1") is True
        assert store.list_entries() == []


# ---------------------------------------------------------------------------
# record_unknowns
# ---------------------------------------------------------------------------

class TestRecordUnknowns:
    def test_records_pending_for_unknown_acronyms(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "PRODUCT_ACRONYM_UNKNOWN_APPEND_ENABLED", True)
        store = _store(tmp_path)
        service = AcronymGlossaryService(store)
        rec = _fail_rec(error_message="ZZQ and QRS failed")
        ctx = service.glossary_for(rec)
        service.record_unknowns(rec, ctx)
        entries = {e.acronym: e for e in store.list_entries()}
        assert "ZZQ" in entries and entries["ZZQ"].status == "needs_review"
        assert entries["ZZQ"].definition is None
        assert entries["ZZQ"].product_code == "M79060-001"
        assert entries["ZZQ"].observed_count >= 1

    def test_repeat_observation_increments_count(self, tmp_path):
        store = _store(tmp_path)
        service = AcronymGlossaryService(store)
        rec = _fail_rec(error_message="QRS QRS QRS failed")
        ctx = service.glossary_for(rec)
        service.record_unknowns(rec, ctx)
        first = {e.acronym: e for e in store.list_entries()}["QRS"].observed_count
        service.record_unknowns(rec, ctx)
        second = {e.acronym: e for e in store.list_entries()}["QRS"].observed_count
        assert second > first

    def test_append_disabled_records_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "PRODUCT_ACRONYM_UNKNOWN_APPEND_ENABLED", False)
        store = _store(tmp_path)
        service = AcronymGlossaryService(store)
        rec = _fail_rec(error_message="NEWACR failed")
        ctx = service.glossary_for(rec)
        service.record_unknowns(rec, ctx)
        assert store.list_entries() == []

    def test_glossary_disabled_returns_inert_context(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "PRODUCT_ACRONYM_GLOSSARY_ENABLED", False)
        service = AcronymGlossaryService(_store(tmp_path))
        ctx = service.glossary_for(_fail_rec(error_message="PAN failed"))
        assert ctx.enabled is False
        assert ctx.used_acronyms == [] and ctx.unknown_acronyms == []


# ---------------------------------------------------------------------------
# prompt composition (works even without product knowledge)
# ---------------------------------------------------------------------------

class TestPromptComposition:
    def test_glossary_injected_without_product_knowledge(self):
        glossary = AcronymGlossaryContext(
            trusted_text="trusted_acronym_glossary ...\nPAN = Board",
            unknown_text="unknown_acronyms_observed ...: QRS",
        )
        prompt = _compose_knowledge_prompt(None, glossary)
        assert prompt is not None
        assert "PAN = Board" in prompt
        assert "QRS" in prompt

    def test_glossary_precedes_knowledge_and_unknown_last(self):
        glossary = AcronymGlossaryContext(
            trusted_text="TRUSTED_GLOSSARY", unknown_text="UNKNOWN_BLOCK"
        )
        knowledge = KnowledgeContext(context_text="PRODUCT_KNOWLEDGE")
        prompt = _compose_knowledge_prompt(knowledge, glossary)
        assert prompt.index("TRUSTED_GLOSSARY") < prompt.index("PRODUCT_KNOWLEDGE")
        assert prompt.index("PRODUCT_KNOWLEDGE") < prompt.index("UNKNOWN_BLOCK")

    def test_no_context_returns_none(self):
        assert _compose_knowledge_prompt(None, None) is None


# ---------------------------------------------------------------------------
# analyzer integration
# ---------------------------------------------------------------------------

class TestAnalyzerGlossaryIntegration:
    def test_passes_glossary_block_and_records_metadata(self, tmp_path):
        received = {}

        def analyze(ec, em, snippet, knowledge_context=None):  # noqa: ANN001, ARG001
            received["knowledge"] = knowledge_context
            return "root", "solution", "stub"

        store = _store(tmp_path)
        store.upsert_entry(acronym="PAN", definition="Board assembly",
                           product_code="M79060-001", status="approved")
        service = AcronymGlossaryService(store)
        job = _job([_fail_rec(error_message="PAN and QRS both tripped")])
        analyze_job(job, analyze_failure=analyze, cache=NoopCache(),
                    acronym_glossary=service)

        rec = job.records[0]
        assert rec.acronyms_used == ["PAN"]
        assert "QRS" in rec.unknown_acronyms
        assert rec.acronym_glossary_hash
        assert "PAN = Board assembly" in received["knowledge"]
        assert "unknown_acronyms_observed" in received["knowledge"]

    def test_records_unknowns_during_analysis(self, tmp_path):
        def analyze(ec, em, snippet):  # noqa: ANN001, ARG001
            return "root", "solution", "stub"

        store = _store(tmp_path)
        service = AcronymGlossaryService(store)
        job = _job([_fail_rec(error_message="QRS tripped")])
        analyze_job(job, analyze_failure=analyze, cache=NoopCache(),
                    acronym_glossary=service)
        assert "QRS" in {e.acronym for e in store.list_entries()}

    def test_no_glossary_leaves_metadata_empty(self, tmp_path):  # noqa: ARG002
        def analyze(ec, em, snippet):  # noqa: ANN001, ARG001
            return "root", "solution", "stub"

        job = _job([_fail_rec(error_message="PAN failed")])
        analyze_job(job, analyze_failure=analyze, cache=NoopCache())
        assert job.records[0].acronyms_used == []
        assert job.records[0].acronym_glossary_hash is None


# ---------------------------------------------------------------------------
# cache-key invalidation
# ---------------------------------------------------------------------------

class TestCacheInvalidation:
    def test_key_differs_by_glossary_hash(self):
        cache = DiskAnalysisCache()
        common = dict(
            error_code="E1", error_message="m", context="ctx",
            context_source="error_message", signature="sig",
        )
        assert cache.make_key(**common, acronym_glossary_hash="h1") != cache.make_key(
            **common, acronym_glossary_hash="h2"
        )
        assert cache.make_key(**common, acronym_glossary_hash="h1") == cache.make_key(
            **common, acronym_glossary_hash="h1"
        )


# ---------------------------------------------------------------------------
# prompt rules
# ---------------------------------------------------------------------------

class TestPromptRules:
    def test_system_prompts_forbid_unknown_expansion(self):
        for system_prompt in (llm_client._SYSTEM_PROMPT, copilot_client._DIAGNOSE_SYSTEM_PROMPT):
            assert "ACRONYM RULES" in system_prompt
            assert "trusted_acronym_glossary" in system_prompt
            assert "Never invent, guess, or infer a full form" in system_prompt

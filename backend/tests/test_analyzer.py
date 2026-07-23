"""Safety-net tests: analyzer signature dedup, cache interactions, and
reanalysis behavior. These lock the LLM-bypass and dedup contract before
the SOLID refactor extracts these into injected abstractions.
"""
from __future__ import annotations

import pytest

from app.analyzer import analyze_job, signature_for, build_llm_context, reanalyze_unit
from app.job_registry import Job
from app.models import UnitRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fail_rec(unit_id: str, error_code: str = "E001",
               error_message: str = "Voltage fault") -> UnitRecord:
    return UnitRecord(unit_id=unit_id, result="FAIL", error_code=error_code,
                      error_message=error_message, run_folder=unit_id)


def _pass_rec(unit_id: str) -> UnitRecord:
    return UnitRecord(unit_id=unit_id, result="PASS", run_folder=unit_id)


def _stub_analyze(error_code, error_message, snippet):
    return "root cause", "suggested solution", "stub"


def _make_job(records: list[UnitRecord]) -> Job:
    job = Job(job_id="test_job_" + records[0].unit_id if records else "empty", workdir="")
    job.records = list(records)
    return job


# ---------------------------------------------------------------------------
# signature_for
# ---------------------------------------------------------------------------

class TestSignatureFor:
    def test_stable_for_same_inputs(self):
        rec = _fail_rec("u1", "E001", "Voltage fault")
        assert signature_for(rec) == signature_for(rec)

    def test_differs_for_different_error_code(self):
        r1 = _fail_rec("u1", "E001", "same message")
        r2 = _fail_rec("u2", "E002", "same message")
        assert signature_for(r1) != signature_for(r2)

    def test_differs_for_different_message(self):
        r1 = _fail_rec("u1", "E001", "message A")
        r2 = _fail_rec("u2", "E001", "message B")
        assert signature_for(r1) != signature_for(r2)

    def test_same_signature_for_same_error_different_unit_ids(self):
        r1 = _fail_rec("u1", "E001", "Voltage fault")
        r2 = _fail_rec("u2", "E001", "Voltage fault")
        assert signature_for(r1) == signature_for(r2)

    def test_normalizes_numeric_tokens(self):
        """Numbers in the message are replaced so different counts share a sig."""
        r1 = _fail_rec("u1", "E001", "Retry count 3 exceeded")
        r2 = _fail_rec("u2", "E001", "Retry count 7 exceeded")
        assert signature_for(r1) == signature_for(r2)

    def test_is_16_char_hex_string(self):
        sig = signature_for(_fail_rec("u1"))
        assert len(sig) == 16
        assert all(c in "0123456789abcdef" for c in sig)


# ---------------------------------------------------------------------------
# build_llm_context
# ---------------------------------------------------------------------------

class TestBuildLlmContext:
    def test_prefers_debug_excerpt(self):
        rec = _fail_rec("u1")
        rec.debug_excerpt = "excerpt text"
        rec.ftrunner_snippet = "snippet text"
        context, source = build_llm_context(rec)
        assert context == "excerpt text"
        assert source == "debug_excerpt"

    def test_falls_back_to_ftrunner_snippet(self):
        rec = _fail_rec("u1")
        rec.debug_excerpt = None
        rec.ftrunner_snippet = "snippet text"
        context, source = build_llm_context(rec)
        assert context == "snippet text"
        assert source == "ftrunner_snippet"

    def test_falls_back_to_error_message(self):
        rec = _fail_rec("u1", error_message="raw error")
        rec.debug_excerpt = None
        rec.ftrunner_snippet = None
        context, source = build_llm_context(rec)
        assert context == "raw error"
        assert source == "error_message"


# ---------------------------------------------------------------------------
# analyze_job — dedup and caching behavior
# ---------------------------------------------------------------------------

class TestAnalyzeJobDedup:
    def test_pass_units_not_analyzed(self, monkeypatch):
        monkeypatch.setattr("app.analysis_cache.get_entry", lambda *a, **kw: None)
        monkeypatch.setattr("app.analysis_cache.set_entry", lambda *a, **kw: None)

        calls = {"n": 0}
        def counting_stub(ec, em, snippet):
            calls["n"] += 1
            return "root", "solution", "stub"

        job = _make_job([_pass_rec("u1"), _pass_rec("u2")])
        analyze_job(job, analyze_failure=counting_stub)
        assert calls["n"] == 0

    def test_same_signature_analyzed_once(self, monkeypatch):
        """Two FAILs with identical error code/message share a sig → one LLM call."""
        monkeypatch.setattr("app.analysis_cache.get_entry", lambda *a, **kw: None)
        monkeypatch.setattr("app.analysis_cache.set_entry", lambda *a, **kw: None)

        calls = {"n": 0}
        def counting_stub(ec, em, snippet):
            calls["n"] += 1
            return "root", "solution", "stub"

        r1 = _fail_rec("u1", "E001", "Voltage fault")
        r2 = _fail_rec("u2", "E001", "Voltage fault")
        job = _make_job([r1, r2])
        analyze_job(job, analyze_failure=counting_stub)

        assert calls["n"] == 1

    def test_different_signatures_each_analyzed(self, monkeypatch):
        monkeypatch.setattr("app.analysis_cache.get_entry", lambda *a, **kw: None)
        monkeypatch.setattr("app.analysis_cache.set_entry", lambda *a, **kw: None)

        calls = {"n": 0}
        def counting_stub(ec, em, snippet):
            calls["n"] += 1
            return "root", "solution", "stub"

        r1 = _fail_rec("u1", "E001", "Voltage fault")
        r2 = _fail_rec("u2", "E002", "Thermal limit exceeded")
        job = _make_job([r1, r2])
        analyze_job(job, analyze_failure=counting_stub)

        assert calls["n"] == 2

    def test_second_unit_inherits_cached_result(self, monkeypatch):
        """The second unit with the same signature should get the same root/solution."""
        monkeypatch.setattr("app.analysis_cache.get_entry", lambda *a, **kw: None)
        monkeypatch.setattr("app.analysis_cache.set_entry", lambda *a, **kw: None)

        def stub(ec, em, snippet):
            return "the root cause", "the solution", "stub"

        r1 = _fail_rec("u1", "E001", "Voltage fault")
        r2 = _fail_rec("u2", "E001", "Voltage fault")
        job = _make_job([r1, r2])
        analyze_job(job, analyze_failure=stub)

        assert r1.root_cause == "the root cause"
        assert r2.root_cause == "the root cause"
        assert r1.suggested_solution == "the solution"
        assert r2.suggested_solution == "the solution"

    def test_uses_job_signature_cache_to_skip_llm(self, monkeypatch):
        """If job.signature_cache already has the sig, the LLM stub is not called."""
        monkeypatch.setattr("app.analysis_cache.get_entry", lambda *a, **kw: None)
        monkeypatch.setattr("app.analysis_cache.set_entry", lambda *a, **kw: None)

        calls = {"n": 0}
        def counting_stub(ec, em, snippet):
            calls["n"] += 1
            return "root", "solution", "stub"

        rec = _fail_rec("u1", "E001", "Voltage fault")
        sig = signature_for(rec)

        job = _make_job([rec])
        job.signature_cache[sig] = ("cached root", "cached solution", "cached")
        analyze_job(job, analyze_failure=counting_stub)

        assert calls["n"] == 0
        assert rec.root_cause == "cached root"
        assert rec.analysis_source == "cached"

    def test_uses_persistent_cache_hit(self, monkeypatch):
        """If analysis_cache.get_entry returns an entry, the stub is not called."""
        cached_entry = {"root_cause": "cached root", "suggested_solution": "cached sol"}
        monkeypatch.setattr("app.analysis_cache.get_entry", lambda *a, **kw: cached_entry)
        monkeypatch.setattr("app.analysis_cache.set_entry", lambda *a, **kw: None)

        calls = {"n": 0}
        def counting_stub(ec, em, snippet):
            calls["n"] += 1
            return "root", "solution", "stub"

        rec = _fail_rec("u1")
        job = _make_job([rec])
        analyze_job(job, analyze_failure=counting_stub)

        assert calls["n"] == 0
        assert rec.root_cause == "cached root"

    def test_analysis_source_set_on_records(self, monkeypatch):
        monkeypatch.setattr("app.analysis_cache.get_entry", lambda *a, **kw: None)
        monkeypatch.setattr("app.analysis_cache.set_entry", lambda *a, **kw: None)

        rec = _fail_rec("u1")
        job = _make_job([rec])
        analyze_job(job, analyze_failure=_stub_analyze)

        assert rec.analysis_source is not None

    def test_signature_stored_on_record(self, monkeypatch):
        monkeypatch.setattr("app.analysis_cache.get_entry", lambda *a, **kw: None)
        monkeypatch.setattr("app.analysis_cache.set_entry", lambda *a, **kw: None)

        rec = _fail_rec("u1")
        job = _make_job([rec])
        analyze_job(job, analyze_failure=_stub_analyze)

        assert rec.signature is not None
        assert len(rec.signature) == 16


# ---------------------------------------------------------------------------
# reanalyze_unit — force refresh
# ---------------------------------------------------------------------------

class TestReanalyzeUnit:
    def test_reanalyze_calls_stub_even_with_cached_sig(self, monkeypatch):
        """force=True bypasses the job signature_cache."""
        monkeypatch.setattr("app.analysis_cache.get_entry", lambda *a, **kw: None)
        monkeypatch.setattr("app.analysis_cache.set_entry", lambda *a, **kw: None)

        calls = {"n": 0}
        def counting_stub(ec, em, snippet):
            calls["n"] += 1
            return "new root", "new solution", "stub"

        rec = _fail_rec("u1")
        sig = signature_for(rec)
        job = _make_job([rec])
        job.signature_cache[sig] = ("old root", "old solution", "cached")

        reanalyze_unit(job, "u1", analyze_failure=counting_stub)
        assert calls["n"] == 1
        assert rec.root_cause == "new root"

    def test_reanalyze_returns_none_for_unknown_unit_id(self, monkeypatch):
        monkeypatch.setattr("app.analysis_cache.get_entry", lambda *a, **kw: None)
        monkeypatch.setattr("app.analysis_cache.set_entry", lambda *a, **kw: None)

        job = _make_job([_fail_rec("u1")])
        result = reanalyze_unit(job, "nonexistent", analyze_failure=_stub_analyze)
        assert result is None

    def test_reanalyze_pass_unit_returns_record_unchanged(self, monkeypatch):
        monkeypatch.setattr("app.analysis_cache.get_entry", lambda *a, **kw: None)
        monkeypatch.setattr("app.analysis_cache.set_entry", lambda *a, **kw: None)

        rec = _pass_rec("u1")
        job = _make_job([rec])
        result = reanalyze_unit(job, "u1", analyze_failure=_stub_analyze)
        assert result is rec
        assert rec.root_cause is None  # PASS units stay untouched

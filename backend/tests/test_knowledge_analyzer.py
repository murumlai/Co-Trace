"""Tests for product-knowledge integration into the failure analyzer + cache."""
from __future__ import annotations

from typing import Any

from app.analysis_cache import DiskAnalysisCache
from app.analyzer import analyze_job
from app.job_registry import Job
from app.knowledge.models import KnowledgeContext, KnownFailureEntry, RetrievalMatch, RfcReference
from app.models import UnitRecord


class NoopCache:
    def make_key(self, **kwargs: Any) -> str:  # noqa: ARG002
        return "cache-key"

    def get(self, cache_key: str) -> dict[str, Any] | None:  # noqa: ARG002
        return None

    def put(self, cache_key: str, **kwargs: Any) -> None:  # noqa: ARG002
        return None


class FakeRetriever:
    def __init__(self, ctx: KnowledgeContext) -> None:
        self.ctx = ctx
        self.calls = 0

    def retrieve(self, record: UnitRecord) -> KnowledgeContext:  # noqa: ARG002
        self.calls += 1
        return self.ctx


class RaisingRetriever:
    def retrieve(self, record: UnitRecord) -> KnowledgeContext:  # noqa: ARG002
        raise RuntimeError("boom")


def _fail_rec(unit_id: str) -> UnitRecord:
    return UnitRecord(
        unit_id=unit_id, result="FAIL", product_code="M79060-001",
        error_code="E1", error_message="voltage droop", run_folder=unit_id,
    )


def _job(records: list[UnitRecord]) -> Job:
    job = Job(job_id="k-job", workdir="")
    job.records = records
    return job


def _matched_ctx() -> KnowledgeContext:
    return KnowledgeContext(
        product_code="M79060-001",
        knowledge_hash="h1",
        match_status="matched",
        matched=True,
        matched_section_ids=["A-s000"],
        matched_categories=["debug_learning"],
        context_text="CURATED PRODUCT CONTEXT",
    )


class TestAnalyzerKnowledgeIntegration:
    def test_passes_context_to_four_arg_callable_and_records_metadata(self):
        received: dict[str, Any] = {}

        def analyze(ec, em, snippet, knowledge_context=None):  # noqa: ANN001, ARG001
            received["knowledge"] = knowledge_context
            return "root", "solution", "stub"

        retriever = FakeRetriever(_matched_ctx())
        job = _job([_fail_rec("u1")])
        analyze_job(job, analyze_failure=analyze, cache=NoopCache(),
                    knowledge_retriever=retriever)

        rec = job.records[0]
        assert rec.knowledge_used is True
        assert rec.knowledge_hash == "h1"
        assert rec.knowledge_categories == ["debug_learning"]
        assert rec.knowledge_section_ids == ["A-s000"]
        assert received["knowledge"] == "CURATED PRODUCT CONTEXT"

    def test_legacy_three_arg_callable_still_works(self):
        def analyze(ec, em, snippet):  # noqa: ANN001, ARG001
            return "root", "solution", "stub"

        retriever = FakeRetriever(_matched_ctx())
        job = _job([_fail_rec("u1")])
        analyze_job(job, analyze_failure=analyze, cache=NoopCache(),
                    knowledge_retriever=retriever)
        assert job.records[0].knowledge_used is True  # metadata still recorded

    def test_retriever_failure_does_not_break_analysis(self):
        calls = {"n": 0}

        def analyze(ec, em, snippet):  # noqa: ANN001, ARG001
            calls["n"] += 1
            return "root", "solution", "stub"

        job = _job([_fail_rec("u1")])
        analyze_job(job, analyze_failure=analyze, cache=NoopCache(),
                    knowledge_retriever=RaisingRetriever())
        assert calls["n"] == 1
        assert job.records[0].root_cause == "root"

    def test_no_retriever_leaves_knowledge_unset(self):
        def analyze(ec, em, snippet):  # noqa: ANN001, ARG001
            return "root", "solution", "stub"

        job = _job([_fail_rec("u1")])
        analyze_job(job, analyze_failure=analyze, cache=NoopCache())
        assert job.records[0].knowledge_used is False
        assert job.records[0].knowledge_hash is None

    def test_exact_rfc_match_replaces_insufficient_llm_solution(self):
        rec = UnitRecord(
            unit_id="u1",
            result="FAIL",
            product_code="N32828-201",
            error_code="FFFFFFFF",
            error_message="INFO  - Disaster : Reading 20V failed!",
            failing_step="20V Test",
            run_folder="u1",
        )
        ctx = KnowledgeContext(
            product_code="N32828-201",
            knowledge_hash="h-rfc",
            match_status="matched",
            matched=True,
            matched_section_ids=["20de193411b1-s005"],
            matched_categories=["rfc_knowledge"],
            context_text="RFC context",
            matches=[
                RetrievalMatch(
                    section_id="20de193411b1-s005",
                    doc_id="20de193411b1",
                    product_code="N32828-201",
                    category="rfc_knowledge",
                    heading="Functional Test RFC \u2014 20V Test",
                    summary="20V Test: Disaster : Reading 20V failed!",
                    known_failures=[
                        KnownFailureEntry(
                            symptom="Disaster : Reading 20V failed!",
                            log_signature="Disaster : Reading 20V failed!",
                            failing_step="20V Test",
                            corrective_action=(
                                "Make sure the power supply to card is turned on; "
                                "check Ambery configuration; if only Standby LED is on, "
                                "send the card to debug for comparator issue."
                            ),
                            confidence="high",
                            rfc_references=[
                                RfcReference(
                                    rfc_id="RFC 1",
                                    notes="Make sure the power supply to card is turned on",
                                    failed_test_name="20V Test",
                                    error_message_or_finding="Disaster : Reading 20V failed!",
                                )
                            ],
                        )
                    ],
                    source_filename="N32828-201_RFC_.xlsx",
                )
            ],
        )

        def analyze(ec, em, snippet, knowledge_context=None):  # noqa: ANN001, ARG001
            return (
                "The supplied evidence shows failure code 'FFFFFFFF' with message "
                "'INFO  - Disaster : Reading 20V failed!', but it does not contain "
                "enough product-specific or log evidence to identify a single root cause.",
                "See root cause above.",
                "llm",
            )

        job = _job([rec])
        analyze_job(job, analyze_failure=analyze, cache=NoopCache(), knowledge_retriever=FakeRetriever(ctx))

        assert rec.knowledge_used is True
        assert rec.knowledge_section_ids == ["20de193411b1-s005"]
        assert "exact rfc_knowledge match" in rec.root_cause
        assert "power supply to card is turned on" in rec.suggested_solution
        assert "See root cause above" not in rec.suggested_solution


class TestCacheKnowledgeInvalidation:
    def test_key_differs_by_knowledge_hash(self):
        cache = DiskAnalysisCache()
        common = dict(
            error_code="E1", error_message="voltage droop", context="ctx",
            context_source="error_message", signature="sig", product_code="M79060-001",
        )
        key_a = cache.make_key(**common, knowledge_hash="hashA")
        key_b = cache.make_key(**common, knowledge_hash="hashB")
        key_a2 = cache.make_key(**common, knowledge_hash="hashA")
        assert key_a != key_b
        assert key_a == key_a2

    def test_key_differs_by_matched_sections(self):
        cache = DiskAnalysisCache()
        common = dict(
            error_code="E1", error_message="m", context="ctx",
            context_source="error_message", signature="sig",
        )
        assert cache.make_key(**common, knowledge_sections="A-s000") != cache.make_key(
            **common, knowledge_sections="A-s001"
        )

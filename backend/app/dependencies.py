"""Composition root: builds and exposes concrete service adapters.

``main.py`` imports from here instead of from concrete implementation modules
so HTTP concerns and application-service construction stay separate. Tests can
swap adapters via ``app.dependency_overrides`` without touching module globals.
"""
from __future__ import annotations

from .analysis_cache import DiskAnalysisCache
from .analyzer import AnalyzerService
from .job_registry import JobRegistry, registry as _registry
from .knowledge.retriever import LexicalKnowledgeRetriever
from .knowledge.service import KnowledgeIngestionService
from .knowledge.storage import KnowledgeStore
from .orchestrator import JobOrchestrator, _default_orchestrator as _orchestrator

# ---------------------------------------------------------------------------
# Singletons — built once at import time from settings
# ---------------------------------------------------------------------------

_analysis_cache = DiskAnalysisCache()
_knowledge_store = KnowledgeStore()
_knowledge_retriever = LexicalKnowledgeRetriever(_knowledge_store)
_knowledge_ingestion = KnowledgeIngestionService(_knowledge_store)
_analyzer_service = AnalyzerService(knowledge_retriever=_knowledge_retriever)


# ---------------------------------------------------------------------------
# FastAPI dependency providers
# ---------------------------------------------------------------------------

def get_registry() -> JobRegistry:
    """Provide the global job registry."""
    return _registry


def get_orchestrator() -> JobOrchestrator:
    """Provide the default job orchestrator."""
    return _orchestrator


def get_analyzer_service() -> AnalyzerService:
    """Provide the analyzer service (cache + LLM provider)."""
    return _analyzer_service


def get_analysis_cache() -> DiskAnalysisCache:
    """Provide the disk-backed analysis cache adapter."""
    return _analysis_cache


def get_knowledge_retriever() -> LexicalKnowledgeRetriever:
    """Provide the product-knowledge retriever."""
    return _knowledge_retriever


def get_knowledge_store() -> KnowledgeStore:
    """Provide the knowledge-pack store (read/preview/delete)."""
    return _knowledge_store


def get_knowledge_ingestion() -> KnowledgeIngestionService:
    """Provide the knowledge ingestion service (scan/parse/summarize/write)."""
    return _knowledge_ingestion

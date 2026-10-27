"""
LLM-based Query Rephrasing Service

Provides query improvement via LLM: rephrasing, decomposition, and expansion.
"""

import os
import logging
from typing import Optional, List, Dict, Tuple
from open_webui.env import RAG_QUERY_REPHRASER, RAG_QUERY_REPHRASER_MODEL, RAG_QUERY_REPHRASER_EMBEDDING_ENGINE, RAG_QUERY_REPHRASER_API_BASE_URL
from open_webui.retrieval.utils import get_embedding_function, get_reranking_function

log = logging.getLogger(__name__)

# FastAPI imports for potential HTTP calls
try:
    from httpx import AsyncClient
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


class QueryRephrasingService:
    """Service for improving queries via LLM."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.model = RAG_QUERY_REPHRASER_MODEL
        self.engine = RAG_QUERY_REPHRASER_EMBEDDING_ENGINE
        self.api_base_url = RAG_QUERY_REPHRASER_API_BASE_URL

    async def rephrase(self, query: str, conversation_history: Optional[List[str]] = None) -> Tuple[str, Dict]:
        """
        Rephrase a query using an LLM.

        Args:
            query: The original user query
            conversation_history: List of previous messages in the conversation

        Returns:
            Tuple of (rephrased_query, metadata)
        """
        if not self.enabled:
            return query, {"rephrased": False, "reason": "disabled"}

        try:
            # For now, use a simple heuristic-based approach
            # TODO: Integrate with actual LLM API
            # Example: call OpenAI/Anthropic/Mistral/etc. to rephrase query

            # Simple rephrasing: add context awareness
            rephrased = self._simple_rephrase(query, conversation_history)

            metadata = {
                "rephrased": True,
                "method": "simple",
                "original_length": len(query),
                "rephrased_length": len(rephrased),
            }

            return rephrased, metadata

        except Exception as e:
            log.error(f"Query rephrasing error: {e}")
            return query, {"rephrased": False, "error": str(e)}

    def _simple_rephrase(self, query: str, history: Optional[List[str]] = None) -> str:
        """Basic rephrasing using heuristics."""
        # Add context from history if available
        if history and history[-1]:
            # Add pronoun resolution based on last user message
            last_user_msg = history[-1]
            if "it" in QueryRephrasingService._get_last_n_words(last_user_msg, 3):
                query = f"Regarding content from previous context: {query}"

        # Handle abbreviations and common issues
        query = query.lower()
        query = query.replace('cause', 'because')
        query = query.replace('dont', 'do not')
        query = query.replace('cant', 'cannot')
        query = query.replace('ive', 'I have')
        query = query.replace('im', 'I am')

        # Capitalize first letter
        if query:
            query = query[0].upper() + query[1:]

        return query


    def rephrase_sync(self, query: str, conversation_history: Optional[List[str]] = None) -> Tuple[str, Dict]:
        """Sync version of rephrasing (heuristic-based)."""
        return self._simple_rephrase(query, conversation_history), {"method": "heuristic"}
    async def decompose(self, query: str) -> List[str]:
        """
        Decompose a complex query into simpler sub-queries.

        Args:
            query: The original user query

        Returns:
            List of simpler sub-queries
        """
        if not self.enabled:
            return [query]

        try:
            # For now, use simple rule-based decomposition
            # TODO: Integrate with actual LLM API for intelligent decomposition

            sub_queries = self._simple_decompose(query)
            return sub_queries

        except Exception as e:
            log.error(f"Query decomposition error: {e}")
            return [query]

    def _simple_decompose(self, query: str) -> List[str]:
        """Decompose query using simple rules."""
        # Split on common conjunctions
        conjunctions = [' and ', ' or ', ' but ', ' however ', ' whereas ', ' while ']
        parts = []

        for conj in conjunctions:
            if conj in query:
                parts = query.split(conj)
                break

        if not parts:
            return [query]

        # Clean up parts
        return [p.strip() for p in parts if p.strip()]


# Singleton instance
_rephrasing_service: Optional[QueryRephrasingService] = None


def get_query_rephrasing_service() -> QueryRephrasingService:
    """Get the singleton query rephrasing service instance."""
    global _rephrasing_service
    if _rephrasing_service is None:
        enabled = os.getenv('RAG_QUERY_REPHRASER', 'False').lower() == 'true'
        _rephrasing_service = QueryRephrasingService(enabled=enabled)
    return _rephrasing_service


def set_query_rephrasing_service(service: QueryRephrasingService):
    """Set the singleton query rephrasing service instance."""
    global _rephrasing_service
    _rephrasing_service = service


def init_query_rephrasing_service():
    """Initialize query rephrasing service based on environment configuration."""
    enabled = os.getenv('RAG_QUERY_REPHRASER', 'False').lower() == 'true'
    service = QueryRephrasingService(enabled=enabled)
    set_query_rephrasing_service(service)
    log.info(f"Query Rephrasing Service: {'Enabled' if enabled else 'Disabled'}")
    return service

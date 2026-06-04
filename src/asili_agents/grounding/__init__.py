"""Grounding module for Vertex AI Search integration.

This module provides RAG capabilities using Vertex AI Search
to ground agent responses in the seller's catalog data.
"""

from asili_agents.grounding.vertex_search import (
    VertexSearchClient,
    search_catalog,
)

__all__ = [
    "VertexSearchClient",
    "search_catalog",
]

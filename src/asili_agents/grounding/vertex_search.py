"""Vertex AI Search client for catalog grounding.

This module provides integration with Vertex AI Search to enable
RAG-based grounding for the Messaging agent. When a customer asks
about products, the agent can retrieve relevant catalog entries
from the search index.

In demo mode, this falls back to the local catalog search.
"""

from typing import Any

from asili_agents.config import get_settings
from asili_agents.tools.catalog import catalog_search


class VertexSearchClient:
    """Client for Vertex AI Search.

    This client wraps the Discovery Engine API to provide
    semantic search over the seller's catalog.
    """

    def __init__(
        self,
        project_id: str | None = None,
        location: str | None = None,
        datastore_id: str | None = None,
    ):
        """Initialize the Vertex AI Search client.

        Args:
            project_id: Google Cloud project ID.
            location: Google Cloud region.
            datastore_id: Vertex AI Search datastore ID.
        """
        settings = get_settings()
        self.project_id = project_id or settings.google_cloud_project
        self.location = location or settings.google_cloud_location
        self.datastore_id = datastore_id or settings.vertex_search_datastore_id
        self._client = None

    def _get_client(self):
        """Get or create the Discovery Engine client."""
        if self._client is None:
            try:
                from google.cloud import discoveryengine_v1 as discoveryengine

                self._client = discoveryengine.SearchServiceClient()
            except ImportError as err:
                raise ImportError(
                    "google-cloud-discoveryengine is required for Vertex AI Search. "
                    "Install with: pip install google-cloud-discoveryengine"
                ) from err
        return self._client

    def search(
        self,
        query: str,
        page_size: int = 10,
    ) -> list[dict[str, Any]]:
        """Search the catalog using Vertex AI Search.

        Args:
            query: Search query string.
            page_size: Maximum number of results to return.

        Returns:
            List of search results with product information.
        """
        settings = get_settings()

        # In demo mode, use local catalog search
        if settings.demo_mode or not self.datastore_id:
            return catalog_search(query)

        # Use Vertex AI Search
        client = self._get_client()

        serving_config = (
            f"projects/{self.project_id}/locations/{self.location}/"
            f"collections/default_collection/dataStores/{self.datastore_id}/"
            f"servingConfigs/default_config"
        )

        request = {
            "serving_config": serving_config,
            "query": query,
            "page_size": page_size,
        }

        response = client.search(request=request)

        results = []
        for result in response.results:
            # Extract document data
            doc = result.document
            data = {}

            # Parse struct fields
            if doc.struct_data:
                for key, value in doc.struct_data.items():
                    data[key] = _parse_struct_value(value)

            results.append(data)

        return results


def _parse_struct_value(value: Any) -> Any:
    """Parse a protobuf Struct value to Python."""
    if hasattr(value, "string_value"):
        return value.string_value
    if hasattr(value, "number_value"):
        return value.number_value
    if hasattr(value, "bool_value"):
        return value.bool_value
    if hasattr(value, "list_value"):
        return [_parse_struct_value(v) for v in value.list_value.values]
    if hasattr(value, "struct_value"):
        return {k: _parse_struct_value(v) for k, v in value.struct_value.fields.items()}
    return str(value)


# Module-level convenience function
_default_client: VertexSearchClient | None = None


def search_catalog(query: str, page_size: int = 10) -> list[dict[str, Any]]:
    """Search the catalog using Vertex AI Search.

    This is a convenience function that uses a default client.
    For more control, instantiate VertexSearchClient directly.

    Args:
        query: Search query string.
        page_size: Maximum number of results to return.

    Returns:
        List of search results with product information.
    """
    global _default_client
    if _default_client is None:
        _default_client = VertexSearchClient()
    return _default_client.search(query, page_size)

"""MongoDB MCP toolset wiring.

In the deployed/graded path, the Messaging and Pricing agents read the seller's
catalog through the official **MongoDB MCP server** (``mongodb-mcp-server``,
launched via ``npx``) instead of in-process Python functions. This is the
agent's only data path: pull the connection string and the agent goes mute
rather than hallucinating. The server runs ``--readOnly``, so the agent can
never mutate the catalog through its tools.

``make_mongodb_mcp_toolset`` returns ``None`` when MongoDB is not configured,
so callers can fall back to the in-process repository tools (local dev + tests).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from asili_agents.config import Settings, get_settings

if TYPE_CHECKING:
    from google.adk.tools.mcp_tool import McpToolset

# Read-only tools the agents are allowed to call on the MongoDB MCP server.
MONGODB_MCP_READ_TOOLS = [
    "find",
    "aggregate",
    "count",
    "list-collections",
    "collection-schema",
]

# In-process + MCP read tools, used to detect whether a run actually retrieved
# from the catalog (vs produced fluent text). Superset of MONGODB_MCP_READ_TOOLS.
READ_TOOL_NAMES = {"catalog_search", "check_stock", "get_costs", *MONGODB_MCP_READ_TOOLS}

# Instruction snippet appended to an agent's prompt when it is MCP-grounded.
MCP_GROUNDING_INSTRUCTION = """
## Data access — MongoDB (read-only, via MCP)

You read the seller's live data from MongoDB through the MongoDB MCP tools
(`find`, `aggregate`, `count`). Treat MongoDB as the single source of truth.

- **Database: `asili`.** Always pass `database: "asili"` to the MongoDB tools.
- The catalog is the **`products`** collection. Each document has:
  `sku`, `name`, `description`, `category`, `origin`, `price`, `cost`,
  `stock_quantity`, `low_stock_threshold`, `unit`.
- Business rules are in the **`policy`** collection (`margin_floor`, discount bands).
- Match products **case-insensitively** — prefer a regex filter, e.g.
  `find(database="asili", collection="products",
  filter={"name": {"$regex": "purple", "$options": "i"}})`.
  If a targeted search returns nothing, `find` the whole `products` collection
  (empty filter) and pick the match yourself before concluding it's absent.
- Answer using ONLY what you read. Never state a price, a stock number, or a
  product detail you did not just read from MongoDB. Only after a broad search
  finds nothing, say the product isn't in the catalog — do not guess.
"""


def make_mongodb_mcp_toolset(settings: Settings | None = None) -> McpToolset | None:
    """Build an ``McpToolset`` backed by the MongoDB MCP server.

    Returns ``None`` if ``mongodb_uri`` is not configured.
    """
    settings = settings or get_settings()
    if not settings.mongodb_uri:
        return None

    from google.adk.tools.mcp_tool import McpToolset
    from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
    from mcp import StdioServerParameters

    args = ["-y", "mongodb-mcp-server"]
    if settings.mcp_read_only:
        args.append("--readOnly")

    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=settings.mcp_server_command,
                args=args,
                # The MongoDB MCP server reads the connection string from env,
                # keeping the secret out of the process arg list.
                env={
                    "MDB_MCP_CONNECTION_STRING": settings.mongodb_uri,
                    "MDB_MCP_READ_ONLY": "true" if settings.mcp_read_only else "false",
                },
            ),
            timeout=30.0,
        ),
        tool_filter=MONGODB_MCP_READ_TOOLS,
    )


def resolve_use_mcp(use_mcp: bool | None, settings: Settings | None = None) -> bool:
    """Resolve an explicit ``use_mcp`` flag, falling back to settings."""
    if use_mcp is not None:
        return use_mcp
    return (settings or get_settings()).use_mcp

"""Stage 2.2 — Graph API (read side).

Thin orchestration over GraphStorage's read methods — the actual query
shapes live in storage.py, next to the Stage 2.1 writes they read back.
"""
from typing import Any

from app.graph.cluster import get_graph_storage


async def get_nodes(*, user_jwt: str) -> list[dict[str, Any]]:
    storage = get_graph_storage()
    return await storage.get_nodes(user_jwt=user_jwt)


async def get_edges(*, user_jwt: str) -> list[dict[str, Any]]:
    storage = get_graph_storage()
    return await storage.get_edges(user_jwt=user_jwt)


async def get_node_chunks(
    *, user_jwt: str, document_id: str
) -> list[dict[str, Any]] | None:
    storage = get_graph_storage()
    return await storage.get_node_chunks(user_jwt=user_jwt, document_id=document_id)

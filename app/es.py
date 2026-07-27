"""Async Elasticsearch client + FastAPI lifespan.

A single ``AsyncElasticsearch`` instance is created on startup and closed on
shutdown. Routers receive it via the ``get_es`` dependency.
"""
from contextlib import asynccontextmanager

from elasticsearch import AsyncElasticsearch

from .config import get_settings

_es: AsyncElasticsearch | None = None


def build_client() -> AsyncElasticsearch:
    s = get_settings()
    return AsyncElasticsearch(
        hosts=[s.ES_HOST],
        basic_auth=(s.ES_USER, s.ES_PASSWORD),
        verify_certs=s.ES_VERIFY_CERTS,
        ca_certs=s.ES_CA_CERTS or None,
        request_timeout=30,
    )


@asynccontextmanager
async def lifespan(app):
    global _es
    _es = build_client()
    try:
        yield
    finally:
        await _es.close()
        _es = None


async def get_es() -> AsyncElasticsearch:
    """FastAPI dependency — returns the shared client."""
    global _es  # only used to lazily build a client outside the lifespan
    if _es is None:
        _es = build_client()
    return _es

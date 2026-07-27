"""v1 API router — aggregates all v1 endpoint routers under /v1.

Add v2 later by creating ``app/api/v2/router.py`` and including it in main.py.
"""
from fastapi import APIRouter

from .endpoints import suggest, search, places, synonyms, reverse, alter_names

api_router = APIRouter(prefix="/v1")
api_router.include_router(suggest.router)
api_router.include_router(search.router)
api_router.include_router(places.router)
api_router.include_router(alter_names.router)
api_router.include_router(synonyms.router)
api_router.include_router(reverse.router)

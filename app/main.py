"""FastAPI application entrypoint.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .es import build_client, get_es
from .security import configure_cors, configure_ip_allowlist
from .api.v1.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # create the async ES client for the dependency
    from . import es as es_module
    es_module._es = build_client()
    try:
        yield
    finally:
        await es_module._es.close()
        es_module._es = None


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Search API",
        version="1.0.0",
        description="FastAPI autocomplete/geocoding search over Elasticsearch (Bangladesh places).",
        lifespan=lifespan,
    )
    configure_cors(app, settings)
    configure_ip_allowlist(app, settings)
    app.include_router(api_router)

    @app.get("/health", tags=["meta"])
    async def health():
        es = await get_es()
        info = await es.info()
        return {"status": "ok", "es": info["version"]["number"], "index": settings.INDEX_NAME}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=get_settings().APP_HOST, port=get_settings().APP_PORT,
                reload=get_settings().DEBUG)

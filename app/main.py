"""FastAPI application entrypoint.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import logging
import time
import warnings
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from .config import get_settings
from .es import build_client, get_es
from .logging_config import setup_logging
from .security import configure_cors, configure_ip_allowlist, configure_api_key
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
    setup_logging(settings.LOG_LEVEL)
    # suppress the "TLS with verify_certs=False is insecure" warning (ES is localhost)
    warnings.filterwarnings("ignore", message=".*verify_certs.*")
    app = FastAPI(
        title="Search API",
        version="1.0.0",
        description="FastAPI autocomplete/geocoding search over Elasticsearch (Bangladesh places).",
        lifespan=lifespan,
        root_path=settings.ROOT_PATH or None,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    configure_cors(app, settings)
    configure_ip_allowlist(app, settings)
    configure_api_key(app, settings)

    # request logging
    logger = logging.getLogger("search_api")

    @app.middleware("http")
    async def log_request(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - start) * 1000
        logger.info("request", extra={
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round(ms),
            "client_ip": request.client.host if request.client else "",
        })
        return response

    app.include_router(api_router)

    @app.get("/health", tags=["meta"])
    async def health():
        es = await get_es()
        info = await es.info()
        return {"status": "ok", "es": info["version"]["number"], "index": settings.INDEX_NAME}

    # Swagger UI: add "Authorize" button for x-api-key
    from fastapi.openapi.utils import get_openapi

    def _custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version,
                             description=app.description, routes=app.routes)
        schema.setdefault("components", {}).setdefault("securitySchemes", {})["APIKeyHeader"] = {
            "type": "apiKey", "in": "header", "name": "x-api-key",
        }
        schema["security"] = [{"APIKeyHeader": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = _custom_openapi

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=get_settings().APP_HOST, port=get_settings().APP_PORT,
                reload=get_settings().DEBUG)

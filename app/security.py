"""Access control: CORS + an IP allowlist middleware.

- CORS uses ``ALLOWED_ORIGINS`` (``*`` allows all).
- The IP allowlist (``ALLOWED_IPS``) is opt-in: if non-empty, only requests from
  the listed IPs/CIDRs (or loopback) are accepted; others get 403. Empty = open.
"""
import ipaddress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import Settings


def configure_cors(app: FastAPI, settings: Settings) -> None:
    origins = settings.allowed_origins or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


class IPAllowlistMiddleware(BaseHTTPMiddleware):
    """Reject requests whose client IP is not in the allowlist (if configured)."""

    def __init__(self, app, allowed: list[str]):
        super().__init__(app)
        self.networks = []
        for entry in allowed:
            try:
                self.networks.append(ipaddress.ip_network(entry, strict=False))
            except ValueError:
                continue  # ignore unparseable entries

    async def dispatch(self, request: Request, call_next):
        if self.networks:  # only enforce when a list is configured
            client = request.client.host if request.client else ""
            if client and not self._allowed(client):
                return JSONResponse(status_code=403, content={"detail": "IP not allowed"})
        return await call_next(request)

    def _allowed(self, ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr in net for net in self.networks)


def configure_ip_allowlist(app: FastAPI, settings: Settings) -> None:
    allowed = settings.allowed_ips
    if allowed:
        app.add_middleware(IPAllowlistMiddleware, allowed=allowed)

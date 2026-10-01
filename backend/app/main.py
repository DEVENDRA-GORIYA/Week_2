import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.api.v1.router import api_router
from app.config import get_settings
from app.core.errors import HelixError
from app.core.rate_limit import SlidingWindowLimiter
from app.database import init_db
from app.providers.factory import build_provider

logger = logging.getLogger("helix")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await init_db()
    provider = build_provider(settings)
    app.state.provider = provider
    app.state.inference_provider = settings.inference_provider
    app.state.rate_limiter = SlidingWindowLimiter(settings.rate_limit_rpm)
    logger.info("helix started provider=%s model=%s", provider.name, provider.model)
    try:
        yield
    finally:
        current = getattr(app.state, "provider", None)
        if current is not None:
            await current.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        summary="JWT-protected inference API for local open models.",
        description=(
            "Versioned contracts for chat, structured extraction, and tool calls. "
            "The model runs in a separate local server (Ollama) or a free-tier "
            "OpenAI-compatible API."
        ),
        lifespan=lifespan,
        debug=settings.debug,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.add_exception_handler(HelixError, helix_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "service": "helix",
            "docs": "/docs",
            "health": f"{settings.api_v1_prefix}/health",
        }

    return app


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", uuid4().hex)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


async def helix_error_handler(_request: Request, exc: HelixError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
        headers=exc.headers,
    )


async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {
            "loc": [str(part) for part in error.get("loc", [])],
            "msg": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request validation failed.",
                "details": jsonable_encoder(details),
            }
        },
    )


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = create_app()

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.database import assert_connection_is_not_privileged
from app.integrations import firebase
from app.routers import account, auth, exercises, health, profile, program

# Spec 6.5: security headers on every response.
_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    # Spec 4.7/6.5: the app must refuse to run against a superuser or BYPASSRLS
    # connection, because RLS is silently bypassed for either. Awaited here, inside the
    # loop that will serve the app, rather than at import time: app.database is
    # imported before any loop exists under pytest (collection is synchronous) but
    # *inside* an already-running loop under uvicorn (the app import string is resolved
    # from within Server.serve()), and a bare asyncio.run() at import time works under
    # the former and crashes under the latter. See assert_connection_is_not_privileged's
    # docstring. An unhandled exception here fails ASGI startup loudly -- uvicorn logs
    # "ERROR: Application startup failed" and exits without serving a single request.
    await assert_connection_is_not_privileged()
    # A.5 item 15: Firebase Admin SDK init used to run as a side effect of importing
    # app.integrations.firebase (itself pulled in transitively by importing this module),
    # so anything that merely imported the app required a valid service-account JSON.
    # Called here instead, beside the privilege assertion, so the app can start without
    # one -- social sign-in alone is unavailable until it is configured.
    firebase.init_firebase()
    yield


def create_app() -> FastAPI:
    configure_logging()
    logger = get_logger(__name__)

    app = FastAPI(title="Gymak API", version="0.1.0", lifespan=_lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_trace_id_and_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Spec 7.2: every response carries trace_id, and it is the same value that
        # appears in the server log line.
        trace_id = uuid.uuid4().hex.upper()
        request.state.trace_id = trace_id
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        for header, value in _SECURITY_HEADERS.items():
            response.headers[header] = value
        response.headers["X-Trace-Id"] = trace_id

        logger.info(
            "request_handled",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            trace_id=trace_id,
        )
        return response

    register_exception_handlers(app)

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(profile.router, prefix="/api/v1")
    app.include_router(account.router, prefix="/api/v1")
    app.include_router(exercises.router, prefix="/api/v1")
    app.include_router(program.router, prefix="/api/v1")

    return app


app = create_app()

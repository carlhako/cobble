"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from cobble import __version__
from cobble.logging import configure_logging, get_logger
from cobble.settings import Settings, get_settings
from cobble.staticfiles import SPAStaticFiles, frontend_built, static_dir

log = get_logger("app")


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_logging()
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = getattr(app.state, "runtime", None)
        if runtime is not None:
            await runtime.startup()
        try:
            yield
        finally:
            if runtime is not None:
                await runtime.shutdown()

    app = FastAPI(title="cobble", version=__version__, lifespan=lifespan)
    app.state.settings = settings

    @app.get("/health", tags=["meta"])
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": __version__})

    # API routers are registered by the runtime wiring in cobble.runtime.
    from cobble.runtime import Runtime

    runtime = Runtime(settings)
    app.state.runtime = runtime
    runtime.attach(app)

    if frontend_built():
        app.mount("/", SPAStaticFiles(directory=static_dir(), html=True), name="spa")
    else:
        log.warning(
            "No built frontend at %s; only the API is being served. "
            "Run `npm --prefix web run build` for local UI.",
            static_dir(),
        )

    return app

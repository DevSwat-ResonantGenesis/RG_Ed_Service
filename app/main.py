"""ED Service - Execution Director main application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import Base, engine
from . import models  # Ensure models are registered
from .routers import router
from .tools import register_builtin_tools, register_git_tools, register_docker_tools, register_test_tools


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Register all tools
    register_builtin_tools()
    register_git_tools()
    register_docker_tools()
    register_test_tools()
    
    yield
    
    # Shutdown
    await engine.dispose()


app = FastAPI(
    title="ED Service - Execution Director",
    description="Code execution sandbox, file system abstraction, agent tools, and multi-agent controller",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health")
async def root_health():
    """Root health check."""
    return {"service": "ed", "status": "ok"}

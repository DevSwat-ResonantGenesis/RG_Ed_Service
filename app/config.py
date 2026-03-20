"""ED Service configuration."""

import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = os.getenv(
        "ED_DATABASE_URL",
        os.getenv(
            "DATABASE_URL",
            f"postgresql+asyncpg://{os.getenv('ED_DB_USER', os.getenv('AUTH_DB_USER', 'doadmin'))}:"
            f"{os.getenv('ED_DB_PASSWORD', os.getenv('AUTH_DB_PASSWORD', ''))}@"
            f"{os.getenv('ED_DB_HOST', os.getenv('AUTH_DB_HOST', 'db'))}:"
            f"{os.getenv('ED_DB_PORT', os.getenv('AUTH_DB_PORT', '5432'))}/"
            f"{os.getenv('ED_DB_NAME', os.getenv('AUTH_DB_NAME', 'defaultdb'))}?sslmode=require"
        )
    )

    # Service URLs
    LLM_SERVICE_URL: str = "http://llm_service:8000"
    MEMORY_SERVICE_URL: str = "http://memory_service:8000"
    COGNITIVE_SERVICE_URL: str = "http://cognitive_service:8000"
    WORKFLOW_SERVICE_URL: str = "http://workflow_service:8000"
    STORAGE_SERVICE_URL: str = "http://storage_service:8000"

    # Sandbox settings
    SANDBOX_TIMEOUT_SECONDS: int = 300  # 5 minutes max execution
    SANDBOX_MEMORY_LIMIT_MB: int = 512
    SANDBOX_CPU_LIMIT: float = 1.0
    SANDBOX_NETWORK_ENABLED: bool = False
    SANDBOX_BASE_IMAGE: str = "python:3.11-slim"

    # File system settings
    WORKSPACE_ROOT: str = "/workspaces"
    MAX_FILE_SIZE_MB: int = 10
    ALLOWED_EXTENSIONS: str = ".py,.js,.ts,.json,.yaml,.yml,.md,.txt,.html,.css"

    # Agent settings
    MAX_CONCURRENT_AGENTS: int = 10
    AGENT_HEARTBEAT_INTERVAL: int = 5

    # WebSocket settings
    WS_PING_INTERVAL: int = 30
    WS_MAX_CONNECTIONS: int = 100

    class Config:
        env_prefix = "ED_"
        case_sensitive = False


settings = Settings()

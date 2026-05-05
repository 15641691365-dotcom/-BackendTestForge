import os
from pathlib import Path


class Config:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./backend_testforge.db")

    # LLM configuration (read from env, with sensible defaults)
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

    # Server
    SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
    SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

    # Limits
    MAX_FILE_READ_LIMIT = int(os.getenv("MAX_FILE_READ_LIMIT", "20"))

    # Paths
    K6_TEMPLATES_DIR = PROJECT_ROOT / "backend" / "templates" / "k6"
    LOGS_DIR = PROJECT_ROOT / "backend" / "logs"


config = Config()

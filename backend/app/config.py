"""
SIFRA runtime configuration.
Every knob is read from the environment (or backend/.env) so the same code runs
against local SQLite for demos and Supabase/Postgres for deployment.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _database_url() -> str:
    # DATABASE_URL is the standard name (Render, Railway, Neon); SUPABASE_DB_URL kept for older .env files
    url = (os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL") or "sqlite:///./test.db").strip().strip('"\'')
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]   # SQLAlchemy 2 rejects the short scheme
    return url


DATABASE_URL = _database_url()

# CORS: comma separated list, "*" allows everything (hackathon default)
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

# Blockchain sync
SYNC_MAX_TXS = _int("SYNC_MAX_TXS", 150)            # most recent txs pulled per address
SYNC_TTL_SECONDS = _int("SYNC_TTL_SECONDS", 600)    # re-sync an address after this long
HTTP_TIMEOUT = _float("HTTP_TIMEOUT", 8.0)

# Entity attribution (WalletExplorer) - bounded so the UI never hangs
ENTITY_LOOKUP_WORKERS = _int("ENTITY_LOOKUP_WORKERS", 8)
ENTITY_LOOKUP_TIMEOUT = _float("ENTITY_LOOKUP_TIMEOUT", 3.0)
ENTITY_LOOKUP_BUDGET = _float("ENTITY_LOOKUP_BUDGET", 4.0)   # seconds for a whole batch
ENTITY_LOOKUP_MAX = _int("ENTITY_LOOKUP_MAX", 60)             # remote lookups per batch

# ML: sample live mainnet addresses at startup as the anomaly reference population
ML_LIVE_REFERENCE = os.getenv("ML_LIVE_REFERENCE", "true").lower() in ("1", "true", "yes")

# Local LLM (Ollama) for the narrative summary
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:14b")
OLLAMA_TIMEOUT = _float("OLLAMA_TIMEOUT", 20.0)
LLM_ENABLED = os.getenv("LLM_ENABLED", "true").lower() in ("1", "true", "yes")

# Geo-IP enrichment for relay telemetry
GEOIP_ENABLED = os.getenv("GEOIP_ENABLED", "true").lower() in ("1", "true", "yes")

# Optional shared secret for the relay-sensor ingest endpoint
TELEMETRY_TOKEN = os.getenv("TELEMETRY_TOKEN", "")

import logging
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL

log = logging.getLogger("sifra.db")

SQLALCHEMY_DATABASE_URL = DATABASE_URL
IS_SQLITE = SQLALCHEMY_DATABASE_URL.startswith("sqlite")

if IS_SQLITE:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
else:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=60,
        pool_size=10,
        max_overflow=20,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# Columns added after the first release. create_all() never alters existing
# tables, so older databases (local test.db or Supabase) are patched here.
_ADDED_COLUMNS = {
    "transactions": [
        ("ip_address", "VARCHAR"),
        ("country", "VARCHAR"),
        ("city", "VARCHAR"),
        ("latitude", "FLOAT"),
        ("longitude", "FLOAT"),
        ("isp", "VARCHAR"),
        ("is_vpn_tor", "BOOLEAN DEFAULT FALSE"),
        ("txid", "VARCHAR"),
        ("vout", "INTEGER"),
    ],
    "alerts": [
        ("details", "TEXT"),
        ("acknowledged", "BOOLEAN DEFAULT FALSE"),
    ],
    "relay_observations": [
        ("confidence", "FLOAT DEFAULT 1.0"),
    ],
    "analysis_results": [
        ("exposure_score", "FLOAT DEFAULT 0"),
        ("geo_score", "FLOAT DEFAULT 0"),
        ("updated_at", "TIMESTAMP"),
    ],
}


def init_db_schema():
    # Import models so every table is registered on Base before create_all
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, cols in _ADDED_COLUMNS.items():
            if not inspector.has_table(table):
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for col_name, col_type in cols:
                if col_name in existing:
                    continue
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
                    log.info("Added column %s.%s", table, col_name)
                except Exception as exc:  # pragma: no cover - depends on DB permissions
                    log.warning("Could not add column %s.%s: %s", table, col_name, exc)
        if inspector.has_table("transactions"):
            indexes = {ix["name"] for ix in inspector.get_indexes("transactions")}
            if "ix_transactions_txid" not in indexes:
                try:
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_transactions_txid ON transactions (txid)"))
                except Exception as exc:  # pragma: no cover
                    log.warning("Could not create txid index: %s", exc)

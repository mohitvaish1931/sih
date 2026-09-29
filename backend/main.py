import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.config import AUTO_SEED_DEMO, CORS_ORIGINS, ML_LIVE_REFERENCE
from app.database import IS_SQLITE, init_db_schema, SessionLocal
from app.routes import alerts, analysis, graph, live, meta, telemetry, wallet
from app.services.investigation import ENGINE_VERSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sifra")

init_db_schema()


def _ensure_demo_scenarios():
    """Seed the demo cases if they are missing (fresh or reset SQLite file)."""
    if not (AUTO_SEED_DEMO and IS_SQLITE):
        return
    from app.models import AddressTx
    db = SessionLocal()
    try:
        present = db.query(AddressTx.id).filter(AddressTx.address == "bc1_sus_peel_root").first()
    finally:
        db.close()
    if not present:
        from seed_data import seed_database
        log.info("Seeding demo scenarios into the local database ...")
        seed_database()


_ensure_demo_scenarios()


def _warm_up():
    from app.services.anomaly_engine import warm_population, build_live_reference, ensure_model
    db = SessionLocal()
    try:
        warm_population(db)
        ensure_model(db)        # train before the first investigation needs it
        if ML_LIVE_REFERENCE:
            build_live_reference(db)
    except Exception as exc:
        log.warning("Warm-up incomplete: %s", exc)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.services.bitcoin_api import start_provider_monitor
    start_provider_monitor()
    threading.Thread(target=_warm_up, daemon=True).start()
    yield


app = FastAPI(
    title="SIFRA - AI-Powered Bitcoin Forensics & Monitoring API",
    version=ENGINE_VERSION,
    description="Wallet risk scoring, laundering-typology detection, illicit exposure, clustering, "
                "graph tracing, relay telemetry and court-ready reports.",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=2048)

app.include_router(wallet.router)
app.include_router(analysis.router)
app.include_router(graph.router)
app.include_router(live.router)
app.include_router(alerts.router)
app.include_router(telemetry.router)
app.include_router(meta.router)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"Internal error: {type(exc).__name__}"})


@app.get("/")
def home():
    return {"message": "SIFRA Bitcoin Intelligence API is running", "version": ENGINE_VERSION, "docs": "/docs"}

import time

from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.config import OLLAMA_MODEL
from app.database import get_db, IS_SQLITE
from app.demo_scenarios import SCENARIOS
from app.models import AddressTx, AnalysisResult, Alert, ChainTx, RelayObservation
from app.services.bitcoin_api import get_latest_blocks
from app.services.entity_tagger import known_entity_index
from app.services.explainability import llm_available
from app.services.investigation import ENGINE_VERSION

router = APIRouter(tags=["meta"])


@router.get("/api/health")
def health(db: Session = Depends(get_db)):
    t = time.time()
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    db_ms = int((time.time() - t) * 1000)
    blocks = get_latest_blocks(count=1)
    return {
        "status": "ok" if db_ok else "degraded",
        "engine_version": ENGINE_VERSION,
        "database": {"ok": db_ok, "backend": "sqlite" if IS_SQLITE else "postgres", "latency_ms": db_ms},
        "blockchain": {"ok": bool(blocks), "tip_height": blocks[0]["height"] if blocks else None},
        "llm": {"available": llm_available(), "model": OLLAMA_MODEL},
    }


@router.get("/api/stats")
def platform_stats(db: Session = Depends(get_db)):
    levels = dict(db.query(AnalysisResult.risk_level, func.count(AnalysisResult.id))
                  .group_by(AnalysisResult.risk_level).all())
    return {
        "wallets_investigated": db.query(func.count(AnalysisResult.id)).scalar() or 0,
        "risk_levels": {k or "UNKNOWN": v for k, v in levels.items()},
        "transactions_indexed": db.query(func.count(ChainTx.id)).scalar() or 0,
        "alerts": db.query(func.count(Alert.id)).scalar() or 0,
        "relay_observations": db.query(func.count(RelayObservation.id)).scalar() or 0,
    }


@router.get("/api/demo/scenarios")
def demo_scenarios(db: Session = Depends(get_db)):
    seeded = {a for (a,) in db.query(AddressTx.address)
              .filter(AddressTx.address.in_([s["address"] for s in SCENARIOS])).distinct().all()}
    return {"seeded": bool(seeded),
            "scenarios": [dict(s, available=s["address"] in seeded) for s in SCENARIOS]}


@router.get("/api/entities/watchlist")
def watchlist():
    return {"entities": known_entity_index()}

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AnalysisResult, Wallet
from app.routes.deps import validated_address
from app.services.blockchain_sync import sync_wallet_transactions, load_wallet_txs
from app.services.entity_tagger import tag_address
from app.utils import as_utc

router = APIRouter(tags=["wallet"])


@router.get("/api/wallet/{address}")
def wallet_summary(address: str, db: Session = Depends(get_db)):
    """Sync a wallet and return a lightweight summary (last stored verdict, if any)."""
    address = validated_address(address, db)
    sync = sync_wallet_transactions(db, address)
    views = load_wallet_txs(db, address)
    wallet = db.query(Wallet).filter(Wallet.address == address).first()
    analysis = db.query(AnalysisResult).filter(AnalysisResult.wallet_address == address).first()
    return {
        "wallet": address,
        "transactions_count": len(views),
        "sync": sync,
        "entity": tag_address(address, allow_remote=False),
        "cluster_id": wallet.cluster_id if wallet else None,
        "last_verdict": {
            "risk_score": analysis.final_score,
            "risk_level": analysis.risk_level,
            "updated_at": as_utc(analysis.updated_at).isoformat() if analysis.updated_at else None,
        } if analysis else None,
    }

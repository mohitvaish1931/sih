from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.deps import validated_address
from app.services.blockchain_sync import load_wallet_txs, serialize_tx
from app.services.bitcoin_api import get_btc_price_usd
from app.services.investigation import investigate, evidence_digest, evidence_payload, ENGINE_VERSION
from app.services.rule_engine import WEIGHTS
from app.services.risk_engine import COMPONENT_WEIGHTS

router = APIRouter(tags=["investigation"])


@router.get("/api/wallet/{address}/analyze")
def run_analysis(address: str, refresh: bool = Query(False, description="Bypass caches and re-sync from chain"),
                 db: Session = Depends(get_db)):
    """Full forensic investigation of a wallet."""
    address = validated_address(address, db)
    return investigate(db, address, refresh=refresh)


@router.get("/api/wallet/{address}/transactions")
def wallet_transactions(address: str, limit: int = Query(200, le=1000), db: Session = Depends(get_db)):
    address = validated_address(address, db)
    usd = get_btc_price_usd().get("usd", 0)
    views = load_wallet_txs(db, address)
    return {"wallet": address, "count": len(views),
            "transactions": [serialize_tx(v, usd) for v in reversed(views[-limit:])]}


@router.get("/api/wallet/{address}/report")
def case_report(address: str, analyst: str = Query("SIFRA Analyst", max_length=80),
                case_ref: str = Query("", max_length=60), db: Session = Depends(get_db)):
    """Court-ready case report: verdict, evidence, methodology and a SHA-256 evidence fingerprint."""
    address = validated_address(address, db)
    inv = investigate(db, address)
    payload = evidence_payload(inv)
    digest = evidence_digest(payload)
    now = datetime.now(timezone.utc)
    return {
        "case": {
            "case_id": case_ref or f"SIFRA-{now:%Y%m%d}-{digest[:8].upper()}",
            "generated_at": now.isoformat(),
            "analyst": analyst,
            "subject": address,
            "engine_version": ENGINE_VERSION,
            "evidence_sha256": digest,
            "analysis_generated_at": inv["generated_at"],
        },
        "investigation": inv,
        "methodology": {
            "data_sources": [
                "Bitcoin blockchain via Blockstream Esplora / mempool.space (fallback: blockchain.info)",
                "Entity attribution: SIFRA curated list + WalletExplorer.com",
                "Broadcast telemetry: SIFRA P2P relay sensor (first-spy estimator), GeoIP via ip-api.com, "
                "Tor Project exit list",
                "BTC/USD: CoinGecko (fallback mempool.space, blockchain.info)",
            ],
            "risk_fusion": "Weighted noisy-OR over component scores: risk = 1 - prod(1 - w_i * s_i). "
                           f"Weights: {COMPONENT_WEIGHTS}",
            "detector_weights": WEIGHTS,
            "clustering": "Common-input-ownership heuristic; CoinJoin transactions excluded.",
            "ml": "Isolation Forest over 12 behavioural features, scored as a percentile against the reference "
                  "population (investigated wallets + seeded baseline profiles).",
            "limitations": [
                "Attribution labels are intelligence leads, not proof of ownership.",
                "Only the most recent transactions are analysed for very active addresses (see confidence).",
                "Relay IPs identify the first peer that announced a transaction to SIFRA's node; they are "
                "probabilistic origin estimates and must be corroborated.",
                "Common-input-ownership can be defeated by CoinJoin and PayJoin transactions.",
            ],
        },
        "integrity": {
            "algorithm": "SHA-256",
            "digest": digest,
            "covers": "wallet, verdict, findings with evidence, exposure, cluster id/size, analysed txids, "
                      "analysis timestamp, engine version",
            "canonicalization": "JSON with sorted keys and separators (',', ':')",
            "verify": "sha256(canonical_json(integrity.payload)) must equal integrity.digest; "
                      "POST the payload to /api/report/verify to check.",
            "payload": payload,
        },
    }


@router.post("/api/report/verify")
def verify_report(body: dict):
    """Recompute the evidence fingerprint of an exported report payload."""
    payload = body.get("payload", body)
    digest = evidence_digest(payload)
    expected = body.get("digest")
    return {"digest": digest, "matches": (digest == expected) if expected else None}

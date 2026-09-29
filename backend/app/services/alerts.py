"""Persisted investigation alerts (deduplicated per wallet + type within 24h)."""

import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import Alert
from app.utils import as_utc

DEDUPE_WINDOW = timedelta(hours=24)


def _upsert(db: Session, wallet: str, alert_type: str, severity: str, score: float, reason: str,
            details: Optional[Dict] = None) -> Alert:
    since = datetime.now(timezone.utc) - DEDUPE_WINDOW
    existing = (db.query(Alert)
                .filter(Alert.wallet_address == wallet, Alert.alert_type == alert_type)
                .order_by(Alert.id.desc()).first())
    if existing and existing.created_at and as_utc(existing.created_at) >= since:
        existing.severity = severity
        existing.score = score
        existing.reason = reason
        existing.details = json.dumps(details or {}, default=str)
        return existing
    alert = Alert(wallet_address=wallet, alert_type=alert_type, severity=severity, score=score,
                  reason=reason, details=json.dumps(details or {}, default=str),
                  created_at=datetime.now(timezone.utc))
    db.add(alert)
    return alert


def record_investigation_alerts(db: Session, inv: Dict) -> int:
    wallet = inv["wallet"]
    count = 0
    if inv["risk_level"] in ("HIGH", "CRITICAL"):
        _upsert(db, wallet, f"{inv['risk_level']} RISK WALLET", inv["risk_level"], inv["risk_score"],
                f"Fused risk {inv['risk_score']:.0f}/100", {"breakdown": inv.get("score_breakdown")})
        count += 1
    for f in inv.get("findings", []):
        if f["severity"] in ("MEDIUM", "HIGH", "CRITICAL"):
            _upsert(db, wallet, f["title"].upper(), f["severity"], f["points"], f["summary"],
                    {"finding": f["id"], "typology": f["typology"]})
            count += 1
    for d in (inv.get("exposure") or {}).get("direct", [])[:3]:
        sev = "CRITICAL" if d["category"] in ("ransomware", "sanctioned", "darknet") else "HIGH"
        _upsert(db, wallet, f"{d['category_label'].upper()} EXPOSURE", sev, round(100 * d["share"], 1),
                f"Direct flows with {d['entity_name']}", {"counterparty": d["address"], "txids": d["txids"]})
        count += 1
    geo = inv.get("geo_analysis") or {}
    if geo.get("has_impossible_travel"):
        _upsert(db, wallet, "IMPOSSIBLE TRAVEL", "CRITICAL", geo.get("score", 0), geo.get("summary", ""))
        count += 1
    return count


def record_monitor_alert(db: Session, wallet: str, tx: Dict) -> Alert:
    direction = "OUTGOING" if tx.get("direction") in ("sent", "both") else "INCOMING"
    alert = Alert(wallet_address=wallet, alert_type=f"LIVE {direction} TX", severity="HIGH",
                  score=0.0, reason=f"{tx.get('value_btc', 0)} BTC in tx {tx.get('txid', '')[:16]}…",
                  details=json.dumps({"txid": tx.get("txid")}), created_at=datetime.now(timezone.utc))
    db.add(alert)
    db.commit()
    return alert


def serialize_alert(a: Alert) -> Dict:
    try:
        details = json.loads(a.details) if a.details else {}
    except ValueError:
        details = {}
    return {
        "id": a.id,
        "wallet": a.wallet_address,
        "type": a.alert_type,
        "severity": a.severity,
        "score": a.score,
        "reason": a.reason,
        "details": details,
        "acknowledged": bool(a.acknowledged),
        "created_at": as_utc(a.created_at).isoformat() if a.created_at else None,
    }


def recent_alerts(db: Session, limit: int = 20, wallet: Optional[str] = None) -> List[Dict]:
    q = db.query(Alert)
    if wallet:
        q = q.filter(Alert.wallet_address == wallet)
    return [serialize_alert(a) for a in q.order_by(Alert.id.desc()).limit(limit).all()]

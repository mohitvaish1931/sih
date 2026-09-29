"""
Relay telemetry ingest. The P2P sensor (sensor/relay_sensor.py) posts the first
peer that announced each transaction; SIFRA enriches the IP (GeoIP, Tor exit
list) and uses it for geo-velocity analysis.
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import TELEMETRY_TOKEN
from app.database import get_db
from app.models import RelayObservation
from app.services.geoip import lookup_many
from app.utils import as_utc

router = APIRouter(tags=["telemetry"])


class Observation(BaseModel):
    txid: str = Field(..., min_length=64, max_length=64)
    peer_ip: str
    first_seen: float = Field(..., description="Unix timestamp (seconds) when the first inv arrived")
    peers_announcing: int = 1
    confidence: float = Field(1.0, ge=0, le=1)


class ObservationBatch(BaseModel):
    sensor_id: str = "sifra-sensor"
    observations: List[Observation]


@router.post("/api/telemetry/observations")
def ingest(batch: ObservationBatch, db: Session = Depends(get_db),
           x_sifra_token: Optional[str] = Header(None)):
    if TELEMETRY_TOKEN and x_sifra_token != TELEMETRY_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid telemetry token")
    obs = batch.observations[:2000]
    if not obs:
        return {"stored": 0}
    txids = [o.txid for o in obs]
    existing = {t for (t,) in db.query(RelayObservation.txid).filter(RelayObservation.txid.in_(txids)).all()}
    geo = lookup_many([o.peer_ip for o in obs if o.txid not in existing])
    stored = 0
    for o in obs:
        if o.txid in existing:
            continue
        g = geo.get(o.peer_ip, {})
        db.add(RelayObservation(
            txid=o.txid, peer_ip=o.peer_ip,
            first_seen=datetime.fromtimestamp(o.first_seen, timezone.utc),
            peers_announcing=o.peers_announcing, confidence=o.confidence, sensor_id=batch.sensor_id,
            country=g.get("country"), city=g.get("city"), latitude=g.get("lat"), longitude=g.get("lon"),
            isp=g.get("isp"), is_vpn_tor=bool(g.get("is_vpn_tor")),
        ))
        existing.add(o.txid)
        stored += 1
    db.commit()
    return {"stored": stored, "skipped": len(obs) - stored}


@router.get("/api/telemetry/stats")
def stats(db: Session = Depends(get_db)):
    total = db.query(func.count(RelayObservation.id)).scalar() or 0
    last = db.query(func.max(RelayObservation.first_seen)).scalar()
    sensors = [s for (s,) in db.query(RelayObservation.sensor_id).distinct().limit(20).all()]
    countries = db.query(RelayObservation.country, func.count(RelayObservation.id)) \
        .group_by(RelayObservation.country).order_by(func.count(RelayObservation.id).desc()).limit(8).all()
    anonymised = db.query(func.count(RelayObservation.id)).filter(RelayObservation.is_vpn_tor.is_(True)).scalar() or 0
    return {
        "observations": total,
        "anonymised": anonymised,
        "last_observation": as_utc(last).isoformat() if last else None,
        "sensors": sensors,
        "top_countries": [{"country": c or "Unknown", "count": n} for c, n in countries],
    }


@router.get("/api/telemetry/recent")
def recent(limit: int = Query(25, le=200), db: Session = Depends(get_db)):
    rows = db.query(RelayObservation).order_by(RelayObservation.id.desc()).limit(limit).all()
    return {"observations": [{
        "txid": r.txid, "peer_ip": r.peer_ip, "first_seen": as_utc(r.first_seen).isoformat(),
        "country": r.country, "city": r.city, "isp": r.isp, "is_vpn_tor": r.is_vpn_tor,
        "peers_announcing": r.peers_announcing, "confidence": r.confidence, "sensor_id": r.sensor_id,
    } for r in rows]}

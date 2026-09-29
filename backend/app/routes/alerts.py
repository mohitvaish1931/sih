from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Alert
from app.services.alerts import recent_alerts, serialize_alert

router = APIRouter(tags=["alerts"])


@router.get("/api/alerts")
def list_alerts(limit: int = Query(20, le=200), wallet: Optional[str] = None, db: Session = Depends(get_db)):
    return {"alerts": recent_alerts(db, limit=limit, wallet=wallet)}


@router.post("/api/alerts/{alert_id}/ack")
def acknowledge_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.acknowledged = True
    db.commit()
    return serialize_alert(alert)

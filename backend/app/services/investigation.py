"""
Investigation orchestrator: sync -> heuristics -> exposure -> clustering -> ML ->
telemetry -> fusion -> narrative -> persistence. Results are cached briefly so
the graph and report endpoints reuse the same verdict.
"""

import hashlib
import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.models import AnalysisResult, Wallet
from app.services.alerts import record_investigation_alerts
from app.services.anomaly_engine import run_isolation_forest
from app.services.bitcoin_api import get_btc_price_usd, fetch_wallet_balance
from app.services.blockchain_sync import sync_wallet_transactions, load_wallet_txs, serialize_tx, get_sync_state
from app.services.clustering import common_input_cluster, attribute_cluster, persist_cluster
from app.services.entity_tagger import tag_addresses_batch
from app.services.explainability import generate_ai_explanation, recommendations
from app.services.exposure_engine import analyze_exposure, counterparty_flows
from app.services.geo_velocity_engine import analyze_geo_velocity
from app.services.risk_engine import fuse, confidence
from app.services.rule_engine import run_heuristics
from app.utils import is_demo_address

log = logging.getLogger("sifra.investigation")

ENGINE_VERSION = "SIFRA-3.0"
_CACHE_TTL = 90
_cache: Dict[str, Dict] = {}
_cache_lock = threading.Lock()
_inflight: Dict[str, threading.Lock] = defaultdict(threading.Lock)


def cached_investigation(address: str) -> Optional[Dict]:
    with _cache_lock:
        hit = _cache.get(address)
    if hit and time.time() - hit["ts"] < _CACHE_TTL:
        return hit["inv"]
    return None


def investigate(db: Session, address: str, refresh: bool = False) -> Dict:
    with _inflight[address]:          # concurrent requests for one wallet share one run
        if not refresh:
            hit = cached_investigation(address)
            if hit:
                return hit
        inv = _run(db, address, refresh)
        with _cache_lock:
            _cache[address] = {"ts": time.time(), "inv": inv}
        return inv


def _run(db: Session, address: str, refresh: bool) -> Dict:
    t0 = time.time()
    timings = {}
    demo = is_demo_address(address)

    sync = sync_wallet_transactions(db, address, force=refresh)
    timings["sync_ms"] = int((time.time() - t0) * 1000)
    views = load_wallet_txs(db, address)

    price = get_btc_price_usd()
    usd = price.get("usd", 0) or 0

    t = time.time()
    heur = run_heuristics(address, views, db, network_hops=0 if demo else 4)
    timings["heuristics_ms"] = int((time.time() - t) * 1000)

    flows = counterparty_flows(address, views)
    cluster = common_input_cluster(db, address, views)

    t = time.time()
    top_cp = sorted(flows, key=lambda a: -(flows[a]["received_from"] + flows[a]["sent_to"]))[:60]
    peel = next((f for f in heur["findings"] if f["id"] == "peel_chain"), None)
    extra = []
    if peel:
        for h in peel["evidence"].get("hops", []):
            extra += [h["peeled_to"], h["remainder_to"]]
        if peel["evidence"].get("terminal"):
            extra.append(peel["evidence"]["terminal"]["address"])
    entities = tag_addresses_batch([address] + top_cp + cluster["members"][:15] + extra)
    timings["attribution_ms"] = int((time.time() - t) * 1000)
    entity = entities[address]
    if peel and peel["evidence"].get("terminal"):
        term = peel["evidence"]["terminal"]
        ent = entities.get(term["address"]) or {}
        term.update({"entity_name": ent.get("entity_name"), "category": ent.get("category"),
                     "category_label": ent.get("category_label")})

    exposure = analyze_exposure(db, address, views, entities, flows)
    attribute_cluster(cluster, entities)

    t = time.time()
    ml = run_isolation_forest(db, address, views)
    timings["ml_ms"] = int((time.time() - t) * 1000)

    geo = analyze_geo_velocity(views, address)

    components = {
        "behaviour": {"score": heur["score"], "available": bool(views),
                      "summary": ", ".join(f["title"] for f in heur["findings"] if f["severity"] != "INFO")
                      or "No typology triggered"},
        "exposure": {"score": exposure["score"], "available": True,
                     "summary": (f"{len(exposure['direct'])} illicit counterparties, "
                                 f"{len(exposure['indirect'])} at 2 hops") if exposure["score"] else "No illicit exposure"},
        "anomaly": {"score": ml["score"], "available": ml["available"],
                    "summary": (f"More anomalous than {ml['percentile']:.0f}% of {ml['population_size']} reference wallets"
                                if ml["available"] else ml.get("reason", ""))},
        "geo": {"score": geo["score"], "available": geo["data_available"], "summary": geo["summary"]},
    }
    state = get_sync_state(db, address)
    fused = fuse(components, entity, onchain_tx_count=(state.tx_count_onchain if state else 0) or 0)

    # ----- statistics -----
    inflow = sum(v["inflow_btc"] for v in views)
    outflow = sum(v["outflow_btc"] for v in views)
    stamps = [v["timestamp"] for v in views if v["timestamp"]]
    if demo:
        bal_btc = sum(v["received_btc"] for v in views) - sum(v["spent_btc"] for v in views)
        balance = {"confirmed_btc": round(max(0.0, bal_btc), 8), "unconfirmed_btc": 0.0,
                   "lifetime_received_btc": round(sum(v["received_btc"] for v in views), 8),
                   "lifetime_sent_btc": round(sum(v["spent_btc"] for v in views), 8), "tx_count": len(views),
                   "available": True}
    else:
        b = fetch_wallet_balance(address)
        balance = {"confirmed_btc": b.get("confirmed_btc", 0), "unconfirmed_btc": b.get("unconfirmed_btc", 0),
                   "lifetime_received_btc": b.get("total_received_btc", 0),
                   "lifetime_sent_btc": b.get("total_sent_btc", 0), "tx_count": b.get("tx_count", 0),
                   "available": b.get("available", False)}
    balance["confirmed_usd"] = round((balance["confirmed_btc"] or 0) * usd, 2)

    onchain =balance.get("tx_count") or (state.tx_count_onchain if state else 0) or len(views)
    sources = ["demo-seed"] if demo else [s for s in {sync.get("source") or (state.source if state else None)} if s]
    conf = confidence(len(views), onchain, sources)

    statistics = {
        "transactions_count": len(views),
        "onchain_tx_count": onchain,
        "connected_wallets": len(flows),
        "total_received_btc": round(inflow, 8),
        "total_sent_btc": round(outflow, 8),
        "total_received_usd": round(inflow * usd, 2),
        "total_sent_usd": round(outflow * usd, 2),
        "btc_price_usd": usd,
        "btc_price_inr": price.get("inr", 0),
        "first_seen": min(stamps).isoformat() if stamps else None,
        "last_seen": max(stamps).isoformat() if stamps else None,
        "unconfirmed_txs": sum(1 for v in views if v["timestamp"] is None),
    }

    daily: Dict[str, Dict] = {}
    for v in views:
        if not v["timestamp"]:
            continue
        d = v["timestamp"].strftime("%Y-%m-%d")
        row = daily.setdefault(d, {"date": d, "received": 0.0, "sent": 0.0, "tx_count": 0})
        row["received"] += v["inflow_btc"]
        row["sent"] += v["outflow_btc"]
        row["tx_count"] += 1
    time_series = [{"date": d, "received": round(r["received"], 8), "sent": round(r["sent"], 8),
                    "tx_count": r["tx_count"], "received_usd": round(r["received"] * usd, 2),
                    "sent_usd": round(r["sent"] * usd, 2)}
                   for d, r in sorted(daily.items())[-30:]]

    patterns = [f"{f['title']}: {f['summary']}" for f in heur["findings"] if f["severity"] != "INFO"]
    for d in exposure["direct"][:3]:
        patterns.append(f"Direct exposure to {d['category_label']}: {d['entity_name']} ({d['share']:.1%} of value)")
    if geo.get("has_impossible_travel"):
        patterns.append(f"Impossible travel: {geo['max_velocity_kmh']:,.0f} km/h between observed broadcast relays")
    elif geo.get("vpn_tor_count"):
        patterns.append("Broadcast via Tor / VPN relay infrastructure")

    inv = {
        "wallet": address,
        "is_demo": demo,
        "risk_score": fused["risk_score"],
        "risk_level": fused["risk_level"],
        "score_breakdown": fused["breakdown"],
        "adjustments": fused["adjustments"],
        "confidence": conf,
        "patterns": patterns,
        "findings": heur["findings"],
        "behaviour_score": heur["score"],
        "ml_anomaly_score": ml["score"],
        "ml": ml,
        "exposure": exposure,
        "cluster": cluster,
        "entity": entity,
        "counterparty_entities": {a: entities[a] for a in entities if a != address},
        "statistics": statistics,
        "balance": balance,
        "time_series": time_series,
        "geo_analysis": geo,
        "transactions": [serialize_tx(v, usd) for v in reversed(views[-100:])],
        "sync": sync,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine_version": ENGINE_VERSION,
    }

    t = time.time()
    explanation = generate_ai_explanation(inv)
    timings["narrative_ms"] = int((time.time() - t) * 1000)
    inv["ai_explanation"] = explanation["text"]
    inv["explanation_source"] = explanation["source"]
    inv["recommendations"] = recommendations(inv)

    _persist(db, inv, heur["score"], exposure["score"], geo["score"], ml["score"])
    timings["total_ms"] = int((time.time() - t0) * 1000)
    inv["timings"] = timings
    return inv


def _persist(db: Session, inv: Dict, rule_score, exposure_score, geo_score, anomaly_score):
    address = inv["wallet"]
    try:
        row = db.query(AnalysisResult).filter(AnalysisResult.wallet_address == address).first()
        if not row:
            row = AnalysisResult(wallet_address=address)
            db.add(row)
        row.rule_score = rule_score
        row.anomaly_score = anomaly_score
        row.exposure_score = exposure_score
        row.graph_score = exposure_score
        row.geo_score = geo_score
        row.final_score = inv["risk_score"]
        row.risk_level = inv["risk_level"]
        row.reasons = "; ".join(inv["patterns"])[:2000]
        row.updated_at = datetime.now(timezone.utc)

        wallet = db.query(Wallet).filter(Wallet.address == address).first()
        if not wallet:
            wallet = Wallet(address=address)
            db.add(wallet)
        wallet.risk_score = inv["risk_score"]
        wallet.risk_level = inv["risk_level"]
        db.flush()
        persist_cluster(db, address, inv["cluster"], inv["risk_score"])
        record_investigation_alerts(db, inv)
        db.commit()
    except Exception as exc:
        db.rollback()
        log.warning("Could not persist investigation for %s: %s", address, exc)


def _normalize_numbers(obj):
    """1.0 and 1 must hash identically: JavaScript clients re-serialise integral floats as ints."""
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    if isinstance(obj, dict):
        return {k: _normalize_numbers(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize_numbers(v) for v in obj]
    return obj


def canonical_json(payload) -> str:
    return json.dumps(_normalize_numbers(json.loads(json.dumps(payload, default=str))),
                      sort_keys=True, separators=(",", ":"))


def evidence_payload(inv: Dict) -> Dict:
    """The verdict and the evidence it rests on, in a stable JSON-safe form."""
    return json.loads(canonical_json({
        "wallet": inv["wallet"],
        "risk_score": inv["risk_score"],
        "risk_level": inv["risk_level"],
        "findings": [{"id": f["id"], "points": f["points"], "evidence": f["evidence"]} for f in inv["findings"]],
        "exposure": inv["exposure"],
        "cluster": {"id": inv["cluster"].get("cluster_id"), "size": inv["cluster"].get("size")},
        "txids": sorted(t["txid"] for t in inv["transactions"]),
        "generated_at": inv["generated_at"],
        "engine_version": inv["engine_version"],
    }))


def evidence_digest(payload: Dict) -> str:
    """SHA-256 of the canonical evidence payload (chain-of-custody fingerprint)."""
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()

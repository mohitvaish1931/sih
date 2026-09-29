"""
SIFRA behavioural anomaly model.

Each wallet is summarised by 10 scale-free behavioural features (size is
deliberately excluded: big is not suspicious). An Isolation Forest is trained
on a reference population:
  * every wallet already investigated in this SIFRA instance, plus
  * a fixed, seeded baseline of 400 simulated ordinary wallet histories
    (retail, saver, merchant, trader, payroll) passed through the very same
    feature pipeline, so the model is meaningful even on a fresh install.
  * once available, ~80 randomly sampled live mainnet addresses taken from
    the latest blocks (build_live_reference, run in the background at startup).
The target wallet is scored against that population (percentile of its
isolation score) and the features that deviate most from the population
median are reported, so the ML verdict is explainable.

Scoring is one-sided: before scoring, every feature that deviates in the
*benign* direction (e.g. holding funds longer than usual) is clipped to the
population median, so only risk-relevant unusualness can raise the score.
"""

import json
import logging
import math
import statistics
import threading
import time
from datetime import timedelta
from typing import Dict, List, Optional

import numpy as np
from sklearn.ensemble import IsolationForest
from sqlalchemy.orm import Session

from app.models import AddressSync, MlReference

log = logging.getLogger("sifra.ml")

FEATURE_VERSION = 2

# (name, label, risk direction: +1 higher is riskier, -1 lower is riskier, 0 two-sided)
FEATURES = [
    ("outgoing_ratio", "Share of outgoing txs"),
    ("avg_outputs", "Avg outputs per spend (log)"),
    ("avg_inputs", "Avg inputs per tx (log)"),
    ("passthrough_24h", "Value forwarded within 24h"),
    ("log_median_gap_h", "Median gap between txs (log h)"),
    ("gap_cv", "Spend timing irregularity (log CV)"),
    ("round_ratio", "Round-amount share"),
    ("counterparty_diversity", "Counterparties per tx"),
    ("retention", "Value retained in wallet"),
    ("log_max_hourly", "Peak spends per hour (log)"),
]
DIRECTION = {
    "outgoing_ratio": 0, "avg_outputs": 1, "avg_inputs": 0, "passthrough_24h": 1, "log_median_gap_h": -1,
    "gap_cv": 1, "round_ratio": 1, "counterparty_diversity": 1, "retention": -1, "log_max_hourly": 1,
}

_model_lock = threading.Lock()
_model: Dict = {"clf": None, "X": None, "scores": None, "trained_at": 0, "size": 0}
_feature_cache: Dict[str, Dict] = {}
_RETRAIN_SECONDS = 600
MIN_TXS = 5
_baseline_cache: Dict[str, np.ndarray] = {}


def extract_features(address: str, views: List[Dict]) -> Optional[Dict[str, float]]:
    txs = [v for v in views if v["timestamp"] is not None]
    if len(views) < MIN_TXS:
        return None
    n = len(views)
    spends = [v for v in views if v["is_input"]]
    inflow = sum(v["inflow_btc"] for v in views)
    outflow = sum(v["outflow_btc"] for v in views)
    volume = inflow + outflow

    times = sorted(v["timestamp"] for v in txs)
    spend_times = sorted(v["timestamp"] for v in txs if v["is_input"])
    # Timing is an owner signal: use the wallet's own spends when it has enough of them
    basis = spend_times if len(spend_times) >= 3 else times
    gaps = [(b - a).total_seconds() / 3600 for a, b in zip(basis, basis[1:])]
    median_gap = statistics.median(gaps) if gaps else 24 * 30
    if len(spend_times) >= 3 and len(gaps) >= 2 and statistics.mean(gaps) > 0:
        gap_cv = statistics.pstdev(gaps) / statistics.mean(gaps)
    else:
        gap_cv = 1.0   # neutral (Poisson-like) when senders, not the owner, set the rhythm

    # Value forwarded within 24h of arrival
    forwarded = 0.0
    ins = sorted((v for v in txs if v["inflow_btc"] > 0), key=lambda v: v["timestamp"])
    outs = sorted((v for v in txs if v["is_input"] and v["outflow_btc"] > 0), key=lambda v: v["timestamp"])
    for inc in ins:
        nxt = next((o for o in outs if inc["timestamp"] <= o["timestamp"] <= inc["timestamp"] + timedelta(hours=24)), None)
        if nxt:
            forwarded += min(inc["inflow_btc"], nxt["outflow_btc"])
    passthrough = forwarded / inflow if inflow else 0.0

    out_values = [v["outflow_btc"] for v in spends if v["outflow_btc"] > 0]
    round_ratio = (sum(1 for x in out_values if abs(x * 100 - round(x * 100)) < 1e-6) / len(out_values)) if out_values else 0

    parties = set()
    for v in views:
        if v["is_input"]:
            parties.update(o["address"] for o in v["outputs"] if o.get("address") and o["address"] != address)
        else:
            parties.update(i["address"] for i in v["inputs"] if i.get("address"))

    max_hourly, j = 0, 0
    for i in range(len(spend_times)):
        while spend_times[i] - spend_times[j] > timedelta(hours=1):
            j += 1
        max_hourly = max(max_hourly, i - j + 1)

    return {
        "log_tx_count": math.log1p(n),
        "log_volume_btc": math.log1p(volume),
        "outgoing_ratio": len(spends) / n,
        "avg_outputs": math.log1p(statistics.mean([v["output_count"] for v in spends]) if spends else 2),
        "avg_inputs": math.log1p(statistics.mean([v["input_count"] for v in views])),
        "passthrough_24h": min(1.0, passthrough),
        "log_median_gap_h": math.log1p(median_gap),
        "gap_cv": math.log1p(min(gap_cv, 20.0)),
        "round_ratio": round_ratio,
        "counterparty_diversity": min(5.0, len(parties) / n),
        "retention": max(0.0, min(1.0, 1 - (outflow / inflow))) if inflow else 0.0,
        "log_max_hourly": math.log1p(max_hourly),
        "_v": FEATURE_VERSION,
    }


_PROFILES = {
    #            share  n_txs      mean gap (h)  spend prob  inputs/deposit  sender pool
    "retail":   (0.40, (5, 40),   120,          0.40,       (1, 2),         8),
    "saver":    (0.20, (5, 15),   720,          0.15,       (1, 2),         3),
    "merchant": (0.15, (20, 150), 10,           0.12,       (1, 3),         400),
    "trader":   (0.15, (10, 120), 24,           0.50,       (1, 3),         4),
    "payroll":  (0.10, (10, 60),  168,          0.45,       (1, 2),         2),
}


def _simulate_wallet(rng, kind: str) -> List[Dict]:
    """Simulate an ordinary wallet's history in the same view format the engines consume."""
    from datetime import datetime, timezone
    _, (lo, hi), gap_h, p_spend, (in_lo, in_hi), pool = _PROFILES[kind]
    n = int(rng.integers(lo, hi + 1))
    t = datetime(2024, 1, 1, tzinfo=timezone.utc)
    balance, views = 0.0, []
    senders = [f"s{kind}{i}" for i in range(pool)]
    for k in range(n):
        t += timedelta(hours=float(rng.exponential(gap_h)) + 0.05)
        spend = balance > 0.001 and rng.random() < p_spend
        if spend:
            frac = float(rng.uniform(0.05, 0.9))
            amount = round(balance * frac, 2 if rng.random() < 0.35 else 6)
            outs = int(rng.choice([1, 2, 2, 2, 3]))
            inputs_n = int(rng.integers(1, 3)) if kind != "merchant" else int(rng.integers(2, 12))
            views.append({"timestamp": t, "is_input": True, "inflow_btc": 0.0, "outflow_btc": amount,
                          "input_count": inputs_n, "output_count": outs,
                          "inputs": [{"address": "self"}], "outputs": [{"address": f"r{kind}{k}"}]})
            balance -= amount
        else:
            amount = float(rng.lognormal(-2.5 if kind == "merchant" else -1.2, 1.1))
            views.append({"timestamp": t, "is_input": False, "inflow_btc": amount, "outflow_btc": 0.0,
                          "input_count": int(rng.integers(in_lo, in_hi + 1)), "output_count": 2,
                          "inputs": [{"address": senders[int(rng.integers(0, pool))]}], "outputs": []})
            balance += amount
    return views


def _baseline_population(size: int = 400) -> np.ndarray:
    """Deterministic reference population of simulated ordinary wallets."""
    rng = np.random.default_rng(1907)
    kinds = list(_PROFILES)
    probs = [p[0] for p in _PROFILES.values()]
    rows = []
    while len(rows) < size:
        kind = kinds[int(rng.choice(len(kinds), p=probs))]
        feats = extract_features("self", _simulate_wallet(rng, kind))
        if feats:
            rows.append(_feature_vector(feats))
    return np.array(rows, dtype=float)


def _feature_vector(feats: Dict[str, float]) -> List[float]:
    return [float(feats[name]) for name, _ in FEATURES]


def _clip_benign(x: np.ndarray, med: np.ndarray) -> np.ndarray:
    """One-sided scoring: deviations in the benign direction are pulled back to the median."""
    out = x.copy()
    for i, (name, _) in enumerate(FEATURES):
        d = DIRECTION.get(name, 0)
        if d > 0 and out[i] < med[i]:
            out[i] = med[i]
        elif d < 0 and out[i] > med[i]:
            out[i] = med[i]
    return out


def remember_features(address: str, feats: Optional[Dict[str, float]]):
    if feats:
        _feature_cache[address] = feats


LIVE_REFERENCE_TARGET = 80


def _live_reference(db: Session) -> List[List[float]]:
    try:
        rows = db.query(MlReference.features_json).limit(500).all()
        feats = [json.loads(r[0]) for r in rows]
        return [_feature_vector(f) for f in feats if f.get("_v") == FEATURE_VERSION]
    except Exception:
        return []


def _population(db: Session) -> np.ndarray:
    if "base" not in _baseline_cache:
        _baseline_cache["base"] = _baseline_population()
    base = _baseline_cache["base"]
    live = _live_reference(db)
    parts = []
    if len(live) >= 30:
        # Real network behaviour dominates; simulated profiles keep the ordinary-retail tail covered
        parts += [np.array(live), base[:150]]
    else:
        parts.append(base)
        if live:
            parts.append(np.array(live))
    investigated = [_feature_vector(f) for f in _feature_cache.values()]
    if investigated:
        parts.append(np.array(investigated))
    _model["composition"] = {"live_mainnet_sample": len(live), "simulated_baseline": int(parts[1].shape[0]) if len(live) >= 30 else int(base.shape[0]),
                             "investigated": len(investigated)}
    return np.vstack(parts)


def build_live_reference(db: Session, target: int = LIVE_REFERENCE_TARGET) -> int:
    """
    Sample random addresses that appear in the latest blocks, pull their recent
    history and store their behavioural features as the ML reference population.
    """
    import random
    from app.services.bitcoin_api import get_latest_blocks, get_block_txs, fetch_wallet_transactions
    from app.services.blockchain_sync import _view
    from app.utils import from_unix

    have = set()
    for addr, fj in db.query(MlReference.address, MlReference.features_json).all():
        if json.loads(fj).get("_v") == FEATURE_VERSION:
            have.add(addr)
        else:
            db.query(MlReference).filter(MlReference.address == addr).delete()   # stale feature definition
    db.commit()
    if len(have) >= target:
        return 0
    candidates = []
    for b in get_latest_blocks(count=3):
        for tx in get_block_txs(b["hash"], pages=2):
            if tx.get("is_coinbase"):
                continue
            candidates += [o["address"] for o in tx["outputs"] if o.get("address")]
    rng = random.Random(len(candidates))
    rng.shuffle(candidates)
    added = 0
    for addr in dict.fromkeys(candidates):
        if len(have) + added >= target:
            break
        if addr in have:
            continue
        txs = fetch_wallet_transactions(addr, limit=50)
        views = [_view(addr, t["txid"], from_unix(t.get("timestamp")), t.get("block_height"), t.get("fee_btc"),
                       t["inputs"], t["outputs"], "reference") for t in txs]
        feats = extract_features(addr, views)
        if feats:
            db.add(MlReference(address=addr, features_json=json.dumps(feats), tx_count=len(views)))
            db.commit()
            added += 1
        time.sleep(0.25)
    if added:
        with _model_lock:
            _model["clf"] = None     # retrain on the enlarged population
    log.info("ML reference population: +%d live mainnet addresses", added)
    return added


def _get_model(db: Session):
    with _model_lock:
        size = len(_feature_cache)
        stale = time.time() - _model["trained_at"] > _RETRAIN_SECONDS
        if _model["clf"] is None or stale or abs(size - _model["size"]) >= max(3, 0.1 * max(1, _model["size"])):
            X = _population(db)
            clf = IsolationForest(n_estimators=200, contamination="auto", random_state=42)
            clf.fit(X)
            _model.update({"clf": clf, "X": X, "scores": clf.score_samples(X),
                           "trained_at": time.time(), "size": size})
        return _model["clf"], _model["X"], _model["scores"]


def run_isolation_forest(db: Session, address: str, views: Optional[List[Dict]] = None) -> Dict:
    """Score a wallet against the reference population. Returns score + explanation."""
    if views is None:
        from app.services.blockchain_sync import load_wallet_txs
        views = load_wallet_txs(db, address)
    feats = extract_features(address, views)
    if feats is None:
        return {"score": 0.0, "available": False, "reason": f"Needs at least {MIN_TXS} transactions",
                "top_features": [], "population_size": 0, "features": {}}

    clf, X, pop_scores = _get_model(db)
    med = np.median(X, axis=0)
    raw = np.array(_feature_vector(feats))
    x = np.array([_clip_benign(raw, med)])
    s = float(clf.score_samples(x)[0])
    # Fraction of the population that is *less* anomalous than the target
    percentile = float(np.mean(pop_scores > s))
    score = max(0.0, min(100.0, (percentile - 0.5) * 200))

    q75, q25 = np.percentile(X, [75, 25], axis=0)
    iqr = np.where((q75 - q25) < 1e-6, 1.0, q75 - q25)
    z = (x[0] - med) / iqr
    top = []
    for idx in np.argsort(-np.abs(z))[:4]:
        name, label = FEATURES[idx]
        if abs(z[idx]) < 1.0:
            continue
        top.append({"feature": name, "label": label, "value": round(float(x[0][idx]), 3),
                    "population_median": round(float(med[idx]), 3), "deviation_iqr": round(float(z[idx]), 2),
                    "direction": "higher" if z[idx] > 0 else "lower"})

    remember_features(address, feats)

    return {
        "score": round(score, 1),
        "available": True,
        "percentile": round(percentile * 100, 1),
        "isolation_score": round(s, 4),
        "top_features": top,
        "population_size": int(X.shape[0]),
        "investigated_wallets": len(_feature_cache),
        "features": {k: round(v, 4) for k, v in feats.items() if not k.startswith("_")},
        "scoring": "one-sided (benign-direction deviations clipped to population median)",
        "model": "IsolationForest(n_estimators=200)",
        "population": _model.get("composition"),
    }


def warm_population(db: Session, limit: int = 60):
    """Load features of recently investigated wallets so the model reflects this deployment."""
    from app.services.blockchain_sync import load_wallet_txs
    try:
        rows = db.query(AddressSync.address).order_by(AddressSync.last_synced.desc()).limit(limit).all()
        for (addr,) in rows:
            if addr in _feature_cache:
                continue
            feats = extract_features(addr, load_wallet_txs(db, addr))
            remember_features(addr, feats)
    except Exception as exc:
        log.warning("Population warm-up skipped: %s", exc)

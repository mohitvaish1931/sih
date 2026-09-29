"""
SIFRA behavioural heuristics.

Each detector inspects the wallet's normalized transaction views and returns a
Finding with a strength (0..1), evidence (txids, metrics) and the laundering
typology it maps to. Findings are combined with a noisy-OR so several weak
signals add up but the score can never exceed 100.
"""

import json
import logging
import statistics
from collections import Counter
from datetime import timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import AddressTx, ChainTx
from app.utils import as_utc, short

SEVERITY_ORDER = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

# Detector weights: how much a fully-triggered detector contributes to risk
WEIGHTS = {
    "peel_chain": 0.90,
    "coinjoin": 0.80,
    "rapid_passthrough": 0.70,
    "fan_out": 0.60,
    "fan_in": 0.55,
    "burst": 0.50,
    "dormant_reactivation": 0.45,
    "high_connectivity": 0.25,
    "round_amounts": 0.15,
    "dust_target": 0.0,
}


def _severity(points: float) -> str:
    if points >= 60:
        return "HIGH"
    if points >= 35:
        return "MEDIUM"
    if points > 0:
        return "LOW"
    return "INFO"


def _finding(fid: str, title: str, strength: float, summary: str, typology: str,
             evidence: Dict, severity: Optional[str] = None) -> Dict:
    strength = max(0.0, min(1.0, strength))
    points = round(100 * strength * WEIGHTS.get(fid, 0.3), 1)
    return {
        "id": fid,
        "title": title,
        "strength": round(strength, 3),
        "weight": WEIGHTS.get(fid, 0.3),
        "points": points,
        "severity": severity or _severity(points),
        "summary": summary,
        "typology": typology,
        "evidence": evidence,
    }


def _ts(v):
    return v["timestamp"]


def _confirmed(views: List[Dict]) -> List[Dict]:
    return [v for v in views if v["timestamp"] is not None]


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------
def detect_rapid_passthrough(address: str, views: List[Dict]) -> Optional[Dict]:
    """Funds received and pushed onward within an hour (money-mule / layering hop)."""
    txs = _confirmed(views)
    inflows = [v for v in txs if v["inflow_btc"] > 0]
    outflows = [v for v in txs if v["is_input"] and v["outflow_btc"] > 0]
    if not inflows or not outflows:
        return None
    total_in = sum(v["inflow_btc"] for v in inflows)
    outflows.sort(key=_ts)
    remaining = {o["txid"]: o["outflow_btc"] for o in outflows}
    pairs, fast_value, dwell_minutes, events = [], 0.0, [], 0
    for inc in sorted(inflows, key=_ts):
        later = [o for o in outflows if _ts(o) >= _ts(inc)]
        if not later:
            break
        dwell_minutes.append((_ts(later[0]) - _ts(inc)).total_seconds() / 60)
        # Greedily allocate this deposit to spends made within the next hour
        need, forwarded, first_out = inc["inflow_btc"], 0.0, None
        for o in later:
            if (_ts(o) - _ts(inc)) > timedelta(minutes=60) or need <= 0:
                break
            take = min(need, remaining[o["txid"]])
            if take > 0:
                remaining[o["txid"]] -= take
                need -= take
                forwarded += take
                first_out = first_out or o
        if forwarded > 0:
            events += 1
            fast_value += forwarded
            if len(pairs) < 6:
                pairs.append({"in_txid": inc["txid"], "out_txid": first_out["txid"],
                              "minutes": round((_ts(first_out) - _ts(inc)).total_seconds() / 60, 1),
                              "btc": round(forwarded, 6)})
    ratio = fast_value / total_in if total_in else 0
    if events == 0 or (ratio < 0.3 and events < 3):
        return None
    median_dwell = statistics.median(dwell_minutes) if dwell_minutes else None
    return _finding(
        "rapid_passthrough", "Rapid pass-through of funds",
        0.4 + 0.6 * min(1.0, ratio),
        f"{events} deposit(s) forwarded within 60 min; {ratio:.0%} of incoming value left almost immediately "
        f"(median dwell {median_dwell:.0f} min).",
        "Layering - money-mule / pass-through wallet",
        {"events": events, "fast_ratio": round(ratio, 3), "median_dwell_minutes": round(median_dwell or 0, 1),
         "pairs": pairs},
    )


def _spend_ratio(views: List[Dict]) -> float:
    return sum(1 for v in views if v["is_input"]) / len(views) if views else 0.0


def detect_burst(address: str, views: List[Dict]) -> Optional[Dict]:
    """Abnormally many spends inside a one-hour window (receipts are other people's actions)."""
    times = sorted(_ts(v) for v in _confirmed(views) if v["is_input"])
    if len(times) < 10:
        return None
    best, best_start, j = 0, None, 0
    for i in range(len(times)):
        while times[i] - times[j] > timedelta(hours=1):
            j += 1
        if i - j + 1 > best:
            best, best_start = i - j + 1, times[j]
    if best < 10:
        return None
    return _finding(
        "burst", "Transaction burst",
        0.5 + min(0.5, (best - 10) / 30),
        f"{best} outgoing transactions inside a single 60-minute window starting {best_start:%Y-%m-%d %H:%M} UTC.",
        "Automated / scripted movement of funds",
        {"max_tx_per_hour": best, "window_start": best_start.isoformat()},
    )


def _peel_shape(address: str, v: Dict) -> Optional[Dict]:
    """A spend with exactly two outputs: a small 'peel' and a large remainder to a fresh address."""
    if not v["is_input"] or len(v["outputs"]) != 2:
        return None
    outs = [o for o in v["outputs"] if o.get("address")]
    if len(outs) != 2 or any(o["address"] == address for o in outs):
        return None
    small, large = sorted(outs, key=lambda o: o.get("value") or 0)
    total = (small["value"] or 0) + (large["value"] or 0)
    if total <= 0 or small["value"] / total > 0.25:
        return None
    return {"txid": v["txid"], "from": address, "peeled_to": small["address"], "peeled_btc": round(small["value"], 6),
            "remainder_to": large["address"], "remainder_btc": round(large["value"], 6)}


def _spends_of(db: Session, address: str) -> List[ChainTx]:
    txids = [t for (t,) in db.query(AddressTx.txid).filter(AddressTx.address == address,
                                                             AddressTx.is_input.is_(True)).all()]
    if not txids:
        return []
    return db.query(ChainTx).filter(ChainTx.txid.in_(txids[:50])).all()


def _follow_peel_chain(db: Session, start: str, max_hops: int = 12, network_hops: int = 0) -> List[Dict]:
    """
    Follow remainder outputs while each hop keeps peeling. Uses the local database
    first; when `network_hops` > 0 it pulls the next hop's history from the chain.
    """
    from app.services.blockchain_sync import fetch_and_store  # local import avoids a cycle

    hops, current, seen = [], start, {start}
    fetched = 0
    for _ in range(max_hops):
        rows = _spends_of(db, current)
        if not rows and fetched < network_hops:
            fetched += 1
            fetch_and_store(db, current, limit=25)
            rows = _spends_of(db, current)
        found = None
        for row in sorted(rows, key=lambda r: (r.block_time is None, r.block_time)):
            outputs = json.loads(row.outputs_json or "[]")
            inputs = json.loads(row.inputs_json or "[]")
            shape = _peel_shape(current, {"is_input": True, "outputs": outputs, "inputs": inputs, "txid": row.txid})
            if shape:
                shape["time"] = as_utc(row.block_time).isoformat() if row.block_time else None
                found = shape
                break
        if not found or found["remainder_to"] in seen:
            break
        hops.append(found)
        seen.add(found["remainder_to"])
        current = found["remainder_to"]
    return hops


def _terminal_spend(db: Session, address: str) -> Optional[Dict]:
    """Where the chain's last address sent its funds (largest output of its first spend)."""
    rows = sorted(_spends_of(db, address), key=lambda r: (r.block_time is None, r.block_time))
    for row in rows:
        outs = [o for o in json.loads(row.outputs_json or "[]") if o.get("address") and o["address"] != address]
        if outs:
            best = max(outs, key=lambda o: o.get("value") or 0)
            return {"address": best["address"], "btc": round(best.get("value") or 0, 6), "txid": row.txid,
                    "from": address}
    return None


def _median_hop_hours(hops: List[Dict]) -> Optional[float]:
    from datetime import datetime
    stamps = []
    for h in hops:
        if h.get("time"):
            try:
                stamps.append(datetime.fromisoformat(h["time"]))
            except ValueError:
                pass
    if len(stamps) < 2:
        return None
    stamps.sort()
    gaps = [(b - a).total_seconds() / 3600 for a, b in zip(stamps, stamps[1:])]
    return statistics.median(gaps)


def detect_peel_chain(address: str, views: List[Dict], db: Optional[Session] = None,
                      network_hops: int = 0) -> Optional[Dict]:
    own = [p for p in (_peel_shape(address, v) for v in views) if p]
    for p in own:
        v = next((x for x in views if x["txid"] == p["txid"]), None)
        p["time"] = v["timestamp"].isoformat() if v and v["timestamp"] else None
    chain: List[Dict] = []
    terminal = None
    if db is not None and own:
        first = sorted(own, key=lambda h: h["time"] or "9999")[0]
        chain = [first] + _follow_peel_chain(db, first["remainder_to"], network_hops=network_hops)
        terminal = _terminal_spend(db, chain[-1]["remainder_to"]) if len(chain) >= 3 else None
    chain_len = len(chain)
    signal = max(len(own), chain_len)
    if signal < 3:
        return None
    hop_hours = _median_hop_hours(chain if chain_len >= 3 else own)
    # Automated peel chains move hop-to-hop within hours; ordinary HD-wallet
    # change spends are spread over days or weeks.
    pace = 1.0 if hop_hours is None or hop_hours <= 6 else (0.7 if hop_hours <= 48 else 0.4)
    peeled = sum(h["peeled_btc"] for h in (chain or own))
    pace_txt = f", median {hop_hours:.1f} h between hops" if hop_hours is not None else ""
    return _finding(
        "peel_chain", "Peel chain",
        (0.3 + 0.1 * signal) * pace,
        f"{len(own)} peel-shaped spend(s) from this wallet; the remainder was traced through {chain_len} "
        f"consecutive hop(s){pace_txt}, shedding {peeled:.4f} BTC in small payments along the way.",
        "Layering - peel chain (sequential small payments with change forwarded to fresh addresses)",
        {"own_peel_txs": len(own), "chain_length": chain_len, "peeled_btc": round(peeled, 6),
         "median_hop_hours": round(hop_hours, 2) if hop_hours is not None else None,
         "peel_destinations": sorted({h["peeled_to"] for h in (chain or own)})[:10],
         "terminal": terminal,
         "hops": (chain or own)[:15]},
    )


def detect_fan_out(address: str, views: List[Dict]) -> Optional[Dict]:
    """Distribution to many recipients: one wide tx or many sends in a short window."""
    best_tx = None
    for v in views:
        if not v["is_input"]:
            continue
        values = [o["value"] for o in v["outputs"] if o.get("address") and o["address"] != address]
        if len(values) >= 10:
            med = statistics.median(values)
            similar = sum(1 for x in values if med and abs(x - med) / med <= 0.15) / len(values)
            if v["input_count"] < 5 and (best_tx is None or len(values) > best_tx["recipients"]):
                best_tx = {"txid": v["txid"], "recipients": len(values), "equal_share": round(similar, 2)}
    sends = sorted((v for v in _confirmed(views) if v["is_input"]), key=_ts)
    window_best, j = 0, 0
    recipients_window = set()
    for i in range(len(sends)):
        while _ts(sends[i]) - _ts(sends[j]) > timedelta(hours=2):
            j += 1
        rec = {o["address"] for s in sends[j:i + 1] for o in s["outputs"] if o.get("address") and o["address"] != address}
        if len(rec) > window_best:
            window_best, recipients_window = len(rec), rec
    width = max(best_tx["recipients"] if best_tx else 0, window_best)
    if width < 10:
        return None
    return _finding(
        "fan_out", "Fan-out distribution",
        0.45 + min(0.55, (width - 10) / 40),
        f"Funds dispersed to {width} distinct recipients within 2 hours"
        + (f" (single tx {short(best_tx['txid'])} paid {best_tx['recipients']} outputs)." if best_tx else "."),
        "Smurfing / structuring - splitting value across many addresses",
        {"max_recipients_2h": window_best, "widest_tx": best_tx, "sample_recipients": sorted(recipients_window)[:8]},
    )


def detect_fan_in(address: str, views: List[Dict]) -> Optional[Dict]:
    """Aggregation from many distinct senders in a short window (collection account)."""
    incoming = sorted((v for v in _confirmed(views) if v["inflow_btc"] > 0), key=_ts)
    best, j, best_set = 0, 0, set()
    for i in range(len(incoming)):
        while _ts(incoming[i]) - _ts(incoming[j]) > timedelta(hours=24):
            j += 1
        senders = {inp["address"] for s in incoming[j:i + 1] for inp in s["inputs"] if inp.get("address")}
        if len(senders) > best:
            best, best_set = len(senders), senders
    if best < 10:
        return None
    # A collection account forwards what it gathers; a wallet that only ever
    # receives (donation / tribute / deposit address) is far weaker evidence.
    spends = _spend_ratio(views)
    forwarding = 1.0 if spends >= 0.2 else (0.6 if spends >= 0.05 else 0.3)
    note = "" if forwarding == 1.0 else " The wallet rarely spends, so this may be donations or deposits."
    return _finding(
        "fan_in", "Fan-in aggregation",
        (0.45 + min(0.55, (best - 10) / 40)) * forwarding,
        f"{best} distinct senders funded this wallet within 24 hours.{note}",
        "Placement / collection - aggregation of victim or mule deposits",
        {"max_senders_24h": best, "spend_ratio": round(spends, 3), "sample_senders": sorted(best_set)[:8]},
    )


def is_coinjoin(v: Dict) -> Optional[Dict]:
    outs = [round(o.get("value") or 0, 8) for o in v["outputs"] if (o.get("value") or 0) > 0]
    if v["input_count"] < 5 or len(outs) < 5:
        return None
    denom, count = Counter(outs).most_common(1)[0]
    if count >= 5 and count >= 0.3 * len(outs):
        return {"txid": v["txid"], "denomination_btc": denom, "equal_outputs": count,
                "inputs": v["input_count"], "outputs": v["output_count"]}
    return None


def detect_coinjoin(address: str, views: List[Dict]) -> Optional[Dict]:
    # Participation means contributing an input; receiving from a CoinJoin is someone else's mixing.
    joins = [c for c in (is_coinjoin(v) for v in views if v["is_input"]) if c]
    if not joins:
        return None
    return _finding(
        "coinjoin", "CoinJoin / mixing participation",
        0.55 + min(0.45, 0.15 * (len(joins) - 1)),
        f"Participated in {len(joins)} CoinJoin-shaped transaction(s) with equal-value outputs "
        f"(e.g. {joins[0]['equal_outputs']} x {joins[0]['denomination_btc']} BTC).",
        "Obfuscation - mixing breaks the transaction trail",
        {"coinjoins": joins[:8]},
    )


def detect_dormant_reactivation(address: str, views: List[Dict]) -> Optional[Dict]:
    txs = sorted(_confirmed(views), key=_ts)
    best = None
    for prev, cur in zip(txs, txs[1:]):
        gap_days = (_ts(cur) - _ts(prev)).days
        if gap_days >= 365 and cur["is_input"] and cur["outflow_btc"] > 0:
            if best is None or gap_days > best["dormant_days"]:
                best = {"dormant_days": gap_days, "reactivated": _ts(cur).isoformat(), "txid": cur["txid"],
                        "moved_btc": round(cur["outflow_btc"], 6)}
    if not best:
        return None
    return _finding(
        "dormant_reactivation", "Dormant funds reactivated",
        0.4 + min(0.6, best["dormant_days"] / 3650),
        f"Wallet was silent for {best['dormant_days']} days, then moved {best['moved_btc']} BTC.",
        "Movement of long-held proceeds (common for hack / seizure-evading funds)",
        best,
    )


def detect_high_connectivity(address: str, views: List[Dict]) -> Optional[Dict]:
    parties = set()
    for v in views:
        if v["is_input"]:
            parties.update(o["address"] for o in v["outputs"] if o.get("address") and o["address"] != address)
        else:
            parties.update(i["address"] for i in v["inputs"] if i.get("address"))
    if len(parties) <= 15:
        return None
    receive_only = _spend_ratio(views) < 0.05
    return _finding(
        "high_connectivity", "High counterparty connectivity",
        min(1.0, 0.4 + len(parties) / 200) * (0.4 if receive_only else 1.0),
        f"Interacted with {len(parties)} distinct counterparties in the analysed window.",
        "Hub / service-like behaviour",
        {"counterparties": len(parties)},
    )


def detect_round_amounts(address: str, views: List[Dict]) -> Optional[Dict]:
    values = [v["outflow_btc"] for v in views if v["is_input"] and v["outflow_btc"] > 0]
    if len(values) < 5:
        return None
    rounds = [x for x in values if abs(x * 100 - round(x * 100)) < 1e-6]
    ratio = len(rounds) / len(values)
    if ratio < 0.6:
        return None
    return _finding(
        "round_amounts", "Round-number transfers",
        ratio,
        f"{ratio:.0%} of outgoing transfers are round BTC amounts (e.g. {rounds[0]} BTC).",
        "Manually directed payments / OTC settlement",
        {"round_ratio": round(ratio, 2), "sample": rounds[:5]},
    )


def detect_dust_target(address: str, views: List[Dict]) -> Optional[Dict]:
    dust = [v for v in views if 0 < v["inflow_btc"] < 0.00001]
    if len(dust) < 3:
        return None
    return _finding(
        "dust_target", "Dust received",
        1.0,
        f"Received {len(dust)} dust outputs (< 1,000 sats). Usually tributes or dusting attacks, not wallet behaviour.",
        "Informational",
        {"dust_txs": len(dust)},
        severity="INFO",
    )


DETECTORS = [
    detect_peel_chain, detect_coinjoin, detect_rapid_passthrough, detect_fan_out, detect_fan_in,
    detect_burst, detect_dormant_reactivation, detect_high_connectivity, detect_round_amounts, detect_dust_target,
]


def run_heuristics(address: str, views: List[Dict], db: Optional[Session] = None,
                   network_hops: int = 0) -> Dict:
    findings = []
    for det in DETECTORS:
        try:
            if det is detect_peel_chain:
                f = det(address, views, db, network_hops=network_hops)
            else:
                f = det(address, views)
        except Exception as exc:  # a broken detector must never kill the investigation
            f = None
            logging.getLogger("sifra.rules").exception("Detector %s failed: %s", det.__name__, exc)
        if f:
            findings.append(f)
    findings.sort(key=lambda f: (-f["points"], -SEVERITY_ORDER[f["severity"]]))
    remaining = 1.0
    for f in findings:
        remaining *= (1 - f["points"] / 100)
    score = round(100 * (1 - remaining), 1)
    return {"score": score, "findings": findings}


# Backwards-compatible helper used by older code paths
def analyze_wallet_rules(db: Session, address: str):
    from app.services.blockchain_sync import load_wallet_txs
    views = load_wallet_txs(db, address)
    result = run_heuristics(address, views, db)
    return {"wallet": address, "risk_score": result["score"],
            "patterns": [f["title"] for f in result["findings"]], "findings": result["findings"]}

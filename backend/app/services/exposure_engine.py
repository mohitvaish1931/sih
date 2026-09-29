"""
Counterparty exposure analysis.

Direct exposure  - value exchanged with counterparties attributed to illicit
                   categories (darknet, ransomware, hacks, scams, mixers ...).
Indirect exposure - illicit entities one hop further away, using only data
                   already in the local database (no extra network calls).
Also extracts actionable leads: regulated exchanges that funded or received
funds from the wallet (KYC / legal-notice targets).
"""

from collections import defaultdict
from typing import Dict, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AddressTx

from app.services.entity_tagger import ILLICIT_SEVERITY, tag_address

INDIRECT_DISCOUNT = 0.35
DUST_BTC = 0.0001


def counterparty_flows(address: str, views: List[Dict]) -> Dict[str, Dict]:
    """Value attributed to each counterparty (inputs pro-rata for receipts, outputs for spends)."""
    flows: Dict[str, Dict] = defaultdict(lambda: {"received_from": 0.0, "sent_to": 0.0, "tx_count": 0, "txids": []})
    for v in views:
        if v["is_input"]:
            for o in v["outputs"]:
                a = o.get("address")
                if a and a != address:
                    f = flows[a]
                    f["sent_to"] += o.get("value") or 0
                    f["tx_count"] += 1
                    if len(f["txids"]) < 5:
                        f["txids"].append(v["txid"])
        elif v["inflow_btc"] > 0:
            senders = [i for i in v["inputs"] if i.get("address")]
            total = sum(i.get("value") or 0 for i in senders) or 1.0
            for i in senders:
                f = flows[i["address"]]
                f["received_from"] += v["inflow_btc"] * ((i.get("value") or 0) / total)
                f["tx_count"] += 1
                if len(f["txids"]) < 5:
                    f["txids"].append(v["txid"])
    return flows


def analyze_exposure(db: Session, address: str, views: List[Dict], entities: Dict[str, Dict],
                     flows: Dict[str, Dict]) -> Dict:
    total_in = sum(f["received_from"] for f in flows.values())
    total_out = sum(f["sent_to"] for f in flows.values())
    total = (total_in + total_out) or 1e-9

    direct, cashout, funding = [], [], []
    by_category: Dict[str, float] = defaultdict(float)
    cat_in: Dict[str, float] = defaultdict(float)
    cat_out: Dict[str, float] = defaultdict(float)
    illicit_in = illicit_out = 0.0
    for addr, f in flows.items():
        ent = entities.get(addr) or {}
        cat = ent.get("category", "unknown")
        if ent.get("is_known") and cat in ILLICIT_SEVERITY:
            value = f["received_from"] + f["sent_to"]
            if value < DUST_BTC:
                continue   # unsolicited dust is a known false-positive vector
            by_category[cat] += value
            cat_in[cat] += f["received_from"]
            cat_out[cat] += f["sent_to"]
            illicit_in += f["received_from"]
            illicit_out += f["sent_to"]
            direct.append({
                "address": addr, "entity_name": ent.get("entity_name"), "category": cat,
                "category_label": ent.get("category_label"), "icon": ent.get("icon"),
                "received_from_btc": round(f["received_from"], 8), "sent_to_btc": round(f["sent_to"], 8),
                "share": round(value / total, 4), "txids": f["txids"], "hop": 1,
                "confidence": ent.get("confidence"),
            })
        if ent.get("is_known") and cat == "exchange":
            if f["sent_to"] > 0:
                cashout.append({"address": addr, "exchange": ent.get("entity_name"), "btc": round(f["sent_to"], 8),
                                "txids": f["txids"]})
            if f["received_from"] > 0:
                funding.append({"address": addr, "exchange": ent.get("entity_name"),
                                "btc": round(f["received_from"], 8), "txids": f["txids"]})

    indirect = _indirect_exposure(db, address, flows, entities)

    remaining = 1.0
    for cat in by_category:
        sev = ILLICIT_SEVERITY[cat]
        # Sending to an illicit entity is a choice of the wallet owner; receiving may be unsolicited.
        s_out = sev * min(1.0, 0.4 + 3 * cat_out[cat] / total) if cat_out[cat] > 0 else 0.0
        s_in = sev * min(1.0, 0.15 + 3 * cat_in[cat] / total) if cat_in[cat] > 0 else 0.0
        remaining *= (1 - max(s_in, s_out))
    seen_indirect = set()
    for item in indirect:
        key = item["entity_address"]
        if key in seen_indirect:
            continue
        seen_indirect.add(key)
        remaining *= (1 - ILLICIT_SEVERITY.get(item["category"], 0.5) * INDIRECT_DISCOUNT)
    score = round(100 * (1 - remaining), 1)

    direct.sort(key=lambda d: -d["share"])
    cashout.sort(key=lambda d: -d["btc"])
    funding.sort(key=lambda d: -d["btc"])
    return {
        "score": score,
        "direct": direct[:15],
        "indirect": indirect[:15],
        "by_category": {k: round(v, 8) for k, v in by_category.items()},
        "illicit_received_btc": round(illicit_in, 8),
        "illicit_sent_btc": round(illicit_out, 8),
        "illicit_share": round((illicit_in + illicit_out) / total, 4) if total > 1e-9 else 0.0,
        "cashout_exchanges": cashout[:10],
        "funding_exchanges": funding[:10],
    }


def _indirect_exposure(db: Session, address: str, flows: Dict[str, Dict], entities: Dict[str, Dict],
                       max_neighbours: int = 25) -> List[Dict]:
    from app.services.blockchain_sync import load_wallet_txs

    neighbours = sorted(
        (a for a in flows if not (entities.get(a) or {}).get("is_known")),
        key=lambda a: -(flows[a]["received_from"] + flows[a]["sent_to"]),
    )[:max_neighbours]
    if not neighbours:
        return []
    # One aggregate query: only neighbours with history beyond the txs they share with
    # the target can reveal a second hop, so the rest are never loaded.
    known = dict(db.query(AddressTx.address, func.count(AddressTx.id))
                 .filter(AddressTx.address.in_(neighbours)).group_by(AddressTx.address).all())
    candidates = [n for n in neighbours if known.get(n, 0) > flows[n]["tx_count"]]
    found = []
    for n in candidates:
        views = load_wallet_txs(db, n, limit=200)
        if len(views) <= 1:
            continue
        second = counterparty_flows(n, views)
        for addr, f in second.items():
            if addr == address or f["received_from"] + f["sent_to"] < DUST_BTC:
                continue
            ent = tag_address(addr, allow_remote=False)
            cat = ent.get("category")
            if ent.get("is_known") and cat in ILLICIT_SEVERITY:
                found.append({
                    "via": n, "entity_address": addr, "entity_name": ent.get("entity_name"),
                    "category": cat, "category_label": ent.get("category_label"), "icon": ent.get("icon"),
                    "btc": round(f["received_from"] + f["sent_to"], 8), "hop": 2,
                })
    found.sort(key=lambda x: -ILLICIT_SEVERITY.get(x["category"], 0))
    return found

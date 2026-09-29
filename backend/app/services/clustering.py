"""
Address clustering with the common-input-ownership heuristic: all inputs of a
(non-CoinJoin) transaction are controlled by the same entity. CoinJoins are
excluded because they deliberately combine inputs from many owners.
"""

import hashlib
import json
from typing import Dict, List

from sqlalchemy.orm import Session

from app.models import AddressTx, ChainTx, Cluster, Wallet
from app.services.rule_engine import is_coinjoin


def _co_inputs_from_db(db: Session, address: str, limit: int = 60):
    txids = [t for (t,) in db.query(AddressTx.txid).filter(AddressTx.address == address,
                                                             AddressTx.is_input.is_(True)).limit(limit).all()]
    if not txids:
        return []
    out = []
    for row in db.query(ChainTx).filter(ChainTx.txid.in_(txids)).all():
        inputs = json.loads(row.inputs_json or "[]")
        outputs = json.loads(row.outputs_json or "[]")
        view = {"txid": row.txid, "input_count": len(inputs), "output_count": len(outputs), "outputs": outputs}
        if is_coinjoin(view):
            continue
        out.append((row.txid, [i["address"] for i in inputs if i.get("address")]))
    return out


def common_input_cluster(db: Session, address: str, views: List[Dict], max_size: int = 300,
                         second_level: int = 40) -> Dict:
    members = {address}
    co_spend_txs = set()
    skipped_coinjoins = 0
    for v in views:
        if not v["is_input"]:
            continue
        if is_coinjoin(v):
            skipped_coinjoins += 1
            continue
        ins = {i["address"] for i in v["inputs"] if i.get("address")}
        if len(ins) > 1:
            co_spend_txs.add(v["txid"])
            members |= ins

    # One more level of expansion through co-spenders already in the database
    for m in sorted(members - {address})[:second_level]:
        for txid, ins in _co_inputs_from_db(db, m):
            if len(ins) > 1 and len(members) < max_size:
                co_spend_txs.add(txid)
                members |= set(ins)

    size = len(members)
    cluster_id = None
    if size > 1:
        digest = hashlib.sha1(",".join(sorted(members)).encode()).hexdigest()[:10].upper()
        cluster_id = f"CL-{digest}"
    return {
        "cluster_id": cluster_id,
        "size": size,
        "members": sorted(members - {address})[:50],
        "co_spend_txs": len(co_spend_txs),
        "coinjoins_excluded": skipped_coinjoins,
        "method": "Common-input-ownership heuristic (CoinJoin transactions excluded)",
        "truncated": size >= max_size,
    }


def attribute_cluster(cluster: Dict, entities: Dict[str, Dict]) -> Dict:
    counts: Dict[str, Dict] = {}
    for m in cluster.get("members", []):
        ent = entities.get(m) or {}
        if ent.get("is_known"):
            key = ent["entity_name"]
            counts.setdefault(key, {"entity_name": key, "category": ent.get("category"),
                                    "category_label": ent.get("category_label"), "members": 0})
            counts[key]["members"] += 1
    if counts:
        cluster["attributed_entity"] = max(counts.values(), key=lambda c: c["members"])
    else:
        cluster["attributed_entity"] = None
    return cluster


def persist_cluster(db: Session, address: str, cluster: Dict, risk_score: float):
    if not cluster.get("cluster_id"):
        return
    row = db.query(Cluster).filter(Cluster.cluster_id == cluster["cluster_id"]).first()
    if not row:
        row = Cluster(cluster_id=cluster["cluster_id"])
        db.add(row)
    row.wallet_count = cluster["size"]
    row.risk_score = risk_score
    ent = cluster.get("attributed_entity")
    row.description = f"Attributed to {ent['entity_name']}" if ent else "Unattributed co-spend cluster"
    wallet = db.query(Wallet).filter(Wallet.address == address).first()
    if wallet:
        wallet.cluster_id = cluster["cluster_id"]

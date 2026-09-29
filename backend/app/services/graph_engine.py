"""
Investigation graph (Cytoscape.js format).

Nodes are addresses, edges are aggregated value flows (all transactions between
the same pair collapsed into one edge with total BTC, count and sample txids).
Traced peel-chain hops and cluster co-spenders are overlaid when available.
"""

from collections import defaultdict
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.services.bitcoin_api import get_btc_price_usd
from app.services.blockchain_sync import load_wallet_txs, sync_wallet_transactions, fetch_and_store, get_sync_state
from app.services.entity_tagger import tag_addresses_batch, tag_address, ILLICIT_SEVERITY
from app.utils import as_utc

MAX_COUNTERPARTIES = 60


def _node(addr: str, entity: Dict, root: str, stats: Dict, cluster_members=frozenset()) -> Dict:
    cat = entity.get("category", "unknown")
    return {"data": {
        "id": addr,
        "type": "wallet",
        "entity_name": entity.get("entity_name"),
        "entity_category": cat,
        "entity_icon": entity.get("icon", "❓"),
        "entity_color": entity.get("color", "#64748b"),
        "is_known": bool(entity.get("is_known")),
        "is_root": addr == root,
        "illicit": bool(entity.get("is_known") and cat in ILLICIT_SEVERITY),
        "in_cluster": addr in cluster_members,
        "volume_btc": round(stats.get("volume", 0.0), 8),
        "tx_count": stats.get("tx_count", 0),
    }}


def _flows_from_views(address: str, views: List[Dict]):
    """Aggregate directed flows (src, dst) -> totals for one address."""
    edges: Dict[tuple, Dict] = defaultdict(lambda: {"amount": 0.0, "tx_count": 0, "txids": [], "first": None, "last": None})

    def add(src, dst, value, v):
        if not src or not dst or src == dst:
            return
        e = edges[(src, dst)]
        e["amount"] += value or 0
        e["tx_count"] += 1
        if len(e["txids"]) < 5:
            e["txids"].append(v["txid"])
        ts = v["timestamp"]
        if ts:
            e["first"] = min(e["first"], ts) if e["first"] else ts
            e["last"] = max(e["last"], ts) if e["last"] else ts

    for v in views:
        if v["is_input"]:
            for o in v["outputs"]:
                add(address, o.get("address"), o.get("value"), v)
        elif v["inflow_btc"] > 0:
            senders = [i for i in v["inputs"] if i.get("address")]
            if not senders:
                add("COINBASE", address, v["inflow_btc"], v)
                continue
            total = sum(i.get("value") or 0 for i in senders) or 1.0
            # keep graphs readable: attribute to the top 3 contributing inputs
            for i in sorted(senders, key=lambda s: -(s.get("value") or 0))[:3]:
                add(i["address"], address, v["inflow_btc"] * ((i.get("value") or 0) / total), v)
    return edges


def _format(root: str, edges: Dict[tuple, Dict], entities: Dict[str, Dict], btc_usd: float,
            cluster_members=frozenset(), extra_nodes=()) -> Dict:
    stats: Dict[str, Dict] = defaultdict(lambda: {"volume": 0.0, "tx_count": 0})
    for (s, d), e in edges.items():
        for a in (s, d):
            stats[a]["volume"] += e["amount"]
            stats[a]["tx_count"] += e["tx_count"]
    ids = set(stats) | set(extra_nodes) | {root}
    nodes = [_node(a, entities.get(a) or {}, root, stats.get(a, {}), cluster_members) for a in ids]
    out_edges = []
    for (s, d), e in edges.items():
        illicit = any((entities.get(x) or {}).get("category") in ILLICIT_SEVERITY and (entities.get(x) or {}).get("is_known")
                      for x in (s, d))
        out_edges.append({"data": {
            "id": f"{s}->{d}",
            "source": s,
            "target": d,
            "amount": round(e["amount"], 8),
            "amount_usd": round(e["amount"] * btc_usd, 2),
            "tx_count": e["tx_count"],
            "tx_hash": e["txids"][0] if e["txids"] else "",
            "txids": e["txids"],
            "first_seen": as_utc(e["first"]).isoformat() if e["first"] else None,
            "last_seen": as_utc(e["last"]).isoformat() if e["last"] else None,
            "illicit": illicit,
            "kind": e.get("kind", "flow"),
        }})
    return {"nodes": nodes, "edges": out_edges}


def _trim(address: str, edges: Dict[tuple, Dict], keep: set, limit: int = MAX_COUNTERPARTIES):
    volume: Dict[str, float] = defaultdict(float)
    for (s, d), e in edges.items():
        other = d if s == address else s
        volume[other] += e["amount"]
    ranked = sorted(volume, key=lambda a: -volume[a])
    allowed = set(ranked[:limit]) | keep | {address}
    trimmed = {k: v for k, v in edges.items() if k[0] in allowed and k[1] in allowed}
    return trimmed, max(0, len(volume) - len(set(ranked[:limit]) | (keep & set(volume))))


def build_transaction_graph(db: Session, address: str, investigation: Optional[Dict] = None,
                            views: Optional[List[Dict]] = None) -> Dict:
    """Graph around the root wallet, with traced peel hops and cluster members overlaid."""
    if views is None:
        sync_wallet_transactions(db, address)
        views = load_wallet_txs(db, address)
    if not views:
        return {"nodes": [], "edges": [], "truncated": 0}

    edges = _flows_from_views(address, views)
    cluster_members = frozenset()
    keep = set()
    if investigation:
        for f in investigation.get("findings", []):
            if f["id"] == "peel_chain":
                for h in f["evidence"].get("hops", []):
                    for (s, d, val) in ((h["from"], h["remainder_to"], h["remainder_btc"]),
                                        (h["from"], h["peeled_to"], h["peeled_btc"])):
                        e = edges[(s, d)]
                        if e["tx_count"] == 0:
                            e["amount"] += val
                            e["tx_count"] = 1
                            e["txids"].append(h["txid"])
                            e["kind"] = "peel"
                        keep.update((s, d))
                term = f["evidence"].get("terminal")
                if term:
                    e = edges[(term["from"], term["address"])]
                    if e["tx_count"] == 0:
                        e["amount"] += term["btc"]
                        e["tx_count"] = 1
                        e["txids"].append(term["txid"])
                        e["kind"] = "peel"
                    keep.update((term["from"], term["address"]))
        cluster = investigation.get("cluster") or {}
        cluster_members = frozenset(cluster.get("members", [])[:12])
        for m in cluster_members:
            e = edges[(m, address)]
            if e["tx_count"] == 0:
                e["kind"] = "cluster"
                e["tx_count"] = 0
        keep |= set(cluster_members)
        keep |= {d["address"] for d in (investigation.get("exposure") or {}).get("direct", [])}

    edges, truncated = _trim(address, edges, keep)
    addrs = {a for pair in edges for a in pair}
    entities = dict((investigation or {}).get("counterparty_entities") or {})
    # The investigation already attributed the high-volume counterparties; everything
    # else comes from cache only so the graph renders instantly.
    for a in addrs:
        if a not in entities:
            entities[a] = tag_address(a, allow_remote=False)
    if investigation and investigation.get("entity"):
        entities[address] = investigation["entity"]
    btc_usd = get_btc_price_usd().get("usd", 0)
    graph = _format(address, edges, entities, btc_usd, cluster_members)
    graph["truncated"] = truncated
    return graph


def expand_node_graph(db: Session, address: str, root_address: str) -> Dict:
    """Neighbourhood of one node for multi-hop exploration."""
    if get_sync_state(db, address) is None:
        fetch_and_store(db, address, limit=50)
    views = load_wallet_txs(db, address)
    if not views:
        return {"nodes": [], "edges": [], "expanded_address": address}
    edges = _flows_from_views(address, views)
    edges, truncated = _trim(address, edges, {root_address}, limit=40)
    addrs = {a for pair in edges for a in pair} | {address}
    entities = tag_addresses_batch(list(addrs))
    btc_usd = get_btc_price_usd().get("usd", 0)
    graph = _format(root_address, edges, entities, btc_usd, extra_nodes=[address])
    graph["expanded_address"] = address
    graph["truncated"] = truncated
    return graph

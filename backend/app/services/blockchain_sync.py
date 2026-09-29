"""
SIFRA blockchain sync + wallet transaction view.

Storage model
-------------
chain_txs     full transaction (every input and output)       - source of truth
address_txs   address -> txid index (role: input / output)    - fast lookup, clustering
transactions  value-flow edges (primary sender -> output)     - legacy graph / demo data
address_sync  when each address was last pulled from the chain

Every analysis engine consumes the same normalized "wallet tx view" produced by
load_wallet_txs(), whether the data came from the live chain, the demo seed or
older edge-only rows.
"""

import json
import logging
import re
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Iterable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import SYNC_MAX_TXS, SYNC_TTL_SECONDS
from app.models import Transaction, Wallet, ChainTx, AddressTx, AddressSync, RelayObservation
from app.services.bitcoin_api import fetch_history, fetch_wallet_balance
from app.utils import as_utc, from_unix, is_demo_address, sort_key

log = logging.getLogger("sifra.sync")

_EDGE_KEY_RE = re.compile(r"^([0-9a-f]{64})_(\d+)$")
_address_locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()

COINBASE = "COINBASE"
_OUTPUT_INDEX_CAP = 40   # index at most this many output addresses per tx (batch payouts)


def _lock_for(address: str) -> threading.Lock:
    with _locks_guard:
        return _address_locks[address]


def _chunks(items: List, size: int = 400) -> Iterable[List]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def primary_input(inputs: List[Dict]) -> Optional[str]:
    """Deterministic representative sender: the address contributing the most value."""
    best, best_val = None, -1.0
    for i in inputs:
        if i.get("address") and (i.get("value") or 0) > best_val:
            best, best_val = i["address"], i.get("value") or 0
    return best


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------
def get_sync_state(db: Session, address: str) -> Optional[AddressSync]:
    return db.get(AddressSync, address)


def sync_wallet_transactions(db: Session, address: str, force: bool = False,
                             max_txs: int = SYNC_MAX_TXS) -> Dict:
    """
    Pull the most recent `max_txs` transactions of an address from the chain,
    unless it was synced within SYNC_TTL_SECONDS. Demo addresses never hit the network.
    """
    if is_demo_address(address):
        return {"status": "local", "fetched": 0}

    with _lock_for(address):
        state = get_sync_state(db, address)
        now = datetime.now(timezone.utc)
        if (not force and state and state.last_synced
                and now - as_utc(state.last_synced) < timedelta(seconds=SYNC_TTL_SECONDS)):
            return {"status": "cached", "fetched": state.tx_count_fetched,
                    "onchain": state.tx_count_onchain, "last_synced": as_utc(state.last_synced).isoformat()}

        # Balance / lifetime tx count is fetched concurrently with the paginated history
        with ThreadPoolExecutor(max_workers=1) as pool:
            balance_future = pool.submit(fetch_wallet_balance, address)
            history = fetch_history(address, max_txs)
            balance = balance_future.result()
        if history["source"] is None:
            log.warning("No provider returned history for %s", address)
            return {"status": "unavailable", "fetched": 0}

        txs = history["txs"]
        store_transactions(db, address, txs, source=history["source"])
        onchain = balance.get("tx_count") or len(txs)

        state = get_sync_state(db, address) or AddressSync(address=address)
        state.last_synced = now
        state.tx_count_fetched = len(txs)
        state.tx_count_onchain = onchain
        state.source = history["source"]
        db.merge(state)

        wallet = db.query(Wallet).filter(Wallet.address == address).first()
        if not wallet:
            wallet = Wallet(address=address)
            db.add(wallet)
        stamps = [from_unix(t.get("timestamp")) for t in txs if t.get("timestamp")]
        if stamps:
            wallet.first_seen = min(stamps)
            wallet.last_seen = max(stamps)
        _safe_commit(db)
        return {"status": "synced", "fetched": len(txs), "onchain": onchain,
                "source": history["source"], "last_synced": now.isoformat()}


def fetch_and_store(db: Session, address: str, limit: int = 25) -> int:
    """
    Lightweight fetch used while tracing (peel-chain hops, graph peeks). Stores
    the txs but does NOT mark the address as fully synced.
    """
    if is_demo_address(address):
        return 0
    from app.services.bitcoin_api import fetch_wallet_transactions
    txs = fetch_wallet_transactions(address, limit=limit)
    if txs:
        store_transactions(db, address, txs)
    return len(txs)


def _safe_commit(db: Session):
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request stored the same rows first - that's fine.
        db.rollback()


def store_transactions(db: Session, focus_address: str, txs: List[Dict], source: str = "esplora"):
    """Upsert normalized transactions (bitcoin_api shape) plus index rows and flow edges."""
    if not txs:
        return
    txids = [t["txid"] for t in txs if t.get("txid")]

    existing_chain = {}
    for chunk in _chunks(txids):
        for row in db.query(ChainTx).filter(ChainTx.txid.in_(chunk)).all():
            existing_chain[row.txid] = row

    existing_index = set()
    for chunk in _chunks(txids):
        for addr, txid in db.query(AddressTx.address, AddressTx.txid).filter(AddressTx.txid.in_(chunk)).all():
            existing_index.add((addr, txid))

    edge_keys = []
    for t in txs:
        for o in t.get("outputs", []):
            edge_keys.append(f"{t['txid']}_{o.get('n', 0)}")
    existing_edges = set()
    for chunk in _chunks(edge_keys):
        for (key,) in db.query(Transaction.tx_hash).filter(Transaction.tx_hash.in_(chunk)).all():
            existing_edges.add(key)

    new_rows = []
    for t in txs:
        txid = t.get("txid")
        if not txid:
            continue
        block_time = from_unix(t.get("timestamp"))
        row = existing_chain.get(txid)
        if row is None:
            new_rows.append(ChainTx(
                txid=txid,
                block_height=t.get("block_height"),
                block_time=block_time,
                fee_btc=t.get("fee_btc") or 0.0,
                input_count=len(t.get("inputs", [])),
                output_count=len(t.get("outputs", [])),
                inputs_json=json.dumps(t.get("inputs", [])),
                outputs_json=json.dumps(t.get("outputs", [])),
                source=source,
            ))
        elif row.block_height is None and t.get("block_height"):
            row.block_height = t.get("block_height")   # unconfirmed tx got mined
            row.block_time = block_time

        # Address index: every input, capped outputs, always the focus address
        roles: Dict[str, List[bool]] = {}
        for i in t.get("inputs", []):
            if i.get("address"):
                roles.setdefault(i["address"], [False, False])[0] = True
        for idx, o in enumerate(t.get("outputs", [])):
            addr = o.get("address")
            if addr and (idx < _OUTPUT_INDEX_CAP or addr == focus_address):
                roles.setdefault(addr, [False, False])[1] = True
        for addr, (is_in, is_out) in roles.items():
            if (addr, txid) not in existing_index:
                existing_index.add((addr, txid))
                new_rows.append(AddressTx(address=addr, txid=txid, is_input=is_in, is_output=is_out))

        # Flow edges for the focus address (deterministic primary sender)
        sender = primary_input(t.get("inputs", [])) or COINBASE
        focus_is_input = any(i.get("address") == focus_address for i in t.get("inputs", []))
        for o in t.get("outputs", []):
            to_addr = o.get("address")
            if not to_addr:
                continue
            if not (focus_is_input or to_addr == focus_address):
                continue
            key = f"{txid}_{o.get('n', 0)}"
            if key in existing_edges:
                continue
            existing_edges.add(key)
            new_rows.append(Transaction(
                tx_hash=key, txid=txid, vout=o.get("n", 0),
                from_address=sender, to_address=to_addr,
                amount=round(o.get("value") or 0, 8),
                timestamp=block_time, block_height=t.get("block_height"),
            ))

    if new_rows:
        db.add_all(new_rows)
    _safe_commit(db)


# ---------------------------------------------------------------------------
# Wallet transaction view
# ---------------------------------------------------------------------------
def _legacy_txid(edge: Transaction) -> str:
    if edge.txid:
        return edge.txid
    m = _EDGE_KEY_RE.match(edge.tx_hash or "")
    return m.group(1) if m else (edge.tx_hash or f"edge-{edge.id}")


def _view(address: str, txid: str, ts: Optional[datetime], height, fee, inputs, outputs,
          source: str, geo: Optional[Dict] = None) -> Dict:
    spent = sum(i.get("value") or 0 for i in inputs if i.get("address") == address)
    received = sum(o.get("value") or 0 for o in outputs if o.get("address") == address)
    to_others = sum(o.get("value") or 0 for o in outputs if o.get("address") != address)
    is_in = any(i.get("address") == address for i in inputs)
    is_out = received > 0
    if is_in and is_out:
        direction = "both"
    elif is_in:
        direction = "sent"
    else:
        direction = "received"
    return {
        "txid": txid,
        "timestamp": as_utc(ts),
        "block_height": height,
        "confirmed": height is not None or source == "demo",
        "fee_btc": fee or 0.0,
        "inputs": inputs,
        "outputs": outputs,
        "input_count": len(inputs),
        "output_count": len(outputs),
        "is_input": is_in,
        "direction": direction,
        "spent_btc": round(spent, 8),
        "received_btc": round(received, 8),
        # value that left the wallet to third parties (change excluded)
        "outflow_btc": round(to_others if is_in else 0.0, 8),
        # value that arrived from third parties (change excluded)
        "inflow_btc": round(received if not is_in else 0.0, 8),
        "source": source,
        "geo": geo,
    }


def load_wallet_txs(db: Session, address: str, limit: int = 1000) -> List[Dict]:
    """All known transactions touching `address`, oldest first (unconfirmed last)."""
    txids = [t for (t,) in db.query(AddressTx.txid).filter(AddressTx.address == address).limit(limit).all()]
    views: Dict[str, Dict] = {}

    for chunk in _chunks(txids):
        for row in db.query(ChainTx).filter(ChainTx.txid.in_(chunk)).all():
            try:
                inputs = json.loads(row.inputs_json or "[]")
                outputs = json.loads(row.outputs_json or "[]")
            except ValueError:
                continue
            views[row.txid] = _view(address, row.txid, row.block_time, row.block_height,
                                    row.fee_btc, inputs, outputs, row.source or "chain")

    # Edge-only rows (older databases, hand-inserted data)
    legacy = db.query(Transaction).filter(
        (Transaction.from_address == address) | (Transaction.to_address == address)
    ).limit(limit).all()
    groups: Dict[str, List[Transaction]] = defaultdict(list)
    for e in legacy:
        tid = _legacy_txid(e)
        if tid not in views:
            groups[tid].append(e)
    for tid, edges in groups.items():
        senders: Dict[str, float] = defaultdict(float)
        outputs = []
        for n, e in enumerate(sorted(edges, key=lambda x: x.vout if x.vout is not None else 0)):
            senders[e.from_address] += e.amount or 0
            outputs.append({"address": e.to_address, "value": e.amount or 0, "n": e.vout if e.vout is not None else n})
        inputs = [{"address": a, "value": round(v, 8)} for a, v in senders.items() if a != COINBASE]
        first = edges[0]
        geo = None
        if first.latitude is not None and first.longitude is not None and first.ip_address:
            geo = {"ip": first.ip_address, "city": first.city or "Unknown", "country": first.country or "Unknown",
                   "lat": first.latitude, "lon": first.longitude, "isp": first.isp or "Unknown",
                   "is_vpn_tor": bool(first.is_vpn_tor), "first_seen": as_utc(first.timestamp),
                   "source": "stored"}
        source = "demo" if is_demo_address(address) else "edges"
        views[tid] = _view(address, tid, first.timestamp, first.block_height, 0.0, inputs, outputs, source, geo)

    # Relay telemetry (first-spy observations from the P2P sensor)
    all_ids = list(views.keys())
    for chunk in _chunks(all_ids):
        for obs in db.query(RelayObservation).filter(RelayObservation.txid.in_(chunk)).all():
            v = views.get(obs.txid)
            if v is None or obs.latitude is None:
                continue
            current = v.get("geo")
            seen = as_utc(obs.first_seen)
            if current and current.get("source") == "relay" and current.get("first_seen") and current["first_seen"] <= seen:
                continue
            v["geo"] = {"ip": obs.peer_ip, "city": obs.city or "Unknown", "country": obs.country or "Unknown",
                        "lat": obs.latitude, "lon": obs.longitude, "isp": obs.isp or "Unknown",
                        "is_vpn_tor": bool(obs.is_vpn_tor), "first_seen": seen,
                        "peers_announcing": obs.peers_announcing, "sensor_id": obs.sensor_id,
                        "confidence": obs.confidence if obs.confidence is not None else 1.0,
                        "source": "relay"}

    return sorted(views.values(), key=lambda v: sort_key(v["timestamp"]))


def serialize_tx(v: Dict, btc_usd: float = 0.0) -> Dict:
    """JSON-safe version of a wallet tx view for API responses."""
    counterparties = []
    if v["is_input"]:
        counterparties = [o["address"] for o in v["outputs"] if o.get("address") and o["address"] not in
                          {i.get("address") for i in v["inputs"]}]
    else:
        counterparties = [i["address"] for i in v["inputs"] if i.get("address")]
    value = v["outflow_btc"] if v["is_input"] else v["inflow_btc"]
    return {
        "txid": v["txid"],
        "timestamp": v["timestamp"].isoformat() if v["timestamp"] else None,
        "block_height": v["block_height"],
        "confirmed": v["confirmed"],
        "direction": v["direction"],
        "value_btc": round(value, 8),
        "value_usd": round(value * btc_usd, 2),
        "fee_btc": v["fee_btc"],
        "inputs": v["input_count"],
        "outputs": v["output_count"],
        "counterparties": counterparties[:5],
        "source": v["source"],
        "has_telemetry": bool(v.get("geo")),
    }

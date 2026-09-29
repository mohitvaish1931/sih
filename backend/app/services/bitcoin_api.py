"""
SIFRA Bitcoin API Service
Multi-provider failover for real blockchain data.
Providers: Blockstream Esplora -> Mempool.space Esplora -> Blockchain.info
"""

import logging
import threading
import time
from typing import Optional, Dict, Any, List

import requests

from app.config import HTTP_TIMEOUT, SYNC_MAX_TXS

log = logging.getLogger("sifra.btc")

USER_AGENT = "SIFRA/3.0 (blockchain-forensics)"
ESPLORA_BASES = ["https://blockstream.info/api", "https://mempool.space/api"]

# ---------------------------------------------------------------------------
# In-memory TTL cache (thread-safe, bounded)
# ---------------------------------------------------------------------------
_cache: Dict[str, Any] = {}
_cache_lock = threading.Lock()
_CACHE_MAX = 5000


def _cache_get(key: str, ttl_seconds: int = 120) -> Optional[Any]:
    with _cache_lock:
        entry = _cache.get(key)
        if entry and (time.time() - entry["ts"]) < ttl_seconds:
            return entry["val"]
    return None


def _cache_set(key: str, value: Any):
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            # Drop the oldest 10% of entries
            for k, _ in sorted(_cache.items(), key=lambda kv: kv[1]["ts"])[: _CACHE_MAX // 10]:
                _cache.pop(k, None)
        _cache[key] = {"val": value, "ts": time.time()}


def cache_invalidate(prefix: str):
    with _cache_lock:
        for k in [k for k in _cache if k.startswith(prefix)]:
            _cache.pop(k, None)


# ---------------------------------------------------------------------------
# Low-level HTTP helper with retries and per-thread keep-alive sessions
# ---------------------------------------------------------------------------
_local = threading.local()


def _session() -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT})
        _local.session = s
    return s


def _get_json(url: str, timeout: float = HTTP_TIMEOUT, retries: int = 2) -> Optional[Any]:
    """GET request with automatic retries on network errors and 429s."""
    for attempt in range(retries + 1):
        try:
            res = _session().get(url, timeout=timeout)
            if res.status_code == 200:
                return res.json()
            if res.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            if 400 <= res.status_code < 500:
                return None  # invalid address etc. - retrying will not help
        except (requests.exceptions.RequestException, ValueError):
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
    return None


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
def _finalize(tx: Dict, address: str) -> Dict:
    """Add address-relative fields (direction, value) to a normalized tx."""
    inputs, outputs = tx["inputs"], tx["outputs"]
    spent = sum(i["value"] for i in inputs if i["address"] == address)
    received = sum(o["value"] for o in outputs if o["address"] == address)
    to_others = sum(o["value"] for o in outputs if o["address"] != address)
    is_sender = spent > 0
    is_receiver = received > 0
    if is_sender and is_receiver:
        direction = "both"
    elif is_sender:
        direction = "sent"
    else:
        direction = "received"

    tx["direction"] = direction
    tx["value_btc"] = round(to_others if is_sender else received, 8)
    tx["net_btc"] = round(received - spent, 8)
    # Legacy shape used by the live monitor / older clients
    tx["senders"] = [i for i in inputs if i["address"]]
    tx["receivers"] = [o for o in outputs if o["address"]]
    tx["inputs_count"] = len(inputs)
    tx["outputs_count"] = len(outputs)
    return tx


def _normalize_esplora_tx(tx: dict, address: str = "") -> Dict:
    status = tx.get("status", {}) or {}
    inputs = []
    for vin in tx.get("vin", []):
        prevout = vin.get("prevout") or {}
        inputs.append({
            "address": prevout.get("scriptpubkey_address"),
            "value": round(prevout.get("value", 0) / 1e8, 8),
        })
    outputs = []
    for n, vout in enumerate(tx.get("vout", [])):
        outputs.append({
            "address": vout.get("scriptpubkey_address"),
            "value": round(vout.get("value", 0) / 1e8, 8),
            "n": n,
        })
    fee = tx.get("fee")
    if fee is None:
        fee = max(0.0, sum(i["value"] for i in inputs) - sum(o["value"] for o in outputs)) * 1e8
    return _finalize({
        "txid": tx.get("txid", ""),
        "timestamp": status.get("block_time"),
        "block_height": status.get("block_height"),
        "confirmed": bool(status.get("confirmed", False)),
        "fee_btc": round(fee / 1e8, 8),
        "size": tx.get("size", 0),
        "weight": tx.get("weight", 0),
        "is_coinbase": any(v.get("is_coinbase") for v in tx.get("vin", [])),
        "inputs": inputs,
        "outputs": outputs,
    }, address)


def _normalize_blockchain_info_tx(tx: dict, address: str = "") -> Dict:
    inputs = []
    for inp in tx.get("inputs", []):
        prev = inp.get("prev_out") or {}
        inputs.append({"address": prev.get("addr"), "value": round(prev.get("value", 0) / 1e8, 8)})
    outputs = []
    for i, out in enumerate(tx.get("out", [])):
        outputs.append({"address": out.get("addr"), "value": round(out.get("value", 0) / 1e8, 8), "n": out.get("n", i)})
    return _finalize({
        "txid": tx.get("hash", ""),
        "timestamp": tx.get("time") if tx.get("block_height") else None,
        "block_height": tx.get("block_height"),
        "confirmed": tx.get("block_height") is not None,
        "fee_btc": round(tx.get("fee", 0) / 1e8, 8),
        "size": tx.get("size", 0),
        "weight": tx.get("weight", 0),
        "is_coinbase": not any(i["address"] for i in inputs),
        "inputs": inputs,
        "outputs": outputs,
    }, address)


# ---------------------------------------------------------------------------
# 1. Wallet transactions (paginated, multi-provider)
# ---------------------------------------------------------------------------
def fetch_wallet_transactions(address: str, limit: int = 50) -> List[Dict]:
    """Most recent transactions for an address (mempool first, then confirmed)."""
    cache_key = f"txs:{address}:{limit}"
    cached = _cache_get(cache_key, ttl_seconds=180)
    if cached is not None:
        return cached

    txs = _fetch_from_esplora(address, limit)
    if not txs:
        txs = _fetch_from_blockchain_info(address, limit)

    if txs:
        _cache_set(cache_key, txs)
    return txs or []


def fetch_history(address: str, limit: int = SYNC_MAX_TXS) -> Dict[str, Any]:
    """History plus provider metadata, used by the sync layer."""
    txs = _fetch_from_esplora(address, limit)
    source = "esplora"
    if not txs:
        txs = _fetch_from_blockchain_info(address, limit)
        source = "blockchain.info"
    return {"txs": txs or [], "source": source if txs else None}


def _fetch_from_esplora(address: str, limit: int) -> Optional[List[Dict]]:
    max_pages = max(1, (limit // 25) + 1)
    for base in ESPLORA_BASES:
        all_txs: List[Dict] = []
        seen = set()
        last_confirmed = None
        try:
            for page in range(max_pages):
                url = f"{base}/address/{address}/txs"
                if last_confirmed:
                    url += f"/chain/{last_confirmed}"
                data = _get_json(url)
                if data is None or not isinstance(data, list):
                    break
                confirmed_in_page = 0
                for tx in data:
                    txid = tx.get("txid")
                    if txid in seen:
                        continue
                    seen.add(txid)
                    all_txs.append(_normalize_esplora_tx(tx, address))
                    if (tx.get("status") or {}).get("confirmed"):
                        confirmed_in_page += 1
                        last_confirmed = txid
                if confirmed_in_page < 25 or len(all_txs) >= limit:
                    break
                time.sleep(0.15)
            if all_txs or data == []:
                return all_txs[:limit]
        except Exception as exc:
            log.warning("Esplora fetch failed on %s: %s", base, exc)
            continue
    return None


def _fetch_from_blockchain_info(address: str, limit: int) -> Optional[List[Dict]]:
    try:
        data = _get_json(f"https://blockchain.info/rawaddr/{address}?limit={min(limit, 50)}")
        if not data or "txs" not in data:
            return None
        return [_normalize_blockchain_info_tx(tx, address) for tx in data.get("txs", [])][:limit]
    except Exception as exc:
        log.warning("Blockchain.info fetch failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# 2. Wallet balance / summary
# ---------------------------------------------------------------------------
def fetch_wallet_balance(address: str) -> Dict:
    """Confirmed/unconfirmed balance and lifetime tx count for an address."""
    cache_key = f"bal:{address}"
    cached = _cache_get(cache_key, ttl_seconds=120)
    if cached is not None:
        return cached

    for base in ESPLORA_BASES:
        data = _get_json(f"{base}/address/{address}", retries=1)
        if data:
            chain = data.get("chain_stats", {})
            mempool = data.get("mempool_stats", {})
            result = {
                "confirmed_btc": round((chain.get("funded_txo_sum", 0) - chain.get("spent_txo_sum", 0)) / 1e8, 8),
                "unconfirmed_btc": round((mempool.get("funded_txo_sum", 0) - mempool.get("spent_txo_sum", 0)) / 1e8, 8),
                "total_received_btc": round(chain.get("funded_txo_sum", 0) / 1e8, 8),
                "total_sent_btc": round(chain.get("spent_txo_sum", 0) / 1e8, 8),
                "tx_count": chain.get("tx_count", 0) + mempool.get("tx_count", 0),
                "funded_txo_count": chain.get("funded_txo_count", 0),
                "spent_txo_count": chain.get("spent_txo_count", 0),
                "available": True,
            }
            _cache_set(cache_key, result)
            return result

    data = _get_json(f"https://blockchain.info/balance?active={address}", retries=1)
    if data and address in data:
        info = data[address]
        result = {
            "confirmed_btc": round(info.get("final_balance", 0) / 1e8, 8),
            "unconfirmed_btc": 0.0,
            "total_received_btc": round(info.get("total_received", 0) / 1e8, 8),
            "total_sent_btc": round((info.get("total_received", 0) - info.get("final_balance", 0)) / 1e8, 8),
            "tx_count": info.get("n_tx", 0),
            "funded_txo_count": 0,
            "spent_txo_count": 0,
            "available": True,
        }
        _cache_set(cache_key, result)
        return result

    return {"confirmed_btc": 0.0, "unconfirmed_btc": 0.0, "total_received_btc": 0.0, "total_sent_btc": 0.0,
            "tx_count": 0, "funded_txo_count": 0, "spent_txo_count": 0, "available": False}


# ---------------------------------------------------------------------------
# 3. Transaction detail
# ---------------------------------------------------------------------------
def fetch_transaction_detail(txid: str) -> Optional[Dict]:
    cache_key = f"txd:{txid}"
    cached = _cache_get(cache_key, ttl_seconds=600)
    if cached is not None:
        return cached
    for base in ESPLORA_BASES:
        data = _get_json(f"{base}/tx/{txid}", retries=1)
        if data:
            result = _normalize_esplora_tx(data, "")
            _cache_set(cache_key, result)
            return result
    return None


# ---------------------------------------------------------------------------
# 4. Address UTXOs
# ---------------------------------------------------------------------------
def fetch_address_utxos(address: str) -> List[Dict]:
    cache_key = f"utxo:{address}"
    cached = _cache_get(cache_key, ttl_seconds=120)
    if cached is not None:
        return cached
    for base in ESPLORA_BASES:
        data = _get_json(f"{base}/address/{address}/utxo", retries=1)
        if data is not None and isinstance(data, list):
            utxos = [{
                "txid": u.get("txid"),
                "vout": u.get("vout"),
                "value_btc": round(u.get("value", 0) / 1e8, 8),
                "confirmed": (u.get("status") or {}).get("confirmed", False),
                "block_height": (u.get("status") or {}).get("block_height"),
            } for u in data]
            _cache_set(cache_key, utxos)
            return utxos
    return []


# ---------------------------------------------------------------------------
# 5. Live mempool stats
# ---------------------------------------------------------------------------
def get_mempool_stats() -> Dict:
    cache_key = "mempool_stats"
    cached = _cache_get(cache_key, ttl_seconds=30)
    if cached is not None:
        return cached

    data = _get_json("https://mempool.space/api/mempool", timeout=6, retries=1)
    fees = _get_json("https://mempool.space/api/v1/fees/recommended", timeout=6, retries=1)

    result = {
        "tx_count": data.get("count", 0) if data else 0,
        "vsize_bytes": data.get("vsize", 0) if data else 0,
        "total_fee_btc": round(data.get("total_fee", 0) / 1e8, 4) if data else 0,
        "size_mb": round((data.get("vsize", 0) / 1_000_000), 2) if data else 0,
        "fee_fastest": fees.get("fastestFee", 0) if fees else 0,
        "fee_half_hour": fees.get("halfHourFee", 0) if fees else 0,
        "fee_hour": fees.get("hourFee", 0) if fees else 0,
        "fee_economy": fees.get("economyFee", 0) if fees else 0,
        "fee_minimum": fees.get("minimumFee", 0) if fees else 0,
        "available": bool(data),
    }
    if data:
        _cache_set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# 6. Latest blocks
# ---------------------------------------------------------------------------
def get_latest_blocks(count: int = 5) -> List[Dict]:
    cache_key = f"blocks:{count}"
    cached = _cache_get(cache_key, ttl_seconds=30)
    if cached is not None:
        return cached

    data = _get_json("https://mempool.space/api/v1/blocks", timeout=6, retries=1)
    if not data or not isinstance(data, list):
        return []

    blocks = []
    for b in data[:count]:
        extras = b.get("extras") or {}
        blocks.append({
            "height": b.get("height"),
            "hash": b.get("id", ""),
            "timestamp": b.get("timestamp"),
            "tx_count": b.get("tx_count", 0),
            "size_mb": round(b.get("size", 0) / 1_000_000, 2),
            "weight": b.get("weight", 0),
            "pool_name": (extras.get("pool") or {}).get("name", "Unknown"),
            "difficulty": b.get("difficulty", 0),
            "median_fee": extras.get("medianFee"),
            "total_fees_btc": round((extras.get("totalFees") or 0) / 1e8, 4),
        })
    _cache_set(cache_key, blocks)
    return blocks


def get_block_txs(block_hash: str, pages: int = 2) -> List[Dict]:
    """First `pages` x 25 transactions of a block (normalized)."""
    cache_key = f"blocktxs:{block_hash}:{pages}"
    cached = _cache_get(cache_key, ttl_seconds=600)
    if cached is not None:
        return cached
    txs: List[Dict] = []
    for page in range(pages):
        data = _get_json(f"https://mempool.space/api/block/{block_hash}/txs/{page * 25}", timeout=8, retries=1)
        if not data:
            break
        txs.extend(_normalize_esplora_tx(tx, "") for tx in data)
        if len(data) < 25:
            break
    if txs:
        _cache_set(cache_key, txs)
    return txs


# ---------------------------------------------------------------------------
# 7. BTC / USD Price
# ---------------------------------------------------------------------------
def get_btc_price_usd() -> Dict:
    cache_key = "btc_price"
    cached = _cache_get(cache_key, ttl_seconds=60)
    if cached is not None:
        return cached

    data = _get_json(
        "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd,inr"
        "&include_24hr_change=true&include_market_cap=true",
        timeout=6, retries=1,
    )
    if data and "bitcoin" in data:
        btc = data["bitcoin"]
        result = {
            "usd": btc.get("usd", 0),
            "inr": btc.get("inr", 0),
            "usd_24h_change": round(btc.get("usd_24h_change", 0) or 0, 2),
            "usd_market_cap": btc.get("usd_market_cap", 0),
            "source": "coingecko",
        }
        _cache_set(cache_key, result)
        return result

    data = _get_json("https://mempool.space/api/v1/prices", timeout=6, retries=1)
    if data and data.get("USD"):
        result = {"usd": data.get("USD", 0), "inr": 0, "usd_24h_change": 0, "usd_market_cap": 0, "source": "mempool.space"}
        _cache_set(cache_key, result)
        return result

    data = _get_json("https://blockchain.info/ticker", timeout=6, retries=1)
    if data and "USD" in data:
        result = {
            "usd": data["USD"].get("last", 0),
            "inr": (data.get("INR") or {}).get("last", 0),
            "usd_24h_change": 0,
            "usd_market_cap": 0,
            "source": "blockchain.info",
        }
        _cache_set(cache_key, result)
        return result

    return {"usd": 0, "inr": 0, "usd_24h_change": 0, "usd_market_cap": 0, "source": None}


def btc_to_usd(btc_amount: float) -> float:
    price = get_btc_price_usd()
    return round((btc_amount or 0) * price.get("usd", 0), 2)

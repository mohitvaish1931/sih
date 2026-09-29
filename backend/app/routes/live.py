"""
SIFRA Live Data Routes
Real-time mempool stats, blocks, BTC price, whale alerts and wallet monitoring (SSE).
"""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.database import SessionLocal
from app.routes.deps import normalize_address
from app.services.alerts import record_monitor_alert
from app.services.bitcoin_api import (
    get_mempool_stats, get_latest_blocks, get_btc_price_usd, fetch_wallet_transactions,
    get_block_txs, cache_invalidate,
)
from app.services.entity_tagger import tag_address
from app.utils import is_valid_btc_address, short

router = APIRouter(tags=["live"])
log = logging.getLogger("sifra.live")

MONITOR_POLL_SECONDS = 15
WHALE_BTC = 10


@router.get("/api/live/mempool")
def live_mempool():
    return get_mempool_stats()


@router.get("/api/live/blocks")
def live_blocks():
    return get_latest_blocks(count=5)


@router.get("/api/live/price")
def live_price():
    return get_btc_price_usd()


@router.get("/api/live/whale-alerts")
def live_whale_alerts():
    """Largest transactions (>= 10 BTC) among the first 50 txs of the latest block, entity-tagged."""
    blocks = get_latest_blocks(count=1)
    if not blocks:
        return {"whales": [], "block_height": None}
    block = blocks[0]
    btc_usd = get_btc_price_usd().get("usd", 0)
    whales = []
    for tx in get_block_txs(block["hash"], pages=2):
        total = sum(o["value"] for o in tx["outputs"])
        if total < WHALE_BTC or tx.get("is_coinbase"):
            continue
        senders = [i["address"] for i in tx["inputs"] if i.get("address")]
        receivers = [o["address"] for o in sorted(tx["outputs"], key=lambda o: -o["value"]) if o.get("address")]
        from_ent = tag_address(senders[0], allow_remote=False) if senders else {}
        to_ent = tag_address(receivers[0], allow_remote=False) if receivers else {}
        whales.append({
            "txid": tx["txid"],
            "value_btc": round(total, 4),
            "value_usd": round(total * btc_usd, 2),
            "from": from_ent.get("entity_name") or (short(senders[0], 8, 4) if senders else "Coinbase"),
            "to": to_ent.get("entity_name") or (short(receivers[0], 8, 4) if receivers else "Unknown"),
            "from_address": senders[0] if senders else None,
            "to_address": receivers[0] if receivers else None,
            "inputs": len(tx["inputs"]),
            "outputs": len(tx["outputs"]),
            "timestamp": block.get("timestamp"),
        })
    whales.sort(key=lambda x: x["value_btc"], reverse=True)
    return {"whales": whales[:10], "block_height": block.get("height"), "btc_usd": btc_usd}


@router.get("/api/live/monitor/{address}")
async def monitor_wallet_sse(address: str, request: Request):
    """
    Server-Sent Events stream for real-time wallet monitoring. Polls the chain
    every 15 s; each new transaction is pushed to the client and stored as an alert.
    """
    address = normalize_address(address)
    watchable = is_valid_btc_address(address)

    async def event_generator():
        known = set()
        if watchable:
            try:
                initial = await asyncio.to_thread(fetch_wallet_transactions, address, 25)
                known.update(tx.get("txid", "") for tx in initial)
            except Exception as exc:
                log.warning("Monitor bootstrap failed: %s", exc)
        yield f"data: {json.dumps({'type': 'connected', 'address': address, 'known_tx_count': len(known), 'watchable': watchable})}\n\n"

        polls = 0
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(MONITOR_POLL_SECONDS)
            polls += 1
            if not watchable:
                if polls % 2 == 0:
                    yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': int(time.time()), 'polls': polls})}\n\n"
                continue
            try:
                cache_invalidate(f"txs:{address}:")
                current = await asyncio.to_thread(fetch_wallet_transactions, address, 25)
                new = [tx for tx in current if tx.get("txid") and tx["txid"] not in known]
                if new:
                    known.update(tx["txid"] for tx in new)
                    btc_usd = (await asyncio.to_thread(get_btc_price_usd)).get("usd", 0)
                    payload = []
                    for tx in new:
                        payload.append({"txid": tx["txid"], "direction": tx["direction"], "value_btc": tx["value_btc"],
                                        "value_usd": round(tx["value_btc"] * btc_usd, 2),
                                        "confirmed": tx["confirmed"]})
                    await asyncio.to_thread(_store_alerts, address, payload)
                    yield f"data: {json.dumps({'type': 'new_transactions', 'transactions': payload, 'count': len(payload)})}\n\n"
                if polls % 4 == 0:
                    yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': int(time.time()), 'polls': polls})}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


def _store_alerts(address: str, txs):
    db = SessionLocal()
    try:
        for tx in txs:
            record_monitor_alert(db, address, tx)
    except Exception as exc:
        log.warning("Could not store monitor alert: %s", exc)
        db.rollback()
    finally:
        db.close()

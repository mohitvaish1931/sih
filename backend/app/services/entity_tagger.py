"""
SIFRA Entity Tagger
Attributes Bitcoin addresses to real-world entities (exchanges, darknet markets,
ransomware, mixers, ...) and returns labels plus risk modifiers.

Sources, in order:
  1. SIFRA curated list below (every address passes checksum validation; labels
     were cross-checked against WalletExplorer where it has a label)
  2. WalletExplorer.com address lookup (live, bounded by a time budget)
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from typing import Dict, Any, List

import requests

from app.config import (ENTITY_LOOKUP_WORKERS, ENTITY_LOOKUP_TIMEOUT,
                        ENTITY_LOOKUP_BUDGET, ENTITY_LOOKUP_MAX)
from app.utils import is_valid_btc_address

log = logging.getLogger("sifra.entity")

_entity_cache: Dict[str, Any] = {}
_entity_lock = threading.Lock()
_NEGATIVE_TTL = 600   # retry failed remote lookups after 10 minutes

# ---------------------------------------------------------------------------
# Curated entity database
# confidence: high = widely documented / confirmed by WalletExplorer label,
#             medium = open-source attribution without independent confirmation
# ---------------------------------------------------------------------------
KNOWN_ENTITIES: Dict[str, Dict[str, Any]] = {
    # === HISTORICAL ===
    "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa": {"name": "Satoshi Nakamoto (Genesis)", "category": "historical", "risk_modifier": 0, "icon": "👑", "confidence": "high"},
    "1HLoD9E4SDFFPDiYfNYnkBLQ85Y51J3Zb1": {"name": "Bitcoin Pizza (Laszlo)", "category": "historical", "risk_modifier": 0, "icon": "🍕", "confidence": "medium"},

    # === EXCHANGES ===
    "1NDyJtNTjmwk5xPNhjgAMu4HDHigtobu1s": {"name": "Binance Hot Wallet", "category": "exchange", "risk_modifier": -5, "icon": "🏦", "confidence": "high"},
    "3M219KR5vEneNb47ewrPfWyb5jQ2DjxRP6": {"name": "Binance Cold Wallet", "category": "exchange", "risk_modifier": -5, "icon": "🏦", "confidence": "medium"},
    "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo": {"name": "Binance Cold Wallet", "category": "exchange", "risk_modifier": -5, "icon": "🏦", "confidence": "high"},
    "bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h": {"name": "Binance (attributed)", "category": "exchange", "risk_modifier": -5, "icon": "🏦", "confidence": "medium"},
    "1KAt6STtisWMMVo5XGdos9P7DBNNsFfjx7": {"name": "Binance Wallet 2", "category": "exchange", "risk_modifier": -5, "icon": "🏦", "confidence": "medium"},
    "3Cbq7aT1tY8kMxWLbitaG7yT6bPbKChq64": {"name": "Binance", "category": "exchange", "risk_modifier": -5, "icon": "🏦", "confidence": "medium"},
    "3D2oetdNuZUqQHPJmcMDDHYoqkyNVsFk9r": {"name": "Bitfinex Hot Wallet", "category": "exchange", "risk_modifier": -5, "icon": "🏦", "confidence": "medium"},
    "bc1qgdjqv0av3q56jvd82tkdjpy7gdp9ut8tlqmgrpmv24sq90ecnvqqjwvw97": {"name": "Bitfinex Cold (Bech32)", "category": "exchange", "risk_modifier": -5, "icon": "🏦", "confidence": "high"},
    "3LYJfcfHPXYJreMsASk2jkn69LWEYKzexb": {"name": "Kraken Hot Wallet", "category": "exchange", "risk_modifier": -5, "icon": "🏦", "confidence": "medium"},
    "3FHNBLobJnbCTFTVakh5TXmEneyf5PT61B": {"name": "Kraken Cold Wallet", "category": "exchange", "risk_modifier": -5, "icon": "🏦", "confidence": "medium"},
    "3Kzh9qAqVWQhEsfQz7zEQL1EuSx5tyNLNS": {"name": "Coinbase Prime", "category": "exchange", "risk_modifier": -5, "icon": "🏦", "confidence": "medium"},
    "3Nxwenay9Z8Lc9JBiywExpnEFiLp6Afp8v": {"name": "Bitstamp Cold Wallet", "category": "exchange", "risk_modifier": -5, "icon": "🏦", "confidence": "medium"},
    "bc1qx9t2l3pyny2spqpqlye8svce70nppwtaxwdrp4": {"name": "Gemini", "category": "exchange", "risk_modifier": -5, "icon": "🏦", "confidence": "medium"},
    "1HckjUpRGcrrRAtFaaCAUaGjsPx9oYmLaZ": {"name": "Huobi", "category": "exchange", "risk_modifier": -5, "icon": "🏦", "confidence": "high"},
    "17A16QmavnUfCW11DAApiJxp7ARnxN5pGX": {"name": "Poloniex", "category": "exchange", "risk_modifier": -5, "icon": "🏦", "confidence": "high"},
    "1FeexV6bAHb8ybZjqQMjJrcCrHGW9sb6uF": {"name": "Mt. Gox (attributed)", "category": "exchange_defunct", "risk_modifier": 30, "icon": "🏚️", "confidence": "medium"},

    # === DARKNET / LAW ENFORCEMENT ===
    "1FfmbHfnpaZjKFvyi1okTjJJusN455paPH": {"name": "Silk Road-linked Wallet", "category": "darknet", "risk_modifier": 50, "icon": "🕸️", "confidence": "medium"},
    "1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqX": {"name": "Silk Road FBI Seizure", "category": "government_seizure", "risk_modifier": 40, "icon": "⚖️", "confidence": "high"},
    "3BMEXqGpG4FxBA1KWhRFufXfSTRgzfDBhJ": {"name": "Hydra Market (attributed)", "category": "darknet", "risk_modifier": 60, "icon": "🕸️", "confidence": "medium"},

    # === RANSOMWARE / HACKS / SCAMS ===
    "13AM4VW2dhxYgXeQepoHkHSQuy6NgaEb94": {"name": "WannaCry Ransom", "category": "ransomware", "risk_modifier": 80, "icon": "🦠", "confidence": "high"},
    "12t9YDPgwueZ9NyMgw519p7AA8isjr6SMw": {"name": "WannaCry Wallet 2", "category": "ransomware", "risk_modifier": 80, "icon": "🦠", "confidence": "high"},
    "115p7UMMngoj1pMvkpHijcRdfJNXj6LrLn": {"name": "WannaCry Wallet 3", "category": "ransomware", "risk_modifier": 80, "icon": "🦠", "confidence": "high"},
    "bc1qazcm763858nkj2dj986etajv6wquslv8uxwczt": {"name": "Bitfinex 2016 Hack (DOJ-seized)", "category": "hack", "risk_modifier": 70, "icon": "💀", "confidence": "high"},
    "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh": {"name": "Twitter Hack Scam (2020)", "category": "scam", "risk_modifier": 70, "icon": "💀", "confidence": "high"},

    # === MIXERS ===
    "1Enjoy1C4bYBr3tN4sMKxvvJDqG8NkdR4Z": {"name": "Wasabi CoinJoin (attributed)", "category": "mixer", "risk_modifier": 35, "icon": "🌀", "confidence": "medium"},

    # === WHALES / INSTITUTIONAL ===
    "1P5ZEDWTKTFGxQjZphgWPQUpe554WKDfHQ": {"name": "Bitcoin Whale", "category": "whale", "risk_modifier": 5, "icon": "🐋", "confidence": "medium"},
    "37XuVSEpWW4trkfmvWzegTHQt7BdktSKUs": {"name": "Grayscale GBTC (attributed)", "category": "institutional", "risk_modifier": -10, "icon": "🏢", "confidence": "medium"},

    # === MINING POOLS ===
    "1KFHE7w8BhaENAswwryaoccDb6qcT6DbYY": {"name": "F2Pool", "category": "mining", "risk_modifier": -10, "icon": "⛏️", "confidence": "medium"},
    "12dRugNcdxK39288NjcDV4GX7rMsKCGn6B": {"name": "AntPool", "category": "mining", "risk_modifier": -10, "icon": "⛏️", "confidence": "medium"},
    "1CK6KHY6MHgYvmRQ4PAafKYDrg1ejbH1cE": {"name": "Slush Pool", "category": "mining", "risk_modifier": -10, "icon": "⛏️", "confidence": "high"},

    # === GAMBLING ===
    "1dice8EMZmqKvrGE4Qc9bUFf9PX3xaYDp": {"name": "SatoshiDice", "category": "gambling", "risk_modifier": 20, "icon": "🎰", "confidence": "high"},
}

# Demo-scenario counterparties (seed_data.py). Never valid mainnet addresses.
DEMO_ENTITIES: Dict[str, Dict[str, Any]] = {
    "Exchange_Binance_0": {"name": "Demo Exchange A", "category": "exchange", "risk_modifier": -5, "icon": "🏦"},
    "Exchange_Binance_1": {"name": "Demo Exchange B", "category": "exchange", "risk_modifier": -5, "icon": "🏦"},
    "Exchange_Binance_2": {"name": "Demo Exchange C", "category": "exchange", "risk_modifier": -5, "icon": "🏦"},
    "Darknet_Market_Alpha": {"name": "Demo Darknet Market Alpha", "category": "darknet", "risk_modifier": 60, "icon": "🕸️"},
    "Darknet_Market_Hydra": {"name": "Demo Darknet Market Hydra", "category": "darknet", "risk_modifier": 60, "icon": "🕸️"},
    "bc1_demo_ransom_ops": {"name": "Demo Ransomware Operator", "category": "ransomware", "risk_modifier": 80, "icon": "🦠"},
    "bc1_demo_mixer_pool": {"name": "Demo CoinJoin Coordinator", "category": "mixer", "risk_modifier": 35, "icon": "🌀"},
}

# Category metadata for risk coloring and display
CATEGORY_META = {
    "exchange": {"color": "#22c55e", "label": "Exchange", "risk_class": "safe"},
    "exchange_defunct": {"color": "#f59e0b", "label": "Defunct Exchange", "risk_class": "warning"},
    "darknet": {"color": "#ef4444", "label": "Darknet Market", "risk_class": "critical"},
    "ransomware": {"color": "#dc2626", "label": "Ransomware", "risk_class": "critical"},
    "hack": {"color": "#f97316", "label": "Hack Proceeds", "risk_class": "high"},
    "scam": {"color": "#fb7185", "label": "Scam", "risk_class": "high"},
    "sanctioned": {"color": "#b91c1c", "label": "Sanctioned Entity", "risk_class": "critical"},
    "mixer": {"color": "#a855f7", "label": "Mixer / CoinJoin", "risk_class": "high"},
    "coinjoin_cluster": {"color": "#c084fc", "label": "CoinJoin-merged Cluster", "risk_class": "warning"},
    "government": {"color": "#3b82f6", "label": "Government", "risk_class": "safe"},
    "government_seizure": {"color": "#3b82f6", "label": "Law Enforcement Seizure", "risk_class": "safe"},
    "whale": {"color": "#06b6d4", "label": "Whale", "risk_class": "neutral"},
    "institutional": {"color": "#10b981", "label": "Institutional", "risk_class": "safe"},
    "mining": {"color": "#8b5cf6", "label": "Mining Pool", "risk_class": "safe"},
    "historical": {"color": "#f59e0b", "label": "Historical", "risk_class": "neutral"},
    "gambling": {"color": "#eab308", "label": "Gambling", "risk_class": "warning"},
    "service": {"color": "#14b8a6", "label": "Service", "risk_class": "neutral"},
    "unknown": {"color": "#64748b", "label": "Unknown", "risk_class": "neutral"},
}

# Categories counted as illicit when measuring counterparty exposure, with severity (0..1)
ILLICIT_SEVERITY = {
    "ransomware": 1.0, "sanctioned": 1.0, "darknet": 0.9, "hack": 0.85,
    "scam": 0.8, "mixer": 0.6, "exchange_defunct": 0.2, "gambling": 0.25, "coinjoin_cluster": 0.15,
}
# Regulated services that naturally trigger volume heuristics
SERVICE_CATEGORIES = {"exchange", "mining", "institutional", "government", "government_seizure"}

_CATEGORY_ICONS = {
    "exchange": "🏦", "darknet": "🕸️", "ransomware": "🦠", "hack": "💀", "scam": "💀",
    "sanctioned": "⛔", "mixer": "🌀", "coinjoin_cluster": "🌀", "mining": "⛏️", "gambling": "🎰", "government": "🏛️",
    "government_seizure": "⚖️", "institutional": "🏢", "whale": "🐋", "historical": "📜",
    "service": "🧩", "unknown": "❓",
}
_CATEGORY_MODIFIERS = {
    "exchange": -5, "darknet": 60, "ransomware": 80, "hack": 70, "scam": 70, "sanctioned": 90,
    "mixer": 35, "coinjoin_cluster": 5, "mining": -10, "gambling": 20, "government": 0, "institutional": -10,
    "whale": 5, "historical": 0, "service": 0, "unknown": 0,
}


def _entity(address: str, name, category: str, risk_modifier: int, icon: str,
            source: str, confidence: str = "medium", cluster_ref=None) -> Dict[str, Any]:
    meta = CATEGORY_META.get(category, CATEGORY_META["unknown"])
    return {
        "address": address,
        "entity_name": name,
        "category": category,
        "category_label": meta["label"],
        "risk_modifier": risk_modifier,
        "risk_class": meta["risk_class"],
        "color": meta["color"],
        "icon": icon,
        "is_known": name is not None,
        "illicit_severity": ILLICIT_SEVERITY.get(category, 0.0) if name is not None else 0.0,
        "confidence": confidence if name is not None else None,
        "source": source,
        "cluster_ref": cluster_ref,
    }


def _unknown(address: str, source: str = "none", cluster_ref=None) -> Dict[str, Any]:
    return _entity(address, None, "unknown", 0, "❓", source, cluster_ref=cluster_ref)


def _local_lookup(address: str):
    entry = KNOWN_ENTITIES.get(address)
    if entry:
        return _entity(address, entry["name"], entry["category"], entry.get("risk_modifier", 0),
                       entry.get("icon", "❓"), "sifra_db", entry.get("confidence", "medium"))
    entry = DEMO_ENTITIES.get(address)
    if entry:
        return _entity(address, entry["name"], entry["category"], entry.get("risk_modifier", 0),
                       entry.get("icon", "❓"), "demo", "high")
    return None


def _cached(address: str):
    with _entity_lock:
        hit = _entity_cache.get(address)
    if not hit:
        return None
    if hit.get("_negative") and time.time() - hit["_ts"] > _NEGATIVE_TTL:
        return None
    return hit["value"]


def _store(address: str, value: Dict, negative: bool = False):
    with _entity_lock:
        _entity_cache[address] = {"value": value, "_negative": negative, "_ts": time.time()}


def tag_address(address: str, allow_remote: bool = True) -> Dict[str, Any]:
    """Entity information for a single address."""
    local = _local_lookup(address)
    if local:
        return local
    cached = _cached(address)
    if cached is not None:
        return cached
    if not allow_remote or not is_valid_btc_address(address):
        return _unknown(address)
    result, ok = _lookup_wallet_explorer(address)
    _store(address, result, negative=not ok)
    return result


def _lookup_wallet_explorer(address: str):
    """Query WalletExplorer.com. Returns (entity, lookup_succeeded)."""
    try:
        res = requests.get(
            "https://www.walletexplorer.com/api/1/address-lookup",
            params={"address": address, "caller": "sifra"},
            timeout=ENTITY_LOOKUP_TIMEOUT,
            headers={"User-Agent": "SIFRA/3.0"},
        )
        if res.status_code != 200:
            return _unknown(address), False
        data = res.json()
        label = data.get("label") or ""
        wallet_id = data.get("wallet_id")
        if label:
            cat = _map_we_label_to_category(label)
            return _entity(address, label, cat, _CATEGORY_MODIFIERS.get(cat, 0),
                           _CATEGORY_ICONS.get(cat, "❓"), "walletexplorer", "high", wallet_id), True
        return _unknown(address, "walletexplorer", wallet_id), True
    except Exception:
        return _unknown(address), False


def _map_we_label_to_category(label: str) -> str:
    """Map WalletExplorer label strings to SIFRA categories."""
    lab = label.lower()
    if "coinjoinmess" in lab:
        # WalletExplorer's catch-all cluster produced by CoinJoins merging many unrelated users
        return "coinjoin_cluster"
    rules = [
        ("mixer", ["mix", "tumbl", "wasabi", "tornado", "coinjoin", "bitcoinfog", "helix", "chipmixer", "samourai", "whirlpool"]),
        ("darknet", ["silkroad", "silk road", "hydra", "alphabay", "agora", "evolution", "nucleus", "abraxas",
                     "middleearth", "blackbank", "sheep", "pandora", "darknet", "market"]),
        ("ransomware", ["ransomware", "wannacry", "revil", "lockbit", "ransom", "ryuk", "conti"]),
        ("hack", ["hack", "stolen", "theft"]),
        ("scam", ["scam", "ponzi", "fraud"]),
        ("mining", ["pool", "mining", "f2pool", "antpool", "foundry", "slush", "btc.com", "viabtc"]),
        ("gambling", ["gambling", "dice", "casino", "bet", "poker", "lottery", "primedice", "bitzino"]),
        ("government", ["fbi", "doj", "seizure", "government", "bka", "marshals"]),
        ("exchange", ["binance", "coinbase", "kraken", "bitstamp", "gemini", "bitfinex", "huobi", "okex", "okx",
                      "bybit", "kucoin", "poloniex", "bittrex", "btc-e", "localbitcoins", "cex.io", "bitmex",
                      "exchange", "mtgox", "wazirx", "coindcx", "zebpay", "unocoin"]),
    ]
    for category, keys in rules:
        if any(k in lab for k in keys):
            if category == "exchange" and "mtgox" in lab:
                return "exchange_defunct"
            return category
    return "service"


def _store_future(addr: str, fut):
    try:
        entity, ok = fut.result()
    except Exception:
        entity, ok = _unknown(addr), False
    _store(addr, entity, negative=not ok)


def tag_addresses_batch(addresses: List[str], budget: float = ENTITY_LOOKUP_BUDGET,
                        max_remote: int = ENTITY_LOOKUP_MAX) -> Dict[str, Dict]:
    """
    Tag many addresses at once. Local/cached hits are instant; the remaining
    remote lookups run in parallel and stop at `budget` seconds so a big graph
    can never stall the investigation.
    """
    result: Dict[str, Dict] = {}
    remote: List[str] = []
    for addr in dict.fromkeys(a for a in addresses if a and isinstance(a, str)):
        local = _local_lookup(addr)
        if local:
            result[addr] = local
            continue
        cached = _cached(addr)
        if cached is not None:
            result[addr] = cached
            continue
        if is_valid_btc_address(addr) and len(remote) < max_remote:
            remote.append(addr)
        else:
            result[addr] = _unknown(addr)

    if remote:
        deadline = time.time() + budget
        pool = ThreadPoolExecutor(max_workers=min(ENTITY_LOOKUP_WORKERS, len(remote)))
        futures = {}
        for a in remote:
            fut = pool.submit(_lookup_wallet_explorer, a)
            futures[fut] = a
            # Lookups finishing after the deadline still land in the cache for the next request
            fut.add_done_callback(lambda f, addr=a: _store_future(addr, f))
        pending = set(futures)
        while pending and time.time() < deadline:
            done, pending = wait(pending, timeout=max(0.05, deadline - time.time()), return_when=FIRST_COMPLETED)
            for fut in done:
                addr = futures[fut]
                try:
                    entity, _ = fut.result()
                except Exception:
                    entity = _unknown(addr)
                result[addr] = entity
        for fut in pending:
            result[futures[fut]] = _unknown(futures[fut])
        pool.shutdown(wait=False)

    for addr in addresses:
        if addr and addr not in result:
            result[addr] = _unknown(addr)
    return result


def known_entity_index() -> List[Dict[str, Any]]:
    """Curated watchlist exported to the frontend (live-feed watchlist hits)."""
    out = []
    for addr, e in KNOWN_ENTITIES.items():
        meta = CATEGORY_META.get(e["category"], CATEGORY_META["unknown"])
        out.append({"address": addr, "name": e["name"], "category": e["category"],
                    "category_label": meta["label"], "icon": e.get("icon", "❓"),
                    "illicit": e["category"] in ILLICIT_SEVERITY, "confidence": e.get("confidence")})
    return out

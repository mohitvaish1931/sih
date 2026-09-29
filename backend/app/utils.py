"""Shared helpers: timezone-safe datetimes and Bitcoin address validation."""

import hashlib
import re
from datetime import datetime, timezone
from typing import Optional

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Seeded demo scenarios use ids such as "bc1_sus_peel_root". The underscore can
# never appear in a real address, so demo ids can never collide with mainnet.
DEMO_ADDRESS_RE = re.compile(r"^(bc1_[a-z0-9_]{2,60}|Exchange_[A-Za-z0-9_]+|Darknet_[A-Za-z0-9_]+)$")


def as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes, Postgres aware ones. Normalise to aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def from_unix(ts) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def sort_key(dt: Optional[datetime]) -> datetime:
    """Sort key that tolerates None (unconfirmed txs sort last)."""
    return as_utc(dt) or datetime.max.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Address validation
# ---------------------------------------------------------------------------
_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32M_CONST = 0x2BC830A3


def _b58decode_check(addr: str) -> Optional[bytes]:
    num = 0
    for ch in addr:
        idx = _B58_ALPHABET.find(ch)
        if idx < 0:
            return None
        num = num * 58 + idx
    raw = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    pad = len(addr) - len(addr.lstrip("1"))
    raw = b"\x00" * pad + raw
    if len(raw) != 25:
        return None
    payload, checksum = raw[:-4], raw[-4:]
    if hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] != checksum:
        return None
    return payload


def _bech32_polymod(values) -> int:
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            chk ^= gen[i] if ((b >> i) & 1) else 0
    return chk


def _bech32_valid(addr: str) -> bool:
    if addr.lower() != addr and addr.upper() != addr:
        return False
    addr = addr.lower()
    pos = addr.rfind("1")
    if pos < 1 or pos + 7 > len(addr) or len(addr) > 90:
        return False
    hrp, data_part = addr[:pos], addr[pos + 1:]
    if hrp != "bc":
        return False
    if any(c not in _BECH32_CHARSET for c in data_part):
        return False
    data = [_BECH32_CHARSET.find(c) for c in data_part]
    expanded = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]
    const = _bech32_polymod(expanded + data)
    witness_version = data[0]
    if witness_version == 0:
        return const == 1
    return const == _BECH32M_CONST


def is_valid_btc_address(address: str) -> bool:
    """Validate mainnet P2PKH (1...), P2SH (3...) and SegWit/Taproot (bc1...) addresses."""
    if not address or not isinstance(address, str):
        return False
    address = address.strip()
    if address.lower().startswith("bc1"):
        return _bech32_valid(address)
    if address[0] in "13" and 26 <= len(address) <= 35:
        payload = _b58decode_check(address)
        return payload is not None and payload[0] in (0x00, 0x05)
    return False


def is_demo_address(address: str) -> bool:
    return bool(address and DEMO_ADDRESS_RE.match(address))


def short(addr: Optional[str], head: int = 8, tail: int = 6) -> str:
    if not addr:
        return "unknown"
    if len(addr) <= head + tail + 1:
        return addr
    return f"{addr[:head]}…{addr[-tail:]}"

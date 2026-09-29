"""
IP enrichment for relay telemetry: geolocation (ip-api.com batch API, free tier)
and anonymity-network detection (Tor Project bulk exit list + ip-api proxy /
hosting flags).
"""

import ipaddress
import logging
import threading
import time
from typing import Dict, List

import requests

from app.config import GEOIP_ENABLED

log = logging.getLogger("sifra.geoip")

_geo_cache: Dict[str, Dict] = {}
_tor = {"ips": set(), "fetched": 0.0}
_lock = threading.Lock()


def _tor_exits() -> set:
    with _lock:
        if time.time() - _tor["fetched"] < 6 * 3600:
            return _tor["ips"]
    try:
        res = requests.get("https://check.torproject.org/torbulkexitlist", timeout=8)
        if res.status_code == 200:
            ips = {line.strip() for line in res.text.splitlines() if line.strip() and not line.startswith("#")}
            with _lock:
                _tor.update({"ips": ips, "fetched": time.time()})
    except requests.RequestException as exc:
        log.info("Tor exit list unavailable: %s", exc)
        with _lock:
            _tor["fetched"] = time.time() - 5 * 3600   # retry in an hour
    return _tor["ips"]


def _is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return not (addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local)
    except ValueError:
        return False


def lookup_many(ips: List[str]) -> Dict[str, Dict]:
    """Geolocate IPs (cached). Unknown / private IPs map to None-valued records."""
    result: Dict[str, Dict] = {}
    todo = []
    for ip in dict.fromkeys(ips):
        if ip in _geo_cache:
            result[ip] = _geo_cache[ip]
        elif _is_public(ip) and GEOIP_ENABLED:
            todo.append(ip)
        else:
            result[ip] = {"ip": ip, "country": None, "city": None, "lat": None, "lon": None, "isp": None,
                          "is_vpn_tor": False}
    tor = _tor_exits() if todo else set()
    for i in range(0, len(todo), 100):
        batch = todo[i:i + 100]
        try:
            res = requests.post(
                "http://ip-api.com/batch",
                json=[{"query": ip, "fields": "status,query,country,city,lat,lon,isp,proxy,hosting"} for ip in batch],
                timeout=10,
            )
            rows = res.json() if res.status_code == 200 else []
        except (requests.RequestException, ValueError) as exc:
            log.warning("GeoIP batch failed: %s", exc)
            rows = []
        for row in rows:
            ip = row.get("query")
            if not ip:
                continue
            rec = {
                "ip": ip,
                "country": row.get("country"),
                "city": row.get("city"),
                "lat": row.get("lat"),
                "lon": row.get("lon"),
                "isp": row.get("isp"),
                # Tor exits are definitive; a proxy flag on a hosting range is usually just a
                # well-connected node in a data centre, so it is not treated as anonymisation.
                "is_vpn_tor": bool(ip in tor or (row.get("proxy") and not row.get("hosting"))),
                "is_hosting": bool(row.get("hosting")),
                "is_tor": ip in tor,
            }
            if row.get("status") == "success":
                _geo_cache[ip] = rec
            result[ip] = rec
    for ip in ips:
        result.setdefault(ip, {"ip": ip, "country": None, "city": None, "lat": None, "lon": None, "isp": None,
                               "is_vpn_tor": ip in tor})
    return result

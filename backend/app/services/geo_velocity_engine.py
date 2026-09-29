"""
SIFRA Geo-Velocity & Impossible-Travel engine.

Bitcoin transactions carry no IP address. Broadcast locations therefore come
only from *observed* network telemetry:
  * relay observations recorded by sensor/relay_sensor.py (first peer that
    announced the transaction to SIFRA's listening node - "first-spy" estimate)
  * locations stored with the transaction (demo scenarios / imported case data)
Transactions without telemetry are reported as such; nothing is inferred or
synthesised, so this component can only raise risk on real observations.
"""

import math
from typing import List, Dict, Any

IMPOSSIBLE_KMH = 900        # faster than a commercial airliner
MIN_CONFIDENCE = 0.35       # first-spy observations below this are reported but not scored
HOP_CONFIDENCE = 0.6        # both ends of an impossible-travel hop must be at least this reliable
MIN_HOP_MINUTES = 2         # below this, relay propagation jitter dominates
MIN_DISTANCE_KM = 400
MAX_WINDOW_HOURS = 4.0


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)


def _empty(total: int, summary: str) -> Dict[str, Any]:
    return {
        "data_available": False,
        "has_impossible_travel": False,
        "max_velocity_kmh": 0.0,
        "impossible_hops_count": 0,
        "vpn_tor_count": 0,
        "hops": [],
        "locations": [],
        "coverage": {"observed": 0, "total": total},
        "score": 0.0,
        "summary": summary,
        "method": "Relay telemetry (first-spy estimator) - no location is inferred without observation",
    }


def analyze_geo_velocity(views: List[Dict], target_address: str) -> Dict[str, Any]:
    """Velocity between successive observed broadcast locations of the wallet's spends."""
    total = len(views)
    all_observed = [v for v in views if v.get("geo")]
    observed = [v for v in all_observed if (v["geo"].get("confidence") or 1.0) >= MIN_CONFIDENCE]
    low_conf = len(all_observed) - len(observed)
    if not observed and low_conf:
        out = _empty(total, f"{low_conf} relay observation(s) exist but all came from high-volume relay nodes "
                            "(low first-spy confidence), so no location is attributed.")
        out["coverage"]["low_confidence"] = low_conf
        return out
    if not observed:
        return _empty(total, "No broadcast telemetry for this wallet. Run the SIFRA relay sensor to capture "
                             "first-relay peers for new transactions.")

    # Location of a *spend* reflects where the owner broadcast from; receipts are
    # broadcast by the sender, so only spends feed the velocity check.
    spends = [v for v in observed if v["is_input"]]
    series = spends if len(spends) >= 2 else observed

    def when(v):
        return v["geo"].get("first_seen") or v["timestamp"]

    series = sorted((v for v in series if when(v) is not None), key=when)

    location_map: Dict[str, Dict] = {}
    for v in observed:
        g = v["geo"]
        key = g["ip"]
        if key not in location_map:
            location_map[key] = {"ip": g["ip"], "city": g["city"], "country": g["country"], "lat": g["lat"],
                                 "lon": g["lon"], "isp": g["isp"], "is_vpn_tor": g["is_vpn_tor"],
                                 "source": g.get("source"), "confidence": g.get("confidence", 1.0), "tx_count": 0}
        location_map[key]["tx_count"] += 1

    hops, max_velocity, impossible = [], 0.0, 0
    for prev, cur in zip(series, series[1:]):
        a, b = prev["geo"], cur["geo"]
        t0, t1 = when(prev), when(cur)
        dt_h = abs((t1 - t0).total_seconds()) / 3600
        dist = haversine_distance_km(a["lat"], a["lon"], b["lat"], b["lon"])
        velocity = round(dist / max(dt_h, 1 / 60), 1) if dist > 50 else 0.0
        physically_impossible = dist > MIN_DISTANCE_KM and velocity > IMPOSSIBLE_KMH and dt_h <= MAX_WINDOW_HOURS
        hop_conf = min(a.get("confidence") or 1.0, b.get("confidence") or 1.0)
        reliable = hop_conf >= HOP_CONFIDENCE and dt_h * 60 >= MIN_HOP_MINUTES
        is_impossible = physically_impossible and reliable
        reason = None
        if is_impossible:
            impossible += 1
            reason = f"Impossible geo-velocity ({velocity:,.0f} km/h over {dist:,.0f} km in {dt_h * 60:.0f} min)"
        elif physically_impossible:
            reason = ("Implausible jump between relays, not scored: relay-level first-spy estimates this close "
                      "together or this uncertain usually reflect propagation paths, not the sender moving")
        elif a.get("is_vpn_tor") or b.get("is_vpn_tor"):
            reason = "Tor/VPN relay involved"
        max_velocity = max(max_velocity, velocity)
        hops.append({
            "from_city": a["city"], "from_country": a["country"], "from_ip": a["ip"], "from_coords": [a["lat"], a["lon"]],
            "to_city": b["city"], "to_country": b["country"], "to_ip": b["ip"], "to_coords": [b["lat"], b["lon"]],
            "distance_km": dist, "time_diff_minutes": round(dt_h * 60, 1), "velocity_kmh": velocity,
            "is_impossible": is_impossible, "flag_reason": reason, "tx_hash": cur["txid"],
            "confidence": round(hop_conf, 2),
        })

    vpn_count = sum(1 for l in location_map.values() if l["is_vpn_tor"])
    score = 0.0
    if impossible:
        score = min(100.0, 60 + 15 * impossible)
    if vpn_count:
        score = min(100.0, score + 20 + 5 * (vpn_count - 1))

    if impossible:
        summary = (f"CRITICAL: {impossible} impossible-travel event(s); broadcast origin jumped at up to "
                   f"{max_velocity:,.0f} km/h between observed relays.")
    elif vpn_count:
        summary = f"SUSPICIOUS: {vpn_count} broadcast origin(s) resolve to Tor / VPN / hosting infrastructure."
    else:
        summary = f"NORMAL: {len(location_map)} observed broadcast origin(s) within physically plausible travel."

    return {
        "data_available": True,
        "has_impossible_travel": impossible > 0,
        "max_velocity_kmh": max_velocity,
        "impossible_hops_count": impossible,
        "vpn_tor_count": vpn_count,
        "hops": hops,
        "locations": list(location_map.values()),
        "coverage": {"observed": len(observed), "total": total, "low_confidence": low_conf},
        "score": score,
        "summary": summary,
        "method": "Relay telemetry (first-spy estimator) - no location is inferred without observation",
    }

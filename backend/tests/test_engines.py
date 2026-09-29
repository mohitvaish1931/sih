"""Unit tests for the forensic engines on hand-built transaction views."""

from datetime import datetime, timedelta, timezone

from app.services import rule_engine as R
from app.services.geo_velocity_engine import analyze_geo_velocity
from app.services.risk_engine import fuse, risk_level
from app.utils import is_valid_btc_address, is_demo_address, as_utc

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
ME = "bc1_me"


def view(minutes, inputs, outputs, txid=None):
    """Minimal wallet view from (address, value) tuples, relative to ME."""
    ins = [{"address": a, "value": v} for a, v in inputs]
    outs = [{"address": a, "value": v, "n": i} for i, (a, v) in enumerate(outputs)]
    is_input = any(a == ME for a, _ in inputs)
    received = sum(v for a, v in outputs if a == ME)
    to_others = sum(v for a, v in outputs if a != ME)
    return {
        "txid": txid or f"tx{minutes}-{len(outputs)}", "timestamp": T0 + timedelta(minutes=minutes),
        "block_height": 1, "confirmed": True, "fee_btc": 0, "inputs": ins, "outputs": outs,
        "input_count": len(ins), "output_count": len(outs), "is_input": is_input,
        "direction": "sent" if is_input else "received",
        "spent_btc": sum(v for a, v in inputs if a == ME), "received_btc": received,
        "outflow_btc": to_others if is_input else 0.0, "inflow_btc": received if not is_input else 0.0,
        "source": "test", "geo": None,
    }


# ---------------------------------------------------------------------------
# Address validation
# ---------------------------------------------------------------------------
def test_address_validation_vectors():
    assert is_valid_btc_address("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
    assert is_valid_btc_address("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")
    assert is_valid_btc_address("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
    assert is_valid_btc_address("bc1p5d7rjq7g6rdk2yhzks9smlaqtedr4dekq08ge8ztwac72sfr9rusxg3297")
    assert not is_valid_btc_address("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN3")        # bad checksum
    assert not is_valid_btc_address("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5")  # bad bech32 checksum
    assert not is_valid_btc_address("1kr6QSydW9bFQG1mXiPNNu6WpJGmUa9i1g")          # was in the old entity list
    assert not is_valid_btc_address("bc1_sus_peel_root")
    assert is_demo_address("bc1_sus_peel_root") and not is_demo_address("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")


def test_curated_entities_all_have_valid_checksums():
    from app.services.entity_tagger import KNOWN_ENTITIES
    bad = [a for a in KNOWN_ENTITIES if not is_valid_btc_address(a)]
    assert bad == []


def test_as_utc_normalises_naive():
    naive = datetime(2026, 1, 1, 12, 0)
    assert as_utc(naive).tzinfo is not None
    assert as_utc(None) is None


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------
def test_rapid_passthrough_allocates_across_many_spends():
    views = [view(0, [("ex", 101)], [(ME, 100)])]
    remaining = 100.0
    for i in range(20):
        views.append(view(5 + i, [(ME, remaining)], [(f"t{i}", 4.9), (ME, remaining - 4.9)]))
        remaining -= 4.9
    f = R.detect_rapid_passthrough(ME, views)
    assert f is not None and f["evidence"]["fast_ratio"] > 0.9


def test_coinjoin_counts_only_when_wallet_contributes_input():
    cj_inputs = [(f"p{i}", 1.0) for i in range(6)]
    cj_outputs = [(f"o{i}", 0.5) for i in range(6)] + [(ME, 0.5)]
    received_from_coinjoin = view(0, cj_inputs, cj_outputs)
    assert R.detect_coinjoin(ME, [received_from_coinjoin]) is None
    participated = view(10, cj_inputs + [(ME, 1.0)], cj_outputs)
    f = R.detect_coinjoin(ME, [participated])
    assert f is not None and f["evidence"]["coinjoins"][0]["equal_outputs"] >= 5


def test_fan_in_is_dampened_for_receive_only_wallets():
    receipts = [view(i * 10, [(f"s{i}", 1.0)], [(ME, 0.9)]) for i in range(20)]
    weak = R.detect_fan_in(ME, receipts)
    forwarding = receipts + [view(300 + i, [(ME, 1.0)], [(f"r{i}", 0.9)]) for i in range(10)]
    strong = R.detect_fan_in(ME, forwarding)
    assert weak and strong and weak["points"] < strong["points"]


def test_burst_ignores_incoming_transactions():
    receipts = [view(i, [(f"s{i}", 1.0)], [(ME, 0.9)]) for i in range(30)]
    assert R.detect_burst(ME, receipts) is None
    spends = [view(i, [(ME, 1.0)], [(f"r{i}", 0.5), (ME, 0.49)]) for i in range(15)]
    assert R.detect_burst(ME, spends) is not None


def test_peel_shape_requires_small_output_and_fresh_remainder():
    peel = view(0, [(ME, 10)], [("shop", 0.5), ("fresh", 9.49)])
    assert R._peel_shape(ME, peel)["peeled_to"] == "shop"
    even_split = view(0, [(ME, 10)], [("a", 5), ("b", 4.99)])
    assert R._peel_shape(ME, even_split) is None
    change_to_self = view(0, [(ME, 10)], [("shop", 0.5), (ME, 9.49)])
    assert R._peel_shape(ME, change_to_self) is None


def test_heuristics_score_is_bounded():
    views = [view(i, [(ME, 1.0)], [(f"r{i}", 0.5), (ME, 0.49)]) for i in range(40)]
    result = R.run_heuristics(ME, views)
    assert 0 <= result["score"] <= 100


# ---------------------------------------------------------------------------
# Geo-velocity
# ---------------------------------------------------------------------------
def _geo(city, lat, lon, minutes, conf=0.9, vpn=False):
    return {"ip": city, "city": city, "country": "X", "lat": lat, "lon": lon, "isp": "isp",
            "is_vpn_tor": vpn, "first_seen": T0 + timedelta(minutes=minutes), "confidence": conf,
            "source": "relay"}


def test_geo_never_invents_locations():
    views = [view(i, [(ME, 1)], [("x", 0.9)]) for i in range(5)]
    out = analyze_geo_velocity(views, ME)
    assert out["data_available"] is False and out["score"] == 0 and out["locations"] == []


def test_impossible_travel_detected_with_reliable_observations():
    a, b = view(0, [(ME, 1)], [("x", 0.9)]), view(20, [(ME, 1)], [("y", 0.9)])
    a["geo"], b["geo"] = _geo("Frankfurt", 50.11, 8.68, 0), _geo("New York", 40.71, -74.0, 20)
    out = analyze_geo_velocity([a, b], ME)
    assert out["has_impossible_travel"] and out["score"] >= 60


def test_low_confidence_or_jittery_hops_are_not_scored():
    a, b = view(0, [(ME, 1)], [("x", 0.9)]), view(20, [(ME, 1)], [("y", 0.9)])
    a["geo"], b["geo"] = _geo("Frankfurt", 50.11, 8.68, 0, conf=0.4), _geo("New York", 40.71, -74.0, 20, conf=0.4)
    assert not analyze_geo_velocity([a, b], ME)["has_impossible_travel"]
    a["geo"], b["geo"] = _geo("Amsterdam", 52.37, 4.9, 0), _geo("Los Angeles", 34.05, -118.24, 0.1)
    assert not analyze_geo_velocity([a, b], ME)["has_impossible_travel"]


# ---------------------------------------------------------------------------
# Risk fusion
# ---------------------------------------------------------------------------
def test_fusion_bounds_and_levels():
    out = fuse({k: {"score": 100} for k in ("behaviour", "exposure", "anomaly", "geo")}, {})
    assert out["risk_score"] <= 100 and out["risk_level"] == "CRITICAL"
    assert risk_level(10) == "LOW" and risk_level(45) == "MEDIUM" and risk_level(70) == "HIGH"


def test_ml_alone_cannot_leave_low():
    out = fuse({"anomaly": {"score": 100}}, {})
    assert out["risk_level"] == "LOW"


def test_illicit_attribution_sets_floor():
    ent = {"is_known": True, "category": "ransomware", "entity_name": "X", "category_label": "Ransomware"}
    assert fuse({}, ent)["risk_score"] >= 90


def test_service_dampening_keeps_exposure_evidence():
    comps = {"behaviour": {"score": 95}, "exposure": {"score": 80}}
    ex = {"is_known": True, "category": "exchange", "entity_name": "Ex", "category_label": "Exchange"}
    plain = fuse(comps, {})["risk_score"]
    damped = fuse(comps, ex)["risk_score"]
    exposure_only = fuse({"exposure": {"score": 80}}, {})["risk_score"]
    assert exposure_only <= damped < plain


# ---------------------------------------------------------------------------
# Provider circuit breaker
# ---------------------------------------------------------------------------
def test_failing_provider_is_skipped_until_breaker_expires():
    import time as _t
    from app.services import bitcoin_api as B
    url = "https://unreachable.example/api/x"
    assert B._get_json(url, retries=0) is None          # network is blocked in tests
    assert "unreachable.example" in B.breaker_state()
    start = _t.time()
    assert B._get_json(url) is None                      # skipped immediately, no retries
    assert _t.time() - start < 0.05
    B._reset("unreachable.example")
    assert "unreachable.example" not in B.breaker_state()

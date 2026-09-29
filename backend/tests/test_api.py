"""End-to-end API tests against the seeded demo scenarios (offline)."""

import pytest

SUSPICIOUS = ["bc1_sus_peel_root", "bc1_sus_burst", "bc1_sus_mixer", "bc1_sus_geohop", "bc1_sus_ransom_cashout"]


@pytest.mark.parametrize("address", SUSPICIOUS)
def test_suspicious_scenarios_score_high(client, address):
    r = client.get(f"/api/wallet/{address}/analyze")
    assert r.status_code == 200
    d = r.json()
    assert d["risk_level"] in ("HIGH", "CRITICAL"), (address, d["risk_score"], d["score_breakdown"])
    assert d["ai_explanation"] and d["recommendations"]
    assert {b["component"] for b in d["score_breakdown"]} == {"behaviour", "exposure", "anomaly", "geo"}


@pytest.mark.parametrize("address", ["bc1_normal_0", "bc1_normal_3", "bc1_normal_7"])
def test_ordinary_wallets_score_low(client, address):
    d = client.get(f"/api/wallet/{address}/analyze").json()
    assert d["risk_level"] == "LOW", (address, d["risk_score"], d["score_breakdown"])


def test_peel_chain_is_traced_to_exchange_terminus(client):
    d = client.get("/api/wallet/bc1_sus_peel_root/analyze").json()
    peel = next(f for f in d["findings"] if f["id"] == "peel_chain")
    assert peel["evidence"]["chain_length"] >= 8
    assert peel["evidence"]["terminal"]["category"] == "exchange"
    assert any(r["action"].startswith("KYC request") for r in d["recommendations"])


@pytest.mark.parametrize("address", SUSPICIOUS + ["bc1_normal_0"])
def test_narrative_is_consistent_with_findings(client, address):
    d = client.get(f"/api/wallet/{address}/analyze").json()
    triggered = [f for f in d["findings"] if f["severity"] != "INFO"]
    says_none = "No laundering typology" in d["ai_explanation"]
    assert says_none == (not triggered), (address, d["ai_explanation"])


def test_geohop_uses_observed_telemetry(client):
    geo = client.get("/api/wallet/bc1_sus_geohop/analyze").json()["geo_analysis"]
    assert geo["data_available"] and geo["has_impossible_travel"] and geo["vpn_tor_count"] >= 1


def test_ransom_cashout_exposure_and_dormancy(client):
    d = client.get("/api/wallet/bc1_sus_ransom_cashout/analyze").json()
    assert d["exposure"]["direct"][0]["category"] == "ransomware"
    assert any(f["id"] == "dormant_reactivation" for f in d["findings"])
    assert d["exposure"]["cashout_exchanges"]


def test_mixer_coinjoin_and_cluster(client):
    d = client.get("/api/wallet/bc1_sus_mixer/analyze").json()
    ids = {f["id"] for f in d["findings"]}
    assert {"coinjoin", "fan_in", "fan_out"} <= ids
    # CoinJoin inputs must NOT be merged into the wallet's ownership cluster
    assert d["cluster"]["coinjoins_excluded"] >= 1
    assert not any(m.startswith("bc1_cj_peer") for m in d["cluster"]["members"])


def test_invalid_address_rejected(client):
    r = client.get("/api/wallet/1kr6QSydW9bFQG1mXiPNNu6WpJGmUa9i1g/analyze")
    assert r.status_code == 400 and "checksum" in r.json()["detail"]


def test_unknown_demo_id_is_404(client):
    assert client.get("/api/wallet/bc1_does_not_exist/analyze").status_code == 404


def test_graph_contains_peel_hops_and_root(client):
    g = client.get("/api/wallet/bc1_sus_peel_root/graph").json()
    ids = {n["data"]["id"] for n in g["nodes"]}
    assert "bc1_sus_peel_root" in ids and "bc1_peel_node_5" in ids
    assert any(e["data"]["kind"] == "peel" for e in g["edges"])
    assert any(n["data"]["illicit"] for n in g["nodes"])


def test_graph_expand(client):
    g = client.get("/api/wallet/bc1_peel_node_3/graph/expand", params={"root": "bc1_sus_peel_root"}).json()
    assert g["expanded_address"] == "bc1_peel_node_3" and g["edges"]


def test_report_integrity_roundtrip(client):
    rep = client.get("/api/wallet/bc1_sus_geohop/report").json()
    assert rep["case"]["case_id"].startswith("SIFRA-")
    integ = rep["integrity"]
    ok = client.post("/api/report/verify", json={"payload": integ["payload"], "digest": integ["digest"]}).json()
    assert ok["matches"] is True
    # A browser re-serialises 92.0 as 92 - the fingerprint must survive that round trip
    def js_like(o):
        if isinstance(o, float) and o.is_integer():
            return int(o)
        if isinstance(o, dict):
            return {k: js_like(v) for k, v in o.items()}
        if isinstance(o, list):
            return [js_like(v) for v in o]
        return o
    browser = client.post("/api/report/verify", json={"payload": js_like(integ["payload"]), "digest": integ["digest"]}).json()
    assert browser["matches"] is True
    tampered = dict(integ["payload"], risk_score=1.0)
    bad = client.post("/api/report/verify", json={"payload": tampered, "digest": integ["digest"]}).json()
    assert bad["matches"] is False


def test_alerts_are_persisted(client):
    client.get("/api/wallet/bc1_sus_burst/analyze")
    alerts = client.get("/api/alerts", params={"wallet": "bc1_sus_burst"}).json()["alerts"]
    assert alerts and all(a["wallet"] == "bc1_sus_burst" for a in alerts)
    acked = client.post(f"/api/alerts/{alerts[0]['id']}/ack").json()
    assert acked["acknowledged"] is True


def test_demo_scenarios_listed(client):
    d = client.get("/api/demo/scenarios").json()
    assert d["seeded"] and all(s["available"] for s in d["scenarios"])


def test_telemetry_ingest_and_stats(client):
    txid = "ab" * 32
    body = {"sensor_id": "pytest", "observations": [
        {"txid": txid, "peer_ip": "203.0.113.7", "first_seen": 1767225600, "peers_announcing": 4, "confidence": 0.8}]}
    assert client.post("/api/telemetry/observations", json=body).json()["stored"] == 1
    assert client.post("/api/telemetry/observations", json=body).json()["stored"] == 0   # deduplicated
    assert "pytest" in client.get("/api/telemetry/stats").json()["sensors"]


def test_transactions_and_watchlist(client):
    t = client.get("/api/wallet/bc1_sus_burst/transactions").json()
    assert t["count"] >= 25 and t["transactions"][0]["txid"]
    w = client.get("/api/entities/watchlist").json()["entities"]
    assert any(e["illicit"] for e in w)


def test_health_reports_components(client):
    h = client.get("/api/health").json()
    assert h["database"]["ok"] is True and "llm" in h


def test_diagnostics_reports_every_provider(client):
    d = client.get("/api/diagnostics").json()
    assert {"blockstream", "mempool_space", "blockchain_info", "coingecko"} <= set(d["providers"])
    assert all("ok" in p for p in d["providers"].values())

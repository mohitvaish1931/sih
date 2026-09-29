"""
Investigator-facing explanation of a SIFRA verdict.

The narrative is always generated deterministically from the evidence (so it is
reproducible and never invents facts). If a local LLM (Ollama) is reachable it
rewrites that evidence into prose; its output is only accepted when it returns
in time, and the evidence-based text remains the fallback.
"""

import logging
import re
import time
from typing import Dict, List

import requests

from app.config import OLLAMA_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT, LLM_ENABLED
from app.utils import short

log = logging.getLogger("sifra.explain")

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_llm_state = {"checked": 0.0, "up": False}


def llm_available() -> bool:
    if not LLM_ENABLED:
        return False
    if time.time() - _llm_state["checked"] < 60:
        return _llm_state["up"]
    base = OLLAMA_URL.split("/api/")[0]
    try:
        res = requests.get(f"{base}/api/tags", timeout=0.8)
        up = res.status_code == 200 and any(
            m.get("name", "").split(":")[0] == OLLAMA_MODEL.split(":")[0] for m in res.json().get("models", []))
    except Exception:
        up = False
    _llm_state.update({"checked": time.time(), "up": up})
    return up


def build_narrative(inv: Dict) -> str:
    addr = inv["wallet"]
    parts: List[str] = []
    conf = inv.get("confidence", {})
    parts.append(f"SIFRA assesses {short(addr, 10, 6)} as {inv['risk_level']} risk "
                 f"({inv['risk_score']:.0f}/100, {conf.get('level', 'LOW').lower()} confidence - {conf.get('note', '')})")

    ent = inv.get("entity") or {}
    if ent.get("is_known"):
        parts.append(f"The address itself is attributed to {ent['entity_name']} ({ent['category_label']}, "
                     f"{ent.get('confidence') or 'medium'} confidence, source: {ent.get('source')}).")

    findings = [f for f in inv.get("findings", []) if f["severity"] != "INFO"]
    if findings:
        lead = "; ".join(f"{f['title'].lower()} - {f['summary'].rstrip('.')}" for f in findings[:3])
        parts.append(f"Behavioural evidence: {lead}")
    else:
        parts.append("No laundering typology (peel chain, pass-through, fan-in/out, CoinJoin, bursts) was triggered.")
    peel = next((f for f in findings if f["id"] == "peel_chain"), None)
    terminal = (peel or {}).get("evidence", {}).get("terminal")
    if terminal and terminal.get("entity_name"):
        parts.append(f"The traced chain terminates at {terminal['entity_name']} ({terminal['btc']} BTC).")

    exp = inv.get("exposure") or {}
    if exp.get("direct"):
        top = exp["direct"][0]
        parts.append(f"Direct exposure: {exp['illicit_share']:.1%} of analysed value was exchanged with illicit-attributed "
                     f"counterparties, led by {top['entity_name']} ({top['category_label']}).")
    if exp.get("indirect"):
        i = exp["indirect"][0]
        parts.append(f"Indirect exposure: {i['entity_name']} ({i['category_label']}) sits two hops away via "
                     f"{short(i['via'])}.")

    cl = inv.get("cluster") or {}
    if cl.get("size", 1) > 1:
        att = cl.get("attributed_entity")
        parts.append(f"Common-input-ownership links this address to {cl['size'] - 1} other address(es)"
                     + (f", attributed to {att['entity_name']}." if att else "."))

    geo = inv.get("geo_analysis") or {}
    if geo.get("data_available"):
        parts.append(f"Broadcast telemetry: {geo['summary']}")

    ml = inv.get("ml") or {}
    if ml.get("available") and ml.get("score", 0) >= 40 and ml.get("top_features"):
        feats = ", ".join(f"{t['label'].lower()} ({t['direction']})" for t in ml["top_features"][:2])
        parts.append(f"The ML model ranks this behaviour more anomalous than {ml['percentile']:.0f}% of the reference "
                     f"population, driven by {feats}.")

    for adj in inv.get("adjustments", []):
        parts.append(adj["detail"])
    return " ".join(p if p.endswith(".") else p + "." for p in parts)


def recommendations(inv: Dict) -> List[Dict]:
    recs: List[Dict] = []
    exp = inv.get("exposure") or {}
    ids = {f["id"] for f in inv.get("findings", [])}
    level = inv["risk_level"]

    peel = next((f for f in inv.get("findings", []) if f["id"] == "peel_chain"), None)
    terminal = (peel or {}).get("evidence", {}).get("terminal") or {}
    if terminal.get("category") == "exchange":
        recs.append({"priority": "HIGH", "action": "KYC request (chain terminus)",
                     "detail": f"The peel chain ends with {terminal['btc']} BTC deposited to {terminal['entity_name']} "
                               f"({short(terminal['address'])}, tx {short(terminal['txid'])}). Request the depositing "
                               f"account's KYC and withdrawal history."})
    for c in exp.get("cashout_exchanges", [])[:3]:
        recs.append({"priority": "HIGH" if level in ("HIGH", "CRITICAL") else "MEDIUM", "action": "KYC request",
                     "detail": f"Request account holder KYC and deposit records from {c['exchange']} for "
                               f"{c['btc']} BTC received at {short(c['address'])} (tx {short(c['txids'][0])})."})
    for c in exp.get("funding_exchanges", [])[:2]:
        recs.append({"priority": "MEDIUM", "action": "Source-of-funds request",
                     "detail": f"{c['exchange']} funded this wallet with {c['btc']} BTC - request withdrawal "
                               f"records to identify the originating account."})
    if exp.get("direct"):
        recs.append({"priority": "HIGH", "action": "Taint flag",
                     "detail": "Treat outgoing funds as tainted; circulate the address to exchanges / VASPs for "
                               "freeze-on-deposit."})
    if "peel_chain" in ids:
        recs.append({"priority": "HIGH", "action": "Trace remainder",
                     "detail": "Follow the peel-chain remainder to its terminal hop in the graph (double-click nodes); "
                               "terminal hops typically land at exchange deposit addresses."})
    if "coinjoin" in ids:
        recs.append({"priority": "MEDIUM", "action": "Post-mix analysis",
                     "detail": "Funds passed through CoinJoin; analyse post-mix outputs by amount and timing "
                               "correlation rather than by direct links."})
    geo = inv.get("geo_analysis") or {}
    if geo.get("has_impossible_travel") or geo.get("vpn_tor_count"):
        recs.append({"priority": "MEDIUM", "action": "Network attribution",
                     "detail": "Observed relay IPs indicate anonymisation or multiple operators. Relay IPs are "
                               "first-spy estimates - corroborate before requesting subscriber data from ISPs."})
    if level in ("MEDIUM", "HIGH", "CRITICAL"):
        recs.append({"priority": "LOW", "action": "Live monitoring",
                     "detail": "Enable MONITOR to receive an alert the moment this wallet moves funds."})
    if not recs:
        recs.append({"priority": "LOW", "action": "No action",
                     "detail": "No actionable red flags. Keep on watchlist only if linked to an open case."})
    return recs


def generate_ai_explanation(inv: Dict) -> Dict:
    narrative = build_narrative(inv)
    if not llm_available():
        return {"text": narrative, "source": "evidence-template"}

    prompt = (
        "You are a senior blockchain forensics investigator writing for a police case file.\n"
        "Rewrite the EVIDENCE below as a clear 4-5 sentence assessment. Use only facts present in the evidence, "
        "keep every number exactly as given, do not speculate, no greetings, no markdown.\n\n"
        f"EVIDENCE:\n{narrative}\n"
    )
    try:
        res = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "think": False,
            "options": {"temperature": 0.2, "num_predict": 320},
        }, timeout=OLLAMA_TIMEOUT)
        if res.status_code == 200:
            text = _THINK_RE.sub("", res.json().get("response", "")).strip()
            if len(text) > 80:
                return {"text": text, "source": f"llm:{OLLAMA_MODEL}", "evidence": narrative}
    except requests.exceptions.RequestException as exc:
        log.info("LLM unavailable, using evidence template: %s", exc)
    return {"text": narrative, "source": "evidence-template"}

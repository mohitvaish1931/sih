"""
SIFRA risk fusion.

Component scores (0-100) are combined with a weighted noisy-OR:
    risk = 1 - prod(1 - w_i * s_i / 100)
so independent evidence accumulates, no single weak signal can max the score,
and the result is bounded. The wallet's own attribution then sets a floor
(known illicit entity) or dampens behavioural signals (regulated service,
whose volume naturally trips heuristics).
"""

from typing import Dict, List

from app.services.entity_tagger import ILLICIT_SEVERITY, SERVICE_CATEGORIES

COMPONENT_WEIGHTS = {
    "behaviour": 0.85,   # rule-based typology detectors
    "exposure": 0.90,    # value exchanged with illicit counterparties
    "anomaly": 0.45,     # unsupervised ML (supporting evidence only)
    "geo": 0.80,         # observed broadcast telemetry
}
COMPONENT_LABELS = {
    "behaviour": "Behavioural typologies",
    "exposure": "Illicit counterparty exposure",
    "anomaly": "ML behavioural anomaly",
    "geo": "Broadcast geo-velocity",
}


def risk_level(score: float) -> str:
    if score >= 81:
        return "CRITICAL"
    if score >= 61:
        return "HIGH"
    if score >= 31:
        return "MEDIUM"
    return "LOW"


ML_SOLO_WEIGHT = 0.25        # anomaly alone can never lift a wallet out of LOW
CORROBORATION_THRESHOLD = 20  # another component this strong unlocks the full ML weight


SERVICE_SCALE_TXS = 5000   # lifetime txs above which an unlabelled address is almost surely a service


def _dampen_behaviour(fused: float, components: Dict[str, Dict], factor: float) -> float:
    """Scale every non-exposure contribution by `factor`, keeping exposure evidence intact."""
    exposure = float((components.get("exposure") or {}).get("score") or 0)
    p_exp = COMPONENT_WEIGHTS["exposure"] * exposure / 100
    other = 1 - (1 - fused / 100) / max(1e-9, 1 - p_exp)
    return 100 * (1 - (1 - factor * other) * (1 - p_exp))


def fuse(components: Dict[str, Dict], entity: Dict, onchain_tx_count: int = 0) -> Dict:
    remaining = 1.0
    breakdown: List[Dict] = []
    corroborated = any(float((components.get(k) or {}).get("score") or 0) >= CORROBORATION_THRESHOLD
                       for k in COMPONENT_WEIGHTS if k != "anomaly")
    for key, weight in COMPONENT_WEIGHTS.items():
        comp = components.get(key) or {}
        score = float(comp.get("score") or 0.0)
        if key == "anomaly" and not corroborated:
            # Unusual is not illicit: uncorroborated ML evidence gets a reduced weight
            weight = ML_SOLO_WEIGHT
        p = weight * score / 100
        remaining *= (1 - p)
        breakdown.append({
            "component": key,
            "label": COMPONENT_LABELS[key],
            "score": round(score, 1),
            "weight": weight,
            "contribution": round(100 * p, 1),
            "available": comp.get("available", True),
            "summary": comp.get("summary", ""),
        })
    fused = 100 * (1 - remaining)
    adjustments = []

    cat = entity.get("category", "unknown")
    if entity.get("is_known") and cat in ILLICIT_SEVERITY:
        floor = 50 + 45 * ILLICIT_SEVERITY[cat]
        if fused < floor:
            adjustments.append({"type": "entity_floor", "detail":
                                f"Address is attributed to {entity.get('entity_name')} ({entity.get('category_label')}); "
                                f"score floored at {floor:.0f}."})
            fused = floor
    elif entity.get("is_known") and cat in SERVICE_CATEGORIES:
        before = fused
        fused = _dampen_behaviour(fused, components, 0.3)
        if before - fused >= 0.5:
            adjustments.append({"type": "service_dampening", "detail":
                                f"Attributed to regulated service {entity.get('entity_name')}; volume-driven "
                                f"behavioural signals reduced ({before:.0f} -> {fused:.0f}). Illicit exposure is "
                                f"kept in full."})
    elif onchain_tx_count >= SERVICE_SCALE_TXS:
        # Exchange / custodian hot wallets trip every volume heuristic by design.
        before = fused
        fused = _dampen_behaviour(fused, components, 0.35)
        if before - fused >= 0.5:
            adjustments.append({"type": "service_scale_dampening", "detail":
                                f"{onchain_tx_count:,} lifetime transactions indicate a high-volume service "
                                f"(exchange / custodian / processor); volume-driven signals reduced "
                                f"({before:.0f} -> {fused:.0f}). Illicit exposure is kept in full."})

    total = sum(b["contribution"] for b in breakdown) or 1.0
    for b in breakdown:
        b["share"] = round(b["contribution"] / total, 3)

    fused = round(min(100.0, max(0.0, fused)), 1)
    return {"risk_score": fused, "risk_level": risk_level(fused), "breakdown": breakdown, "adjustments": adjustments}


def confidence(analyzed: int, onchain: int, sources: List[str]) -> Dict:
    """How much of the wallet's history backs the verdict."""
    coverage = (analyzed / onchain) if onchain else (1.0 if analyzed else 0.0)
    coverage = min(1.0, coverage)
    if analyzed and coverage >= 0.99:
        level = "HIGH"          # complete history analysed
    elif analyzed >= 50 and coverage >= 0.5:
        level = "HIGH"
    elif analyzed >= 10:
        level = "MEDIUM"
    else:
        level = "LOW"
    note = f"analysed {analyzed} of {onchain or analyzed} on-chain transactions"
    if onchain and analyzed < onchain:
        note += " (most recent first)"
    return {"level": level, "coverage": round(coverage, 3), "analyzed_txs": analyzed,
            "onchain_txs": onchain or analyzed, "note": note, "sources": sources}

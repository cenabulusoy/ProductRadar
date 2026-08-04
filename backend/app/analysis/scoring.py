from __future__ import annotations

from typing import Any


def clamp(value: float, minimum: float = 0, maximum: float = 100) -> int:
    return round(max(minimum, min(maximum, value)))


def _stars(score: int, inverse: bool = False) -> int:
    normalized = 100 - score if inverse else score
    return max(1, min(5, round(normalized / 20)))


def calculate_scores(product: dict[str, Any]) -> dict[str, Any]:
    """Bereken uitlegbare markt-, winst-, risico- en ProductDNA-scores.

    De engine gebruikt alleen velden die nu al in ProductRadar aanwezig zijn.
    Daardoor blijft de uitkomst reproduceerbaar en transparant. Zodra echte
    historische marktdata beschikbaar is, kunnen de afzonderlijke signalen
    worden vervangen zonder de API of frontend opnieuw te ontwerpen.
    """

    average_sales = (product["monthly_sales_low"] + product["monthly_sales_high"]) / 2
    revenue = average_sales * product["sale_price"]
    commission = product["sale_price"] * product["commission_rate"] / 100
    net_profit = product["sale_price"] - product["purchase_price"] - product["shipping_cost"] - commission
    margin = (net_profit / product["sale_price"] * 100) if product["sale_price"] else 0
    roi = (net_profit / product["purchase_price"] * 100) if product["purchase_price"] else 0

    demand = clamp(average_sales / 2.5 + product["review_growth"] * 4 + product["trend"] * 1.5)
    competition = clamp(100 - product["sellers"] * 3.2 - min(product["reviews"] / 35, 30))
    trend = clamp(50 + product["trend"] * 4 + product["review_growth"] * 2)
    margin_score = clamp(margin * 2.2)
    roi_score = clamp(roi / 2.5)
    capital_efficiency = clamp(100 - product["purchase_price"] * 2.2)
    safety = clamp(100 - product["risk_level"])
    confidence = clamp(product.get("confidence", 50))

    market_score = clamp(demand * 0.50 + competition * 0.30 + trend * 0.20)
    profit_score = clamp(margin_score * 0.50 + roi_score * 0.35 + capital_efficiency * 0.15)
    risk_score = clamp(safety * 0.75 + confidence * 0.25)
    opportunity = clamp(market_score * 0.45 + profit_score * 0.35 + risk_score * 0.20)

    buy_reasons: list[str] = []
    avoid_reasons: list[str] = []

    if demand >= 70:
        buy_reasons.append("Sterke geschatte vraag")
    elif demand >= 55:
        buy_reasons.append("Redelijke geschatte vraag")

    if competition >= 65:
        buy_reasons.append("Concurrentie lijkt beheersbaar")
    if margin >= 20:
        buy_reasons.append(f"Gezonde geschatte marge van {margin:.1f}%")
    if roi >= 60:
        buy_reasons.append(f"Sterke geschatte ROI van {roi:.0f}%")
    if trend >= 65:
        buy_reasons.append("Positieve markttrend")
    if product["risk_level"] <= 35:
        buy_reasons.append("Relatief laag product- en retourrisico")

    if product["sellers"] >= 15:
        avoid_reasons.append("Veel actieve aanbieders")
    if product["reviews"] >= 1000:
        avoid_reasons.append("Hoge reviewbarrière")
    if margin < 15:
        avoid_reasons.append("Beperkte winstmarge")
    if roi < 35:
        avoid_reasons.append("Lage opbrengst ten opzichte van de inkoop")
    if product["risk_level"] >= 50:
        avoid_reasons.append("Verhoogd product- of retourrisico")
    if confidence < 60:
        avoid_reasons.append("Analyse heeft nog weinig betrouwbare meetdata")

    if not buy_reasons:
        buy_reasons.append("Aanvullende marktmetingen nodig")
    if not avoid_reasons:
        avoid_reasons.append("Geen zwaar risico zichtbaar in de huidige invoer")

    if opportunity >= 80:
        verdict = "Kansrijk"
        verdict_detail = "Sterke kandidaat voor verdere leveranciers- en marktvalidatie."
    elif opportunity >= 65:
        verdict = "Onderzoeken"
        verdict_detail = "Interessant, maar controleer prijsdruk, leverancier en echte marktvraag."
    elif opportunity >= 50:
        verdict = "Twijfel"
        verdict_detail = "Alleen doorgaan wanneer je een duidelijk prijs- of productvoordeel hebt."
    else:
        verdict = "Niet inkopen"
        verdict_detail = "De huidige verhouding tussen vraag, winst en risico is onvoldoende."

    repeat_purchase_score = clamp(45 + product["review_growth"] * 4 + min(average_sales / 5, 25))
    shipping_ease_score = clamp(100 - product["shipping_cost"] * 8)
    private_label_score = clamp(competition * 0.55 + margin_score * 0.45)
    low_return_risk_score = safety
    cashflow_score = clamp(roi_score * 0.55 + capital_efficiency * 0.45)
    stability_score = clamp(100 - abs(product["trend"]) * 2 + confidence * 0.2)

    product_dna = [
        {"key": "repeat_purchase", "label": "Herhaalaankopen", "score": repeat_purchase_score, "stars": _stars(repeat_purchase_score)},
        {"key": "shipping_ease", "label": "Verzendgemak", "score": shipping_ease_score, "stars": _stars(shipping_ease_score)},
        {"key": "private_label", "label": "Private-label potentieel", "score": private_label_score, "stars": _stars(private_label_score)},
        {"key": "return_risk", "label": "Laag retourrisico", "score": low_return_risk_score, "stars": _stars(low_return_risk_score)},
        {"key": "cashflow", "label": "Cashflow", "score": cashflow_score, "stars": _stars(cashflow_score)},
        {"key": "stability", "label": "Marktstabiliteit", "score": stability_score, "stars": _stars(stability_score)},
    ]

    return {
        "average_monthly_sales": round(average_sales),
        "monthly_revenue": round(revenue, 2),
        "net_profit_per_unit": round(net_profit, 2),
        "margin_percent": round(margin, 1),
        "roi_percent": round(roi, 1),
        "market_score": market_score,
        "profit_score": profit_score,
        "risk_score": risk_score,
        "opportunity_score": opportunity,
        "demand_score": demand,
        "competition_score": competition,
        "trend_score": trend,
        "margin_score": margin_score,
        "roi_score": roi_score,
        "capital_efficiency_score": capital_efficiency,
        "confidence_score": confidence,
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "buy_reasons": buy_reasons,
        "avoid_reasons": avoid_reasons,
        "product_dna": product_dna,
    }

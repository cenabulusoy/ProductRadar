from __future__ import annotations


def clamp(value: float, minimum: float = 0, maximum: float = 100) -> int:
    return round(max(minimum, min(maximum, value)))


def calculate_scores(product: dict) -> dict:
    average_sales = (product["monthly_sales_low"] + product["monthly_sales_high"]) / 2
    revenue = average_sales * product["sale_price"]
    commission = product["sale_price"] * product["commission_rate"] / 100
    net_profit = product["sale_price"] - product["purchase_price"] - product["shipping_cost"] - commission
    margin = (net_profit / product["sale_price"] * 100) if product["sale_price"] else 0
    roi = (net_profit / product["purchase_price"] * 100) if product["purchase_price"] else 0

    demand = clamp(average_sales / 2.5 + product["review_growth"] * 4 + product["trend"] * 1.5)
    competition = clamp(100 - product["sellers"] * 3.2 - min(product["reviews"] / 35, 30))
    profit = clamp(margin * 2.2 + min(roi / 4, 25))
    trend = clamp(50 + product["trend"] * 4 + product["review_growth"] * 2)
    safety = clamp(100 - product["risk_level"])

    market_score = clamp(demand * 0.55 + competition * 0.30 + trend * 0.15)
    profit_score = profit
    risk_score = safety
    opportunity = clamp(market_score * 0.45 + profit_score * 0.35 + risk_score * 0.20)

    buy_reasons = []
    avoid_reasons = []
    if demand >= 65:
        buy_reasons.append("Sterke geschatte vraag")
    if competition >= 60:
        buy_reasons.append("Concurrentie lijkt beheersbaar")
    if margin >= 20:
        buy_reasons.append(f"Gezonde geschatte marge van {margin:.1f}%")
    if product["trend"] > 3:
        buy_reasons.append("Positieve markttrend")
    if product["sellers"] >= 15:
        avoid_reasons.append("Veel actieve aanbieders")
    if product["reviews"] >= 1000:
        avoid_reasons.append("Hoge reviewbarrière")
    if margin < 15:
        avoid_reasons.append("Beperkte winstmarge")
    if product["risk_level"] >= 50:
        avoid_reasons.append("Verhoogd product- of retourrisico")
    if not buy_reasons:
        buy_reasons.append("Aanvullende marktmetingen nodig")
    if not avoid_reasons:
        avoid_reasons.append("Geen zwaar risico zichtbaar in de huidige invoer")

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
        "buy_reasons": buy_reasons,
        "avoid_reasons": avoid_reasons,
    }

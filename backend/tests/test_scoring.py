from app.services.scoring import calculate_scores


def test_score_range():
    product = {
        "monthly_sales_low": 100,
        "monthly_sales_high": 200,
        "sale_price": 29.95,
        "purchase_price": 10.0,
        "shipping_cost": 4.25,
        "commission_rate": 15,
        "review_growth": 4,
        "trend": 5,
        "sellers": 8,
        "reviews": 250,
        "risk_level": 30,
    }
    result = calculate_scores(product)
    assert 0 <= result["opportunity_score"] <= 100
    assert result["net_profit_per_unit"] > 0

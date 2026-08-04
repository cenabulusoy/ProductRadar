from app.analysis.scoring import calculate_scores


def sample_product() -> dict:
    return {
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
        "confidence": 70,
    }


def test_score_range():
    result = calculate_scores(sample_product())
    for field in ("market_score", "profit_score", "risk_score", "opportunity_score"):
        assert 0 <= result[field] <= 100
    assert result["net_profit_per_unit"] > 0


def test_decision_engine_is_explainable():
    result = calculate_scores(sample_product())
    assert result["verdict"] in {"Kansrijk", "Onderzoeken", "Twijfel", "Niet inkopen"}
    assert result["verdict_detail"]
    assert result["buy_reasons"]
    assert result["avoid_reasons"]
    assert len(result["product_dna"]) == 6
    assert all(1 <= item["stars"] <= 5 for item in result["product_dna"])

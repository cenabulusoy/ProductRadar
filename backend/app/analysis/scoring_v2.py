"""Pure, replayable v2 decisions. No database, live calls or v1 dependencies."""
from copy import deepcopy
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import math
from statistics import median
from typing import Literal

from pydantic import Field, model_validator

from app.analysis.financial_v2 import FinancialInputs, Model, Provenance, calculate_financial, market_reference
from app.analysis.scoring_v2_policy import POLICY

VERSION = "2.0.0-scoring.1"
CAP_EXPLANATIONS = {
    "block": "Een expliciet bevestigde verkoopblokkade verhindert inkopen.",
    "loss": "De bijdrage per stuk in het basisscenario is nul of negatief.",
    "stress_loss": "De bijdrage bij lagere prijs en hogere operationele kosten is nul of negatief.",
    "weak_demand": "Het voldoende onderbouwde vraagsignaal is zwak.",
    "high_risk": "Het voldoende onderbouwde risicoprofiel is hoog.",
    "unproven_demand": "De vraag is nog onvoldoende onderbouwd; een afzetschatting is geen verkoopmeting.",
    "confidence_below_75": "De datakwaliteit is onvoldoende voor Kansrijk.",
    "confidence_below_50": "Er is onvoldoende bewijs voor een inkoopbeslissing; eerst onderzoeken.",
    "not_ready": "Niet alle aanvullende voorwaarden voor Kansrijk zijn aangetoond.",
}


class Assessment(Model):
    value: int = Field(strict=True)
    explanation: str = Field(min_length=1, max_length=1000, pattern=r"\S")
    provenance: Provenance

    @model_validator(mode="after")
    def valid(self):
        if self.value not in (0, 50, 100):
            raise ValueError("Assessment must be 0, 50 or 100")
        return self


class OperationalInputs(Model):
    fragility: Assessment | None = None
    handling: Assessment | None = None
    obsolescence: Assessment | None = None
    supplier: Assessment | None = None
    inventory_exposure: Assessment | None = None


class DemandEstimate(Model):
    monthly_sales_lower: int = Field(ge=0, le=1000000000, strict=True)
    scope: Literal["market"]
    method: str = Field(min_length=1, max_length=1000, pattern=r"\S")
    provenance: Provenance

    @model_validator(mode="after")
    def estimated(self):
        if self.provenance.kind != "estimated":
            raise ValueError("Market sales estimate must remain estimated")
        return self


class DeliveryComparison(Model):
    market_snapshot_id: int = Field(gt=0, strict=True)
    offer_id: str = Field(min_length=1, max_length=200)
    days_later: int = Field(ge=-365, le=365, strict=True)
    same_order_conditions: bool = Field(strict=True)
    explanation: str = Field(min_length=1, max_length=1000, pattern=r"\S")
    provenance: Provenance


class SalesBlock(Model):
    confirmed: bool = Field(strict=True)
    explanation: str = Field(min_length=1, max_length=1000, pattern=r"\S")
    provenance: Provenance


class ScoringInputs(Model):
    financial: FinancialInputs
    operational: OperationalInputs = Field(default_factory=OperationalInputs)
    demand_estimate: DemandEstimate | None = None
    delivery: DeliveryComparison | None = None
    sales_block: SalesBlock | None = None

    @model_validator(mode="after")
    def conservative(self):
        if self.financial.scenario_mode != "conservative":
            raise ValueError("Scoring requires the conservative financial scenario")
        def declared(value):
            if isinstance(value, dict):
                if value.get("kind") == "official_measured":
                    raise ValueError("Official measurements must be server-loaded, not caller-declared")
                for child in value.values():
                    declared(child)
        declared(self.model_dump(mode="json"))
        return self


def clip(value):
    return max(0., min(100., value))


def stamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("Timezone required")
    return parsed.astimezone(timezone.utc)


def freshness(recorded_at, as_of, group):
    try:
        age = (as_of - stamp(recorded_at)).total_seconds() / 86400
    except (ValueError, TypeError):
        return 0.
    free, half, cutoff = POLICY["freshness_days"][group]
    if age < 0 or age > cutoff:
        return 0.
    return 1. if age <= free else 2 ** (-(age - free) / half)


def quality(provenance, as_of, group, documented_assessment=False):
    if not provenance:
        return 0.
    source = POLICY["source_quality"][provenance["kind"]]
    # Explicit dated operational/delivery assessment is the design's quality=1;
    # this is documented caller evidence, not an independently verified fact.
    if documented_assessment and provenance["kind"] == "manual_or_imported":
        source = 1.
    return source * freshness(provenance["recorded_at"], as_of, group)


def official(source, when, snapshot_id):
    return {"kind": "official_measured", "source": source, "recorded_at": when, "snapshot_id": snapshot_id}


def observed_market(record, as_of):
    """Recount underlying offers; never trust cached derived totals."""
    result = {"status": "unknown", "offer_count": None, "unique_seller_count": None,
              "price_min": None, "price_max": None, "reference": None, "quality": 0., "provenance": None,
              "relevant_offer": None, "data_kinds": {"offer_fields": "official_measured",
              "offer_count": "derived", "unique_seller_count": "derived", "price_range": "derived"}}
    if not record or not isinstance(record.get("payload"), dict):
        return result
    p, sid = record["payload"], record["id"]
    try:
        measured = stamp(p["measured_at"])
        if measured != stamp(record["measured_at"]) or measured > as_of or p.get("source") != "bol Retailer API":
            return result
        result["provenance"] = official("bol Retailer API v10 products/{ean}/offers", p["measured_at"], sid)
        # Validate at measurement time: historical observations have the same contract.
        ref = market_reference(p, sid, measured)
        empty = ref["reason"] == "market_has_no_offers"
        if ref["status"] != "usable" and not empty:
            return result
        sellers = set()
        for row in p["offers"]:
            retailer = row.get("retailerId")
            if not isinstance(retailer, str) or not retailer.strip():
                return result
            sellers.add(retailer.strip())
        prices = [float(r["price"]) for r in p["offers"]]
        result.update(status="complete", offer_count=len(p["offers"]), unique_seller_count=len(sellers),
                      price_min=min(prices) if prices else None, price_max=max(prices) if prices else None,
                      reference=ref, quality=freshness(p["measured_at"], as_of, "market"),
                      relevant_offer=next((deepcopy(row) for row in p["offers"] if row["offerId"] == ref["offer_id"]), None))
    except (KeyError, ValueError, TypeError, ArithmeticError):
        pass
    return result


def rating_observation(record, ean, as_of):
    try:
        p = record["payload"]
        if (p["ean"] != ean or p["api_version"] != "v10" or p["source"] != "bol Retailer API v10"
                or p["language"] != "nl" or p["endpoints"]["ratings"]["status"] != "ok"
                or p["endpoints"]["ratings"]["version"] != "v10"
                or p["endpoints"]["ratings"]["path"] != "products/{ean}/ratings"):
            return None
        when = stamp(p["fetched_at"])
        if when != stamp(record["measured_at"]) or when > as_of:
            return None
        rows = p["ratings"]["distribution"]
        if not isinstance(rows, list):
            return None
        buckets = {}
        for row in rows:
            star, count = row["rating"], row["count"]
            if type(star) is not int or star not in range(1, 6) or star in buckets or type(count) is not int or not 0 <= count <= 10**12:
                return None
            buckets[star] = count
        return {"id": record["id"], "when": when, "count": sum(buckets.values()),
                "negative_count": sum(buckets.get(s, 0) for s in (1, 2)),
                "bol_product_id": p.get("bol_product_id"), "distribution": rows,
                "quality": freshness(p["fetched_at"], as_of, "ratings"),
                "provenance": official("bol Retailer API v10 products/{ean}/ratings nl", p["fetched_at"], record["id"])}
    except (KeyError, ValueError, TypeError):
        return None


def demand_metric(records, ean, as_of, estimate):
    metric = {"score": None, "quality": 0., "route": None, "growth_per_30_days": None,
              "snapshot_ids": [], "reason": "no_comparable_rating_history", "estimate_comparison": estimate}
    observations = [rating_observation(r, ean, as_of) for r in records]
    # The newest failed observation is not silently replaced with an older success.
    latest = observations[0] if observations else None
    if latest and latest["quality"] > 0:
        candidates = []
        broken = False
        previous = latest
        for older in observations[1:]:
            if not older:
                continue
            interval = (latest["when"] - older["when"]).total_seconds() / 86400
            if interval > POLICY["demand"]["max_interval_days"]:
                break
            if older["bol_product_id"] != latest["bol_product_id"] or older["count"] > previous["count"]:
                broken = True
            previous = older
            if interval >= POLICY["demand"]["min_interval_days"]:
                candidates.append((abs(interval - 30), older, interval))
        if candidates and not broken:
            _, older, interval = min(candidates, key=lambda c: (c[0], c[1]["id"]))
            growth = 30 * (latest["count"] - older["count"]) / interval
            metric.update(score=clip(100 * math.log1p(growth) / math.log1p(POLICY["demand"]["rating_anchor"])),
                          quality=POLICY["demand"]["rating_quality_cap"] * latest["quality"], route="rating_growth",
                          growth_per_30_days=growth, snapshot_ids=[older["id"], latest["id"]], reason=None)
        elif broken:
            metric["reason"] = "rating_identity_or_count_discontinuity"
    if metric["score"] is None and estimate:
        q = quality(estimate["provenance"], as_of, "ratings")
        if q > 0:
            metric.update(score=clip(100 * math.log1p(estimate["monthly_sales_lower"]) / math.log1p(POLICY["demand"]["estimate_anchor"])),
                          quality=min(POLICY["demand"]["estimate_quality_cap"], q), route="estimated_market_sales")
    return metric, latest


def price_risk(records, as_of):
    days = {}
    for record in records:
        p = record.get("payload")
        if not isinstance(p, dict):
            continue
        try:
            when = stamp(p["measured_at"])
            if not 0 <= (as_of - when).total_seconds() / 86400 <= POLICY["history_window_days"]:
                continue
            obs = observed_market(record, when)
            if obs["status"] != "complete" or not obs["reference"] or obs["reference"]["price"] is None:
                continue
            # Latest valid observation per UTC day, not a burst of same-day requests.
            day = when.date()
            if day not in days or when > days[day][0]:
                days[day] = (when, float(obs["reference"]["price"]), record["id"], obs["reference"]["reason"])
        except (KeyError, ValueError, TypeError):
            continue
    rows = sorted(days.values())
    result = {"score": None, "quality": 0., "snapshot_ids": [r[2] for r in rows], "spread": None}
    if len(rows) < POLICY["risk"]["min_days"]:
        return result
    span = (rows[-1][0] - rows[0][0]).total_seconds() / 86400
    if span < POLICY["risk"]["min_span"] or len({r[3] for r in rows}) != 1:
        return result
    prices = [r[1] for r in rows]
    spread = (max(prices) - min(prices)) / median(prices)
    q = 1. if len(rows) >= POLICY["risk"]["full_days"] and span >= POLICY["risk"]["full_span"] else POLICY["risk"]["limited_quality"]
    result.update(score=clip(100 * spread / POLICY["risk"]["price_spread_anchor"]), spread=spread,
                  quality=q * freshness(rows[-1][0].isoformat(), as_of, "market"))
    return result


def calculate_decision(inputs: ScoringInputs, *, as_of: datetime, ean: str,
                       identity=None, product_snapshots=(), market_snapshots=()):
    """Caller must supply server-loaded observations. Inputs are frozen into output."""
    if as_of.utcoffset() is None:
        raise ValueError("Timezone required")
    frozen = inputs.model_dump(mode="json")

    def check_dates(value):
        if isinstance(value, dict):
            if "provenance" in value and stamp(value["provenance"]["recorded_at"]) > as_of:
                raise ValueError("Future provenance")
            for child in value.values():
                check_dates(child)
        elif isinstance(value, list):
            for child in value:
                check_dates(child)
    check_dates(frozen)
    # Sort by persisted measurement time, including invalid/partial latest payloads.
    def order(record):
        try:
            return stamp(record["measured_at"]), record["id"]
        except (ValueError, TypeError, KeyError):
            # Fail closed: malformed times precede valid history, never disappear.
            return datetime.max.replace(tzinfo=timezone.utc), record["id"]
    products = sorted(deepcopy(product_snapshots), key=order, reverse=True)
    markets = sorted(deepcopy(market_snapshots), key=order, reverse=True)
    current = markets[0] if markets else None
    market = observed_market(current, as_of)
    financial = calculate_financial(inputs.financial, as_of=as_of,
                                   market_payload=current["payload"] if current else None,
                                   snapshot_id=current["id"] if current else None)
    base, stress = financial["base"], financial["stress"]
    demand, ratings = demand_metric(products, ean, as_of, frozen["demand_estimate"])
    qd, d = demand["quality"], demand["score"]
    delivery_score, delivery_q = None, 0.
    delivery = frozen["delivery"]
    ref = market["reference"]
    if (delivery and current and ref and delivery["market_snapshot_id"] == current["id"]
            and delivery["offer_id"] == ref["offer_id"] and delivery["same_order_conditions"]):
        selected = next((o for o in current["payload"]["offers"] if o["offerId"] == ref["offer_id"]), {})
        # An explicit comparison also requires actual delivery metadata for that offer.
        try:
            delivery_date = date.fromisoformat(selected.get("maxDeliveryDate", ""))
            valid_delivery = delivery_date >= stamp(current["payload"]["measured_at"]).date()
        except (ValueError, TypeError):
            valid_delivery = False
        if valid_delivery:
            delivery_q = quality(delivery["provenance"], as_of, "market", True)
            if delivery_q > 0:
                delivery_score = 100 if delivery["days_later"] <= 0 else (50 if delivery["days_later"] == 1 else 0)
    c, qc, pressure = None, 0., None
    n = market["unique_seller_count"]
    cp = POLICY["competition"]
    if market["quality"] > 0 and n is not None and n >= 1:
        pressure = min(cp["pressure_cap"], 100 / (1 + math.log(n) / math.log(cp["seller_log_base"])))
        c = cp["pressure_weight"] * pressure + cp["delivery_weight"] * (delivery_score if delivery_score is not None else cp["unknown_delivery_prior"])
        qc = market["quality"] * (cp["pressure_weight"] + cp["delivery_weight"] * delivery_q)

    financial_qualities = {}
    def cost_qualities(value, path):
        if isinstance(value, dict):
            if "provenance" in value:
                financial_qualities[path] = quality(value["provenance"], as_of, "cost")
            for key, child in value.items():
                if key != "provenance":
                    cost_qualities(child, path + "." + key)
    cost_qualities(frozen["financial"], "financial")
    p, qp = None, 0.
    pi = float(base["contribution_per_unit"]) if base["contribution_per_unit"] is not None else None
    stress_pi = float(stress["contribution_per_unit"]) if stress["contribution_per_unit"] is not None else None
    margin = float(base["contribution_margin_percent"]) if base["contribution_margin_percent"] is not None else None
    roi = float(base["inventory_roi_percent"]) if base["inventory_roi_percent"] is not None else None
    components = {"margin": None, "contribution": None, "roi": None}
    if pi is not None and roi is not None:
        pp = POLICY["profitability"]
        components = {"margin": clip(100 * margin / pp["margin_anchor_percent"]),
                      "contribution": clip(100 * pi / pp["contribution_anchor"]),
                      "roi": clip(100 * roi / pp["roi_anchor_percent"])}
        p = sum(components[k] * pp[k + "_weight"] for k in components)
        qp = min([market["quality"], *financial_qualities.values()]) if financial_qualities else 0.

    operations = {}
    op_scores, op_q = [], []
    for name in POLICY["operational_fields"]:
        item = frozen["operational"][name]
        q = quality(item["provenance"], as_of, "operational", True) if item else 0.
        score = item["value"] if item and q > 0 else None
        operations[name] = {"score": score, "quality": q}
        op_scores.append(score if score is not None else POLICY["risk"]["unknown_prior"])
        op_q.append(q)
    operational_score = sum(op_scores) / 5 if any(q > 0 for q in op_q) else None
    operational_q = sum(op_q) / 5
    rating_risk, rating_q = None, 0.
    rp = POLICY["risk"]
    if ratings and ratings["quality"] > 0 and ratings["count"] > 0:
        rating_risk = clip(100 * ((ratings["negative_count"] + rp["bad_rating_prior"]) /
                                  (ratings["count"] + rp["rating_prior_total"])) / rp["negative_share_anchor"])
        rating_q = ratings["quality"]
    price = price_risk(markets, as_of)
    risk_parts = {"operational": {"score": operational_score, "quality": operational_q},
                  "quality": {"score": rating_risk, "quality": rating_q}, "price": price}
    qr = sum(rp[k + "_weight"] * v["quality"] for k, v in risk_parts.items())
    risk = sum(rp[k + "_weight"] * (v["score"] if v["score"] is not None else rp["unknown_prior"])
               for k, v in risk_parts.items()) if qr > 0 else None
    scores = {"demand": d, "competition": c, "profitability": p, "risk": risk}
    qualities = {"demand": qd, "competition": qc, "profitability": qp, "risk": qr}
    weights, th = POLICY["weights"], POLICY["thresholds"]
    confidence = 100 * sum(weights[k] * qualities[k] for k in weights)
    effective = {k: 50 + qualities[k] * ((100 - v if k == "risk" else v) - 50) if v is not None else 50.
                 for k, v in scores.items()}
    contributions = {k: weights[k] * effective[k] for k in weights}
    penalty = POLICY["confidence_penalty"] * (100 - confidence)
    uncapped = clip(sum(contributions.values()) - penalty)
    missing = ["financial." + v for v in base["missing_inputs"]]
    if not identity or identity.get("ean") != ean:
        missing.append("product_identity")
    elif products:
        payload = products[0].get("payload")
        if isinstance(payload, dict) and (payload.get("ean") != ean or
                (payload.get("bol_product_id") and identity.get("bol_product_id") and
                 payload["bol_product_id"] != identity["bol_product_id"])):
            missing.append("conflicting_product_identity")
    if current is None or financial["price_selection"]["market_reference"]["status"] != "usable" or market["quality"] == 0:
        missing.append("current_complete_market_price")
    if market["status"] != "complete":
        missing.append("complete_market_offers")
    if roi is None and pi is not None:
        missing.append("positive_landed_cost_for_roi")
    if financial_qualities and min(financial_qualities.values()) == 0:
        missing.append("current_financial_evidence")
    safeguards = []
    def cap(code, condition):
        if condition:
            safeguards.append({"code": code, "cap": POLICY["caps"][code], "explanation": CAP_EXPLANATIONS[code]})
    block = frozen["sales_block"]
    blocked = bool(block and block["confirmed"])
    loss = pi is not None and pi <= 0
    cap("block", blocked)
    cap("loss", loss)
    cap("stress_loss", stress_pi is not None and stress_pi <= 0)
    cap("weak_demand", d is not None and d < th["weak_demand"] and qd >= th["demand_quality"])
    cap("high_risk", risk is not None and risk >= th["high_risk"] and qr >= th["risk_quality"])
    cap("unproven_demand", qd < th["demand_quality"])
    cap("confidence_below_75", confidence < th["confidence_ready"])
    cap("confidence_below_50", confidence < th["confidence_low"])
    ready = (not missing and not blocked and qd >= th["demand_quality"] and qp >= th["profit_quality"]
             and qc >= th["competition_quality"] and qr >= th["risk_quality"] and confidence >= th["confidence_ready"]
             and p is not None and p >= th["profitability"] and margin >= th["margin_percent"]
             and stress_pi is not None and stress_pi > 0 and risk is not None and risk < th["max_promising_risk"])
    cap("not_ready", not ready)
    capped = min([uncapped, *(s["cap"] for s in safeguards)])
    opportunity = None if missing else capped
    # Confirmed prohibition overrides missing inputs. Incomplete decisions stay null.
    if blocked:
        opportunity = 0.
    if blocked or loss:
        verdict, verdict_reason = "Niet inkopen", "confirmed_block" if blocked else "nonpositive_base_contribution"
    elif missing or confidence < th["confidence_low"]:
        verdict, verdict_reason = "Onderzoeken", "insufficient_evidence"
    elif ready and opportunity >= th["promising"]:
        verdict, verdict_reason = "Kansrijk", "all_readiness_conditions_met"
    elif opportunity >= th["investigate"]:
        verdict, verdict_reason = "Onderzoeken", "investigate_commercial_case"
    elif opportunity >= th["doubt"]:
        verdict, verdict_reason = "Twijfel", "weak_or_vulnerable_case"
    else:
        verdict, verdict_reason = "Niet inkopen", "low_supported_opportunity"
    labels = {"demand": "Vraagsignaal", "competition": "Concurrentie en leverpositie",
              "profitability": "Bijdrage, marge en voorraad-ROI", "risk": "Operationeel, kwaliteits- en prijsrisico"}
    drivers = [{"code": k, "label": labels[k], "points_vs_neutral": contributions[k] - weights[k] * 50,
                "score": scores[k], "quality": qualities[k]} for k in weights if scores[k] is not None]
    frozen_evidence = {"ean": ean, "as_of": as_of.isoformat(), "inputs": frozen, "identity": deepcopy(identity),
                       "product_snapshots": products, "market_snapshots": markets}
    config = deepcopy(POLICY)
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    config_hash = sha256(canonical(config).encode()).hexdigest()
    analysis_id = sha256(canonical({"version": VERSION, "config": config_hash, "evidence": frozen_evidence}).encode()).hexdigest()
    return {"decision_engine_version": VERSION, "score_config_version": POLICY["version"], "score_config_hash": config_hash,
            "input_schema_version": "1", "analysis_id": analysis_id, "as_of": as_of.isoformat(),
            "scope": {"ean": ean, "country": "NL", "condition": "NEW"}, "status": "incomplete" if missing else "complete",
            "subscores": {**scores, "data_confidence": confidence}, "input_quality": qualities,
            "effective_subscores": effective, "weighted_contributions": contributions,
            "confidence_penalty": penalty, "opportunity_before_caps": uncapped, "opportunity_score": opportunity,
            "verdict": verdict, "verdict_reason": verdict_reason, "safeguards": safeguards,
            "missing_critical_inputs": sorted(set(missing)),
            "unknown_signals": [k for k, v in scores.items() if v is None] + (["delivery_comparison"] if delivery_score is None else []),
            "readiness_missing": (["positive_stress_contribution"] if stress_pi is None or stress_pi <= 0 else [])
                + (["demand_evidence"] if qd < th["demand_quality"] else [])
                + (["risk_evidence"] if qr < th["risk_quality"] else []),
            "positive_drivers": sorted([v for v in drivers if v["points_vs_neutral"] > 0], key=lambda v: -v["points_vs_neutral"]),
            "negative_drivers": sorted([v for v in drivers if v["points_vs_neutral"] < 0], key=lambda v: v["points_vs_neutral"]),
            "financial": financial, "metrics": {"demand": demand, "market": market, "seller_pressure": pressure,
                "delivery": {"score": delivery_score, "quality": delivery_q}, "profitability": components,
                "risk": risk_parts, "operational": operations},
            "financial_input_quality": financial_qualities,
            "provenance": {"manual_inputs": "caller_declared", "official_inputs": "server_loaded_snapshots",
                           "rating_distribution": ratings["provenance"] if ratings else None,
                           "rating_growth": {"kind": "derived", "snapshot_ids": demand["snapshot_ids"]},
                           "market_counts": {"kind": "derived", "snapshot_id": current["id"] if current else None},
                           "scores": {"kind": "derived", "source": VERSION, "recorded_at": as_of.isoformat()}},
            "score_config": config, "frozen_evidence": frozen_evidence,
            "limitations": ["Ratings are a demand proxy, not sales", "Risk is not a return probability",
                            "Contributions are after declared costs, not guaranteed net profit",
                            "Manual evidence is caller-declared, not independently verified"]}
